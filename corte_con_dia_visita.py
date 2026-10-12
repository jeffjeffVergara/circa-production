#!/usr/bin/env python3
"""
CUADRO DE COMISIONES CON DIA DE VISITA  (solo lectura)
======================================================

Pedido por Paola el 06-oct-2026. NO recalcula nada: importa `calcular()` de
`circa_corte_v2.py` tal cual, para que las cifras sean byte a byte las del
corte oficial, y le pega al DETALLE el `dia_visita` / `dia_entrega` / `grupo`
de cada bodega.

POR QUE SE CRUZA APARTE Y NO SE TOCA EL SCRIPT OFICIAL
------------------------------------------------------
`dia_visita` NO esta en el `select` de `bodega_vendedores` que usa v2 (solo
trae bodega_id, vendedor_id, activo, rol). El CLAUDE.md documenta esa trampa
como pisada tres veces: una columna fuera del select llega vacia y la regla
que la use falla EN SILENCIO (da cero, no da error). Asi que no se agrega la
columna al select de v2 — se trae en una consulta propia y se une despues.

LLAVE DEL CRUCE: el numero de pedido (CRC-xxx)
----------------------------------------------
Verificado el 06-oct-2026 sobre los 460 pedidos DIMAX: los numeros son unicos
(404 numeros distintos, 0 duplicados; los otros 56 pedidos tienen numero NULL
y nunca llegan al detalle del corte). Se cruza numero -> bodega_id -> mapeo.
NO se empareja por nombre de bodega: el CLAUDE.md lo prohibe explicitamente
porque los nombres difieren entre tablas ("PECEROS ANDIA, GRACIELA" vs
"PECEROS ANDIA RICARDO ELEUTERIO" son bodegas distintas).

Uso:
    python3 corte_con_dia_visita.py
"""
import importlib.util
import os
import sys
from collections import defaultdict
from datetime import date

RUTA = os.path.dirname(os.path.abspath(__file__))


def _mod(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, os.path.join(RUTA, archivo))
    m = importlib.util.module_from_spec(spec)
    guardado, sys.argv = sys.argv, [archivo]
    try:
        spec.loader.exec_module(m)
    finally:
        sys.argv = guardado
    return m


C = _mod("C", "circa_corte_comisiones.py")
V2 = _mod("V2", "circa_corte_v2.py")

PERIODOS = [
    ("Setiembre", date(2026, 9, 1), date(2026, 9, 30)),
    ("Octubre", date(2026, 10, 1), date(2026, 10, 6)),
]

AZUL, GRIS = V2.AZUL, V2.GRIS
VERDE, AMARILLO, ROJO = V2.VERDE, V2.AMARILLO, V2.ROJO


# ---------------------------------------------------------------- ruta
def mapa_ruta(base, key):
    """bodega_id -> (dia_visita, dia_entrega, grupo) de su mapeo ACTIVO.

    Se excluyen las bodegas es_test: el corte v2 ya las descarta, y el 06-oct
    entraron 91 mapeos de prueba (VWTEST-*) que son los unicos que tienen mas
    de un mapeo activo por bodega. Entre bodegas reales el mapeo activo es
    unico, verificado ese mismo dia.
    """
    test = {b["id"] for b in C.fetch_todo(base, key, "bodegas", "id,es_test")
            if b.get("es_test") is True}
    out, choque = {}, []
    for m in C.fetch_todo(base, key, "bodega_vendedores",
                          "bodega_id,dia_visita,dia_entrega,grupo,activo",
                          "activo=eq.true"):
        bid = m["bodega_id"]
        if bid in test:
            continue
        fila = (m.get("dia_visita"), m.get("dia_entrega"), m.get("grupo"))
        if bid in out and out[bid] != fila:
            choque.append(bid)          # no se elige solo: se reporta
            continue
        out[bid] = fila
    return out, choque


def mapa_pedidos(base, key):
    """numero de pedido -> bodega_id (llave exacta del cruce)."""
    return {p["numero"]: p["bodega_id"]
            for p in C.fetch_todo(base, key, "pedidos", "numero,bodega_id",
                                  f"distribuidor_id=eq.{C.DIMAX_DISTRIBUIDOR_ID}")
            if p.get("numero")}


