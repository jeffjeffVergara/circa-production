"""
preventa_ocr.py — Parser OCR para tickets BsSoft (screenshots de app)
Usa Tesseract (gratuito) + regex estructurado.
Todos los imports son lazy/safe — si falta una dependencia,
el módulo se carga igual y falla solo al llamar parse_ticket_bsoft().
"""

import re
import io
import logging
from typing import Optional

logger = logging.getLogger("circa.ocr")


def _ensure_deps():
    """Importa PIL y pytesseract. Lanza RuntimeError si no están."""
    try:
        from PIL import Image, ImageFilter
        import pytesseract
        return Image, ImageFilter, pytesseract
    except ImportError as e:
        raise RuntimeError(
            f"Dependencia OCR faltante: {e}. "
            "Verificar que Pillow y pytesseract estén en requirements.txt "
            "y tesseract-ocr en Dockerfile."
        )


def _preprocess_image(img):
    """Preprocesa screenshot de app BsSoft para Tesseract."""
    _, ImageFilter, _ = _ensure_deps()

    w, h = img.size
    # Escalar si es muy pequeño
    if w < 800:
        ratio = 800 / w
        from PIL import Image as PILImage
        img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

    # Solo grayscale + sharpen. NO binarizar: los screenshots de app
    # tienen fondo oscuro+texto claro Y fondo claro+texto oscuro.
    # Tesseract 4 (LSTM) maneja ambos sin binarización manual.
    img = img.convert("L")
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _ocr_image(image_bytes: bytes) -> str:
    """Ejecuta Tesseract sobre bytes de imagen. Retorna texto crudo."""
    Image, _, pytesseract = _ensure_deps()

    img = Image.open(io.BytesIO(image_bytes))

    # Convertir RGBA a RGB (screenshots con transparencia)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    processed = _preprocess_image(img)

    # Intentar múltiples configuraciones de Tesseract
    configs = [
        {"lang": "spa", "config": "--psm 3 --oem 3"},
        {"lang": "spa", "config": "--psm 6 --oem 3"},
        {"lang": "eng", "config": "--psm 3 --oem 3"},
    ]

    best_text = ""
    for cfg in configs:
        try:
            text = pytesseract.image_to_string(
                processed,
                lang=cfg["lang"],
                config=cfg["config"],
            )
            logger.info(f"OCR config {cfg}: {len(text)} chars")
            if len(text.strip()) > len(best_text.strip()):
                best_text = text
            # Si encontramos "Codigo" en el texto, es el bueno
            if "odigo" in text or "ODIGO" in text or "P0" in text:
                logger.info(f"OCR match found with config {cfg}")
                return text
        except Exception as e:
            logger.warning(f"OCR config {cfg} failed: {e}")
            continue

    return best_text


# --- Regex patterns para ticket BsSoft ---

_RE_CODIGO = re.compile(
    r"C[oó]digo\s*:\s*(P?\d{3,5})",
    re.IGNORECASE,
)
_RE_UNIDAD = re.compile(
    r"Unidad\s*:\s*(\w+)\s*[Xx]\s*(\d+)",
    re.IGNORECASE,
)
_RE_CANTIDAD = re.compile(
    r"Cantidad\s*:\s*(\d+)",
    re.IGNORECASE,
)
_RE_PRECIO = re.compile(
    r"Precio\s*:\s*\.?(\d*\.?\d+)",
    re.IGNORECASE,
)
_RE_TOTAL = re.compile(
    r"Total\s*:\s*\.?(\d*\.?\d+)",
    re.IGNORECASE,
)
_RE_DOC_NUM = re.compile(r"V\d{4}-\d{5,7}")
_RE_FECHA = re.compile(r"(\d{1,2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})")
_RE_ENTREGA = re.compile(r"F\.\s*Entrega\s*:?\s*(\d{1,2}/\d{2}/\d{4})", re.IGNORECASE)


