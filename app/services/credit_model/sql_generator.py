"""Generación SQL para alta de bodega piloto."""

from __future__ import annotations

from typing import Any

from app.services.credit_model.constants import DIMAX_ID
from app.services.credit_model.helpers import (
    dia_min,
    doc_info,
    normaliza_grupo,
    rol_de,
    sql_str,
    telefono_e164,
    titulo,
)


def generar_sql(b: dict[str, Any]) -> dict[str, Any]:
    c = b["cliente"]
    a = b["analisis"]
    doc = doc_info(c.get("DNI/RUC"))
    tel = telefono_e164(c.get("TELEFONO"))
    razon = str(c.get("RazonSocial", "")).strip()
    direccion = titulo(c.get("Direccion"))
    distrito = titulo(c.get("Distrito"))
    tier = a["tier"]

    vendedores = []
    for n in ("1", "2"):
        cod = c.get("COD VENDEDOR " + n)
        if not cod:
            continue
        grupo = c.get("GRUPO " + n)
        vendedores.append({
            "codigo": str(cod).strip(),
            "nombre": str(c.get("VENDEDOR " + n, "")).strip(),
            "rol": rol_de(grupo),
            "grupo": normaliza_grupo(grupo),
            "supervisor": str(c.get("SUPERVISOR " + n, "")).strip(),
            "dia_visita": dia_min(c.get("DIA VISITA " + n)),
            "dia_entrega": dia_min(c.get("DIA ENTREGA " + n)),
        })

    ins = []
    for v in vendedores:
        ins.append("-- Vendedor %s (%s) - se crea solo si no existe"
                    % (v["codigo"], v["nombre"]))
        ins.append("INSERT INTO vendedores (distribuidor_id, codigo, nombre, activo)")
        ins.append("SELECT %s, %s, %s, true" % (
            sql_str(DIMAX_ID), sql_str(v["codigo"]), sql_str(v["nombre"])))
        ins.append("WHERE NOT EXISTS (SELECT 1 FROM vendedores")
        ins.append("  WHERE codigo = %s AND distribuidor_id = %s);"
                    % (sql_str(v["codigo"]), sql_str(DIMAX_ID)))
        ins.append("")

    ins.append("-- Crear la bodega (estado inactivo, disponible 0 hasta onboarding)")
    ins.append("INSERT INTO bodegas (")
    ins.append("  distribuidor_id, razon_social, nombre_comercial, telefono_whatsapp,")
    ins.append("  ruc, dni_representante, solo_dni_sin_ruc,")
    ins.append("  direccion_fiscal, direccion_despacho, distrito,")
    ins.append("  es_test, en_piloto, estado, linea_aprobada, linea_disponible)")
    ins.append("SELECT %s, %s, %s, %s," % (
        sql_str(DIMAX_ID), sql_str(razon), sql_str(razon), sql_str(tel)))
    ins.append("       %s, %s, %s," % (
        sql_str(doc["ruc"]), sql_str(doc["dni"]),
        "true" if doc["solo_dni"] else "false"))
    ins.append("       %s, %s, %s," % (
        sql_str(direccion), sql_str(direccion), sql_str(distrito)))
    ins.append("       false, true, 'inactivo', %d, 0" % tier)
    ins.append("WHERE NOT EXISTS (")
    ins.append("  SELECT 1 FROM bodegas WHERE telefono_whatsapp = %s);" % sql_str(tel))
    ins.append("")

    if vendedores:
        ins.append("-- Mapear vendedores a la bodega")
        ins.append("INSERT INTO bodega_vendedores")
        ins.append("  (bodega_id, vendedor_id, rol, grupo, supervisor,"
                    " dia_visita, dia_entrega, activo)")
        ins.append("SELECT b.id, v.id, t.rol, t.grupo, t.supervisor,"
                    " t.dia_visita, t.dia_entrega, true")
        ins.append("FROM (VALUES")
        filas_v = ["  (%s, %s, %s, %s, %s, %s)" % (
            sql_str(v["codigo"]), sql_str(v["rol"]), sql_str(v["grupo"]),
            sql_str(v["supervisor"]), sql_str(v["dia_visita"]),
            sql_str(v["dia_entrega"])) for v in vendedores]
        ins.append(",\n".join(filas_v))
        ins.append(") AS t(vendedor_codigo, rol, grupo, supervisor,"
                    " dia_visita, dia_entrega)")
        ins.append("JOIN bodegas b ON b.telefono_whatsapp = %s" % sql_str(tel))
        ins.append("JOIN vendedores v ON v.codigo = t.vendedor_codigo")
        ins.append("              AND v.distribuidor_id = %s" % sql_str(DIMAX_ID))
        ins.append("              AND v.activo = true")
        ins.append("WHERE NOT EXISTS (SELECT 1 FROM bodega_vendedores bv")
        ins.append("  WHERE bv.bodega_id = b.id AND bv.vendedor_id = v.id);")

    verif = "\n".join([
        "SELECT 'bodega' AS tipo, razon_social AS detalle,",
        "       linea_aprobada::text AS aprob, linea_disponible::text AS disp,",
        "       estado::text AS estado",
        "FROM bodegas WHERE telefono_whatsapp = %s" % sql_str(tel),
        "UNION ALL",
        "SELECT 'mapping', b.razon_social || ' -> ' || v.codigo,",
        "       bv.rol, bv.grupo, bv.dia_visita",
        "FROM bodega_vendedores bv",
        "JOIN bodegas b ON b.id = bv.bodega_id",
        "JOIN vendedores v ON v.id = bv.vendedor_id",
        "WHERE b.telefono_whatsapp = %s;" % sql_str(tel),
    ])

    return {
        "inserts": "\n".join(ins),
        "verificacion": verif,
        "vendedores": vendedores,
        "telefono": tel,
    }


def sql_para_archivo(b: dict[str, Any]) -> str:
    s = b["sql"]
    cab = ("-- ====================================================\n"
           "-- Bodega: %s\n"
           "-- Linea aprobada: S/%d  (modelo: consumo 7d = S/%.2f)\n"
           "-- ====================================================\n"
           % (str(b["cliente"].get("RazonSocial", "")).strip(),
              b["analisis"]["tier"], b["analisis"]["linea_7d"]))
    return cab + "BEGIN;\n\n" + s["inserts"] + "\n\n" + s["verificacion"] + "\n\nCOMMIT;\n"
