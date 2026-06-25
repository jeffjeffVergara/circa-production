#!/usr/bin/env python3
"""
Parche portal distribuidor v2:
1. Filtro Real/Test
2. Ordenar por fecha
3. Buscador por bodega/código
4. Flujo simplificado: recibido → en_camino → entregado
"""
import os, sys

REPO = os.path.expanduser("~/Projects/circa-deploy-temp")

def patch(txt, old, new, label):
    if old in txt:
        txt = txt.replace(old, new)
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} — PATRÓN NO ENCONTRADO")
    return txt

# ═══════════════════════════════════════════════════════════
# 1. DISTRIBUIDOR.HTML
# ═══════════════════════════════════════════════════════════
dist_path = os.path.join(REPO, "static/distribuidor.html")
h = open(dist_path).read()
print("── distribuidor.html ──")

# 1A. Stat cards: Preparando→En Camino, Despachados→Entregados
h = patch(h,
    """<div class="stat-card" onclick="filterOrders('en_preparacion',this)"><div class="stat-count count-preparacion" id="countPrep">0</div><div class="stat-label">Preparando</div></div>
<div class="stat-card" onclick="filterOrders('despachado',this)"><div class="stat-count count-despachado" id="countDesp">0</div><div class="stat-label">Despachados</div></div>""",
    """<div class="stat-card" onclick="filterOrders('en_camino',this)"><div class="stat-count count-despachado" id="countCamino">0</div><div class="stat-label">En Camino</div></div>
<div class="stat-card" onclick="filterOrders('entregado',this)"><div class="stat-count count-preparacion" id="countEntregado">0</div><div class="stat-label">Entregados</div></div>""",
    "Stat cards")

# 1B. renderStats: update counts
h = patch(h,
    "document.getElementById('countPrep').textContent=allPedidos.filter(p=>p.estado==='en_preparacion').length;document.getElementById('countDesp').textContent=allPedidos.filter(p=>['despachado','en_camino'].includes(p.estado)).length",
    "document.getElementById('countCamino').textContent=allPedidos.filter(p=>['en_camino','despachado','en_preparacion'].includes(p.estado)).length;document.getElementById('countEntregado').textContent=allPedidos.filter(p=>p.estado==='entregado').length",
    "renderStats counts")

# 1C. NEXT_ACTION: simplify flow
h = patch(h,
    "const NEXT_ACTION={preventa_aceptada:{label:'Marcar Recibido',next:'recibido',icon:'\\u2705',cls:'action-primary'},confirmado:{label:'Marcar Recibido',next:'recibido',icon:'\\u2705',cls:'action-primary'},recibido:{label:'Iniciar Preparacion',next:'en_preparacion',icon:'\\ud83d\\udce6',cls:'action-primary'},en_preparacion:{label:'Despachar',next:'despachado',icon:'\\ud83d\\ude9a',cls:'action-success'},despachado:{label:'Confirmar En Camino',next:'en_camino',icon:'\\ud83d\\ude9a',cls:'action-primary'},en_camino:{label:'Confirmar Entrega',next:'entregado',icon:'\\ud83c\\udf89',cls:'action-success'}};",
    "const NEXT_ACTION={preventa_aceptada:{label:'Marcar Recibido',next:'recibido',icon:'\\u2705',cls:'action-primary'},confirmado:{label:'Marcar Recibido',next:'recibido',icon:'\\u2705',cls:'action-primary'},recibido:{label:'En Camino',next:'en_camino',icon:'\\ud83d\\ude9a',cls:'action-primary'},en_preparacion:{label:'En Camino',next:'en_camino',icon:'\\ud83d\\ude9a',cls:'action-primary'},despachado:{label:'En Camino',next:'en_camino',icon:'\\ud83d\\ude9a',cls:'action-primary'},en_camino:{label:'Confirmar Entrega',next:'entregado',icon:'\\ud83c\\udf89',cls:'action-success'}};",
    "NEXT_ACTION simplificado")