def _parse_items_from_text(text: str) -> list[dict]:
    lines = text.split("\n")
    items = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        m_codigo = _RE_CODIGO.search(line)
        if not m_codigo:
            if i + 1 < len(lines):
                m_codigo = _RE_CODIGO.search(lines[i + 1].strip())
                if m_codigo:
                    descripcion = line
                    i += 1
                    line = lines[i].strip()
                else:
                    i += 1
                    continue
            else:
                i += 1
                continue
        else:
            descripcion = lines[i - 1].strip() if i > 0 else ""

        sku_raw = m_codigo.group(1)
        sku = sku_raw if sku_raw.startswith("P") else f"P{sku_raw}"

        unidad_tipo = ""
        pack_qty = 1
        cantidad = 1
        precio = 0.0
        total = 0.0

        search_window = "\n".join(lines[i:min(i + 6, len(lines))])

        m_unidad = _RE_UNIDAD.search(search_window)
        if m_unidad:
            unidad_tipo = m_unidad.group(1).upper()
            pack_qty = int(m_unidad.group(2))

        m_cantidad = _RE_CANTIDAD.search(search_window)
        if m_cantidad:
            cantidad = int(m_cantidad.group(1))

        m_precio = _RE_PRECIO.search(search_window)
        if m_precio:
            try:
                precio = float(m_precio.group(1))
            except ValueError:
                precio = 0.0

        m_total = _RE_TOTAL.search(search_window)
        if m_total:
            try:
                total = float(m_total.group(1))
            except ValueError:
                total = 0.0

        pack_size = f"{unidad_tipo} x {pack_qty}" if unidad_tipo else "UND x 1"

        es_bonificacion = (
            "BONIFICACION" in descripcion.upper()
            or "BONIF" in descripcion.upper()
            or (precio == 0 and total == 0)
        )

        items.append({
            "sku": sku,
            "descripcion": descripcion,
            "unidad": unidad_tipo or "UND",
            "pack_size": pack_size,
            "pack_qty": pack_qty,
            "cantidad": cantidad,
            "precio": precio,
            "total": total,
            "es_bonificacion": es_bonificacion,
        })

        i += 5

    return items


def _parse_header_from_text(text: str) -> dict:
    header = {}
    m_doc = _RE_DOC_NUM.search(text)
    if m_doc:
        header["documento"] = m_doc.group()
    m_fecha = _RE_FECHA.search(text)
    if m_fecha:
        header["fecha"] = m_fecha.group(1)
        header["hora"] = m_fecha.group(2)
    m_entrega = _RE_ENTREGA.search(text)
    if m_entrega:
        header["fecha_entrega"] = m_entrega.group(1)
    return header


def parse_ticket_bsoft(image_bytes: bytes) -> dict:
    errors = []
    try:
        raw_text = _ocr_image(image_bytes)
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return {
            "raw_text": "",
            "header": {},
            "items": [],
            "parse_errors": [f"Error OCR: {str(e)}"],
        }

    logger.info(f"OCR text length: {len(raw_text)} chars")
    header = _parse_header_from_text(raw_text)
    items = _parse_items_from_text(raw_text)

    if not items:
        errors.append("No se detectaron items en la imagen. Verifica que sea un ticket BsSoft.")

    return {
        "raw_text": raw_text,
        "header": header,
        "items": items,
        "parse_errors": errors,
    }


def merge_items_multiples(lista_parseos: list[dict]) -> dict:
    merged: dict[str, dict] = {}
    headers = []
    all_errors = []
    raw_texts = []

    for parseo in lista_parseos:
        headers.append(parseo.get("header", {}))
        all_errors.extend(parseo.get("parse_errors", []))
        raw_texts.append(parseo.get("raw_text", ""))

        for item in parseo.get("items", []):
            sku = item["sku"]
            if sku in merged:
                merged[sku]["cantidad"] += item["cantidad"]
                merged[sku]["total"] = round(
                    merged[sku]["precio"] * merged[sku]["cantidad"], 2
                )
            else:
                merged[sku] = dict(item)

    return {
        "items": list(merged.values()),
        "headers": headers,
        "all_errors": all_errors,
        "raw_texts": raw_texts,
    }
