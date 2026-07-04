"""
Reportes HTML de bodegas para backoffice.
- Listas para vender: enroladas, línea 100% disponible, sin crédito vigente
- Sin enrolar: tienen línea aprobada pero no han firmado contrato
"""
from datetime import datetime

async def get_enroladas_listas(supabase):
    """Bodegas enroladas con línea completa disponible (sin crédito vigente)."""
    res = supabase.table("bodegas").select(
        "id,codigo_afiliado,razon_social,nombre_comercial,distrito,"
        "telefono_whatsapp,linea_aprobada,linea_disponible"
    ).eq("es_test", False).not_.is_("contrato_firmado_at", "null").gt(
        "linea_aprobada", 0
    ).execute()
    # Filtrar donde linea_disponible == linea_aprobada (sin crédito activo)
    bodegas = [b for b in (res.data or [])
               if b.get("linea_disponible") and b.get("linea_aprobada")
               and float(b["linea_disponible"]) == float(b["linea_aprobada"])]
    # Traer vendedores
    if not bodegas:
        return []
    ids = [b["id"] for b in bodegas]
    bv_res = supabase.table("bodega_vendedores").select(
        "bodega_id,vendedores(nombre)"
    ).eq("activo", True).in_("bodega_id", ids).execute()
    vend_map = {}
    for bv in (bv_res.data or []):
        v = bv.get("vendedores") or {}
        vend_map[bv["bodega_id"]] = v.get("nombre", "")
    # Traer supervisores
    bv_sup = supabase.table("bodega_vendedores").select(
        "bodega_id,supervisor"
    ).eq("activo", True).in_("bodega_id", ids).execute()
    sup_map = {}
    for bv in (bv_sup.data or []):
        sup_map[bv["bodega_id"]] = bv.get("supervisor") or ""
    for b in bodegas:
        b["vendedor"] = vend_map.get(b["id"], "")
        b["supervisor"] = sup_map.get(b["id"], "")
    bodegas.sort(key=lambda x: (x["supervisor"] or "zzz", x["vendedor"] or "zzz", x["razon_social"]))
    return bodegas


async def get_sin_enrolar(supabase):
    """Bodegas con línea aprobada > 0 pero sin contrato firmado."""
    res = supabase.table("bodegas").select(
        "id,codigo_afiliado,razon_social,nombre_comercial,distrito,"
        "telefono_whatsapp,linea_aprobada,linea_disponible,estado,"
        "onboarding_fase"
    ).eq("es_test", False).is_("contrato_firmado_at", "null").gt(
        "linea_aprobada", 0
    ).execute()
    bodegas = res.data or []
    if not bodegas:
        return []
    ids = [b["id"] for b in bodegas]
    bv_res = supabase.table("bodega_vendedores").select(
        "bodega_id,vendedores(nombre)"
    ).eq("activo", True).in_("bodega_id", ids).execute()
    vend_map = {}
    for bv in (bv_res.data or []):
        v = bv.get("vendedores") or {}
        vend_map[bv["bodega_id"]] = v.get("nombre", "")
    bv_sup = supabase.table("bodega_vendedores").select(
        "bodega_id,supervisor"
    ).eq("activo", True).in_("bodega_id", ids).execute()
    sup_map = {}
    for bv in (bv_sup.data or []):
        sup_map[bv["bodega_id"]] = bv.get("supervisor") or ""
    for b in bodegas:
        b["vendedor"] = vend_map.get(b["id"], "")
        b["supervisor"] = sup_map.get(b["id"], "")
    bodegas.sort(key=lambda x: (x["supervisor"] or "zzz", x["vendedor"] or "zzz", x["razon_social"]))
    return bodegas


def _fmt_tel(t):
    if not t:
        return ""
    t = t.replace("+51", "").strip()
    if len(t) == 9:
        return f"{t[:3]} {t[3:6]} {t[6:]}"
    return t


