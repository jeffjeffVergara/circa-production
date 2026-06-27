"""Análisis de riesgo y alertas del modelo de líneas."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any

from app.services.credit_model.constants import (
    CICLO_LARGO_DIAS,
    CV_IRREGULAR,
    MIN_PEDIDOS_HISTORIAL,
    VENTANA_DIAS,
)
from app.services.credit_model.helpers import tier_para


def analizar(hist) -> dict[str, Any] | None:
    por_fecha = defaultdict(float)
    for r in hist:
        if len(r) < 5:
            continue
        fecha, sellout = r[2], r[4]
        if fecha is not None and sellout is not None:
            por_fecha[fecha] += float(sellout)
    fechas = sorted(por_fecha)
    if not fechas:
        return None
    ultima = fechas[-1]
    corte = ultima - timedelta(days=VENTANA_DIAS)
    p6 = {f: v for f, v in por_fecha.items() if f >= corte}
    f6 = sorted(p6)
    n6 = len(f6)
    if n6 == 0:
        return None
    total6 = sum(p6.values())
    ticket = total6 / n6
    ticket_maximo = max(p6.values()) if p6 else ticket
    cv = None
    if n6 > 1:
        difs = [(f6[i + 1] - f6[i]).days for i in range(len(f6) - 1)]
        dias_entre = sum(difs) / len(difs)
        if len(difs) >= 2 and dias_entre:
            cv = statistics.pstdev(difs) / dias_entre
    else:
        dias_entre = float(VENTANA_DIAS)
    consumo_diario = ticket / dias_entre if dias_entre else ticket
    linea_7d = consumo_diario * 7
    return {
        "desde": corte,
        "hasta": ultima,
        "pedidos": n6,
        "total": total6,
        "ticket": ticket,
        "ticket_maximo": ticket_maximo,
        "dias_entre": dias_entre,
        "cv": cv,
        "consumo_diario": consumo_diario,
        "linea_7d": linea_7d,
        "tier": tier_para(linea_7d),
    }


def clasificar_avisos(a: dict[str, Any]) -> dict[str, list[str]]:
    revisar, notas = [], []

    if a["pedidos"] < MIN_PEDIDOS_HISTORIAL:
        revisar.append(
            "Historial corto: solo %d pedidos en 6 meses. Decidir si hay "
            "comportamiento suficiente para asignar linea." % a["pedidos"]
        )

    if a["linea_7d"] > 500:
        revisar.append(
            "El consumo de 7 dias (S/%.2f) supera el tier maximo de S/500. "
            "Bodega de alto volumen: revisar manualmente." % a["linea_7d"]
        )

    if a["dias_entre"] > CICLO_LARGO_DIAS:
        revisar.append(
            "Ciclo de compra largo: compra cada ~%.0f dias, bastante mas que "
            "el plazo de credito de 7 dias. Bodega poco frecuente: monitorear "
            "de cerca el comportamiento de pago." % a["dias_entre"]
        )

    if a.get("cv") is not None and a["cv"] > CV_IRREGULAR:
        revisar.append(
            "Compra irregular: los intervalos entre pedidos varian mucho "
            "(coef. de variacion %.2f; lo regular es por debajo de %.2f). "
            "Comportamiento poco predecible: monitorear de cerca."
            % (a["cv"], CV_IRREGULAR)
        )

    if a["ticket"] > a["tier"]:
        notas.append(
            "Ticket promedio (S/%.2f) mayor que la linea (S/%d). Por politica "
            "conservadora se mantiene el tier; la bodega pagara la diferencia "
            "en efectivo. Sube de tier cuando tenga historial de pago."
            % (a["ticket"], a["tier"])
        )

    return {"revisar": revisar, "notas": notas}