# 1D. canInv (sustento): only entregado
h = patch(h,
    "const canInv=['despachado','en_camino','entregado'].includes(p.estado)",
    "const canInv=p.estado==='entregado'",
    "Sustento solo en entregado")

# 1E. Facturar: keep on en_camino + entregado
# canInv was used for both factura and sustento. Now they're separate.
# Sustento = canInv (entregado only). Facturar = canFact (en_camino + entregado)
# Need to add canFact variable
h = patch(h,
    "const canInv=p.estado==='entregado';const fecha=",
    "const canInv=p.estado==='entregado';const canFact=['despachado','en_camino','entregado'].includes(p.estado);const fecha=",
    "Agregar canFact")

# Update facturar button to use canFact instead of canInv
h = patch(h,
    "+(canInv?'<button class=\"action-btn action-invoice\" onclick=\"openInvoice(\\''+p.id+'\\')\">Facturar</button>':'')",
    "+(canFact?'<button class=\"action-btn action-invoice\" onclick=\"openInvoice(\\''+p.id+'\\')\">Facturar</button>':'')",
    "Facturar usa canFact")

# 1F. Filter by en_camino should include despachado and en_preparacion (backward compat)
h = patch(h,
    "if(currentFilter==='despachado')f=allPedidos.filter(p=>['despachado','en_camino'].includes(p.estado))",
    "if(currentFilter==='en_camino')f=allPedidos.filter(p=>['en_preparacion','despachado','en_camino'].includes(p.estado))",
    "Filtro en_camino agrupa legacy")

# 1G. Sort by date (most recent first) — add .sort() after filter
h = patch(h,
    "else f=allPedidos.filter(p=>ESTADOS_ACTIVOS.includes(p.estado));document.getElementById('filterLabel')",
    "else f=allPedidos.filter(p=>ESTADOS_ACTIVOS.includes(p.estado));f.sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));document.getElementById('filterLabel')",
    "Ordenar por fecha desc")

# 1H. Add search bar + Real/Test toggle in the orders header
h = patch(h,
    """<div class="orders-section"><div class="orders-header"><div class="orders-title">Pedidos</div><div style="display:flex;gap:10px;align-items:center"><button onclick="exportCSV()" style="background:transparent;border:1px solid var(--circa-border);color:var(--circa-text-muted);padding:6px 14px;border-radius:8px;font-size:12px;cursor:pointer;font-family:inherit">Descargar CSV</button><div class="filter-label" id="filterLabel">Mostrando: Todos</div></div></div><div id="ordersList"></div></div>""",
    """<div class="orders-section"><div class="orders-header"><div class="orders-title">Pedidos</div><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><input type="text" id="searchInput" placeholder="Buscar bodega o código..." oninput="renderOrders()" style="background:var(--circa-card);border:1px solid var(--circa-border);color:var(--circa-text);padding:6px 12px;border-radius:8px;font-size:12px;width:180px;font-family:inherit"><div style="display:flex;gap:4px"><button id="btnReal" onclick="setTestMode('real')" style="padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;border:1px solid var(--circa-border);background:var(--circa-green);color:#fff">Reales</button><button id="btnTest" onclick="setTestMode('test')" style="padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;border:1px solid var(--circa-border);background:transparent;color:var(--circa-text-muted)">Pruebas</button></div><button onclick="exportCSV()" style="background:transparent;border:1px solid var(--circa-border);color:var(--circa-text-muted);padding:6px 14px;border-radius:8px;font-size:12px;cursor:pointer;font-family:inherit">Descargar CSV</button><div class="filter-label" id="filterLabel">Mostrando: Todos</div></div></div><div id="ordersList"></div></div>""",
    "Search bar + toggle Real/Test")

