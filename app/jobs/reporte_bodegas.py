"""
Reportes HTML de bodegas para backoffice.
- Listas para vender: enroladas, linea 100% disponible, sin credito vigente
- Sin enrolar: tienen linea aprobada pero no han firmado contrato
"""
from datetime import datetime


def get_enroladas_listas(supabase):
    """Bodegas enroladas con linea completa disponible (sin credito vigente)."""
    res = supabase.table("bodegas").select(
        "id,codigo_afiliado,razon_social,nombre_comercial,distrito,"
        "telefono_whatsapp,linea_aprobada,linea_disponible,contrato_firmado_at"
    ).eq("es_test", False).gt("linea_aprobada", 0).execute()
    # Filtrar: contrato firmado Y linea_disponible == linea_aprobada
    bodegas = []
    for b in (res.data or []):
        if not b.get("contrato_firmado_at"):
            continue
        la = float(b.get("linea_aprobada") or 0)
        ld = float(b.get("linea_disponible") or 0)
        if la > 0 and ld == la:
            bodegas.append(b)
    if not bodegas:
        return []
    ids = [b["id"] for b in bodegas]
    return _enrich_vendedores(supabase, bodegas, ids)


def get_sin_enrolar(supabase):
    """Bodegas con linea aprobada > 0 pero sin contrato firmado."""
    res = supabase.table("bodegas").select(
        "id,codigo_afiliado,razon_social,nombre_comercial,distrito,"
        "telefono_whatsapp,linea_aprobada,linea_disponible,estado,"
        "onboarding_fase,contrato_firmado_at"
    ).eq("es_test", False).gt("linea_aprobada", 0).execute()
    bodegas = [b for b in (res.data or []) if not b.get("contrato_firmado_at")]
    if not bodegas:
        return []
    ids = [b["id"] for b in bodegas]
    return _enrich_vendedores(supabase, bodegas, ids)


def _enrich_vendedores(supabase, bodegas, ids):
    """Agrega vendedor y supervisor a cada bodega."""
    # Traer bodega_vendedores con vendedor_id
    bv_res = supabase.table("bodega_vendedores").select(
        "bodega_id,vendedor_id,supervisor"
    ).eq("activo", True).in_("bodega_id", ids).execute()
    # Map bodega_id -> {vendedor_id, supervisor}
    bv_map = {}
    for bv in (bv_res.data or []):
        bid = bv["bodega_id"]
        if bid not in bv_map:
            bv_map[bid] = bv
    # Traer nombres de vendedores
    vend_ids = list(set(bv["vendedor_id"] for bv in bv_map.values() if bv.get("vendedor_id")))
    vend_names = {}
    if vend_ids:
        vr = supabase.table("vendedores").select("id,nombre").in_("id", vend_ids).execute()
        for v in (vr.data or []):
            vend_names[v["id"]] = v["nombre"]
    for b in bodegas:
        bv = bv_map.get(b["id"], {})
        b["vendedor"] = vend_names.get(bv.get("vendedor_id", ""), "")
        b["supervisor"] = bv.get("supervisor") or ""
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
            nombre = nombre[:35] + "..."
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
<div class="sub">Bodegas listas para financiar &mdash; {fecha}</div>
<div class="summary"><span><b>{len(bodegas)}</b> bodegas</span><span>Linea total: <b>S/{total_linea:,.0f}</b></span><span>Enroladas, sin credito vigente</span></div>
<table><thead><tr><th>#</th><th>Bodega</th><th>Distrito</th><th>Vendedor</th><th>Linea</th><th>Telefono</th></tr></thead>
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
            nombre = nombre[:35] + "..."
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
<div class="sub">Bodegas sin enrolar con linea aprobada &mdash; {fecha}</div>
<div class="summary"><span><b>{len(bodegas)}</b> bodegas</span><span>Linea aprobada total: <b>S/{total_linea:,.0f}</b></span><span>Pendientes de contrato + PIN</span></div>
<table><thead><tr><th>#</th><th>Bodega</th><th>Distrito</th><th>Vendedor</th><th>Linea aprob.</th><th>Telefono</th><th>Fase</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""
