"""
preventa_ocr.py — Parser OCR para tickets BsSoft (screenshots de app)
Tesseract + regex. Imports lazy para no crashear el app si falta dependencia.
"""

import re
import io
import logging

logger = logging.getLogger("circa.ocr")


def _ensure_deps():
    try:
        from PIL import Image, ImageFilter
        import pytesseract
        return Image, ImageFilter, pytesseract
    except ImportError as e:
        raise RuntimeError(f"Dependencia OCR faltante: {e}")


def _ocr_image(image_bytes: bytes) -> str:
    Image, _, pytesseract = _ensure_deps()

    img = Image.open(io.BytesIO(image_bytes))

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Scale up if small (phone screenshots ~720px need 2x for Tesseract)
    w, h = img.size
    if w < 1400:
        ratio = 2
        img = img.resize((w * ratio, h * ratio), Image.LANCZOS)

    # NO grayscale, NO binarization — Tesseract 4+ handles color images well
    # Raw RGB gives best results on BsSoft screenshots
    text = pytesseract.image_to_string(
        img,
        lang="spa",
        config="--psm 3 --oem 3",
    )

    # If spa produced nothing, try eng
    if len(text.strip()) < 20:
        logger.warning("spa produced little text, trying eng")
        text = pytesseract.image_to_string(
            img,
            lang="eng",
            config="--psm 3 --oem 3",
        )

    return text


def _normalize_sku(raw: str) -> str:
    """POO33 -> P0033 (OCR confuses O and 0)"""
    raw = raw.upper().strip()
    if raw.startswith("P"):
        return "P" + raw[1:].replace("O", "0")
    return raw.replace("O", "0")


# Regex patterns — allow O/0 interchangeably in codes
_RE_CODIGO = re.compile(
    r"C[oó]digo\s*:\s*(P?[0-9O]{3,5})",
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
_RE_FECHA = re.compile(r"(\d{1,2}/\d{2}/\d{4})\s+(\d{1,2}[: ]\d{2}[: ]?\d{0,2})")
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
                else:
                    i += 1
                    continue
            else:
                i += 1
                continue
        else:
            descripcion = lines[i - 1].strip() if i > 0 else ""

        sku = _normalize_sku(m_codigo.group(1))

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


def _extract_bodega_name(text: str) -> str:
    """Extrae nombre de bodega del header del ticket BsSoft.
    Es la primera línea con texto ALL-CAPS sustancial (>5 chars)."""
    lines = text.strip().split("\n")
    name_parts = []
    found_start = False
    for l in lines:
        l = l.strip()
        if not l or len(l) < 3:
            if found_start:
                break
            continue
        # Skip status bar (time pattern at start)
        if re.match(r'^\d{1,2}:\d{2}', l):
            continue
        # Skip lines with too many symbols/numbers (not a name)
        alpha_ratio = sum(1 for c in l if c.isalpha()) / max(len(l), 1)
        if alpha_ratio < 0.6:
            if found_start:
                break
            continue
        # Check if it looks like a name (mostly uppercase letters)
        cleaned = re.sub(r'^[^A-Za-zÁÉÍÓÚÑ]+', '', l)
        if cleaned and len(cleaned) > 3:
            if not found_start:
                found_start = True
            name_parts.append(cleaned)
            # Most bodega names are 1-2 lines
            if len(name_parts) >= 2:
                break
        elif found_start:
            break
    return " ".join(name_parts).strip()


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
    header["bodega_nombre"] = _extract_bodega_name(text)
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
                pass  # Dedup: mantener primera ocurrencia, ignorar duplicados
            else:
                merged[sku] = dict(item)

    return {
        "items": list(merged.values()),
        "headers": headers,
        "all_errors": all_errors,
        "raw_texts": raw_texts,
    }