def render_listas_html(bodegas):
    fecha = datetime.now().strftime("%d/%m/%Y")
    total_linea = sum(float(b.get("linea_aprobada", 0)) for b in bodegas)
    rows = ""
    current_sup = None
    for i, b in enumerate(bodegas, 1):
        sup = b.get("supervisor") or "SIN SUPERVISOR"
        if sup != current_sup:
            current_sup = sup
            sup_short = " ".join(sup.split()[:2]) if sup != "SIN SUPERVISOR" else sup
            rows += f'<tr><td colspan="6" style="background:#1a2332;color:#4fc3f7;font-weight:700;padding:10px 14px;font-size:13px">👤 {sup_short}</td></tr>\n'
        nombre = b.get("nombre_comercial") or b.get("razon_social") or ""
        if len(nombre) > 35:
            nombre = nombre[:35] + "…"
        distrito = b.get("distrito") or ""
        vendedor = b.get("vendedor") or ""
        if vendedor:
            parts = vendedor.split()
            vendedor = parts[0].title() + (" " + parts[1].title() if len(parts) > 1 else "")
        linea = f'S/{float(b.get("linea_aprobada", 0)):.0f}'
        tel = _fmt_tel(b.get("telefono_whatsapp"))
        rows += f'<tr><td style="color:#4fc3f7;font-weight:600">{i}</td><td>{nombre}</td><td>{distrito}</td><td>{vendedor}</td><td style="font-weight:600">{linea}</td><td>{tel}</td></tr>\n'

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bodegas listas para financiar</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#0f1923;color:#e0e0e0;padding:24px}}
h1{{font-size:18px;font-weight:800;color:#4fc3f7;letter-spacing:2px;margin-bottom:4px}}
.sub{{color:#90a4ae;font-size:13px;margin-bottom:16px}}
.summary{{display:flex;gap:24px;margin-bottom:16px;font-size:14px}}
.summary b{{color:#4fc3f7}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 14px;color:#546e7a;font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #263238}}
td{{padding:8px 14px;border-bottom:1px solid #1e2d3d}}
tr:hover td{{background:#1a2332}}
</style></head><body>
<h1>CIRCA</h1>
<div class="sub">Bodegas listas para financiar — {fecha}</div>
<div class="summary"><span><b>{len(bodegas)}</b> bodegas</span><span>Línea total: <b>S/{total_linea:,.0f}</b></span><span>Enroladas, sin crédito vigente</span></div>
<table><thead><tr><th>#</th><th>Bodega</th><th>Distrito</th><th>Vendedor</th><th>Línea</th><th>Teléfono</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""


def render_sin_enrolar_html(bodegas):
    fecha = datetime.now().strftime("%d/%m/%Y")
    total_linea = sum(float(b.get("linea_aprobada", 0)) for b in bodegas)
    rows = ""
    current_sup = None
    for i, b in enumerate(bodegas, 1):
        sup = b.get("supervisor") or "SIN SUPERVISOR"
        if sup != current_sup:
            current_sup = sup
            sup_short = " ".join(sup.split()[:2]) if sup != "SIN SUPERVISOR" else sup
            rows += f'<tr><td colspan="7" style="background:#2a1a00;color:#ffa726;font-weight:700;padding:10px 14px;font-size:13px">👤 {sup_short}</td></tr>\n'
        nombre = b.get("nombre_comercial") or b.get("razon_social") or ""
        if len(nombre) > 35:
            nombre = nombre[:35] + "…"
        distrito = b.get("distrito") or ""
        vendedor = b.get("vendedor") or ""
        if vendedor:
            parts = vendedor.split()
            vendedor = parts[0].title() + (" " + parts[1].title() if len(parts) > 1 else "")
        linea = f'S/{float(b.get("linea_aprobada", 0)):.0f}'
        tel = _fmt_tel(b.get("telefono_whatsapp"))
        fase = b.get("onboarding_fase") or b.get("estado") or ""
        rows += f'<tr><td style="color:#ffa726;font-weight:600">{i}</td><td>{nombre}</td><td>{distrito}</td><td>{vendedor}</td><td style="font-weight:600">{linea}</td><td>{tel}</td><td>{fase}</td></tr>\n'

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bodegas sin enrolar</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#0f1923;color:#e0e0e0;padding:24px}}
h1{{font-size:18px;font-weight:800;color:#ffa726;letter-spacing:2px;margin-bottom:4px}}
.sub{{color:#90a4ae;font-size:13px;margin-bottom:16px}}
.summary{{display:flex;gap:24px;margin-bottom:16px;font-size:14px}}
.summary b{{color:#ffa726}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 14px;color:#546e7a;font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #263238}}
td{{padding:8px 14px;border-bottom:1px solid #1e2d3d}}
tr:hover td{{background:#1a2332}}
</style></head><body>
<h1>CIRCA</h1>
<div class="sub">Bodegas sin enrolar con línea aprobada — {fecha}</div>
<div class="summary"><span><b>{len(bodegas)}</b> bodegas</span><span>Línea aprobada total: <b>S/{total_linea:,.0f}</b></span><span>Pendientes de contrato + PIN</span></div>
<table><thead><tr><th>#</th><th>Bodega</th><th>Distrito</th><th>Vendedor</th><th>Línea aprob.</th><th>Teléfono</th><th>Fase</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""
