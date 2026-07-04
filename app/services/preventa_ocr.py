"""
preventa_ocr.py — Parser OCR para tickets BsSoft (screenshots de app)
Usa Tesseract (gratuito) + regex estructurado.

Formato esperado por item:
    DESCRIPCIÓN PRODUCTO
    Codigo : P0XXX
    Unidad : UND|CJA X N
    Cantidad : N
    Precio : XX.XX
    Total : XX.XX
"""

import re
import io
import logging
from typing import Optional

from PIL import Image, ImageFilter

logger = logging.getLogger("circa.ocr")

# --- Tesseract import (fail-safe) ---
try:
    import pytesseract
except ImportError:
    pytesseract = None
    logger.warning("pytesseract no instalado — OCR deshabilitado")


def _preprocess_image(img: Image.Image) -> Image.Image:
    """Convierte screenshot de app BsSoft a imagen óptima para Tesseract."""
    # Escalar si es muy pequeño (screenshots de celular suelen ser 1080px+)
    w, h = img.size
    if w < 800:
        ratio = 800 / w
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # Grayscale
    img = img.convert("L")

    # Sharpen ligeramente
    img = img.filter(ImageFilter.SHARPEN)

    # Binarizar con threshold adaptivo simple
    # Los tickets BsSoft tienen fondo oscuro+texto claro Y fondo claro+texto oscuro
    # Usamos threshold alto para capturar ambos
    img = img.point(lambda x: 255 if x > 140 else 0, "1")

    return img


def _ocr_image(image_bytes: bytes) -> str:
    """Ejecuta Tesseract sobre bytes de imagen. Retorna texto crudo."""
    if pytesseract is None:
        raise RuntimeError("pytesseract no disponible")

    img = Image.open(io.BytesIO(image_bytes))

    # Si es RGBA (screenshot con transparencia), convertir
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg

    processed = _preprocess_image(img)

    text = pytesseract.image_to_string(
        processed,
        lang="spa",
        config="--psm 6 --oem 3",  # PSM 6 = bloque uniforme de texto
    )
    return text


# --- Regex patterns para ticket BsSoft ---

# Item block: captura descripción, código, unidad, cantidad, precio, total
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

# Header patterns
_RE_DOC_NUM = re.compile(r"V\d{4}-\d{5,7}")
_RE_FECHA = re.compile(r"(\d{1,2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})")
_RE_ENTREGA = re.compile(r"F\.\s*Entrega\s*:?\s*(\d{1,2}/\d{2}/\d{4})", re.IGNORECASE)


def _parse_items_from_text(text: str) -> list[dict]:
    """
    Parsea texto OCR de ticket BsSoft y extrae items estructurados.
    Retorna lista de dicts con: sku, descripcion, unidad, pack_qty,
    cantidad, precio, total, es_bonificacion.
    """
    lines = text.split("\n")
    items = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Buscar línea con Codigo
        m_codigo = _RE_CODIGO.search(line)
        if not m_codigo:
            # Revisar si la línea actual es parte de un bloque de item
            # mirando las siguientes líneas
            if i + 1 < len(lines):
                m_codigo = _RE_CODIGO.search(lines[i + 1].strip())
                if m_codigo:
                    # La línea actual es la descripción
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
            # El código está en esta línea; la descripción es la línea anterior
            descripcion = lines[i - 1].strip() if i > 0 else ""

        sku_raw = m_codigo.group(1)
        # Normalizar: asegurar que empiece con P
        sku = sku_raw if sku_raw.startswith("P") else f"P{sku_raw}"

        # Buscar unidad, cantidad, precio, total en las siguientes 4-6 líneas
        unidad_tipo = ""
        pack_qty = 1
        cantidad = 1
        precio = 0.0
        total = 0.0

        search_window = "\n".join(
            lines[i : min(i + 6, len(lines))]
        )

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

        # Construir pack_size string para match con catalogo_distribuidor.unidades
        # Formato en BD: "CJA x 12", "UND x 1"
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

        # Avanzar pasado el bloque
        i += 5  # Saltar las líneas del bloque (Codigo/Unidad/Cantidad/Precio/Total)

    return items


def _parse_header_from_text(text: str) -> dict:
    """Extrae metadata del header del ticket."""
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
    """
    Pipeline completo: imagen → OCR → parse → items estructurados.

    Retorna:
        {
            "raw_text": str,           # texto OCR crudo (para debug)
            "header": dict,            # metadata del ticket
            "items": list[dict],       # items parseados
            "parse_errors": list[str], # errores de parsing
        }
    """
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
    logger.debug(f"OCR raw:\n{raw_text}")

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
    """
    Combina items de múltiples imágenes (páginas de un mismo ticket).

    Regla: si el mismo SKU aparece en múltiples imágenes, SUMA cantidades.
    Rationale: fotos de páginas consecutivas del mismo ticket.

    Retorna:
        {
            "items": list[dict],       # items combinados
            "headers": list[dict],     # headers de cada imagen
            "all_errors": list[str],   # errores acumulados
            "raw_texts": list[str],    # textos crudos por imagen
        }
    """
    merged: dict[str, dict] = {}  # keyed by SKU
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
                # Sumar cantidad
                merged[sku]["cantidad"] += item["cantidad"]
                # Recalcular total
                merged[sku]["total"] = round(
                    merged[sku]["precio"] * merged[sku]["cantidad"], 2
                )
            else:
                merged[sku] = dict(item)  # copy

    return {
        "items": list(merged.values()),
        "headers": headers,
        "all_errors": all_errors,
        "raw_texts": raw_texts,
    }
