#!/usr/bin/env python3
"""Cobranzas VENCIDAS por vendedor (+ resumen por supervisor).

Reconstruye el flujo que generaba `Cobranzas_Vencidas_YYYY-MM-DD.txt`.
NO modifica circa_agente_vendedores.py: reutiliza sus funciones ya
validadas (mismo origen de datos que el mensaje de grupo).

Uso:
    python3 circa_cobranzas_vendedor.py                 # a stdout
    python3 circa_cobranzas_vendedor.py --fecha 2026-07-27
    python3 circa_cobranzas_vendedor.py --guardar       # escribe el .txt

Notas de criterio (no había código original que replicar exacto):
  - Solo VENCIDAS: dias_vencido >= 1 (excluye "vence hoy/mañana").
  - Monto = monto_total_credito, o (monto_financiado + fee_monto) si falta.
    Igual que build_grupo() en circa_agente_vendedores.py.
  - Nombre de vendedor: nombre_corto(); saludo: primer_nombre().
    Consistente con el agente actual (si la BD cambió el nombre, cambia aquí).
  - 🚨 se marca cuando dias_vencido >= UMBRAL_CRITICO (default 7).
"""
import sys
from datetime import date

import circa_agente_vendedores as ag

UMBRAL_CRITICO = 7  # días vencido para marcar 🚨 (editable)


def _fecha() -> date:
    forz = ag._fecha_cli()
    return forz or ag.hoy_lima()


def _dias_vencido(p, hoy: date) -> int:
    try:
        return (hoy - date.fromisoformat(p.get("fecha_vencimiento") or "")).days
    except ValueError:
        return 0


def _monto(p) -> float:
    return float(
        p.get("monto_total_credito")
        or ((p.get("monto_financiado") or 0) + (p.get("fee_monto") or 0))
    )


def _info_vendedores(client) -> dict:
    """codigo -> {celular, supervisor}. Columnas confirmadas por uso en
    circa_agente_vendedores.py (celular en q_visitas_hoy, supervisor en
    stats_comisiones)."""
    r = client.table("vendedores").select("codigo,celular,supervisor").execute()
    out = {}
    for v in r.data or []:
        cod = v.get("codigo")
        if cod:
            out[cod] = {
                "celular": (v.get("celular") or "").replace("+", "").replace(" ", ""),
                "supervisor": (v.get("supervisor") or "SIN SUPERVISOR").strip() or "SIN SUPERVISOR",
            }
    return out


def build_cobranzas(hoy: date, client) -> str:
    cobranza = ag.asignar_vendedor_cartera(
        ag.q_cobranza(client, hoy), ag.q_mapa_vendedores(client)
    )
    info = _info_vendedores(client)

    # Solo vencidas, agrupadas por vendedor de cartera.
    por_vend = {}  # codigo -> {"v":..., "items":[(bodega, monto, dias)]}
    for p in cobranza:
        dias = _dias_vencido(p, hoy)
        if dias < 1:
            continue
        v = p.get("vendedores") or {}
        cod = v.get("codigo") or "ZZZ"
        b = p.get("bodegas") or {}
        por_vend.setdefault(cod, {"v": v, "items": []})
        por_vend[cod]["items"].append((ag.nombre_bodega(b), _monto(p), dias))

    if not por_vend:
        return "✅ Hoy no hay cobranzas vencidas en ninguna cartera. 🎉"

    for d in por_vend.values():
        d["items"].sort(key=lambda x: (-x[2], -x[1]))  # dias desc, monto desc
        d["total"] = sum(m for _, m, _ in d["items"])

    orden = sorted(por_vend.items(), key=lambda kv: -kv[1]["total"])

    # ── PARTE 1 — mensaje por vendedor ────────────────────────────────
    L = ["=" * 60, "PARTE 1 — MENSAJE POR VENDEDOR (cobranza)", "=" * 60, ""]
    for cod, d in orden:
        v = d["v"]
        cel = info.get(cod, {}).get("celular", "")
        link = f" · wa.me/{cel}" if cel else ""
        L.append(f">>> PARA: {cod} · {ag.nombre_corto(v)}{link}")
        L.append("-" * 30)
        L.append(f"Hola {ag.primer_nombre(v)}! 📌 Cobranzas vencidas de tu "
                 f"cartera — ayúdalas a ponerse al día hoy:")
        for nom, monto, dias in d["items"]:
            crit = " 🚨" if dias >= UMBRAL_CRITICO else ""
            L.append(f"  🔴 {nom} · {ag.fmt_monto(monto)} · {dias} día(s) vencido{crit}")
        L.append(f"  💰 Total por cobrar: {ag.fmt_monto(d['total'])}")
        L.append("Un recordatorio o visita hoy destraba el pago. ¡Gracias! 💙")
        L.append("")

    # ── PARTE 2 — resumen por supervisor ──────────────────────────────
    por_sup = {}  # supervisor -> [(cod, d)]
    for cod, d in orden:
        sup = info.get(cod, {}).get("supervisor", "SIN SUPERVISOR")
        por_sup.setdefault(sup, []).append((cod, d))

    L += ["", "=" * 60, "PARTE 2 — RESUMEN POR SUPERVISOR", "=" * 60, ""]
    for sup in sorted(por_sup):
        vends = sorted(por_sup[sup], key=lambda kv: -kv[1]["total"])
        n_bod = sum(len(d["items"]) for _, d in vends)
        tot = sum(d["total"] for _, d in vends)
        L.append(f">>> PARA SUPERVISOR: {sup}")
        L.append("-" * 30)
        L.append(f"Cobranzas vencidas de tu equipo: {n_bod} bodega(s) · {ag.fmt_monto(tot)}")
        for _, d in vends:
            det = ", ".join(f"{nom} {ag.fmt_monto(m)} ({dias}d)"
                            for nom, m, dias in d["items"])
            L.append(f"  • {ag.nombre_corto(d['v'])} — {len(d['items'])} · "
                     f"{ag.fmt_monto(d['total'])}: {det}")
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def main():
    hoy = _fecha()
    client = ag.sb()
    texto = build_cobranzas(hoy, client)
    print(texto)
    if "--guardar" in sys.argv:
        import os
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f"Cobranzas_Vencidas_{hoy.isoformat()}.txt")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
        print(f"\n💾 Guardado: {ruta}", file=sys.stderr)


if __name__ == "__main__":
    main()
