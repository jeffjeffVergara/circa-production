#!/usr/bin/env python3
"""
CIRCA — Motor de Corte de Comisiones de Vendedores · v2.3
=========================================================
Un comando calcula las comisiones del periodo y genera un Excel claro
(agrupado por supervisor, vende arriba / no vende abajo) + mensajes de Mari.

CAMBIOS v2.3 (decisiones Paola, jul-2026):
  A. RETENCION JUNIO = S/1 por CADA financiamiento de bodega de cohorte
     junio (reemplaza el bono escalonado S/2/4/9 del PDF). Cada S/1 lleva
     su estado (A PAGAR / EN VUELO / VENCIDO); bodega atrasada -> EN ESPERA.
  B. TOP = el vendedor que mas bodegas ENROLA en el mes (financiadas + cash).
     S/20 se suman al A PAGAR en corte de mes completo si el top es unico.
  C. Arrastre generalizado: tambien los pedidos de julio en adelante
     (recompra S/1, retencion S/1, activacion S/5) arrastran al corte del
     mes en que la bodega pague.

CAMBIOS v2.2 (17-jul-2026):
  0. Esquema JULIO 2026 con dispatch por fecha del periodo. Cortes con
     --desde anterior al 1-jul siguen calculando con el esquema junio.

CAMBIOS v2.1 (jul-2026):
  a. El calculo vive en calcular_comisiones(), importable por el agente
     diario (circa_agente_vendedores.py) — una sola fuente de verdad.
  b. FIX: bodegas con es_test=NULL (fast-track) SI entran al universo.
  c. Errores del calculo lanzan RuntimeError (no sys.exit).

CAMBIOS v2.0 (jun-2026):
  1. Vendedores SIEMPRE con su supervisor (columna + agrupacion en Excel).
  2. Comision EN VUELO (amarillo) hasta que la bodega pague. Verde = a pagar.
  3. Los que SI venden arriba, los que NO venden abajo.
  4. Total por vendedor con su pago final (solo MATERIALIZADO/verde).
  5. Top vendedor: estrella ⭐.

USO:
    python3 circa_corte_comisiones.py --desde 2026-07-01 --hasta 2026-07-31

REQUISITOS (una vez):
    pip install requests openpyxl --break-system-packages
    export CIRCA_SUPABASE_URL="https://rhxqcoijzgqlecpdfhde.supabase.co"
    export CIRCA_SUPABASE_KEY="<service_role key>"
    (tambien acepta SUPABASE_URL / SUPABASE_KEY, y el .env junto al script)

ESQUEMA — dispatch automatico por fecha del periodo:
  · Periodo que inicia ANTES del 1-jul-2026 -> esquema JUNIO:
      Afiliacion financiada S/5 | Afiliacion cash S/3 (1 vez por bodega)
      Recompra financiada S/2, max 4, primer mes de la bodega (cash NO paga)
      Meta semanal: 5 afiliaciones financiadas en la semana = S/10 (max 4/mes)
      Top: estrella, NO suma al pago.
  · Periodo que inicia el 1-jul-2026 o despues -> esquema JULIO:
      Activacion financiada S/5 (1 vez por bodega; la cash NO paga en julio)
      Recompra financiada S/1, bodegas de cohorte julio, sin tope
      Retencion: S/1 por cada financiamiento de bodega de cohorte junio
      Meta: S/10 UNA vez al mes si TODAS las semanas ISO completas del mes
        tuvieron 5+ activaciones financiadas (se paga al corte de mes)
      Top: S/20 al que mas bodegas ENROLA (financiadas + cash); se suma al
        A PAGAR en corte de mes completo si hay top unico; empate -> aviso.
      ARRASTRE: comisiones EN VUELO/VENCIDAS de periodos anteriores (desde
        el 17-jun) se pagan en el corte del periodo en que la bodega pago,
        con el monto del esquema original. Meta y top NO arrastran.

ESTADOS DE COMISION (deterministas por periodo):
    MATERIALIZADA (verde): pagado hasta --hasta, o pedido cash -> a pagar.
    EN VUELO (amarillo): financiado, sin pagar dentro del periodo, en plazo.
    VENCIDA (rojo): financiado, sin pagar, vencido -> en espera.
    Pagos posteriores a --hasta entran por ARRASTRE en el corte siguiente:
    re-correr un corte historico nunca duplica pagos.

SEGURIDAD:
    Solo LECTURA. Excluye es_test=true y cuentas internas. Atribucion ambigua o
    sin vendedor -> hoja ALERTAS (nunca adivina).
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

try:
    import requests
except ImportError as exc:
    sys.exit(f"FALTA UNA LIBRERIA: {exc}. Corre: pip install requests openpyxl --break-system-packages")

# ----------------------------- Configuracion ------------------------------
TARIFAS = {"afiliacion_financiada": 5.0, "afiliacion_cash": 3.0,
           "recompra_financiada": 2.0, "meta_semanal": 10.0}
MAX_RECOMPRAS_MES1 = 4
META_SEMANAL_AFILIACIONES = 5
MAX_METAS_POR_PERIODO = 4
DIAS_PRIMER_MES = 30

# Esquema JULIO 2026 (PDF 30-jun + decisiones Paola 17-jul).
JULIO_INICIO = date(2026, 7, 1)
JUNIO_INICIO = date(2026, 6, 1)
ESQUEMA_INICIO = date(2026, 6, 17)  # antes de esto no se devengo comision
# Desde esta fecha, las bodegas de cohorte ANTERIOR a junio tambien retienen
# S/1 por financiamiento (decision Paola 24-ago-2026, NO retroactiva).
AGOSTO_INICIO = date(2026, 8, 1)
TARIFAS_JUL = {"activacion_financiada": 5.0, "recompra_julio": 1.0,
               "retencion_junio": 1.0, "retencion_prejunio": 1.0,
               "meta_mensual": 10.0, "top_mensual": 20.0}

DIMAX_DISTRIBUIDOR_ID = "d1a2b3c4-0001-4000-8000-000000000002"
CODIGOS_INTERNOS = {"VW-PAO", "VW-CYNTHIA", "CIRCA01", "VWTEST-JV", "VW-SARASVATI"}
ESTADOS_EXCLUIDOS_FRAGMENTOS = ("cancel", "rechaz", "expir", "anulad")

VERDE, VERDE_TXT = "C6EFCE", "0E6B3A"
AMARILLO, AMARILLO_TXT = "FFEB9C", "9C6500"
ROJO, ROJO_TXT = "FFC7CE", "9C0006"
AZUL, GRIS = "2F56C9", "E7ECF5"

# ------------------------------- Supabase ---------------------------------
def env_o_falla(*nombres):
    """Devuelve la primera variable de entorno presente entre las candidatas.
    Fallback: .env junto al script (mismo formato que usa el agente diario)."""
    for n in nombres:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        for n in nombres:
            v = os.environ.get(n, "").strip()
            if v:
                return v
    sys.exit(f"ERROR: falta la variable de entorno {nombres[0]}. Ver cabecera del script.")


def fetch_todo(base_url, key, tabla, select, filtros=""):
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"}
    filas, offset, page = [], 0, 1000
    while True:
        url = f"{base_url}/rest/v1/{tabla}?select={select}"
        if filtros:
            url += f"&{filtros}"
        headers["Range"] = f"{offset}-{offset + page - 1}"
        r = requests.get(url, headers=headers, timeout=60)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"ERROR Supabase '{tabla}' (HTTP {r.status_code}): {r.text[:400]}")
        lote = r.json()
        filas.extend(lote)
        if len(lote) < page:
            return filas
        offset += page


_FRAC_TS = re.compile(r"\.(\d+)")


def parse_ts(v):
    """Parsea un timestamp ISO de PostgREST.

    OJO (bug corregido 31-ago-2026): datetime.fromisoformat en Python <3.11
    solo acepta fracciones de segundo de 3 o 6 digitos. Postgres serializa
    con los digitos significativos que tenga, asi que timestamps como
    '2026-08-20T14:44:44.13623+00:00' (5 digitos) lanzaban ValueError y esta
    funcion devolvia None EN SILENCIO. Efecto: 11 de 140 pagos se leian como
    'nunca pago' -> la regla de bodega al dia congelaba toda la comision de
    esas bodegas. Normalizamos la fraccion a 6 digitos antes de parsear.
    """
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    m = _FRAC_TS.search(s)
    if m and len(m.group(1)) != 6:
        s = s[:m.start(1)] + m.group(1)[:6].ljust(6, "0") + s[m.end(1):]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_d(v):
    ts = parse_ts(v)
    if ts:
        return ts.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def nombre_pila(v):
    # Prefiere el nombre_corto explicito de la base (siempre correcto).
    # Si no existe, cae a una regla automatica (APELLIDO APELLIDO NOMBRES).
    corto = (v.get("nombre_corto") or "").strip()
    if corto:
        return corto
    t = (v.get("nombre") or "").split()
    if len(t) >= 3:
        return f"{t[2]} {t[0]}".title()
    if len(t) == 2:
        return f"{t[1]} {t[0]}".title()
    return (t[0] if t else v.get("codigo", "")).title()


# ------------------------------ Calculo -----------------------------------
def calcular_comisiones(base_url, key, desde, hasta, hoy=None, verbose=True):
    """Calcula las comisiones del periodo [desde, hasta] (fechas date).

    SOLO LECTURA. Devuelve un dict con:
        vendedores   lista de vendedores reales activos (supervisor, celular)
        vend         {vendedor_id: vendedor}
        paga         {vendedor_id: {"MAT"|"VUELO"|"VENC": monto}}
        cnt          {vendedor_id: {concepto: cantidad}} — incluye
                     retencion_junio (n de S/1), arrastre_monto,
                     semanas_cumplidas/evaluadas, metas_semanales, top_pagado
        afil_sem     {vendedor_id: {(iso_año, iso_sem): activ. financiadas}}
        afil_periodo {vendedor_id: enrolamientos del periodo (fin + cash)}
        top_vid      vendedor_id top o None (empate -> None + aviso)
        detalle      filas para la hoja Detalle
        alertas      filas para la hoja Alertas
        ambiguas     set de bodega_id con atribucion ambigua
        esquema      "junio" | "julio"

    Lanza RuntimeError si no puede calcular (el CLI lo convierte en exit).
    """
    if hoy is None:
        hoy = date.today()
    say = print if verbose else (lambda *a, **k: None)

    vendedores = fetch_todo(base_url, key, "vendedores",
                            "id,codigo,nombre,celular,activo,supervisor,nombre_corto",
                            f"distribuidor_id=eq.{DIMAX_DISTRIBUIDOR_ID}&activo=eq.true")
    vendedores = [v for v in vendedores if v["codigo"] not in CODIGOS_INTERNOS]
    if not vendedores:
        raise RuntimeError("0 vendedores reales activos.")
    vend = {v["id"]: v for v in vendedores}
    sin_sup = [v["codigo"] for v in vendedores if not (v.get("supervisor") or "").strip()]
    say(f"  Vendedores reales activos: {len(vendedores)}")
    if sin_sup:
        say(f"  AVISO sin supervisor: {', '.join(sin_sup)}")

    bv = fetch_todo(base_url, key, "bodega_vendedores", "bodega_id,vendedor_id,activo,rol", "activo=eq.true")
    por_bod = defaultdict(list)
    for f in bv:
        if f["vendedor_id"] in vend:
            por_bod[f["bodega_id"]].append(f)
    bod_a_vend, ambiguas = {}, set()
    for bid, mps in por_bod.items():
        if len(mps) == 1:
            bod_a_vend[bid] = mps[0]["vendedor_id"]
        else:
            no_conf = [m for m in mps if (m.get("rol") or "").upper() != "CONFITERIA"]
            if len(no_conf) == 1:
                bod_a_vend[bid] = no_conf[0]["vendedor_id"]
            else:
                ambiguas.add(bid)
    say(f"  Mapeos a vendedores reales: {len(bv)} ({len(ambiguas)} ambiguas)")

    # v2.1: es_test=NULL (fast-track) cuenta como bodega REAL. Solo se
    # excluye es_test=true explicito — mismo criterio que el agente diario.
    bodegas = fetch_todo(base_url, key, "bodegas", "id,nombre_comercial,razon_social,es_test")
    bodegas = [b for b in bodegas if b.get("es_test") is not True]
    bod = {b["id"]: b for b in bodegas}
    say(f"  Bodegas reales (incluye es_test NULL): {len(bodegas)}")

    pedidos = fetch_todo(base_url, key, "pedidos",
                         "id,numero,bodega_id,vendedor_id,monto_financiado,monto_contado,total,"
                         "estado,origen,created_at,pagado_at,fecha_pagado,fecha_vencimiento",
                         f"distribuidor_id=eq.{DIMAX_DISTRIBUIDOR_ID}")
    pedidos = [p for p in pedidos if p["bodega_id"] in bod]
    estados = sorted({(p.get("estado") or "NULL") for p in pedidos})
    excl = {e for e in estados if any(f in e.lower() for f in ESTADOS_EXCLUIDOS_FRAGMENTOS)}
    say(f"\n  Estados: {', '.join(estados)}")
    if excl:
        say(f"  Excluidos: {', '.join(sorted(excl))}")
    pedidos = [p for p in pedidos if (p.get("estado") or "NULL") not in excl]
    say(f"  Pedidos validos: {len(pedidos)}")

    for p in pedidos:
        p["_f"] = parse_ts(p["created_at"]).date() if parse_ts(p["created_at"]) else None
        p["_fin"] = float(p["monto_financiado"] or 0) > 0
        p["_pag"] = parse_ts(p.get("pagado_at")) or parse_ts(p.get("fecha_pagado"))
        p["_venc"] = parse_d(p.get("fecha_vencimiento"))

    pb = defaultdict(list)
    for p in pedidos:
        if p["_f"]:
            pb[p["bodega_id"]].append(p)
    for l in pb.values():
        l.sort(key=lambda x: x["created_at"])

    def estado_com(p):
        # Determinista por periodo: pagado DESPUES de --hasta no es MAT de
        # este corte (se pagara por arrastre en el corte del periodo en que
        # pago). Asi un re-corrido historico nunca duplica pagos.
        if not p["_fin"]:
            return "MAT"
        if p["_pag"] is not None and p["_pag"].date() <= hasta:
            return "MAT"
        if p["_venc"] and p["_venc"] < hoy:
            return "VENC"
        return "VUELO"

    def atribuir(p):
        return p.get("vendedor_id") if p.get("vendedor_id") in vend else bod_a_vend.get(p["bodega_id"])

    detalle, alertas = [], []
    paga = defaultdict(lambda: defaultdict(float))
    cnt = defaultdict(lambda: defaultdict(int))
    afil_sem = defaultdict(lambda: defaultdict(int))
    afil_periodo = defaultdict(int)

    def reg(vid, nb, p, concepto, monto, estado=None, etiqueta=None):
        est = estado if estado is not None else estado_com(p)
        paga[vid][est] += monto
        cnt[vid][concepto] += 1
        detalle.append((vend[vid].get("supervisor") or "SIN SUPERVISOR", vend[vid]["codigo"],
                        nb, p.get("numero") or "", p["_f"],
                        (etiqueta or concepto).replace("_", " "), monto, est))

    esquema = "julio" if desde >= JULIO_INICIO else "junio"
    say(f"  Esquema aplicado: {esquema.upper()}")

    if esquema == "junio":
        for bid, lst in pb.items():
            fin_mes1 = lst[0]["_f"] + timedelta(days=DIAS_PRIMER_MES)
            nb = bod[bid].get("nombre_comercial") or bod[bid].get("razon_social") or bid[:8]
            recompras = 0
            for idx, p in enumerate(lst):
                vid = atribuir(p)
                if vid is None:
                    if desde <= p["_f"] <= hasta:
                        motivo = "ATRIBUCION AMBIGUA" if bid in ambiguas else "SIN VENDEDOR asignado"
                        alertas.append((p.get("numero") or p["id"][:8], nb, p["_f"], motivo))
                    continue
                en = desde <= p["_f"] <= hasta
                if idx == 0:
                    c = "afiliacion_financiada" if p["_fin"] else "afiliacion_cash"
                    if en:
                        afil_periodo[vid] += 1
                        if p["_fin"]:
                            afil_sem[vid][p["_f"].isocalendar()[:2]] += 1
                        reg(vid, nb, p, c, TARIFAS[c])
                else:
                    if not p["_fin"]:
                        continue
                    if p["_f"] <= fin_mes1:
                        if recompras >= MAX_RECOMPRAS_MES1:
                            if en:
                                detalle.append((vend[vid].get("supervisor") or "SIN SUPERVISOR", vend[vid]["codigo"],
                                                nb, p.get("numero") or "", p["_f"], "recompra (sobre tope 4)", 0.0, "NOPAGA"))
                            continue
                        recompras += 1
                        if en:
                            reg(vid, nb, p, "recompra_financiada", TARIFAS["recompra_financiada"])
                    elif en:
                        cnt[vid]["bolsa_mes2"] += 1
                        detalle.append((vend[vid].get("supervisor") or "SIN SUPERVISOR", vend[vid]["codigo"],
                                        nb, p.get("numero") or "", p["_f"], "recompra mes 2+ (bolsa)", 0.0, "BOLSA"))

        for vid, sem in afil_sem.items():
            metas = min(sum(1 for c in sem.values() if c >= META_SEMANAL_AFILIACIONES), MAX_METAS_POR_PERIODO)
            if metas:
                cnt[vid]["metas_semanales"] = metas
                paga[vid]["MAT"] += metas * TARIFAS["meta_semanal"]

    else:
        # ---------------------- ESQUEMA JULIO 2026 ------------------------
        # REGLA DE CALIDAD (PDF): "El bono de una bodega se paga solo si esa
        # bodega esta al dia. Mientras siga atrasada, su comision
        # —activacion, recompra y financiado— queda en espera. Apenas paga,
        # se te libera el bono."
        # Modelo determinista: una comision se LIBERA (pasa a A PAGAR) en la
        # fecha en que se cumplen AMBAS: (1) su pedido esta pagado, (2) la
        # bodega esta al dia. Se paga en el corte del periodo que contiene
        # esa fecha de liberacion — sea el corte del pedido o uno posterior
        # (arrastre). Nada se pierde ni se paga dos veces.
        #
        # atrasada_hasta[bid]: al cierre del periodo tiene pedido financiado
        #   vencido e impago -> TODO lo de esa bodega queda EN ESPERA.
        # lib_bodega[bid]: fecha en que la bodega quedo al dia (pago mas
        #   tardio de sus pedidos que estuvieron vencidos); None = nunca
        #   estuvo vencida.
        atrasada_hasta, lib_bodega = {}, {}
        for bid, lst in pb.items():
            atras, lib = False, None
            for p in lst:
                if not p["_fin"] or not p["_venc"]:
                    continue
                pagd = p["_pag"].date() if p["_pag"] else None
                if pagd is None or pagd > hasta:
                    if p["_venc"] <= hasta:
                        atras = True
                elif pagd > p["_venc"]:
                    lib = pagd if lib is None else max(lib, pagd)
            atrasada_hasta[bid] = atras
            lib_bodega[bid] = lib

        def liberacion(bid, p):
            """Fecha en que la comision del pedido queda liberada, o None si
            el pedido sigue impago al cierre del periodo. Pagos anteriores
            al 1-jul pertenecen al regimen de junio (su corte ya los pago
            sin bloqueo por bodega): liberacion = fecha de pago, nunca se
            re-liberan aqui."""
            pagd = p["_pag"].date() if p["_pag"] else None
            if pagd is None or pagd > hasta:
                return None
            if pagd < JULIO_INICIO:
                return pagd
            lb = lib_bodega.get(bid)
            return max(pagd, lb) if lb else pagd

        def reg_arrastre(vid, nb, p, concepto, monto):
            paga[vid]["MAT"] += monto
            cnt[vid]["arrastre_monto"] += monto
            detalle.append(((vend[vid].get("supervisor") or "SIN SUPERVISOR"), vend[vid]["codigo"],
                            nb, p.get("numero") or "", p["_f"],
                            concepto.replace("_", " ") + " (arrastre)", monto, "MAT"))

        def reg_julio(vid, bid, nb, p, concepto, monto):
            """Registra una comision aplicando la regla de bodega al dia.
            en-periodo: MAT si liberada, EN ESPERA si bodega atrasada,
            VUELO/VENC si impaga. pre-periodo: arrastre solo si la
            liberacion cae dentro de este periodo."""
            en = desde <= p["_f"] <= hasta
            if atrasada_hasta[bid]:
                if en:
                    reg(vid, nb, p, concepto, monto, estado="VENC",
                        etiqueta=concepto + " (EN ESPERA: bodega atrasada)")
                # pre-periodo bloqueado: se liberara (y arrastrara) cuando
                # la bodega se ponga al dia.
                return
            lib = liberacion(bid, p)
            if lib is not None and desde <= lib <= hasta:
                if en:
                    reg(vid, nb, p, concepto, monto)          # MAT
                else:
                    reg_arrastre(vid, nb, p, concepto, monto)  # liberada ahora
            elif en:
                reg(vid, nb, p, concepto, monto)  # impaga: VUELO/VENC
            # pre-periodo con liberacion anterior al periodo: ya se pago en
            # su corte. Liberacion futura: pagara en el corte que toque.

        def es_relevante(bid, p):
            """Para alertas de pedidos sin vendedor: en periodo o liberando
            en este periodo."""
            if desde <= p["_f"] <= hasta:
                return True
            lib = None if atrasada_hasta[bid] else liberacion(bid, p)
            return lib is not None and desde <= lib <= hasta and p["_f"] >= ESQUEMA_INICIO

        for bid, lst in pb.items():
            cohorte = lst[0]["_f"]
            fin_mes1_jun = cohorte + timedelta(days=DIAS_PRIMER_MES)
            recompras_jun = 0  # tope 4 del esquema junio (pedidos fechados en junio)
            nb = bod[bid].get("nombre_comercial") or bod[bid].get("razon_social") or bid[:8]
            for idx, p in enumerate(lst):
                vid = atribuir(p)
                if vid is None:
                    if p["_fin"] and es_relevante(bid, p):
                        motivo = "ATRIBUCION AMBIGUA" if bid in ambiguas else "SIN VENDEDOR asignado"
                        alertas.append((p.get("numero") or p["id"][:8], nb, p["_f"], motivo))
                    continue
                en = desde <= p["_f"] <= hasta
                sup_cod = (vend[vid].get("supervisor") or "SIN SUPERVISOR", vend[vid]["codigo"])

                if idx == 0:
                    if en:
                        afil_periodo[vid] += 1  # top = enrolamientos (fin + cash)
                        if p["_fin"]:
                            afil_sem[vid][p["_f"].isocalendar()[:2]] += 1
                    if p["_fin"]:
                        if p["_f"] >= ESQUEMA_INICIO:
                            reg_julio(vid, bid, nb, p, "afiliacion_financiada",
                                      TARIFAS["afiliacion_financiada"])
                    elif en:
                        # En julio la afiliacion cash NO paga — se reporta.
                        cnt[vid]["afiliacion_cash"] += 1
                        detalle.append((*sup_cod, nb, p.get("numero") or "", p["_f"],
                                        "afiliacion cash (S/0 en julio)", 0.0, "NOPAGA"))
                    continue

                # idx > 0 (recompras / financiamientos posteriores)
                if not p["_fin"]:
                    continue
                if p["_f"] < JULIO_INICIO:
                    # Recompra fechada en junio: esquema junio (S/2, tope 4,
                    # primer mes). El contador avanza siempre (misma logica
                    # que v2.0); paga por liberacion/arrastre.
                    if p["_f"] >= ESQUEMA_INICIO and p["_f"] <= fin_mes1_jun:
                        if recompras_jun < MAX_RECOMPRAS_MES1:
                            recompras_jun += 1
                            reg_julio(vid, bid, nb, p, "recompra_financiada",
                                      TARIFAS["recompra_financiada"])
                    continue

                # Pedido fechado en julio en adelante
                if cohorte >= JULIO_INICIO:
                    reg_julio(vid, bid, nb, p, "recompra_financiada",
                              TARIFAS_JUL["recompra_julio"])
                elif cohorte >= JUNIO_INICIO:
                    reg_julio(vid, bid, nb, p, "retencion_junio",
                              TARIFAS_JUL["retencion_junio"])
                elif p["_f"] >= AGOSTO_INICIO:
                    # Decisión Paola 24-ago-2026: las bodegas de cohorte
                    # ANTERIOR a junio también retienen S/1 por financiamiento.
                    # Se activa por FECHA DEL PEDIDO (no por periodo del corte),
                    # así re-correr un corte de junio o julio da exactamente el
                    # mismo resultado que antes: no es retroactivo.
                    reg_julio(vid, bid, nb, p, "retencion_prejunio",
                              TARIFAS_JUL["retencion_prejunio"])
                elif en:
                    cnt[vid]["bolsa_mes2"] += 1
                    detalle.append((*sup_cod, nb, p.get("numero") or "", p["_f"],
                                    "recompra cohorte pre-junio (S/0 — sin esquema)", 0.0, "BOLSA"))

        # Meta mensual: S/10 UNA vez si TODAS las semanas evaluadas del mes
        # tuvieron 5+ activaciones financiadas. Solo cuentan semanas ISO
        # COMPLETAS (lunes a domingo) dentro del mes — el ejemplo del PDF
        # (20 act = 4 semanas x 5) asume semanas enteras. Solo se paga en
        # corte de mes completo; en avances parciales se reporta el ritmo.
        mes_ini = desde.replace(day=1)
        ult_dia_mes = (desde.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        def lunes(wk):
            return date.fromisocalendar(wk[0], wk[1], 1)

        def domingo(wk):
            return date.fromisocalendar(wk[0], wk[1], 7)

        semanas_mes, d = [], mes_ini
        while d <= ult_dia_mes:
            wk = d.isocalendar()[:2]
            if wk not in semanas_mes and lunes(wk) >= mes_ini and domingo(wk) <= ult_dia_mes:
                semanas_mes.append(wk)
            d += timedelta(days=1)
        # Una semana esta "evaluada" cuando ya termino (su domingo <= hasta)
        evaluadas = [wk for wk in semanas_mes if domingo(wk) <= hasta]
        for vid in vend:
            cumplidas = sum(1 for wk in evaluadas
                            if afil_sem[vid].get(wk, 0) >= META_SEMANAL_AFILIACIONES)
            if evaluadas:
                cnt[vid]["semanas_evaluadas"] = len(evaluadas)
                cnt[vid]["semanas_cumplidas"] = cumplidas
            if (hasta >= ult_dia_mes and evaluadas
                    and cumplidas == len(evaluadas)):
                cnt[vid]["metas_semanales"] = 1
                paga[vid]["MAT"] += TARIFAS_JUL["meta_mensual"]

    top_vid = None
    if afil_periodo:
        top_n = max(afil_periodo.values())
        tops = [v for v, n in afil_periodo.items() if n == top_n and n > 0]
        top_vid = tops[0] if len(tops) == 1 else None
        if len(tops) > 1:
            say(f"\n  AVISO empate top ({len(tops)} con {top_n} enrolamientos). Decidir manual.")

    # Esquema julio: el top S/20 esta PUBLICADO como pago -> se suma al
    # A PAGAR en el corte de mes completo si hay top unico. En avances
    # parciales solo se marca la estrella (el lider puede cambiar).
    if esquema == "julio" and top_vid is not None:
        fin_mes = (desde.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if hasta >= fin_mes:
            paga[top_vid]["MAT"] += TARIFAS_JUL["top_mensual"]
            cnt[top_vid]["top_pagado"] = 1
            detalle.append(((vend[top_vid].get("supervisor") or "SIN SUPERVISOR"),
                            vend[top_vid]["codigo"], "—", "", hasta,
                            "top vendedor del mes", TARIFAS_JUL["top_mensual"], "MAT"))

    return {"vendedores": vendedores, "vend": vend, "paga": paga, "cnt": cnt,
            "afil_sem": afil_sem, "afil_periodo": afil_periodo, "top_vid": top_vid,
            "detalle": detalle, "alertas": alertas, "ambiguas": ambiguas,
            "esquema": esquema}


# ------------------------------- Main -------------------------------------
def main():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        sys.exit(f"FALTA UNA LIBRERIA: {exc}. Corre: pip install requests openpyxl --break-system-packages")

    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    args = ap.parse_args()
    desde, hasta = date.fromisoformat(args.desde), date.fromisoformat(args.hasta)
    if hasta < desde:
        sys.exit("ERROR: --hasta es anterior a --desde.")

    base_url = env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    key = env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")
    print(f"Corte de comisiones {desde} a {hasta} (solo lectura)\n")

    try:
        r = calcular_comisiones(base_url, key, desde, hasta, verbose=True)
    except RuntimeError as exc:
        sys.exit(f"ERROR: {exc}")

    vendedores, vend = r["vendedores"], r["vend"]
    paga, cnt = r["paga"], r["cnt"]
    top_vid, detalle, alertas = r["top_vid"], r["detalle"], r["alertas"]

    # ------------------------------- Excel --------------------------------
    base = f"Corte_Comisiones_{desde}_{hasta}"
    wb = Workbook()
    thin = Side(style="thin", color="D0D7E5")
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    hf = PatternFill("solid", fgColor=AZUL)
    ht = Font(color="FFFFFF", bold=True, size=11)
    sf = PatternFill("solid", fgColor=GRIS)

    ws = wb.active
    ws.title = "Resumen"
    ws.merge_cells("A1:K1")
    ws["A1"] = f"CORTE DE COMISIONES  ·  {desde.strftime('%d/%m/%Y')} a {hasta.strftime('%d/%m/%Y')}"
    ws["A1"].font = Font(bold=True, size=14, color=AZUL)
    ws.row_dimensions[1].height = 26
    ws.merge_cells("A2:K2")
    ws["A2"] = ("Verde = a pagar (bodega ya pago)   |   Amarillo = en vuelo (se paga si la bodega paga)"
                "   |   Rojo = en espera (no pago a tiempo)   |   ⭐ = top del mes")
    ws["A2"].font = Font(italic=True, size=9, color="5B6678")

    cab = ["Vendedor", "Cod.", "Afil.fin", "Afil.cash", "Recompras", "Ret.jun", "Metas",
           "A PAGAR S/", "EN VUELO S/", "VENCIDO S/", "⭐"]

    def cabecera(f):
        for j, h in enumerate(cab, 1):
            c = ws.cell(row=f, column=j, value=h)
            c.fill, c.font, c.border = hf, ht, borde
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[f].height = 30

    def fila_vend(f, v):
        vid = v["id"]
        mat, vu, ve = round(paga[vid]["MAT"], 2), round(paga[vid]["VUELO"], 2), round(paga[vid]["VENC"], 2)
        vals = [nombre_pila(v), v["codigo"], cnt[vid]["afiliacion_financiada"],
                cnt[vid]["afiliacion_cash"], cnt[vid]["recompra_financiada"],
                cnt[vid]["retencion_junio"], cnt[vid]["metas_semanales"],
                mat, vu, ve, "⭐" if vid == top_vid else ""]
        for j, val in enumerate(vals, 1):
            c = ws.cell(row=f, column=j, value=val)
            c.border = borde
            c.alignment = Alignment(horizontal="center" if j > 1 else "left", vertical="center")
        ws.cell(row=f, column=8).fill = PatternFill("solid", fgColor=VERDE)
        ws.cell(row=f, column=8).font = Font(bold=True, color=VERDE_TXT)
        if vu > 0:
            ws.cell(row=f, column=9).fill = PatternFill("solid", fgColor=AMARILLO)
            ws.cell(row=f, column=9).font = Font(color=AMARILLO_TXT)
        if ve > 0:
            ws.cell(row=f, column=10).fill = PatternFill("solid", fgColor=ROJO)
            ws.cell(row=f, column=10).font = Font(color=ROJO_TXT)
        return mat, vu, ve

    def total_v(v):
        vid = v["id"]
        return (paga[vid]["MAT"] + paga[vid]["VUELO"] + paga[vid]["VENC"]
                + cnt[vid]["afiliacion_financiada"] + cnt[vid]["afiliacion_cash"]
                + cnt[vid]["recompra_financiada"] + cnt[vid]["retencion_junio"])

    venden = sorted([v for v in vendedores if total_v(v) > 0],
                    key=lambda v: (v.get("supervisor") or "ZZZ", -paga[v["id"]]["MAT"]))
    no_venden = sorted([v for v in vendedores if total_v(v) == 0],
                       key=lambda v: (v.get("supervisor") or "ZZZ", v["codigo"]))

    f = 4
    tm = tv = tx = 0.0
    ws.cell(row=f, column=1, value="✅ VENDEDORES CON ACTIVIDAD").font = Font(bold=True, size=12, color=VERDE_TXT)
    f += 1
    cabecera(f); f += 1
    sup = None
    for v in venden:
        s = v.get("supervisor") or "SIN SUPERVISOR"
        if s != sup:
            ws.merge_cells(start_row=f, start_column=1, end_row=f, end_column=11)
            c = ws.cell(row=f, column=1, value=f"  Supervisor: {s}")
            c.fill, c.font = sf, Font(bold=True, color=AZUL)
            f += 1; sup = s
        m, vu, ve = fila_vend(f, v)
        tm += m; tv += vu; tx += ve; f += 1

    f += 1
    ws.cell(row=f, column=1, value="⬜ SIN ACTIVIDAD EN EL PERIODO").font = Font(bold=True, size=12, color="8A93A6")
    f += 1
    cabecera(f); f += 1
    sup = None
    for v in no_venden:
        s = v.get("supervisor") or "SIN SUPERVISOR"
        if s != sup:
            ws.merge_cells(start_row=f, start_column=1, end_row=f, end_column=11)
            c = ws.cell(row=f, column=1, value=f"  Supervisor: {s}")
            c.fill, c.font = sf, Font(bold=True, color="8A93A6")
            f += 1; sup = s
        fila_vend(f, v); f += 1

    f += 1
    ws.cell(row=f, column=1, value="TOTAL EQUIPO").font = Font(bold=True, size=12)
    for col, val, color in [(8, tm, VERDE), (9, tv, AMARILLO), (10, tx, ROJO)]:
        c = ws.cell(row=f, column=col, value=round(val, 2))
        c.fill = PatternFill("solid", fgColor=color)
        c.font = Font(bold=True, size=12)
        c.border = borde

    for j, a in enumerate([26, 8, 9, 9, 11, 8, 8, 13, 13, 12, 5], 1):
        ws.column_dimensions[get_column_letter(j)].width = a
    ws.freeze_panes = "A4"

    # Detalle
    wd = wb.create_sheet("Detalle")
    for j, h in enumerate(["Supervisor", "Vendedor", "Bodega", "Pedido", "Fecha", "Concepto", "S/", "Estado"], 1):
        c = wd.cell(row=1, column=j, value=h); c.fill, c.font = hf, ht
    rr = 2
    estado_legible = {"MAT": "A PAGAR", "VUELO": "EN VUELO", "VENC": "VENCIDO", "BOLSA": "BOLSA M2+", "NOPAGA": "SOBRE TOPE"}
    for d in sorted(detalle):
        s, cod, b, p, fch, con, mon, est = d
        for j, val in enumerate([s, cod, b, p, fch.isoformat() if fch else "", con, mon, estado_legible.get(est, est)], 1):
            wd.cell(row=rr, column=j, value=val)
        ce = wd.cell(row=rr, column=8)
        if est == "MAT":
            ce.fill = PatternFill("solid", fgColor=VERDE); ce.font = Font(color=VERDE_TXT)
        elif est == "VUELO":
            ce.fill = PatternFill("solid", fgColor=AMARILLO); ce.font = Font(color=AMARILLO_TXT)
        elif est == "VENC":
            ce.fill = PatternFill("solid", fgColor=ROJO); ce.font = Font(color=ROJO_TXT)
        rr += 1
    for j, a in enumerate([26, 10, 28, 14, 11, 38, 7, 12], 1):
        wd.column_dimensions[get_column_letter(j)].width = a
    wd.freeze_panes = "A2"

    # Alertas
    wa = wb.create_sheet("Alertas")
    for j, h in enumerate(["Pedido", "Bodega", "Fecha", "Problema"], 1):
        c = wa.cell(row=1, column=j, value=h); c.fill, c.font = hf, ht
    for i, al in enumerate(alertas, 2):
        wa.cell(row=i, column=1, value=al[0]); wa.cell(row=i, column=2, value=al[1])
        wa.cell(row=i, column=3, value=al[2].isoformat() if al[2] else ""); wa.cell(row=i, column=4, value=al[3])
    for j, a in enumerate([16, 28, 11, 40], 1):
        wa.column_dimensions[get_column_letter(j)].width = a

    wb.save(f"{base}.xlsx")

    # Mensajes de Mari
    lineas = []
    for v in sorted(vendedores, key=lambda x: (x.get("supervisor") or "ZZZ", x["codigo"])):
        vid = v["id"]
        mat, vu, ve = round(paga[vid]["MAT"], 2), round(paga[vid]["VUELO"], 2), round(paga[vid]["VENC"], 2)
        n = nombre_pila(v)
        if mat == 0 and vu == 0 and ve == 0 and cnt[vid]["bolsa_mes2"] == 0:
            msg = (f"Hola {n} 👋 Soy Mari. Esta semana aun no registro bodegas tuyas en Circa. "
                   f"Dime cual de tu ruta quieres activar primero y te preparo todo: linea, promos y que decirle.")
        else:
            partes = []
            if cnt[vid]["afiliacion_financiada"]:
                partes.append(f"{cnt[vid]['afiliacion_financiada']} activacion(es) financiada(s)")
            if cnt[vid]["afiliacion_cash"]:
                partes.append(f"{cnt[vid]['afiliacion_cash']} afiliacion(es) cash")
            if cnt[vid]["recompra_financiada"]:
                partes.append(f"{cnt[vid]['recompra_financiada']} recompra(s) financiada(s)")
            if cnt[vid]["retencion_junio"]:
                partes.append(f"{cnt[vid]['retencion_junio']} financiamiento(s) de tus bodegas de junio (S/1 c/u)")
            if cnt[vid]["metas_semanales"]:
                partes.append("bono mensual de ritmo")
            if cnt[vid]["arrastre_monto"]:
                partes.append(f"S/{cnt[vid]['arrastre_monto']:.2f} liberados del mes anterior")
            if cnt[vid]["top_pagado"]:
                partes.append("bono TOP del mes (S/20)")
            msg = (f"Hola {n} 👋 Soy Mari. Tu avance Circa del {desde.strftime('%d/%m')} al {hasta.strftime('%d/%m')}: "
                   + " + ".join(partes) + f". Llevas S/{mat:.2f} confirmados a pagar.")
            if vu:
                msg += f" Y S/{vu:.2f} en camino — se confirman cuando esas bodegas paguen su pedido."
            if ve:
                msg += f" Ojo: S/{ve:.2f} en espera por bodegas que no pagaron a tiempo — ayudalas a ponerse al dia."
            if vid == top_vid and not cnt[vid]["top_pagado"]:
                msg += " 🏆 ¡Vas TOP del mes!"
            msg += " El pago sale a fin de mes por Yape. 💪"
        lineas.append(f"=== {v['codigo']} · {v['nombre']} · {v.get('celular') or 'SIN CELULAR'} "
                      f"· Sup: {v.get('supervisor') or '-'} ===\n{msg}\n")
    with open(f"Mensajes_{base}.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas))

    print(f"\nLISTO:")
    print(f"  {base}.xlsx  (Resumen + Detalle + {len(alertas)} alertas)")
    print(f"  Mensajes_{base}.txt  ({len(vendedores)} mensajes)")
    print(f"\n  A PAGAR (confirmado): S/{tm:.2f}")
    print(f"  EN VUELO (si pagan):  S/{tv:.2f}")
    print(f"  VENCIDO (en espera):  S/{tx:.2f}")
    if top_vid:
        print(f"  ⭐ Top: {vend[top_vid]['codigo']}")
    if alertas:
        print(f"\n  ATENCION: {len(alertas)} alertas — resolver ANTES de pagar.")


if __name__ == "__main__":
    # MOTOR OFICIAL = circa_corte_v2 (esquema agosto + filtros 5 y 6).
    # Decision Paola 22-sep-2026. El main() de arriba (JULIO) quedo OBSOLETO
    # (pagaba metas/recompras diferenciadas/retenciones que agosto elimino).
    # Se conserva por historial y por sus helpers que circa_corte_v2 importa.
    import circa_corte_v2 as V2
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--desde", required=True); _ap.add_argument("--hasta", required=True)
    _a = _ap.parse_args()
    _d, _h = date.fromisoformat(_a.desde), date.fromisoformat(_a.hasta)
    if _h < _d: sys.exit("ERROR: --hasta es anterior a --desde.")
    _base_url = env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    _key = env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")
    print(f"Corte de comisiones (agosto + filtros 5 y 6)  {_d} a {_h}  (solo lectura)\n")
    _r = V2.calcular(_base_url, _key, _d, _h, verbose=True)
    _b = f"Corte_Comisiones_{_d}_{_h}"
    V2.escribir_excel(_r, _b + ".xlsx")
    V2.escribir_mensajes(_r, "Mensajes_" + _b + ".txt")
    _tm = sum(x["A PAGAR"] for x in _r["paga"].values())
    print(f"\nLISTO: {_b}.xlsx   A PAGAR S/{_tm:.2f}")
