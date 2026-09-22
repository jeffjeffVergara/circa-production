#!/usr/bin/env python3
"""
CORTE DE COMISIONES v2 — esquema simple (definido por Paola, 31-ago-2026)
=========================================================================

Reemplaza la logica del esquema julio de `circa_corte_comisiones.py`, que
bloqueaba toda la comision de una bodega atrasada y arrastraba comisiones
viejas de un corte a otro. Aqui NO hay bloqueo por bodega ni arrastre.

LAS REGLAS (textual de Paola)
-----------------------------
1. ENROLADOS: "corresponden a los enrolados en el mes que ya pagaron al menos
   un financiamiento. Si aun no los pagan, estan 'en vuelo' y se pagaran apenas
   estas paguen."
      -> S/5 por bodega cuyo PRIMER pedido financiado cae dentro del periodo.
      -> A PAGAR si esa bodega ya pago CUALQUIERA de sus financiamientos.
      -> Si no, EN VUELO.

2. FINANCIADOS: "se pagan los que se hicieron durante el mes y estos ya fueron
   pagados por la bodega. No se pagan financiados del mes anterior porque esos
   apenas pagaron las bodegas se les deposito a los vendedores ya."
      -> S/1 por cada pedido financiado creado dentro del periodo que NO sea el
         primero de la bodega (el primero ya paga como enrolamiento).
      -> A PAGAR si ese pedido esta pagado. Si no, EN VUELO.
      -> NUNCA se miran pedidos de meses anteriores: ya se pagaron aparte, los
         primeros dias del mes siguiente.

3. BONO TOP: S/20 al vendedor con mas enrolados del periodo. Si hay empate no
   se asigna solo: se emite un AVISO para decidir a mano.

4. Sin metas semanales. Sin retenciones diferenciadas: todo financiado paga
   igual, sin importar la antiguedad de la bodega.

QUE NO CUENTA COMO FINANCIAMIENTO (verificado contra la base el 31-ago-2026)
---------------------------------------------------------------------------
- `monto_financiado = 0`.
- Pedido pagado en EFECTIVO (`estado = 'pagado_cash'` o `metodo_pago =
  'efectivo'`) aunque conserve `monto_financiado > 0`: al anular el
  financiamiento no siempre se limpia el campo. Sin financiamiento Circa no hay
  comision.
- Pedido AUN NO ENTREGADO. La activacion se paga al entregar: una preventa
  aceptada pero sin despachar no activo nada. El criterio va por ESTADO, no por
  `fecha_entregado` (ver ESTADOS_ENTREGADOS).
- Pedidos cancelados / rechazados.

LOS TRES ESTADOS [definidos por Paola, 31-ago-2026]
---------------------------------------------------
  A PAGAR  — la bodega ya pago. Se le deposita al vendedor.
  EN VUELO — no ha pagado pero AUN ESTA DENTRO de su plazo (los 7 dias).
  VENCIDO  — ya cumplio su ciclo de plazo y no pago.

VENCIDO **no** es una perdida para el vendedor: la comision se le sigue pagando
apenas la bodega pague. Se separa de EN VUELO para que se vea donde hay que
cobrar. Es una senal de cobranza, no un castigo.

El corte no castiga a la bodega entera: cada pedido se evalua solo. Si una
bodega tiene un pedido vencido y otros dos pagados, los dos pagados se cobran
igual. (En el esquema julio se congelaba todo, y por eso MONTES MONTENEGRO
salia con sus 3 pedidos en VENCIDO teniendo 2 pagados.)

Uso
---
    python3 circa_corte_v2.py --desde 2026-08-01 --hasta 2026-08-30

Solo lectura: no escribe en la base.
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import circa_corte_comisiones as C  # fetch_todo, parse_ts (ya corregido), env_o_falla

TARIFA_ENROLADO = 5.0
TARIFA_FINANCIADO = 1.0
BONO_TOP = 20.0

# Peru = UTC-5 todo el ano (no usa horario de verano).
TZ_PERU = timezone(timedelta(hours=-5))


def dia_peru(ts):
    """Convierte un timestamp de la base al DIA CALENDARIO peruano.

    Postgres guarda en UTC. Un pago hecho a las 22:58 del 28 en Lima se guarda
    como 2026-08-29T03:58Z: comparar la fecha UTC contra el calendario del
    negocio lo corre un dia. Al 31-ago-2026 eso afectaba a 8 pedidos.
    """
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(TZ_PERU).date()


def fecha_pago_efectiva(p):
    """Cuando la BODEGA pago, no cuando Circa lo registro.

    Se toma la evidencia mas temprana entre:
      · `pago_cliente_sustento_subido_at` — la bodega subio su comprobante
      · `fecha_pagado` / `pagado_at`      — alguien lo marco pagado en el sistema

    Por que la mas temprana [decision de Paola, 31-ago-2026]: el vendedor no
    controla cuanto tarda la verificacion. Caso PACARA ASPAJO CRC-129: subio
    sustento el 28-ago y recien lo marcaron el 31; con `fecha_pagado` sola
    quedaba fuera del corte al 30-ago y salia VENCIDO teniendo pagado.
    Al 31-ago-2026 habia 5 pedidos con ese desfase, dos cruzando cierre de mes.

    Solo 75 de 138 pagos tienen sustento, asi que el fallback importa.
    """
    cands = [dia_peru(C.parse_ts(p.get(k)))
             for k in ("pago_cliente_sustento_subido_at", "pagado_at", "fecha_pagado")]
    cands = [d for d in cands if d is not None]
    return min(cands) if cands else None

# Estados en los que la bodega YA recibio el producto. Verificado el
# 31-ago-2026: los 138 pedidos 'pagado' y los 42 'entregado' tienen
# fecha_entregado al 100%; 'preventa_aceptada' no la tiene.
ESTADOS_ENTREGADOS = {"entregado", "pagado", "pagado_cash", "pago_reportado"}

AZUL, GRIS = "1F3864", "F2F2F2"
VERDE, AMARILLO, ROJO = "E2EFDA", "FFF2CC", "FCE4EC"


# --------------------------------------------------------------------------
def calcular(base_url, key, desde, hasta, hoy=None, verbose=True):
    """`hoy` = fecha contra la que se juzga si un plazo ya vencio. Por defecto
    la fecha real de corrida. Un pedido con fecha_vencimiento anterior a `hoy`
    y sin pagar esta VENCIDO; si su fecha aun no llega, esta EN VUELO."""
    if hoy is None:
        hoy = date.today()

    def say(m):
        if verbose:
            print(m)

    vendedores = [v for v in C.fetch_todo(
        base_url, key, "vendedores", "id,codigo,nombre,nombre_corto,activo,es_admin,supervisor")
        if v.get("activo") and not v.get("es_admin")]
    vend = {v["id"]: v for v in vendedores}
    say(f"  Vendedores activos: {len(vend)}")

    mapa = {}
    for m in C.fetch_todo(base_url, key, "bodega_vendedores",
                          "bodega_id,vendedor_id,activo,rol", "activo=eq.true"):
        if m["vendedor_id"] in vend:
            mapa.setdefault(m["bodega_id"], m["vendedor_id"])
    say(f"  Bodegas mapeadas a un vendedor: {len(mapa)}")

    bodegas = [b for b in C.fetch_todo(base_url, key, "bodegas",
                                       "id,nombre_comercial,razon_social,es_test")
               if b.get("es_test") is not True]
    bod = {b["id"]: b for b in bodegas}
    say(f"  Bodegas reales: {len(bod)}")

    pedidos = [p for p in C.fetch_todo(
        base_url, key, "pedidos",
        # OJO: si falta una columna aqui, llega vacia y la regla que la use falla
        # en silencio. Paso ya cometido dos veces el 31-ago-2026 con
        # fecha_entregado y con fecha_vencimiento.
        "numero,bodega_id,vendedor_id,monto_financiado,monto_contado,estado,metodo_pago,"
        "created_at,fecha_pagado,pagado_at,pago_cliente_sustento_subido_at,"
        "fecha_entregado,fecha_vencimiento,plazo_dias",
        f"distribuidor_id=eq.{C.DIMAX_DISTRIBUIDOR_ID}") if p["bodega_id"] in bod]
    pedidos = [p for p in pedidos
               if not any(f in str(p.get("estado") or "").lower()
                          for f in C.ESTADOS_EXCLUIDOS_FRAGMENTOS)]

    descartes = defaultdict(int)
    for p in pedidos:
        p["_f"] = dia_peru(C.parse_ts(p["created_at"]))
        estado = str(p.get("estado") or "").lower()
        metodo = str(p.get("metodo_pago") or "").lower()
        fin = float(p.get("monto_financiado") or 0)
        p["_motivo"] = None
        if fin <= 0:
            p["_motivo"] = "sin financiamiento"
        elif estado == "pagado_cash" or metodo == "efectivo":
            p["_motivo"] = "pagado en efectivo"
        elif estado not in ESTADOS_ENTREGADOS:
            p["_motivo"] = f"no entregado ({estado})"
        p["_fin"] = p["_motivo"] is None
        if p["_motivo"] and fin > 0:
            descartes[p["_motivo"]] += 1
        p["_pagd"] = fecha_pago_efectiva(p)
        p["_pagado"] = p["_pagd"] is not None and p["_pagd"] <= hasta
        # Ya cumplio su ciclo de plazo (los 7 dias corren desde la ENTREGA:
        # fecha_vencimiento = fecha_entregado + plazo_dias, ver CLAUDE.md).
        p["_venc"] = C.parse_d(p.get("fecha_vencimiento"))
        p["_vencido"] = p["_venc"] is not None and p["_venc"] < hoy

    say(f"  Pedidos vivos: {len(pedidos)} | financiados validos: "
        f"{sum(1 for p in pedidos if p['_fin'])}")
    for k, n in sorted(descartes.items(), key=lambda x: -x[1]):
        say(f"     descartados con financiado>0 por {k}: {n}")

    por_bod = defaultdict(list)
    for p in pedidos:
        if p["_fin"] and p["_f"]:
            por_bod[p["bodega_id"]].append(p)
    for l in por_bod.values():
        l.sort(key=lambda x: (x["created_at"], x.get("numero") or ""))

    def atribuir(p):
        vid = mapa.get(p["bodega_id"])
        if vid:
            return vid
        v = p.get("vendedor_id")
        return v if v in vend else None

    paga = defaultdict(lambda: defaultdict(float))
    cnt = defaultdict(lambda: defaultdict(int))
    detalle, alertas = [], []

    for bid, lst in por_bod.items():
        nb = bod[bid].get("nombre_comercial") or bod[bid].get("razon_social") or bid[:8]
        bodega_pago = any(q["_pagado"] for q in lst)
        primero = lst[0]
        for p in lst:
            if not (desde <= p["_f"] <= hasta):
                continue          # regla 2: nunca se miran meses anteriores
            vid = atribuir(p)
            if vid is None:
                alertas.append((p.get("numero") or "(sin numero)", nb, p["_f"],
                                "SIN VENDEDOR asignado"))
                continue
            enrol = p is primero
            if enrol:
                # El enrolamiento se libera con CUALQUIER financiamiento pagado
                # de la bodega. Si no pago ninguno, el ciclo que manda es el del
                # propio pedido de enrolamiento.
                pagado, vencido = bodega_pago, p["_vencido"]
                concepto, tarifa = "enrolado", TARIFA_ENROLADO
            else:
                pagado, vencido = p["_pagado"], p["_vencido"]
                concepto, tarifa = "financiado", TARIFA_FINANCIADO
            est = "A PAGAR" if pagado else ("VENCIDO" if vencido else "EN VUELO")
            paga[vid][est] += tarifa
            cnt[vid][concepto + "s"] += 1
            if est == "A PAGAR":
                cnt[vid][concepto + "s_pagados"] += 1
            elif est == "VENCIDO":
                cnt[vid][concepto + "s_vencidos"] += 1
            etiq = concepto
            if est == "VENCIDO" and p["_venc"]:
                etiq += f" (vencio {p['_venc'].isoformat()})"
            detalle.append((vend[vid].get("supervisor") or "SIN SUPERVISOR",
                            vend[vid]["codigo"], nb, p.get("numero") or "", p["_f"],
                            etiq, tarifa, est))

    # ---- Bono top: mas enrolados del periodo. Empate -> aviso, no se asigna.
    top_vid, aviso_top = None, None
    if cnt:
        mx = max((c["enrolados"] for c in cnt.values()), default=0)
        empatados = [v for v, c in cnt.items() if c["enrolados"] == mx and mx > 0]
        if len(empatados) == 1:
            top_vid = empatados[0]
            _vt = cnt[top_vid].get("enrolados_vencidos",0)+cnt[top_vid].get("financiados_vencidos",0)
            if _vt == 0:  # filtro 6: bono solo si el estrella no tiene vencidos
                paga[top_vid]["A PAGAR"] += BONO_TOP
                cnt[top_vid]["bono_top"] = 1
            else:
                cnt[top_vid]["bono_top_retenido"] = 1
        elif len(empatados) > 1:
            aviso_top = (mx, [vend[v]["codigo"] for v in empatados])

    return {"vend": vend, "paga": paga, "cnt": cnt, "detalle": detalle,
            "alertas": alertas, "top_vid": top_vid, "aviso_top": aviso_top,
            "desde": desde, "hasta": hasta}


# --------------------------------------------------------------------------
def escribir_excel(r, ruta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.pagebreak import Break

    vend, paga, cnt = r["vend"], r["paga"], r["cnt"]
    thin = Side(style="thin", color="D0D7E5")
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    AR = lambda **k: Font(name="Arial", **k)  # noqa: E731

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = (f"CORTE DE COMISIONES  ·  {r['desde'].strftime('%d/%m/%Y')} a "
                f"{r['hasta'].strftime('%d/%m/%Y')}")
    ws["A1"].font = AR(bold=True, size=14, color=AZUL)
    ws["A2"] = (f"ENROLADOS: bodegas nuevas del mes, S/{TARIFA_ENROLADO:.0f} c/u   ·   "
                f"FINANCIADOS: recompras del mes, S/{TARIFA_FINANCIADO:.0f} c/u   ·   "
                f"el bono del top (S/{BONO_TOP:.0f}) va sumado dentro de PAGADO")
    ws["A2"].font = AR(size=10)
    ws["A3"] = ("PAGADO = la bodega ya pago, se deposita ahora   ·   VENCIDO = se le paso el "
                "plazo y no pago, hay que cobrar   ·   EN VUELO = aun dentro de su plazo.   "
                "VENCIDO y EN VUELO se le pagan igual al vendedor apenas la bodega pague.")
    ws["A3"].font = AR(size=10, italic=True)

    cab = ["Vendedor", "Cod.", "Enrolados", "Financiados (recompras)",
           "PAGADO S/", "VENCIDO S/", "EN VUELO S/", "⭐"]
    fila = 5
    for j, h in enumerate(cab, 1):
        c = ws.cell(row=fila, column=j, value=h)
        c.font = AR(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", wrap_text=True, vertical="center")
        c.border = borde
    fila += 1

    activos = [v for v in paga
               if (paga[v]["A PAGAR"] or paga[v]["EN VUELO"] or paga[v]["VENCIDO"])]
    sin = [v for v in vend if v not in activos]
    por_sup = defaultdict(list)
    for v in activos:
        por_sup[vend[v].get("supervisor") or "SIN SUPERVISOR"].append(v)

    ini_datos = fila + 1
    for sup in sorted(por_sup):
        c = ws.cell(row=fila, column=1, value=f"  Supervisor: {sup}")
        c.font = AR(bold=True, size=10)
        c.fill = PatternFill("solid", fgColor=GRIS)
        fila += 1
        for vid in sorted(por_sup[sup], key=lambda v: -paga[v]["A PAGAR"]):
            v, c_ = vend[vid], cnt[vid]
            vals = [v.get("nombre") or "", v["codigo"], c_["enrolados"], c_["financiados"],
                    paga[vid]["A PAGAR"], paga[vid]["VENCIDO"], paga[vid]["EN VUELO"],
                    "⭐" if vid == r["top_vid"] else ""]
            for j, val in enumerate(vals, 1):
                cc = ws.cell(row=fila, column=j, value=val)
                cc.font = AR(size=10)
                cc.border = borde
                if val and j in (5, 6, 7):
                    cc.fill = PatternFill("solid",
                                          fgColor={5: VERDE, 6: ROJO, 7: AMARILLO}[j])
                if j in (5, 6, 7):
                    cc.number_format = '#,##0.00'
            fila += 1
    fin_datos = fila - 1

    if sin:
        fila += 1
        c = ws.cell(row=fila, column=1, value="⬜ SIN MOVIMIENTO EN EL PERIODO")
        c.font = AR(bold=True, size=11)
        fila += 1
        for vid in sorted(sin, key=lambda v: vend[v]["codigo"]):
            ws.cell(row=fila, column=1, value=vend[vid].get("nombre") or "").font = AR(size=10)
            ws.cell(row=fila, column=2, value=vend[vid]["codigo"]).font = AR(size=10)
            fila += 1

    fila += 1
    ws.cell(row=fila, column=1, value="TOTAL EQUIPO").font = AR(bold=True, size=11)
    for j, col in ((3, "C"), (4, "D"), (5, "E"), (6, "F"), (7, "G")):
        c = ws.cell(row=fila, column=j, value=f"=SUM({col}{ini_datos}:{col}{fin_datos})")
        c.font = AR(bold=True, size=11)
        c.border = borde
        if j >= 5:
            c.number_format = '#,##0.00'
    for col, w in zip("ABCDEFGH", (32, 9, 11, 20, 13, 13, 13, 5)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = f"A{ini_datos}"

    # ---- Detalle
    wd = wb.create_sheet("Detalle")
    for j, h in enumerate(["Supervisor", "Vendedor", "Bodega", "Pedido", "Fecha",
                           "Concepto", "S/", "Estado"], 1):
        c = wd.cell(row=1, column=j, value=h)
        c.font = AR(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.border = borde
    for i, d in enumerate(sorted(r["detalle"], key=lambda x: (x[0], x[1], x[2], x[4])), start=2):
        for j, val in enumerate(d, 1):
            c = wd.cell(row=i, column=j, value=val.isoformat() if isinstance(val, date) else val)
            c.font = AR(size=10)
            c.border = borde
            if j == 7:
                c.number_format = '#,##0.00'
            if j == 8:
                c.fill = PatternFill("solid", fgColor={"A PAGAR": VERDE, "EN VUELO": AMARILLO,
                                                       "VENCIDO": ROJO}.get(val, AMARILLO))
    for col, w in zip("ABCDEFGH", (26, 10, 36, 11, 12, 13, 8, 11)):
        wd.column_dimensions[col].width = w
    wd.freeze_panes = "A2"
    wd.auto_filter.ref = f"A1:H{max(1, len(r['detalle']) + 1)}"

    # ---- Por vendedor: un bloque por cada uno, para mandarselo
    wv = wb.create_sheet("Por vendedor")
    wv.sheet_view.showGridLines = False
    porv = defaultdict(list)
    for d in r["detalle"]:
        porv[d[1]].append(d)
    cod_a_vid = {vend[v]["codigo"]: v for v in vend}
    f = 1
    for cod in sorted(porv, key=lambda c: -paga[cod_a_vid[c]]["A PAGAR"]):
        vid = cod_a_vid[cod]
        v, c_ = vend[vid], cnt[vid]
        wv.cell(row=f, column=1, value=f"{v.get('nombre') or ''}  ({cod})").font = \
            AR(bold=True, size=13, color=AZUL)
        wv.cell(row=f + 1, column=1,
                value=f"Corte {r['desde'].strftime('%d/%m/%Y')} a {r['hasta'].strftime('%d/%m/%Y')}"
                      f"   ·   Supervisor: {v.get('supervisor') or '—'}").font = AR(size=9, italic=True)
        f += 3
        for j, h in enumerate(["Bodega", "Pedido", "Fecha", "Concepto", "S/", "Estado"], 1):
            c = wv.cell(row=f, column=j, value=h)
            c.font = AR(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor=AZUL)
            c.border = borde
        f += 1
        ini = f
        for d in sorted(porv[cod], key=lambda x: (x[2], x[4])):
            vals = [d[2], d[3], d[4].isoformat() if isinstance(d[4], date) else d[4],
                    d[5], d[6], d[7]]
            for j, val in enumerate(vals, 1):
                c = wv.cell(row=f, column=j, value=val)
                c.font = AR(size=10)
                c.border = borde
                if j == 5:
                    c.number_format = '#,##0.00'
                if j == 6:
                    c.fill = PatternFill("solid", fgColor={"A PAGAR": VERDE, "VENCIDO": ROJO}
                                         .get(val, AMARILLO))
        # ^ el for anterior no avanzaba la fila; se avanza aqui
            f += 1
        fin = f - 1

        notas = [("A PAGAR", VERDE, "Se te deposita ahora"),
                 ("VENCIDO", ROJO, "Ya se paso el plazo: hay que cobrar. Se paga apenas paguen"),
                 ("EN VUELO", AMARILLO, "Se paga la prox semana, cuando paguen")]
        f += 1
        base_totales = f
        for etiqueta, color, nota in notas:
            c = wv.cell(row=f, column=4, value=etiqueta)
            c.font = AR(bold=True, size=10)
            c.fill = PatternFill("solid", fgColor=color)
            c.border = borde
            t = wv.cell(row=f, column=5,
                        value=f'=SUMIF(F{ini}:F{fin},"{etiqueta}",E{ini}:E{fin})'
                              + (f"+{BONO_TOP:.0f}" if (etiqueta == "A PAGAR" and c_.get("bono_top")) else ""))
            t.font = AR(bold=True, size=10)
            t.number_format = '#,##0.00'
            t.border = borde
            t.fill = PatternFill("solid", fgColor=color)
            wv.cell(row=f, column=6, value=nota).font = AR(size=9, italic=True)
            f += 1
        if c_.get("bono_top"):
            wv.cell(row=f, column=4, value="incluye bono TOP").font = AR(size=9, italic=True)
            wv.cell(row=f, column=5, value=BONO_TOP).font = AR(size=9, italic=True)
            wv.cell(row=f, column=5).number_format = '#,##0.00'
            f += 1
        c = wv.cell(row=f, column=4, value="TOTAL DEL MES")
        c.font = AR(bold=True, size=11)
        c.border = borde
        t = wv.cell(row=f, column=5, value=f"=SUM(E{base_totales}:E{base_totales + 2})")
        t.font = AR(bold=True, size=11)
        t.number_format = '#,##0.00'
        t.border = borde
        wv.cell(row=f, column=6,
                value=f"{c_['enrolados']} enrolado(s) + {c_['financiados']} financiado(s)"
                ).font = AR(size=9, italic=True)
        f += 3
        wv.row_breaks.append(Break(id=f - 1))   # un vendedor por pagina al imprimir
    for col, w in zip("ABCDEF", (38, 11, 12, 30, 10, 52)):
        wv.column_dimensions[col].width = w

    # ---- Alertas
    wa = wb.create_sheet("Alertas")
    for j, h in enumerate(["Pedido", "Bodega", "Fecha", "Problema"], 1):
        c = wa.cell(row=1, column=j, value=h)
        c.font = AR(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor=AZUL)
    if r["aviso_top"]:
        mx, cods = r["aviso_top"]
        wa.cell(row=2, column=4,
                value=f"EMPATE en el bono top: {', '.join(cods)} con {mx} enrolados. "
                      f"No se asigno el S/{BONO_TOP:.0f}: decidir a mano.").font = AR(bold=True)
    base_fila = 3 if r["aviso_top"] else 2
    for i, a in enumerate(sorted(set(r["alertas"])), start=base_fila):
        for j, val in enumerate(a, 1):
            wa.cell(row=i, column=j,
                    value=val.isoformat() if isinstance(val, date) else val).font = AR(size=10)
    for col, w in zip("ABCD", (12, 38, 12, 70)):
        wa.column_dimensions[col].width = w

    wb.save(ruta)


def escribir_mensajes(r, ruta):
    lineas = []
    for vid in sorted(r["vend"], key=lambda v: r["vend"][v]["codigo"]):
        v, c, p = r["vend"][vid], r["cnt"][vid], r["paga"][vid]
        nom = C.nombre_pila(v)   # recibe el dict del vendedor, no el string
        lineas.append(f">>> PARA: {v['codigo']} · {v.get('nombre') or ''}")
        if not (p["A PAGAR"] or p["EN VUELO"] or p["VENCIDO"]):
            lineas.append(f"Hola {nom}, este mes todavia no registras enrolamientos ni "
                          f"financiamientos. Cualquier cosa nos escribes.\n")
            continue
        partes = []
        if c["enrolados"]:
            partes.append(f"{c['enrolados']} enrolado(s), {c['enrolados_pagados']} ya pagando")
        if c["financiados"]:
            partes.append(f"{c['financiados']} financiado(s), {c['financiados_pagados']} ya cobrados")
        msg = f"Hola {nom}! Este mes llevas " + " y ".join(partes) + "."
        if c.get("bono_top"):
            msg += f" Ademas eres el TOP del mes: +S/{BONO_TOP:.0f} de bono."
        msg += f" Te confirmamos S/{p['A PAGAR']:.2f}."
        if p["EN VUELO"]:
            msg += (f" Tienes S/{p['EN VUELO']:.2f} en vuelo: esas bodegas siguen dentro "
                    f"de su plazo y se te pagan apenas paguen.")
        if p["VENCIDO"]:
            nv = c.get("enrolados_vencidos", 0) + c.get("financiados_vencidos", 0)
            msg += (f" OJO: S/{p['VENCIDO']:.2f} estan en {nv} pedido(s) que YA se pasaron "
                    f"de plazo. Apurate con esa cobranza: apenas paguen se te libera.")
        lineas.append(msg + "\n")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas))
    return sum(1 for v in r["vend"])


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    args = ap.parse_args()
    desde, hasta = date.fromisoformat(args.desde), date.fromisoformat(args.hasta)
    if hasta < desde:
        sys.exit("ERROR: --hasta es anterior a --desde.")

    base_url = C.env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    key = C.env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")
    print(f"Corte de comisiones v2  {desde} a {hasta}  (solo lectura)\n")

    r = calcular(base_url, key, desde, hasta, verbose=True)

    base = f"Corte_v2_{desde}_{hasta}"
    escribir_excel(r, base + ".xlsx")
    n = escribir_mensajes(r, "Mensajes_" + base + ".txt")

    tm = sum(d["A PAGAR"] for d in r["paga"].values())
    tv = sum(d["EN VUELO"] for d in r["paga"].values())
    tx = sum(d["VENCIDO"] for d in r["paga"].values())
    ne = sum(c["enrolados"] for c in r["cnt"].values())
    nf = sum(c["financiados"] for c in r["cnt"].values())
    nx = sum(c["enrolados_vencidos"] + c["financiados_vencidos"] for c in r["cnt"].values())
    print(f"\nLISTO:\n  {base}.xlsx\n  Mensajes_{base}.txt  ({n} mensajes)")
    print(f"\n  Enrolados del mes:   {ne}  ({sum(c['enrolados_pagados'] for c in r['cnt'].values())} ya pagando)")
    print(f"  Financiados del mes: {nf}  ({sum(c['financiados_pagados'] for c in r['cnt'].values())} ya cobrados)")
    print(f"\n  A PAGAR (confirmado):        S/{tm:.2f}")
    print(f"  EN VUELO (dentro de plazo):  S/{tv:.2f}")
    print(f"  VENCIDO (ya paso el plazo):  S/{tx:.2f}   en {nx} pedido(s) — cobrar")
    if r["top_vid"]:
        print(f"  ⭐ Top del mes: {r['vend'][r['top_vid']]['codigo']} "
              f"({r['cnt'][r['top_vid']]['enrolados']} enrolados) +S/{BONO_TOP:.0f}")
    if r["aviso_top"]:
        mx, cods = r["aviso_top"]
        print(f"  ⚠️  AVISO empate top: {', '.join(cods)} con {mx} enrolados. Decidir a mano.")
    if r["alertas"]:
        print(f"  ⚠️  {len(set(r['alertas']))} alerta(s) — revisar hoja Alertas.")


if __name__ == "__main__":
    main()
