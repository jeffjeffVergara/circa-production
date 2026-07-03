"""
Reporte diario de cobranzas.
Endpoint: GET /api/distribuidor/admin/cobranzas/reporte-diario
Retorna HTML con tabla de pedidos vencidos/por vencer.
"""

import logging
from datetime import datetime, timedelta
from app.services import db

logger = logging.getLogger("circa.jobs.cobranza_diaria")


async def get_pedidos_vencidos() -> list:
    """Pedidos financiados vencidos o que vencen mañana."""
    tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()

    pedidos = (
        db.sb.table("pedidos")
        .select(
            "id, numero, estado, monto_financiado, fee_monto, "
            "monto_total_credito, fecha_vencimiento, plazo_dias, "
            "bodega_id, bodegas(razon_social)"
        )
        .in_("estado", ["entregado", "preventa_aceptada", "confirmado"])
        .gt("monto_financiado", 0)
        .lte("fecha_vencimiento", tomorrow)
        .order("fecha_vencimiento")
        .execute()
    ).data or []

    seen = set()
    rows = []
    for p in pedidos:
        if p["id"] in seen:
            continue
        seen.add(p["id"])

        numero = p.get("numero") or "—"
        if numero.startswith("TEST-"):
            continue

        razon = (p.get("bodegas") or {}).get("razon_social", "?")
        bod_id = p.get("bodega_id")

        vendor = "—"
        try:
            bv = (
                db.sb.table("bodega_vendedores")
                .select("vendedores(codigo, nombre)")
                .eq("bodega_id", bod_id)
                .eq("activo", True)
                .order("created_at")
                .limit(1)
                .execute()
            ).data
            if bv and bv[0].get("vendedores"):
                v = bv[0]["vendedores"]
                nombre_corto = v["nombre"].split()[0]
                vendor = f"{v['codigo']} {nombre_corto}"
        except Exception:
            pass

        fv = p.get("fecha_vencimiento")
        dias = (datetime.now().date() - datetime.strptime(fv, "%Y-%m-%d").date()).days if fv else 0

        rows.append({
            "numero": numero,
            "razon_social": razon,
            "vendedor": vendor,
            "monto_financiado": float(p.get("monto_financiado") or 0),
            "debe": float(p.get("monto_total_credito") or 0),
            "fecha_vencimiento": fv,
            "dias_vencido": dias,
        })

    rows.sort(key=lambda r: r["fecha_vencimiento"] or "")
    return rows


def render_html(rows: list) -> str:
    fecha = datetime.now().strftime("%d/%m/%Y")
    total_debe = sum(r["debe"] for r in rows)

    def badge(dias):
        if dias > 0:
            return f'<span class="badge red">\U0001f534 {dias}d vencido</span>'
        elif dias == 0:
            return '<span class="badge yellow">\U0001f7e1 Hoy</span>'
        else:
            return '<span class="badge green">\U0001f7e2 Mañana</span>'

    def razon_corta(r, mx=22):
        parts = r.split()
        return " ".join(parts[:2])[:mx] if len(parts) > 2 else r[:mx]

    trs = ""
    for r in rows:
        fv = datetime.strptime(r["fecha_vencimiento"], "%Y-%m-%d").strftime("%d/%m") if r["fecha_vencimiento"] else "—"
        trs += f"""<tr>
      <td>{r['numero']}</td>
      <td>{razon_corta(r['razon_social'])}</td>
      <td>{r['vendedor']}</td>
      <td>S/{r['monto_financiado']:.0f}</td>
      <td class="monto">S/{r['debe']:.2f}</td>
      <td>{fv}</td>
      <td>{badge(r['dias_vencido'])}</td>
    </tr>\n"""

    trs += f"""<tr class="total">
      <td colspan="4"><b>TOTAL</b></td>
      <td class="monto"><b>S/{total_debe:.2f}</b></td>
      <td colspan="2">{len(rows)} pedido(s)</td>
    </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Poppins',sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}
.hdr{{display:flex;align-items:center;gap:10px;margin-bottom:14px}}
.logo{{font-size:20px;font-weight:700;color:#4fc3f7}}
.date{{font-size:12px;color:#888}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#16213e;color:#4fc3f7;padding:8px 6px;text-align:left;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px}}
td{{padding:8px 6px;border-bottom:1px solid #2a2a4a}}
.monto{{font-weight:700;color:#fff}}
.badge{{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600}}
.red{{background:#ff525233;color:#ff5252}}
.yellow{{background:#ffd74033;color:#ffd740}}
.green{{background:#69f0ae33;color:#69f0ae}}
.total td{{border-top:2px solid #4fc3f7;background:#16213e}}
</style></head>
<body>
<div class="hdr">
  <span class="logo">CIRCA</span>
  <span class="date">Cobranzas — {fecha}</span>
</div>
<table>
<thead><tr>
  <th>Pedido</th><th>Bodega</th><th>Vendedor</th><th>Financiado</th><th>Debe</th><th>Vence</th><th>Estado</th>
</tr></thead>
<tbody>{trs}</tbody>
</table>
</body></html>"""
