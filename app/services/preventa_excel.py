"""
Parser del Excel de preventa que sale del sistema DIMAX.

Convierte el archivo en la estructura que espera db.crear_pedido_preventa:
    items_dimax = [{sku_distribuidor, descripcion, cantidad, unidad,
                    precio_unitario, subtotal}, ...]
mas total_pedido, descuento_prorrateado, y la bodega/fecha leidas del
nombre del archivo (que es como DIMAX identifica al cliente).

Reglas del formato DIMAX (validadas contra archivos reales):
- 'Total' = monto cobrado real (ya con descuento). 'SubTotal' = antes de descuento.
- Filas BONIFICACION tienen Total = 0 -> son regalos (no se cobran).
- 'Codigo' viene con ceros a la izquierda; el catalogo guarda sin ceros (lstrip).
- 'Unidad' "UND x 1" / "CJA X 24" (X mayus o minus) -> pack_size case-insensitive.
- El nombre del archivo trae bodega y fecha. Separadores reales vistos:
  "NOMBRE BODEGA 04.06.26.xlsx" (espacios + puntos) y tambien guiones bajos.
"""
import os
import re

import openpyxl

COL_CODIGO = "Codigo"
COL_DESCRIPCION = "Descripcion"
COL_CANTIDAD = "Cantidad"
COL_UNIDAD = "Unidad"
COL_PRECIO = "P. Unitario"
COL_SUBTOTAL = "SubTotal"
COL_TOTAL = "Total"

# Fecha al final del nombre: DD<sep>MM<sep>YY(YY), sep = espacio/punto/guion/guion_bajo
_FECHA_RE = re.compile(r"[ ._\-]+(\d{1,2})[ ._\-](\d{1,2})[ ._\-](\d{2,4})\s*$")


def parse_filename(filename: str):
    """'URBANO CHIHUANTITO DAVID GENARO 04.06.26.xlsx' o 'NOMBRE_preventa.xlsx'
       -> ('URBANO CHIHUANTITO DAVID GENARO', '2026-06-04').
       Si no hay fecha al final, devuelve (nombre_limpio, None)."""
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    base = re.sub(r"[_\s\-]+preventa\s*$", "", base, flags=re.I)
    fecha_iso, nombre_part = None, base
    m = _FECHA_RE.search(base)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        anio = yy if len(yy) == 4 else ("20" + yy)
        try:
            fecha_iso = "%04d-%02d-%02d" % (int(anio), int(mm), int(dd))
        except ValueError:
            fecha_iso = None
        nombre_part = base[:m.start()]
    nombre = re.sub(r"\s+", " ", re.sub(r"[._\-]+", " ", nombre_part)).strip()
    return nombre, fecha_iso


def _pack_size(unidad) -> int:
    try:
        return int(str(unidad).lower().split("x")[-1].strip())
    except (ValueError, AttributeError):
        return 1


def parse_preventa_excel(source, filename: str = None) -> dict:
    """source: ruta (str) o archivo en memoria (BytesIO/bytes).
       filename: nombre original (para sacar bodega/fecha). Si source es ruta y
       filename es None, se usa la ruta."""
    name_for_parse = filename if filename is not None else (source if isinstance(source, str) else "")
    bodega_nombre, fecha = parse_filename(name_for_parse)

    if isinstance(source, (bytes, bytearray)):
        import io
        source = io.BytesIO(source)

    wb = openpyxl.load_workbook(source, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("El Excel esta vacio.")

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(headers)}
    faltantes = [c for c in (COL_CODIGO, COL_CANTIDAD, COL_PRECIO, COL_TOTAL) if c not in idx]
    if faltantes:
        raise ValueError(f"Faltan columnas {faltantes}. Encontre: {headers}")

    def col(row, name, default=None):
        i = idx.get(name)
        return row[i] if (i is not None and i < len(row)) else default

    items, warnings = [], []
    total_pedido = descuento = 0.0
    n_regalos = 0
    for r in rows[1:]:
        cod = col(r, COL_CODIGO)
        if cod is None or str(cod).strip() == "":
            continue
        desc = str(col(r, COL_DESCRIPCION) or "").strip()
        try:
            cant = int(col(r, COL_CANTIDAD) or 0)
        except (ValueError, TypeError):
            cant = 0
            warnings.append(f"Cantidad invalida en SKU {cod}, use 0.")
        unidad = str(col(r, COL_UNIDAD) or "UND x 1").strip()
        precio = round(float(col(r, COL_PRECIO) or 0), 4)
        subt = round(float(col(r, COL_SUBTOTAL) or 0), 2)
        total_l = round(float(col(r, COL_TOTAL) or 0), 2)
        es_regalo = (total_l == 0) or desc.upper().startswith("BONIFICAC")
        if es_regalo:
            n_regalos += 1
        else:
            total_pedido += total_l
            descuento += round(subt - total_l, 2)
        items.append({
            "sku_distribuidor": str(cod).strip().lstrip("0") or "0",
            "descripcion": desc, "cantidad": cant, "unidad": unidad,
            "pack_size": _pack_size(unidad), "precio_unitario": precio,
            "subtotal": total_l, "es_regalo": es_regalo,
        })
    if not items:
        raise ValueError("El Excel no tiene filas de productos.")
    total_pedido, descuento = round(total_pedido, 2), round(descuento, 2)
    return {
        "bodega_nombre": bodega_nombre, "fecha": fecha, "items": items,
        "total_pedido": total_pedido, "descuento_prorrateado": descuento,
        "monto_productos": round(total_pedido + descuento, 2),
        "n_items": len([i for i in items if not i["es_regalo"]]),
        "n_regalos": n_regalos, "warnings": warnings,
    }


def _norm_nombre(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper().strip())


def match_bodega_por_nombre(nombre_archivo: str, distribuidor_id: str) -> tuple[dict | None, list[dict]]:
    """Busca bodega del distribuidor similar al nombre del archivo Excel."""
    from app.services import db as circa_db

    target = _norm_nombre(nombre_archivo)
    if not target:
        return None, []
    filas = circa_db.sb.table("bodegas").select(
        "id, razon_social, nombre_comercial, distrito, linea_disponible, estado, distribuidor_id"
    ).eq("distribuidor_id", distribuidor_id).execute().data or []
    tset = set(target.split())
    scored: list[tuple[int, dict]] = []
    for b in filas:
        score = 0
        for campo in (b.get("razon_social"), b.get("nombre_comercial")):
            c = _norm_nombre(campo)
            if not c:
                continue
            if c == target:
                score = 100
                break
            cset = set(c.split())
            if tset and cset:
                ov = len(tset & cset) / len(tset | cset)
                score = max(score, int(round(ov * 100)))
        if score >= 55:
            scored.append((score, b))
    scored.sort(key=lambda x: x[0], reverse=True)
    candidatos = [{
        "id": b["id"],
        "razon_social": b.get("razon_social") or b.get("nombre_comercial") or "(sin nombre)",
        "distrito": b.get("distrito") or "",
        "linea_disponible": b.get("linea_disponible") or 0,
        "estado": b.get("estado") or "",
        "score": s,
    } for s, b in scored[:5]]
    sugerida = candidatos[0] if (candidatos and candidatos[0]["score"] >= 80) else None
    return sugerida, candidatos


if __name__ == "__main__":
    import sys, json
    res = parse_preventa_excel(sys.argv[1])
    print(json.dumps({k: v for k, v in res.items() if k != "items"}, indent=2, ensure_ascii=False))