# 1I. Add setTestMode function (before first uploadSustento only)
_old_u = "async function uploadSustento(pid,file)"
_new_u = """function setTestMode(mode){var url=new URL(location.href);if(mode==='test'){url.searchParams.set('test','only');document.getElementById('btnTest').style.background='var(--circa-blue)';document.getElementById('btnTest').style.color='#fff';document.getElementById('btnReal').style.background='transparent';document.getElementById('btnReal').style.color='var(--circa-text-muted)'}else{url.searchParams.delete('test');document.getElementById('btnReal').style.background='var(--circa-green)';document.getElementById('btnReal').style.color='#fff';document.getElementById('btnTest').style.background='transparent';document.getElementById('btnTest').style.color='var(--circa-text-muted)'}location.href=url.toString()}
(function(){if(ONLY_TEST){var r=document.getElementById('btnReal');var t=document.getElementById('btnTest');if(r){r.style.background='transparent';r.style.color='var(--circa-text-muted)'}if(t){t.style.background='var(--circa-blue)';t.style.color='#fff'}}})();
async function uploadSustento(pid,file)"""
if _old_u in h:
    h = h.replace(_old_u, _new_u, 1)
    print("  ✅ setTestMode + init toggle state")
else:
    print("  ❌ setTestMode — PATRÓN NO ENCONTRADO")

# 1J. Add search filter in renderOrders (filter by search input)
h = patch(h,
    "f.sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));document.getElementById('filterLabel')",
    "var _sq=(document.getElementById('searchInput')||{}).value||'';if(_sq){var _sl=_sq.toLowerCase();f=f.filter(p=>{var _b=p.bodegas||{};return ((_b.nombre_comercial||'')+' '+(_b.razon_social||'')+' '+(_b.codigo_afiliado||'')+' '+(p.numero||'')).toLowerCase().indexOf(_sl)>=0})}f.sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));document.getElementById('filterLabel')",
    "Search filter logic")

open(dist_path, 'w').write(h)
print(f"  Guardado: {dist_path} ({len(h.splitlines())} líneas)\n")

# ═══════════════════════════════════════════════════════════
# 2. ORDER_STATUS.PY
# ═══════════════════════════════════════════════════════════
os_path = os.path.join(REPO, "app/services/order_status.py")
o = open(os_path).read()
print("── order_status.py ──")

# 2A. STATUS_FLOW: recibido → en_camino (keep legacy entries)
o = patch(o,
    '    "recibido": "en_preparacion",',
    '    "recibido": "en_camino",  # simplificado: skip en_preparacion+despachado',
    "STATUS_FLOW recibido→en_camino")

# 2B. VALID_TRANSITIONS: recibido allows en_camino
o = patch(o,
    '    "recibido": ["en_preparacion", "cancelado"],',
    '    "recibido": ["en_camino", "cancelado"],',
    "VALID_TRANSITIONS recibido")

# 2C. STATUS_MESSAGES: update recibido
o = patch(o,
    '    "recibido": "El distribuidor confirmó que recibió tu pedido.",',
    '    "recibido": "El distribuidor recibió tu pedido y lo está preparando.",',
    "STATUS_MESSAGES recibido")

open(os_path, 'w').write(o)
print(f"  Guardado: {os_path}\n")

# ═══════════════════════════════════════════════════════════
# 3. DISTRIBUIDOR.PY (WA_MESSAGES)
# ═══════════════════════════════════════════════════════════
dp_path = os.path.join(REPO, "app/routes/distribuidor.py")
d = open(dp_path).read()
print("── distribuidor.py ──")

# 3A. WA recibido
d = patch(d,
    '    "recibido": "✅ *Pedido {numero} recibido*\\n{distribuidor} confirmo que recibio tu pedido.",',
    '    "recibido": "✅ *Pedido {numero} recibido*\\n{distribuidor} recibió tu pedido y lo está preparando.",',
    "WA recibido")

# 3B. WA en_camino
d = patch(d,
    '    "en_camino": "🚚 *Pedido {numero} en camino*\\nTu pedido va camino a tu bodega.",',
    '    "en_camino": "🚚 *Pedido {numero} en camino*\\nTu pedido salió del almacén y va camino a tu bodega.",',
    "WA en_camino")

open(dp_path, 'w').write(d)
print(f"  Guardado: {dp_path}\n")

print("═" * 50)
print("✅ Parche completo. Verificá con:")
print("   git diff --stat")
print("   git diff app/services/order_status.py")
print("   git diff app/routes/distribuidor.py")
