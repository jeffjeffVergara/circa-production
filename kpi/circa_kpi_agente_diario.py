#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CIRCA — Agente KPI diario v2
============================
Corre a diario. Lee vw_kpi_diario_v2 + vistas de estado, construye todas
las ventanas de análisis en Python (no en SQL), compara contra períodos
anteriores (NA donde no hay historia), detecta bodegas que cayeron a
inactivas vs el snapshot anterior, guarda snapshot JSONB y genera:
  - circa_kpi_YYYY-MM-DD.xlsx  (ejecutivo)
  - circa_kpi_YYYY-MM-DD.md    (resumen + análisis)

Ventanas:
  - Desde inicio (acumulado total)
  - Meses cerrados (todos)
  - MTD (mes en curso) vs mismo rango del mes anterior (día 1..N)
  - Semanas ISO (lun-dom, hora Lima)
  - Semana en curso vs semana anterior (W-1) y semana comparable (W-4)

Uso:
  export SUPABASE_URL="https://rhxqcoijzgqlecpdfhde.supabase.co"
  export SUPABASE_SERVICE_KEY="<key>"
  export ANTHROPIC_API_KEY="<key>"        # opcional: análisis narrativo
  python3 circa_kpi_agente_diario.py

Scheduling: Railway cron (servicio aparte, mismo repo) o launchd/cron local.
"""

import os, sys, json, datetime as dt
import pandas as pd
from supabase import create_client

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
TZ_HOY = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=5)   # Lima = UTC-5
HOY = TZ_HOY.date()
INACTIVO_DIAS = 15          # definición Tier3/Zombie confirmada por Paola
METAS = {"afiliaciones_dia": 5, "pedidos_financiados_dia": 5,
         "recompra_7d": 0.65, "recompra_14d": 0.85}
METRICAS = ["afiliaciones", "pedidos", "pedidos_financiados",
            "bodegas_compraron", "bodegas_financiaron",
            "gmv", "monto_financiado", "monto_contado", "revenue_fee"]

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def fetch(vista, **eq):
    q = sb.table(vista).select("*")
    for k, v in eq.items():
        q = q.eq(k, v)
    rows, page = [], 0
    while True:
        r = q.range(page * 1000, page * 1000 + 999).execute()
        rows += r.data
        if len(r.data) < 1000:
            return rows
        page += 1


# ----------------------------------------------------------------------
# 1. Base diaria
# ----------------------------------------------------------------------
df = pd.DataFrame(fetch("vw_kpi_diario_v2"))
if df.empty:
    sys.exit("vw_kpi_diario_v2 sin datos — ¿se corrió 02_vistas_kpi_v2.sql?")
df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
df = df.set_index("fecha").sort_index()
# calendario completo (días sin actividad = 0)
full = pd.date_range(df.index.min(), HOY, freq="D").date
df = df.reindex(full, fill_value=0)
df.index.name = "fecha"
INICIO = df.index.min()


def agg(d0, d1):
    """Suma métricas en [d0, d1]. None si el rango precede al inicio de Circa."""
    if d1 < INICIO:
        return None
    sub = df.loc[max(d0, INICIO):d1]
    if sub.empty:
        return None
    return sub[METRICAS].sum().round(2).to_dict()


def comparar(actual, previo):
    """Δ% por métrica; 'NA' si no hay período previo o base 0."""
    out = {}
    for m in METRICAS:
        if previo is None or previo.get(m) in (None, 0):
            out[m] = "NA"
        else:
            out[m] = round((actual[m] - previo[m]) / previo[m] * 100, 1)
    return out


# ----------------------------------------------------------------------
# 2. Ventanas
# ----------------------------------------------------------------------
reporte = {"fecha": str(HOY), "inicio_circa": str(INICIO)}

# 2a. Acumulado desde inicio
reporte["desde_inicio"] = agg(INICIO, HOY)

# 2b. Meses cerrados (todos) + Δ vs mes anterior
meses = []
m = pd.Timestamp(INICIO).to_period("M")
while m < pd.Timestamp(HOY).to_period("M"):
    d0, d1 = m.start_time.date(), m.end_time.date()
    cur = agg(d0, d1)
    prev = agg((m - 1).start_time.date(), (m - 1).end_time.date())
    meses.append({"mes": str(m), "kpis": cur, "vs_mes_anterior_pct": comparar(cur, prev)})
    m += 1
reporte["meses_cerrados"] = meses

# 2c. MTD vs mismo rango del mes anterior (día 1..N)
mtd0 = HOY.replace(day=1)
mtd = agg(mtd0, HOY)
prev_m = (pd.Timestamp(mtd0) - pd.offsets.MonthBegin(1)).date()
try:
    prev_fin = prev_m.replace(day=HOY.day)
except ValueError:                       # mes anterior más corto
    prev_fin = (pd.Timestamp(mtd0) - dt.timedelta(days=1)).date()
mtd_prev = agg(prev_m, min(prev_fin, mtd0 - dt.timedelta(days=1)))
reporte["mtd"] = {"rango": [str(mtd0), str(HOY)], "kpis": mtd,
                  "vs_mismo_rango_mes_anterior_pct": comparar(mtd, mtd_prev)}

# 2d. Semanas ISO: en curso, W-1, W-4 (comparable)
lun = HOY - dt.timedelta(days=HOY.weekday())
sem = {}
for nombre, off in [("semana_en_curso", 0), ("semana_anterior", 7), ("semana_comparable_w4", 28)]:
    a = lun - dt.timedelta(days=off)
    b = min(a + dt.timedelta(days=6), HOY)
    sem[nombre] = {"rango": [str(a), str(b)], "kpis": agg(a, b)}
sem["curso_vs_anterior_pct"] = comparar(sem["semana_en_curso"]["kpis"], sem["semana_anterior"]["kpis"])
sem["curso_vs_comparable_pct"] = comparar(sem["semana_en_curso"]["kpis"], sem["semana_comparable_w4"]["kpis"])
reporte["semanas"] = sem

# 2e. Ayer vs metas diarias
ayer = agg(HOY - dt.timedelta(days=1), HOY - dt.timedelta(days=1)) or {}
reporte["ayer"] = {"kpis": ayer, "metas": {
    "afiliaciones": f"{ayer.get('afiliaciones', 0)}/{METAS['afiliaciones_dia']}",
    "pedidos_financiados": f"{ayer.get('pedidos_financiados', 0)}/{METAS['pedidos_financiados_dia']}"}}

# ----------------------------------------------------------------------
# 3. Stock: recompra, tiers, líneas, inactivos, vendedores
#    (vistas existentes; si alguna cambia de schema, no rompe el reporte)
# ----------------------------------------------------------------------
def safe(vista):
    try:
        return fetch(vista)
    except Exception as e:
        return {"error": f"{vista}: {e}"}

reporte["recompra"] = safe("vw_recompra")
reporte["tiers"] = safe("vw_tiers_resumen")
reporte["pipeline_limbo"] = safe("vw_kpi_pipeline_v2")     # preventas sin numero (no-GMV)
reporte["data_quality"] = safe("vw_kpi_dq_v2")             # filas que rompen el cuadre

lineas = pd.DataFrame(safe("vw_kpi_lineas_v2"))
if not lineas.empty and "utilizacion" not in lineas.columns.tolist()[:1]:
    activas = lineas[lineas["linea_aprobada"] > 0]
    reporte["uso_linea"] = {
        "bodegas_con_linea": int(len(activas)),
        "linea_aprobada_total": float(activas["linea_aprobada"].sum()),
        "linea_disponible_total": float(activas["linea_disponible"].sum()),
        "utilizacion_promedio": round(float(activas["utilizacion"].dropna().mean() or 0), 4),
        "top10_utilizacion": activas.sort_values("utilizacion", ascending=False)
            .head(10)[["codigo_afiliado", "nombre_comercial", "utilizacion"]]
            .to_dict("records")}

# Inactivos: >15d sin compra + delta vs snapshot anterior
uc = pd.DataFrame(safe("vw_kpi_ultima_compra_v2"))
inactivos_hoy = []
if not uc.empty:
    uc["ultima_compra"] = pd.to_datetime(uc["ultima_compra"]).dt.date
    inactivos_hoy = uc[uc["ultima_compra"] < HOY - dt.timedelta(days=INACTIVO_DIAS)]["bodega_id"].tolist()
prev_snap = sb.table("kpi_snapshots_diario").select("payload") \
    .order("fecha", desc=True).limit(1).execute().data
prev_inactivos = set((prev_snap[0]["payload"].get("inactivos_ids") or []) if prev_snap else [])
reporte["inactivos"] = {
    "total": len(inactivos_hoy),
    "nuevos_desde_ultimo_snapshot": [i for i in inactivos_hoy if i not in prev_inactivos]}
reporte["inactivos_ids"] = inactivos_hoy

# Top vendedores enrolando (mes en curso) — usa vendedor de ENROLAMIENTO,
# nunca pedidos.vendedor_id (trae ADMIN CIRCA)
try:
    bc = pd.DataFrame(fetch("vw_bodega_comercial"))
    bo = pd.DataFrame(sb.table("bodegas").select("id,contrato_firmado_at,es_test")
                      .eq("es_test", False).execute().data)
    bo["f"] = pd.to_datetime(bo["contrato_firmado_at"], utc=True) - pd.Timedelta(hours=5)
    bo = bo[bo["f"].dt.date >= mtd0]
    col_v = next(c for c in bc.columns if "vendedor" in c and "id" not in c)
    top = bc.merge(bo, left_on="bodega_id", right_on="id") \
            .groupby(col_v).size().sort_values(ascending=False).head(10)
    reporte["top_vendedores_enrolando_mtd"] = top.to_dict()
except Exception as e:
    reporte["top_vendedores_enrolando_mtd"] = {"error": str(e)}

# ----------------------------------------------------------------------
# 4. Snapshot (upsert idempotente)
# ----------------------------------------------------------------------
sb.table("kpi_snapshots_diario").upsert(
    {"fecha": str(HOY), "payload": json.loads(json.dumps(reporte, default=str))}).execute()

# ----------------------------------------------------------------------
# 5. Análisis narrativo (Claude API si hay key; si no, reglas)
# ----------------------------------------------------------------------
analisis = ""
if os.environ.get("ANTHROPIC_API_KEY"):
    try:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model="claude-sonnet-4-6", max_tokens=1500,
            messages=[{"role": "user", "content":
                "Eres el analista de KPIs de Circa (infraestructura de comercio y "
                "crédito para bodegas en Perú, piloto en curso). Analiza este JSON "
                "de KPIs diarios. Sé directo, en español peruano. Estructura: "
                "1) lo más importante hoy (bueno o malo primero lo malo), "
                "2) tendencias vs períodos anteriores (ignora los NA, son esperados "
                "en un negocio nuevo), 3) alertas (metas incumplidas, inactivaciones "
                "nuevas, caída de recompra), 4) una acción concreta recomendada. "
                "Máximo 300 palabras.\n\n" + json.dumps(reporte, default=str)}])
        analisis = msg.content[0].text
    except Exception as e:
        analisis = f"(análisis API falló: {e})"
if not analisis:
    alertas = []
    if ayer.get("afiliaciones", 0) < METAS["afiliaciones_dia"]:
        alertas.append(f"Afiliaciones ayer {ayer.get('afiliaciones',0)} < meta {METAS['afiliaciones_dia']}")
    if ayer.get("pedidos_financiados", 0) < METAS["pedidos_financiados_dia"]:
        alertas.append(f"Financiados ayer {ayer.get('pedidos_financiados',0)} < meta {METAS['pedidos_financiados_dia']}")
    if reporte["inactivos"]["nuevos_desde_ultimo_snapshot"]:
        alertas.append(f"{len(reporte['inactivos']['nuevos_desde_ultimo_snapshot'])} bodegas cayeron a inactivas")
    dq = reporte.get("data_quality")
    if isinstance(dq, list) and dq:
        alertas.append(f"{len(dq)} pedidos con inconsistencia de montos (ver hoja DataQuality)")
    limbo = reporte.get("pipeline_limbo")
    if isinstance(limbo, list):
        viejos = [x for x in limbo if x.get("dias_en_limbo", 0) > 7]
        if viejos:
            alertas.append(f"{len(viejos)} preventas >7 dias en limbo (S/{sum(float(x['monto']) for x in viejos):.2f})")
    analisis = "ALERTAS:\n- " + "\n- ".join(alertas) if alertas else "Sin alertas contra metas."

# ----------------------------------------------------------------------
# 6. Salidas: Excel + Markdown
# ----------------------------------------------------------------------
out = os.environ.get("KPI_OUT_DIR", ".")
xlsx = f"{out}/circa_kpi_{HOY}.xlsx"
with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
    pd.DataFrame([reporte["desde_inicio"]]).to_excel(w, sheet_name="Desde_inicio", index=False)
    if meses:
        pd.json_normalize(meses).to_excel(w, sheet_name="Meses_cerrados", index=False)
    pd.json_normalize([reporte["mtd"]]).to_excel(w, sheet_name="MTD", index=False)
    pd.json_normalize([sem]).to_excel(w, sheet_name="Semanas", index=False)
    df.reset_index().to_excel(w, sheet_name="Diario", index=False)
    if isinstance(reporte.get("recompra"), list) and reporte["recompra"]:
        pd.DataFrame(reporte["recompra"]).to_excel(w, sheet_name="Recompra", index=False)
    if isinstance(reporte.get("tiers"), list) and reporte["tiers"]:
        pd.DataFrame(reporte["tiers"]).to_excel(w, sheet_name="Tiers", index=False)
    if isinstance(reporte.get("pipeline_limbo"), list) and reporte["pipeline_limbo"]:
        pd.DataFrame(reporte["pipeline_limbo"]).to_excel(w, sheet_name="Pipeline_limbo", index=False)
    if isinstance(reporte.get("data_quality"), list) and reporte["data_quality"]:
        pd.DataFrame(reporte["data_quality"]).to_excel(w, sheet_name="DataQuality", index=False)

md = f"{out}/circa_kpi_{HOY}.md"
with open(md, "w") as f:
    f.write(f"# Circa KPI — {HOY}\n\n## Análisis\n{analisis}\n\n"
            f"## Ayer vs metas\n{json.dumps(reporte['ayer'], indent=2, default=str)}\n\n"
            f"## Detalle\n```json\n{json.dumps(reporte, indent=2, default=str)}\n```\n")

# Subir a Supabase Storage (bucket privado 'reportes-kpi')
try:
    for path, ctype in [(xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                        (md, "text/markdown")]:
        with open(path, "rb") as fh:
            sb.storage.from_("reportes-kpi").upload(
                path.split("/")[-1], fh.read(),
                file_options={"content-type": ctype, "upsert": "true"})
    print("Reportes subidos a Storage/reportes-kpi")
except Exception as e:
    print(f"AVISO: upload a Storage fallo ({e}) — snapshot en BD igual quedo guardado")

print(f"OK — snapshot {HOY} guardado. Salidas: {xlsx}, {md}\n\n{analisis}")
