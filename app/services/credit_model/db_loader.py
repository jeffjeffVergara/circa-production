"""Ejecución de carga de bodegas piloto (Postgres directo o Supabase API)."""

from __future__ import annotations

import os
from typing import Any

from app.services.bodega_onboarding_snapshot import onboarding_alta_fields
from app.services.credit_model.constants import DB_ENV_VAR, DIMAX_ID
from app.services.credit_model.helpers import doc_info, titulo


def get_db_url() -> str:
    url = os.environ.get(DB_ENV_VAR, "").strip()
    if not url:
        raise RuntimeError(
            "No se encontro %s. Configura la cadena de conexion Postgres de Supabase."
            % DB_ENV_VAR
        )
    return url


def _linea_aprobada(record: dict[str, Any]) -> int:
    linea = record.get("linea_aprobada") or record.get("tier")
    if linea is None:
        raise ValueError("Falta linea_aprobada en el registro de carga")
    return max(1, int(linea))


def _verificacion_rows(bodega: dict, mappings: list[dict]) -> list[tuple]:
    rows: list[tuple] = [
        (
            "bodega",
            bodega.get("razon_social") or "",
            str(bodega.get("linea_aprobada") or ""),
            str(bodega.get("linea_disponible") or ""),
            str(bodega.get("estado") or ""),
        )
    ]
    for m in mappings:
        rows.append((
            "mapping",
            f"{bodega.get('razon_social', '')} -> {m.get('codigo', '')}",
            m.get("rol") or "",
            m.get("grupo") or "",
            m.get("dia_visita") or "",
        ))
    return rows


def ejecutar_bodega_supabase(record: dict[str, Any]) -> tuple[bool, Any]:
    """Carga una bodega usando el cliente Supabase (SUPABASE_URL + SERVICE_KEY)."""
    from app.services import db

    c = record.get("cliente") or {}
    tel = (record.get("sql") or {}).get("telefono") or record.get("telefono") or ""
    if not tel:
        return False, "Telefono de bodega no disponible"
    if not c.get("RazonSocial") and record.get("razon_social"):
        c = dict(c)
        c["RazonSocial"] = record["razon_social"]

    linea = _linea_aprobada(record)
    doc = doc_info(c.get("DNI/RUC"))
    alta = onboarding_alta_fields(linea)
    razon = str(c.get("RazonSocial", "")).strip()

    existing = (
        db.sb.table("bodegas")
        .select("id,razon_social,linea_aprobada,linea_disponible,estado")
        .eq("telefono_whatsapp", tel)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not existing:
        payload = {
            "distribuidor_id": DIMAX_ID,
            "razon_social": razon,
            "nombre_comercial": razon,
            "telefono_whatsapp": tel,
            "ruc": doc["ruc"],
            "dni_representante": doc["dni"],
            "solo_dni_sin_ruc": doc["solo_dni"],
            "direccion_fiscal": titulo(c.get("Direccion")),
            "direccion_despacho": titulo(c.get("Direccion")),
            "distrito": titulo(c.get("Distrito")),
            "es_test": False,
            "en_piloto": True,
            "estado": "inactivo",
            "linea_aprobada": linea,
            "linea_disponible": 0,
            "linea_alta": int(alta["linea_alta"]),
            "scoring_alta": int(alta["scoring_alta"]),
        }
        try:
            db.sb.table("bodegas").insert(payload).execute()
        except Exception as e:
            return False, str(e)

    bodega = (
        db.sb.table("bodegas")
        .select("id,razon_social,linea_aprobada,linea_disponible,estado")
        .eq("telefono_whatsapp", tel)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not bodega:
        return False, "No se pudo crear ni encontrar la bodega"
    bodega_row = bodega[0]
    bodega_id = bodega_row["id"]
    mapping_info: list[dict] = []

    for v in record.get("vendedores") or []:
        codigo = str(v.get("codigo") or "").strip()
        if not codigo:
            continue
        vrows = (
            db.sb.table("vendedores")
            .select("id")
            .eq("distribuidor_id", DIMAX_ID)
            .eq("codigo", codigo)
            .eq("activo", True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if vrows:
            vid = vrows[0]["id"]
        else:
            try:
                vins = (
                    db.sb.table("vendedores")
                    .insert({
                        "distribuidor_id": DIMAX_ID,
                        "codigo": codigo,
                        "nombre": str(v.get("nombre") or "").strip(),
                        "activo": True,
                    })
                    .execute()
                    .data
                    or []
                )
            except Exception as e:
                return False, f"Error creando vendedor {codigo}: {e}"
            if not vins:
                return False, f"No se pudo crear vendedor {codigo}"
            vid = vins[0]["id"]

        exists = (
            db.sb.table("bodega_vendedores")
            .select("id")
            .eq("bodega_id", bodega_id)
            .eq("vendedor_id", vid)
            .limit(1)
            .execute()
            .data
        )
        if not exists:
            try:
                db.sb.table("bodega_vendedores").insert({
                    "bodega_id": bodega_id,
                    "vendedor_id": vid,
                    "rol": v.get("rol"),
                    "grupo": v.get("grupo"),
                    "supervisor": v.get("supervisor"),
                    "dia_visita": v.get("dia_visita"),
                    "dia_entrega": v.get("dia_entrega"),
                    "activo": True,
                }).execute()
            except Exception as e:
                return False, f"Error mapeando vendedor {codigo}: {e}"

        mapping_info.append({
            "codigo": codigo,
            "rol": v.get("rol"),
            "grupo": v.get("grupo"),
            "dia_visita": v.get("dia_visita"),
        })

    return True, _verificacion_rows(bodega_row, mapping_info)


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


def _load_one(record: dict[str, Any], *, conn=None) -> tuple[bool, Any]:
    if conn is not None:
        return ejecutar_bodega(conn, record)
    return ejecutar_bodega_supabase(record)


def load_bodegas_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Carga bodegas ya procesadas (dict interno con sql/avisos).
    Usa CIRCA_DB_URL si está configurada; si no, Supabase API.
    """
    db_url = os.environ.get(DB_ENV_VAR, "").strip()
    conn = None
    if db_url:
        try:
            import psycopg2
        except ImportError as e:
            raise RuntimeError(
                "psycopg2-binary no instalado; necesario para cargar bodegas."
            ) from e
        conn = psycopg2.connect(db_url)

    resultados = []
    ok_count = 0
    fail_count = 0

    try:
        for b in records:
            nombre = str(b.get("razon_social") or b["cliente"].get("RazonSocial", "")).strip()
            tel = b.get("sql", {}).get("telefono") or b.get("telefono") or ""
            if b["avisos"]["revisar"] and not b.get("_confirmar_revision"):
                resultados.append({
                    "telefono": tel,
                    "nombre": nombre,
                    "ok": False,
                    "error": "Requiere confirmacion de revision",
                    "skipped": True,
                })
                continue
            exito, res = _load_one(b, conn=conn)
            if exito:
                ok_count += 1
                verif = [
                    {"tipo": row[0], "detalle": row[1], "extra": list(row[2:])}
                    for row in (res or [])
                ]
                resultados.append({
                    "telefono": tel,
                    "nombre": nombre,
                    "ok": True,
                    "verificacion": verif,
                })
            else:
                fail_count += 1
                resultados.append({
                    "telefono": tel,
                    "nombre": nombre,
                    "ok": False,
                    "error": str(res),
                })
    finally:
        if conn is not None:
            conn.close()

    return {
        "ok": ok_count,
        "fallo": fail_count,
        "resultados": resultados,
        "via": "postgres" if db_url else "supabase",
    }
