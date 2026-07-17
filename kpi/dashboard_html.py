# -*- coding: utf-8 -*-
"""Genera dashboard.html (CEO / GROWTH / RIESGO) desde los frames del agente v3."""
import datetime as dt

CSS = """
*{box-sizing:border-box;margin:0;font-family:-apple-system,Segoe UI,Arial,sans-serif}
body{background:#0f1420;color:#e8ecf4;padding:16px;max-width:1100px;margin:auto}
h1{font-size:20px;color:#fff}.sub{color:#8b95a8;font-size:12px;margin:4px 0 14px}
.tabs{display:flex;gap:8px;margin-bottom:16px}
.tab{padding:8px 18px;border-radius:8px;background:#1a2233;cursor:pointer;font-weight:600;font-size:14px;border:1px solid #2a3450}
.tab.on{background:#2f5cff;border-color:#2f5cff}
.panel{display:none}.panel.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:18px}
.kpi{background:#161d2e;border:1px solid #232d45;border-radius:10px;padding:12px}
.kpi .l{font-size:11px;color:#8b95a8;text-transform:uppercase}.kpi .v{font-size:22px;font-weight:700;margin-top:2px}
.kpi .d{font-size:11px;margin-top:2px}
.g{color:#3ddc84}.y{color:#ffc541}.r{color:#ff5964}.na{color:#5a6478}
h2{font-size:14px;color:#aab6cf;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:12px;background:#161d2e;border-radius:10px;overflow:hidden}
th{background:#1e2740;text-align:left;padding:7px 9px;color:#8b95a8;font-size:11px;text-transform:uppercase}
td{padding:6px 9px;border-top:1px solid #222c46}
.pill{padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700}
.pg{background:#12351f;color:#3ddc84}.py{background:#3a2f10;color:#ffc541}.pr{background:#3a1418;color:#ff5964}
.note{font-size:11px;color:#5a6478;margin-top:6px}
"""

def sem(v, meta, invert=False):
    if v is None or v == "NA": return "na", "NA"
    ok = v <= meta if invert else v >= meta
    warn = (v <= meta*1.25 if invert else v >= meta*0.7)
    return ("g" if ok else "y" if warn else "r"), v

def kpi(label, valor, delta="", cls=""):
    return f'<div class="kpi"><div class="l">{label}</div><div class="v {cls}">{valor}</div><div class="d {cls}">{delta}</div></div>'

