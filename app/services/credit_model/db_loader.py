"""Ejecución del SQL de carga en Postgres."""

from __future__ import annotations

import os
from typing import Any

from app.services.credit_model.constants import DB_ENV_VAR


def get_db_url() -> str:
    url = os.environ.get(DB_ENV_VAR, "").strip()
    if not url:
        raise RuntimeError(
            "No se encontro %s. Configura la cadena de conexion Postgres de Supabase."
            % DB_ENV_VAR
        )
    return url


def ejecutar_bodega(conn, b: dict[str, Any]) -> tuple[bool, Any]:
    """Corre los INSERT de una bodega y devuelve (ok, resultado_verificacion)."""
    cur = conn.cursor()
    try:
        cur.execute(b["sql"]["inserts"])
        conn.commit()
        cur.execute(b["sql"]["verificacion"])
        filas = cur.fetchall()
        cur.close()
        return True, filas
    except Exception as e:
        conn.rollback()
        cur.close()
        return False, str(e)


def load_bodegas_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Carga bodegas ya procesadas (dict interno con sql/avisos).
    Cada item debe tener confirmar_revision=True si tenía avisos.revisar.
    """
    try:
        import psycopg2
    except ImportError as e:
        raise RuntimeError(
            "psycopg2-binary no instalado; necesario para cargar bodegas."
        ) from e

    conn = psycopg2.connect(get_db_url())
    resultados = []
    ok_count = 0
    fail_count = 0

    try:
        for b in records:
            nombre = str(b["cliente"].get("RazonSocial", "")).strip()
            if b["avisos"]["revisar"] and not b.get("_confirmar_revision"):
                resultados.append({
                    "telefono": b["sql"]["telefono"],
                    "nombre": nombre,
                    "ok": False,
                    "error": "Requiere confirmacion de revision",
                    "skipped": True,
                })
                continue
            exito, res = ejecutar_bodega(conn, b)
            if exito:
                ok_count += 1
                verif = [
                    {"tipo": row[0], "detalle": row[1], "extra": list(row[2:])}
                    for row in (res or [])
                ]
                resultados.append({
                    "telefono": b["sql"]["telefono"],
                    "nombre": nombre,
                    "ok": True,
                    "verificacion": verif,
                })
            else:
                fail_count += 1
                resultados.append({
                    "telefono": b["sql"]["telefono"],
                    "nombre": nombre,
                    "ok": False,
                    "error": str(res),
                })
    finally:
        conn.close()

    return {
        "ok": ok_count,
        "fallo": fail_count,
        "resultados": resultados,
    }
