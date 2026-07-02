"""Orquestación del modelo de líneas de crédito."""

from __future__ import annotations

import glob
import os
from datetime import date, datetime
from typing import Any

from app.services.credit_model.constants import MODELO_ID
from app.services.credit_model.db_loader import ejecutar_bodega, get_db_url, load_bodegas_records
from app.services.credit_model.excel_reader import leer_bodega, leer_bodega_bytes
from app.services.credit_model.report_generator import (
    generar_reporte_consolidado,
    generar_sql_consolidado,
)
from app.services.credit_model.risk_analyzer import analizar, clasificar_avisos
from app.services.credit_model.sql_generator import generar_sql, sql_para_archivo
from app.services.credit_model.whatsapp_generator import generar_mensaje


def _json_val(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _serialize_cliente(cliente: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _json_val(v) for k, v in cliente.items()}


def _serialize_analisis(analisis: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in analisis.items():
        if k in ("desde", "hasta"):
            out[k] = v.date().isoformat() if hasattr(v, "date") else _json_val(v)
        else:
            out[k] = _json_val(v) if not isinstance(v, float) else round(v, 4) if v is not None else None
    return out


def enrich_bodega_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Añade análisis, avisos, SQL y mensaje a un registro leído del Excel."""
    a = analizar(raw["historial"])
    if not a:
        return None
    raw = dict(raw)
    raw["analisis"] = a
    raw["avisos"] = clasificar_avisos(a)
    raw["sql"] = generar_sql(raw)
    raw["mensaje"] = generar_mensaje(raw)
    return raw


def serialize_bodega(b: dict[str, Any]) -> dict[str, Any]:
    """Representación JSON para API / front."""
    c = b["cliente"]
    a = b["analisis"]
    return {
        "archivo": b.get("archivo", ""),
        "codigo": str(c.get("Codigo", "")).strip(),
        "razon_social": str(c.get("RazonSocial", "")).strip(),
        "telefono": b["sql"]["telefono"],
        "documento": _json_val(c.get("DNI/RUC")),
        "clasificacion": _json_val(c.get("Clasificacion")),
        "cliente": _serialize_cliente(c),
        "analisis": _serialize_analisis(a),
        "avisos": b["avisos"],
        "necesita_revision": bool(b["avisos"]["revisar"]),
        "tier": a["tier"],
        "tier_modelo": a["tier"],
        "linea_7d": round(float(a["linea_7d"]), 2),
        "mensaje": b["mensaje"],
        "reporte_ficha": _ficha_resumen(b),
        "sql_block": sql_para_archivo(b),
        "sql_inserts": b["sql"]["inserts"],
        "sql_verificacion": b["sql"]["verificacion"],
        "vendedores": b["sql"]["vendedores"],
    }


def _ficha_resumen(b: dict[str, Any]) -> str:
    from app.services.credit_model.report_generator import generar_ficha

    return generar_ficha(b)


def process_path(path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = leer_bodega(path)
    except Exception as e:
        return None, str(e)
    enriched = enrich_bodega_record(raw)
    if not enriched:
        return None, "Sin historial de compras utilizable."
    return enriched, None


def process_bytes(content: bytes, filename: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = leer_bodega_bytes(content, filename)
    except Exception as e:
        return None, str(e)
    enriched = enrich_bodega_record(raw)
    if not enriched:
        return None, "Sin historial de compras utilizable."
    return enriched, None


def process_files(
    file_items: list[tuple[bytes, str]],
) -> dict[str, Any]:
    """Procesa uno o más Excel DIMAX (bytes + nombre)."""
    procesadas: list[dict[str, Any]] = []
    errores: list[dict[str, str]] = []
    vistos: dict[str, str] = {}

    for content, filename in file_items:
        nombre = filename or "upload.xlsx"
        b, err = process_bytes(content, nombre)
        if err:
            errores.append({"archivo": nombre, "error": err})
            continue
        codigo = str(b["cliente"].get("Codigo", "")).strip()
        if codigo and codigo in vistos:
            errores.append({
                "archivo": nombre,
                "error": "DUPLICADO: codigo %s ya estaba en %s. Se omite."
                % (codigo, vistos[codigo]),
            })
            continue
        if codigo:
            vistos[codigo] = nombre
        procesadas.append(b)

    serializadas = [serialize_bodega(b) for b in procesadas]
    return {
        "modelo": MODELO_ID,
        "total": len(serializadas),
        "revisar": sum(1 for s in serializadas if s["necesita_revision"]),
        "bodegas": serializadas,
        "errores": errores,
        "reporte_md": generar_reporte_consolidado(procesadas) if procesadas else "",
        "sql_consolidado": generar_sql_consolidado(procesadas) if procesadas else "",
    }


def apply_linea_to_load_item(item: dict[str, Any]) -> dict[str, Any]:
    """Aplica linea_aprobada opcional al SQL de carga."""
    from app.services.credit_model.sql_generator import (
        extract_linea_from_sql_inserts,
        patch_sql_linea,
        sql_block_from_parts,
    )

    out = dict(item)
    linea = out.get("linea_aprobada")
    if linea is None:
        linea = extract_linea_from_sql_inserts(out.get("sql_inserts") or "")
    if linea is None:
        return out
    linea = int(linea)
    if linea < 1:
        raise ValueError("La línea debe ser mayor a 0")
    inserts = patch_sql_linea(out["sql_inserts"], linea)
    out["sql_inserts"] = inserts
    out["tier"] = linea
    out["linea_aprobada"] = linea
    out["sql_block"] = sql_block_from_parts(
        razon_social=out.get("razon_social") or "",
        linea_aprobada=linea,
        linea_7d=float(out.get("linea_7d") or 0),
        sql_inserts=inserts,
        sql_verificacion=out["sql_verificacion"],
    )
    return out


def record_from_load_item(item: dict[str, Any]) -> dict[str, Any]:
    """Reconstruye registro mínimo para db_loader desde payload del front."""
    from app.services.credit_model.sql_generator import extract_linea_from_sql_inserts

    item = apply_linea_to_load_item(item)
    necesita = bool(item.get("necesita_revision"))
    confirmada = bool(item.get("confirmar_revision"))
    revisar: list[str] = []
    if necesita and not confirmada:
        revisar = ["Requiere confirmacion de revision en backoffice"]
    cliente = item.get("cliente") or {}
    if not cliente.get("RazonSocial") and item.get("razon_social"):
        cliente = dict(cliente)
        cliente["RazonSocial"] = item["razon_social"]
    linea = (
        item.get("linea_aprobada")
        or item.get("tier")
        or extract_linea_from_sql_inserts(item.get("sql_inserts") or "")
    )
    return {
        "cliente": cliente,
        "razon_social": item.get("razon_social") or cliente.get("RazonSocial") or "",
        "telefono": item.get("telefono"),
        "vendedores": item.get("vendedores") or [],
        "linea_aprobada": linea,
        "avisos": {"revisar": revisar, "notas": []},
        "_confirmar_revision": confirmada,
        "sql": {
            "inserts": item["sql_inserts"],
            "verificacion": item["sql_verificacion"],
            "telefono": item["telefono"],
        },
    }


def load_bodegas_from_api(items: list[dict[str, Any]]) -> dict[str, Any]:
    records = [record_from_load_item(it) for it in items]
    return load_bodegas_records(records)


def juntar_archivos(args: list[str]) -> list[str]:
    archivos: list[str] = []
    for a in args:
        if os.path.isdir(a):
            archivos += sorted(glob.glob(os.path.join(a, "*.xlsx")))
        elif a.lower().endswith(".xlsx"):
            archivos.append(a)
    return archivos


def process_paths_cli(paths: list[str]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    procesadas: list[dict[str, Any]] = []
    errores: list[tuple[str, str]] = []
    vistos: dict[str, str] = {}

    for path in paths:
        nombre = os.path.basename(path)
        b, err = process_path(path)
        if err:
            errores.append((nombre, err))
            continue
        codigo = str(b["cliente"].get("Codigo", "")).strip()
        if codigo and codigo in vistos:
            errores.append((
                nombre,
                "DUPLICADO: codigo %s ya estaba en %s. Se omite." % (codigo, vistos[codigo]),
            ))
            continue
        if codigo:
            vistos[codigo] = nombre
        procesadas.append(b)
    return procesadas, errores


def escribir_salida_cli(procesadas: list[dict[str, Any]]) -> None:
    os.makedirs("salida_carga", exist_ok=True)
    reporte = generar_reporte_consolidado(procesadas)
    if reporte.startswith("# Circa"):
        reporte = reporte.replace(
            "# Circa - Reporte de carga de bodegas",
            "# Circa - Reporte de carga de bodegas\n\nGenerado por cargar_bodega.py",
            1,
        )
    with open("salida_carga/reporte_bodegas.md", "w", encoding="utf-8") as f:
        f.write(reporte)
    sql = generar_sql_consolidado(procesadas)
    with open("salida_carga/carga_bodegas.sql", "w", encoding="utf-8") as f:
        f.write(sql)


def correr_modo_ejecutar_cli(procesadas: list[dict[str, Any]]) -> None:
    """Carga interactiva por consola (modo --ejecutar del CLI)."""
    import sys

    try:
        get_db_url()
    except RuntimeError as e:
        print("\n%s" % e)
        sys.exit(1)
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        print("\nEl modo --ejecutar necesita psycopg2. Instalalo con:")
        print("    pip3 install psycopg2-binary")
        sys.exit(1)
    import psycopg2

    limpias = [b for b in procesadas if not b["avisos"]["revisar"]]
    a_revisar = [b for b in procesadas if b["avisos"]["revisar"]]
    aprobadas: list[dict[str, Any]] = []

    if limpias:
        print("\nBodegas listas para cargar (sin observaciones):")
        for b in limpias:
            print("  - %-40s linea S/%d" % (
                str(b["cliente"].get("RazonSocial", ""))[:40],
                b["analisis"]["tier"],
            ))
        r = input(
            "\nEscribi CARGAR para cargar estas %d bodegas (o ENTER para saltarlas): "
            % len(limpias)
        ).strip()
        if r == "CARGAR":
            aprobadas += limpias
        else:
            print("  -> se omiten las bodegas limpias.")

    for b in a_revisar:
        nombre = str(b["cliente"].get("RazonSocial", "")).strip()
        print("\n--- REVISAR: %s (linea S/%d) ---" % (nombre, b["analisis"]["tier"]))
        for x in b["avisos"]["revisar"]:
            print("  ! %s" % x)
        r = input("Cargar esta bodega igual? (si / no): ").strip().lower()
        if r == "si":
            b_copy = dict(b)
            b_copy["_confirmar_revision"] = True
            aprobadas.append(b_copy)
        else:
            print("  -> omitida.")

    if not aprobadas:
        print("\nNo se aprobo ninguna bodega. Nada que cargar.")
        return

    print("\nConectando a la base...")
    conn = psycopg2.connect(get_db_url())
    ok, fallo = 0, 0
    for b in aprobadas:
        nombre = str(b["cliente"].get("RazonSocial", "")).strip()
        exito, res = ejecutar_bodega(conn, b)
        if exito:
            ok += 1
            print("\n  OK  %s" % nombre)
            for fila in res:
                print("       " + " | ".join(str(x) for x in fila))
        else:
            fallo += 1
            print("\n  ERROR  %s" % nombre)
            print("       %s" % res)
    conn.close()
    print("\n=== Carga terminada: %d cargada(s), %d con error ===" % (ok, fallo))