def tbl(headers, rows, empty="Sin registros"):
    if not rows: return f'<p class="note">{empty}</p>'
    h = "".join(f"<th>{x}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"

def build(d):
    """d: dict con todas las metricas/listas ya calculadas por el agente."""
    def delta(x):
        if x in (None, "NA"): return '<span class="na">NA</span>'
        c = "g" if x >= 0 else "r"
        return f'<span class="{c}">{"+" if x>=0 else ""}{x}% vs ant.</span>'

    ceo = '<div class="grid">'
    ceo += kpi("MAFM (financian este mes)", d["mafm"], delta(d["mafm_delta"]))
    ceo += kpi("Enroladas MTD", d["enrol_mtd"], delta(d["enrol_delta"]))
    ceo += kpi("Activas 30d", f'{d["activas30"]} / {d["enroladas"]}')
    ceo += kpi("1er financiamiento MTD", d["primer_fin_mtd"])
    c7, _ = sem(d["rec7"], d["meta_rec7"]); c14, _ = sem(d["rec14"], d["meta_rec14"])
    ceo += kpi("Recompra 7d", f'{d["rec7"]}%', f'meta {d["meta_rec7"]}%', c7)
    ceo += kpi("Recompra 14d", f'{d["rec14"]}%', f'meta {d["meta_rec14"]}%', c14)
    ceo += kpi("GMV semana", f'S/ {d["gmv_sem"]:,.0f}', delta(d["gmv_sem_delta"]))
    ceo += kpi("GMV MTD", f'S/ {d["gmv_mtd"]:,.0f}', delta(d["gmv_mtd_delta"]))
    ceo += kpi("Revenue MTD", f'S/ {d["rev_mtd"]:,.2f}')
    ceo += kpi("Ticket prom. MTD", f'S/ {d["ticket_mtd"]:,.0f}')
    ceo += kpi("Cartera vigente", f'S/ {d["cartera"]:,.0f}')
    p7c, _ = sem(d["par7"], 5, invert=True); p30c, _ = sem(d["par30"], 2, invert=True)
    ceo += kpi("PAR7", f'{d["par7"]}%', "circuit: 5/8/10", p7c)
    ceo += kpi("PAR30", f'{d["par30"]}%', "", p30c)
    ceo += kpi("Utilizacion linea prom.", f'{d["util_prom"]}%')
    ceo += kpi("Time to 1er fin (mediana)", f'{d["ttff"]} dias')
    ceo += kpi("Dias entre compras (med.)", f'{d["tbp"]} dias')
    ceo += "</div>"
    if d["alertas"]:
        ceo += "<h2>Alertas</h2>" + "".join(f'<p class="r">• {a}</p>' for a in d["alertas"])

    g = "<h2>A. Llamar hoy — dia 5-7 sin recompra</h2>" + tbl(
        ["Bodega","Tel","Vendedor","Ult. compra","Dias","Linea disp."], d["llamar_hoy"], "Nadie en ventana critica hoy")
    g += "<h2>B. Zombies — enroladas sin pedido</h2>" + tbl(
        ["Bodega","Tel","Vendedor","Dias enrolada"], d["zombies"])
    g += "<h2>C. Riesgo de abandono (dias desde ultima compra O pago, lo mas reciente)</h2>" + tbl(
        ["Bodega","Tel","Vendedor","Ult. actividad","Dias","Pagos punt.","Banda"], d["abandono"])
    g += '<p class="note">Bodegas con credito abierto no vencido = EN CICLO: excluidas de A y C (regla 17-jul).</p>' 
    g += "<h2>D. VIP — candidatas a subir linea</h2>" + tbl(
        ["Bodega","Linea actual","Sugerida","Pagos puntuales","Health"], d["vip"])
    g += "<h2>E. Pipeline / limbo</h2>" + tbl(
        ["Pedido","Bodega","Estado","Monto","Dias"], d["limbo"], "Pipeline limpio")
    g += "<h2>F. Ranking vendedores por CALIDAD (40 act / 30 rec / 20 cob / 10 enrol)</h2>" + tbl(
        ["Vendedor","Score","Afiliadas","% financiaron","% recompraron","% cobranza ok","Enrol. MTD"], d["rk_vend"])
    g += '<p class="note">Score v0 calibrable — pesos definidos 17-jul-2026.</p>'

    r = '<div class="grid">'
    r += kpi("Cartera vigente", f'S/ {d["cartera"]:,.0f}')
    r += kpi("Vencido", f'S/ {d["vencido"]:,.0f}', f'{d["n_vencidos"]} pedidos', "r" if d["n_vencidos"] else "g")
    r += kpi("PAR7", f'{d["par7"]}%', "", p7c) + kpi("PAR30", f'{d["par30"]}%', "", p30c)
    r += kpi("Utilizacion promedio", f'{d["util_prom"]}%')
    r += kpi("Sin utilizacion 30d", d["sin_util"])
    r += "</div>"
    r += "<h2>Subir linea</h2>" + tbl(["Bodega","Actual","Sugerida","Pagos puntuales"], d["subir"])
    r += "<h2>Cobrar / congelar (vencidos activos)</h2>" + tbl(
        ["Pedido","Bodega","Vendedor","Monto fin.","Dias atraso"], d["cobrar"], "Cero vencidos")
    r += "<h2>Health Score por bodega (v0: 25 frec / 25 pago / 20 util / 20 recur / 10 antig)</h2>" + tbl(
        ["Bodega","Score","Frecuencia/sem","Pago","Utilizacion","Dias sin pedir","Segmento"], d["health"])

    tabs = [("CEO", ceo), ("GROWTH", g), ("RIESGO", r)]
    body = '<div class="tabs">' + "".join(
        f'<div class="tab{" on" if i==0 else ""}" onclick="go({i})">{n}</div>' for i,(n,_) in enumerate(tabs)) + "</div>"
    body += "".join(f'<div class="panel{" on" if i==0 else ""}" id="p{i}">{c}</div>' for i,(_,c) in enumerate(tabs))
    js = "function go(i){document.querySelectorAll('.tab,.panel').forEach(e=>e.classList.remove('on'));document.querySelectorAll('.tab')[i].classList.add('on');document.getElementById('p'+i).classList.add('on')}"
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Circa OS {d['fecha']}</title><style>{CSS}</style></head><body>"
            f"<h1>CIRCA — Sistema Operativo</h1><div class='sub'>{d['fecha']} · datos en vivo del piloto · GMV neto · hora Lima</div>"
            f"{body}<script>{js}</script></body></html>")
