"""Reporte Markdown del modelo de líneas."""

from __future__ import annotations

from typing import Any

from app.services.credit_model.helpers import etiqueta_regularidad
from app.services.credit_model.sql_generator import sql_para_archivo


def generar_ficha(b: dict[str, Any]) -> str:
    c, a = b["cliente"], b["analisis"]
    L = ["## %s" % str(c.get("RazonSocial", "")).strip(), ""]
    L.append("- Archivo: `%s`" % b["archivo"])
    L.append("- Codigo: %s  |  Documento: %s  |  Clasificacion: %s"
             % (c.get("Codigo"), c.get("DNI/RUC"), c.get("Clasificacion")))
    L.append("")
    L.append("### Analisis de riesgo (ultimos 6 meses)")
    L.append("")
    L.append("| Metrica | Valor |")
    L.append("|---|---|")
    L.append("| Periodo | %s -> %s |" % (a["desde"].date(), a["hasta"].date()))
    L.append("| Pedidos | %d |" % a["pedidos"])
    L.append("| Total comprado | S/%.2f |" % a["total"])
    L.append("| Ticket promedio | S/%.2f |" % a["ticket"])
    if a.get("ticket_maximo") is not None:
        L.append("| Ticket maximo | S/%.2f |" % a["ticket_maximo"])
    L.append("| Dias entre pedidos | %.1f |" % a["dias_entre"])
    L.append("| Regularidad de compra | %s |" % etiqueta_regularidad(a))
    L.append("| Consumo diario | S/%.2f |" % a["consumo_diario"])
    L.append("| Linea necesaria 7 dias | S/%.2f |" % a["linea_7d"])
    L.append("| **Tier asignado (conservador)** | **S/%d** |" % a["tier"])
    L.append("")
    if b["avisos"]["revisar"]:
        L.append("### ⚠ Necesita tu decision")
        L.append("")
        for x in b["avisos"]["revisar"]:
            L.append("- %s" % x)
        L.append("")
    if b["avisos"]["notas"]:
        L.append("### Notas")
        L.append("")
        for x in b["avisos"]["notas"]:
            L.append("- %s" % x)
        L.append("")
    L.append("### SQL de carga")
    L.append("")
    L.append("```sql")
    L.append(sql_para_archivo(b))
    L.append("```")
    L.append("")
    L.append("### Mensaje de WhatsApp")
    L.append("")
    L.append("```")
    L.append(b["mensaje"])
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    return "\n".join(L)


def generar_reporte_consolidado(procesadas: list[dict[str, Any]]) -> str:
    rep = [
        "# Circa - Reporte de carga de bodegas",
        "",
        "Generado por modelo de lineas de credito  |  %d bodega(s) procesada(s)"
        % len(procesadas),
        "",
        "---",
        "",
    ]
    for b in procesadas:
        rep.append(generar_ficha(b))
    return "\n".join(rep)


def generar_sql_consolidado(procesadas: list[dict[str, Any]]) -> str:
    parts = ["-- Circa - SQL de carga de bodegas", "-- Cada bodega es un bloque BEGIN/COMMIT independiente.", ""]
    for b in procesadas:
        parts.append(sql_para_archivo(b))
        parts.append("")
    return "\n".join(parts)