# ---------------------------------------------------------------- excel
def escribir(resultados, ruta_salida, ruta_bod, ped2bod, choques):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color="D0D7E5")
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    AR = lambda **k: Font(name="Arial", **k)  # noqa: E731

    def cabecera(ws, cab, fila):
        for j, h in enumerate(cab, 1):
            c = ws.cell(row=fila, column=j, value=h)
            c.font = AR(bold=True, color="FFFFFF", size=10)
            c.fill = PatternFill("solid", fgColor=AZUL)
            c.alignment = Alignment(horizontal="center", wrap_text=True,
                                    vertical="center")
            c.border = borde

    wb = Workbook()
    wb.remove(wb.active)

    # ---- una hoja de resumen por periodo -----------------------------
    for etiqueta, r in resultados:
        vend, paga, cnt = r["vend"], r["paga"], r["cnt"]
        ws = wb.create_sheet(f"Resumen {etiqueta}")
        ws["A1"] = (f"COMISIONES {etiqueta.upper()}  ·  "
                    f"{r['desde'].strftime('%d/%m/%Y')} a "
                    f"{r['hasta'].strftime('%d/%m/%Y')}")
        ws["A1"].font = AR(bold=True, size=14, color=AZUL)
        ws["A2"] = (f"ENROLADOS S/{V2.TARIFA_ENROLADO:.0f} c/u  ·  "
                    f"FINANCIADOS S/{V2.TARIFA_FINANCIADO:.0f} c/u  ·  "
                    f"bono top S/{V2.BONO_TOP:.0f} ya sumado dentro de PAGADO")
        ws["A2"].font = AR(size=10)
        ws["A3"] = ("PAGADO = la bodega ya pago, se deposita ahora  ·  VENCIDO = se le "
                    "paso el plazo y no pago, hay que cobrar  ·  EN VUELO = aun dentro "
                    "de su plazo. VENCIDO y EN VUELO se pagan igual apenas la bodega pague.")
        ws["A3"].font = AR(size=10, italic=True)

        cab = ["Vendedor", "Cod.", "Enrolados", "Financiados (recompras)",
               "PAGADO S/", "VENCIDO S/", "EN VUELO S/", "⭐"]
        fila = 5
        cabecera(ws, cab, fila)
        fila += 1

        activos = [v for v in paga
                   if (paga[v]["A PAGAR"] or paga[v]["EN VUELO"] or paga[v]["VENCIDO"])]
        por_sup = defaultdict(list)
        for v in activos:
            por_sup[vend[v].get("supervisor") or "SIN SUPERVISOR"].append(v)

        ini = fila + 1
        for sup in sorted(por_sup):
            c = ws.cell(row=fila, column=1, value=f"  Supervisor: {sup}")
            c.font = AR(bold=True, size=10)
            c.fill = PatternFill("solid", fgColor=GRIS)
            fila += 1
            for vid in sorted(por_sup[sup], key=lambda v: -paga[v]["A PAGAR"]):
                v, c_ = vend[vid], cnt[vid]
                vals = [v.get("nombre") or "", v["codigo"], c_["enrolados"],
                        c_["financiados"], paga[vid]["A PAGAR"],
                        paga[vid]["VENCIDO"], paga[vid]["EN VUELO"],
                        "⭐" if vid == r["top_vid"] else ""]
                for j, val in enumerate(vals, 1):
                    cc = ws.cell(row=fila, column=j, value=val)
                    cc.font = AR(size=10)
                    cc.border = borde
                    if j in (5, 6, 7):
                        cc.number_format = '#,##0.00'
                        if val:
                            cc.fill = PatternFill(
                                "solid", fgColor={5: VERDE, 6: ROJO, 7: AMARILLO}[j])
                fila += 1
        fin = fila - 1

        fila += 1
        ws.cell(row=fila, column=1, value="TOTAL EQUIPO").font = AR(bold=True, size=11)
        for j in (3, 4, 5, 6, 7):
            col = get_column_letter(j)
            c = ws.cell(row=fila, column=j, value=f"=SUM({col}{ini}:{col}{fin})")
            c.font = AR(bold=True, size=11)
            c.border = borde
            if j >= 5:
                c.number_format = '#,##0.00'
        if r["aviso_top"]:
            mx, cods = r["aviso_top"]
            fila += 2
            ws.cell(row=fila, column=1,
                    value=(f"⚠️ EMPATE en el top: {', '.join(cods)} con {mx} "
                           f"enrolados. El bono de S/{V2.BONO_TOP:.0f} NO se asigno "
                           f"— se decide a mano.")).font = AR(bold=True, size=10,
                                                              color="C00000")
        for col, w in zip("ABCDEFGH", (32, 9, 11, 20, 13, 13, 13, 5)):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "A6"

    # ---- detalle unico, con dia de visita ----------------------------
    ws = wb.create_sheet("Detalle con dia visita")
    ws["A1"] = "DETALLE DE COMISIONES CON DIA DE VISITA DE LA BODEGA"
    ws["A1"].font = AR(bold=True, size=14, color=AZUL)
    ws["A2"] = ("Una fila por comision. 'Dia visita' sale del mapeo ACTIVO de la bodega "
                "en bodega_vendedores, cruzado por numero de pedido. Ojo: la visita "
                "ocurre un dia ANTES del despacho, y los 7 dias de plazo corren desde "
                "la ENTREGA, no desde la visita.")
    ws["A2"].font = AR(size=10, italic=True)

    cab = ["Periodo", "Supervisor", "Cod.", "Vendedor", "Bodega", "Pedido",
           "Fecha pedido", "Concepto", "S/", "Estado", "Dia visita",
           "Dia entrega", "Grupo"]
    cabecera(ws, cab, 4)
    fila = 5
    sin_ruta = []
    for etiqueta, r in resultados:
        cod2nom = {v["codigo"]: (v.get("nombre") or "") for v in r["vend"].values()}
        for sup, cod, bodega, numero, f, concepto, tarifa, estado in r["detalle"]:
            bid = ped2bod.get(numero)
            dv, de, gr = ruta_bod.get(bid, (None, None, None))
            if not dv:
                sin_ruta.append((etiqueta, cod, bodega, numero))
            vals = [etiqueta, sup, cod, cod2nom.get(cod, ""), bodega, numero,
                    f, concepto, tarifa, estado, dv or "— sin dia —",
                    de or "—", gr or "—"]
            for j, val in enumerate(vals, 1):
                cc = ws.cell(row=fila, column=j, value=val)
                cc.font = AR(size=10)
                cc.border = borde
                if j == 7:
                    cc.number_format = 'dd/mm/yyyy'
                if j == 9:
                    cc.number_format = '#,##0.00'
                if j == 10:
                    cc.fill = PatternFill("solid", fgColor={
                        "A PAGAR": VERDE, "VENCIDO": ROJO,
                        "EN VUELO": AMARILLO}.get(val, "FFFFFF"))
                if j == 11 and not dv:
                    cc.fill = PatternFill("solid", fgColor=ROJO)
            fila += 1
    for col, w in zip("ABCDEFGHIJKLM",
                      (11, 30, 8, 28, 38, 10, 13, 24, 8, 11, 12, 12, 15)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:M{fila - 1}"

    # ---- alertas ------------------------------------------------------
    ws = wb.create_sheet("Alertas")
    ws["A1"] = "ALERTAS DEL CRUCE"
    ws["A1"].font = AR(bold=True, size=14, color=AZUL)
    fila = 3
    ws.cell(row=fila, column=1,
            value="Lineas de comision cuya bodega NO tiene dia de visita").font = AR(bold=True)
    fila += 1
    cabecera(ws, ["Periodo", "Cod.", "Bodega", "Pedido"], fila)
    fila += 1
    for t in sin_ruta or [("—", "—", "ninguna: todas las bodegas con comision tienen dia de visita", "—")]:
        for j, val in enumerate(t, 1):
            ws.cell(row=fila, column=j, value=val).font = AR(size=10)
        fila += 1

    fila += 2
    ws.cell(row=fila, column=1,
            value="Alertas del corte oficial (hoja Alertas de v2)").font = AR(bold=True)
    fila += 1
    cabecera(ws, ["Periodo", "Pedido", "Bodega", "Fecha", "Motivo"], fila)
    fila += 1
    hay = False
    for etiqueta, r in resultados:
        for a in sorted(set(r["alertas"])):
            hay = True
            for j, val in enumerate((etiqueta,) + tuple(a), 1):
                ws.cell(row=fila, column=j, value=val).font = AR(size=10)
            fila += 1
    if not hay:
        ws.cell(row=fila, column=1, value="ninguna").font = AR(size=10)
        fila += 1

    if choques:
        fila += 2
        ws.cell(row=fila, column=1,
                value=(f"⚠️ {len(choques)} bodega(s) real(es) con mas de un mapeo activo "
                       f"y ruta distinta — NO se eligio ninguna, revisar a mano")
                ).font = AR(bold=True, color="C00000")
    for col, w in zip("ABCDE", (12, 10, 40, 13, 30)):
        ws.column_dimensions[col].width = w

    wb.save(ruta_salida)
    return sin_ruta


# ---------------------------------------------------------------- main
def main():
    base = C.env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    key = C.env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")

    print("Cuadro de comisiones con dia de visita  (solo lectura)\n")
    ruta_bod, choques = mapa_ruta(base, key)
    ped2bod = mapa_pedidos(base, key)
    print(f"  Bodegas reales con ruta mapeada: {len(ruta_bod)}")
    print(f"  Pedidos DIMAX con numero: {len(ped2bod)}")
    if choques:
        print(f"  ⚠️  {len(choques)} bodega(s) real(es) con mapeo activo ambiguo")

    resultados = []
    for etiqueta, desde, hasta in PERIODOS:
        print(f"\n— {etiqueta}  {desde} a {hasta}")
        r = V2.calcular(base, key, desde, hasta, verbose=False)
        resultados.append((etiqueta, r))
        tm = sum(d["A PAGAR"] for d in r["paga"].values())
        tv = sum(d["EN VUELO"] for d in r["paga"].values())
        tx = sum(d["VENCIDO"] for d in r["paga"].values())
        print(f"    A PAGAR S/{tm:.2f} · EN VUELO S/{tv:.2f} · VENCIDO S/{tx:.2f}"
              f" · {len(r['detalle'])} lineas")

    salida = os.path.join(RUTA, "CIRCA_Comisiones_con_dia_visita_2026-10-06.xlsx")
    sin_ruta = escribir(resultados, salida, ruta_bod, ped2bod, choques)
    print(f"\nLISTO: {os.path.basename(salida)}")
    print(f"  Lineas sin dia de visita: {len(sin_ruta)}")


if __name__ == "__main__":
    main()
