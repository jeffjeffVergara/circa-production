#!/usr/bin/env python3
"""
AJUSTE MANUAL DEL CORTE — pedidos que terminaron pagados en EFECTIVO.

Que hace
--------
Regenera el Excel y el TXT del corte de comisiones neutralizando los pedidos
que la bodega termino pagando al contado pero que quedaron con
`monto_financiado > 0` en la base. Sin financiamiento Circa no hay comision:
es la misma regla que ya aplica el flujo normal (ver CLAUDE.md, caso LEIVA
GRACIAN CRC-150, donde `monto_financiado` si se puso en 0).

NO modifica `circa_corte_comisiones.py` ni la base de datos. Solo intercepta
en memoria la lectura de `pedidos` y pone `monto_financiado = 0` en los
pedidos afectados, que es exactamente como se veria el pedido si el campo se
hubiera limpiado al anular el financiamiento.

Criterio de deteccion [Confirmado contra la base el 31-ago-2026]
----------------------------------------------------------------
    estado = 'pagado_cash'  OR  metodo_pago = 'efectivo'
    Y   monto_financiado > 0

Al 31-ago-2026 ese criterio captura UN solo pedido en todo DIMAX: CRC-184
(CASTELLANOS JUAN PEDRO). Los otros 4 pedidos en efectivo de la base ya
tienen `monto_financiado = 0` y por eso nunca generaron comision.

Los pedidos anulados/eliminados (`preventa_cancelada`, `rechazado`) ya los
excluye el script oficial; aqui no hace falta tocarlos.

Uso
---
    python3 ajuste_cash_corte.py --desde 2026-08-01 --hasta 2026-08-30

Salida (sufijo _ajustado, NO pisa los archivos oficiales):
    Corte_Comisiones_<desde>_<hasta>_ajustado.xlsx
    Mensajes_Corte_Comisiones_<desde>_<hasta>_ajustado.txt

El Excel ajustado lleva una hoja extra "Ajustes" con los pedidos neutralizados,
para que quede la trazabilidad de por que difiere del corte oficial.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import circa_corte_comisiones as C  # noqa: E402

REPO = os.path.dirname(os.path.abspath(__file__))

# Pedidos neutralizados en esta corrida (se llena en tiempo de ejecucion).
AJUSTADOS = []


# Estados que significan "la bodega YA recibio el producto".
# Verificado el 31-ago-2026: los 138 pedidos 'pagado' y los 42 'entregado'
# tienen fecha_entregado poblada al 100%. 'preventa_aceptada' no la tiene.
ESTADOS_ENTREGADOS = {"entregado", "pagado", "pagado_cash", "pago_reportado"}


def _motivo_ajuste(p):
    """Devuelve el motivo por el que el pedido NO debe generar comision, o None.

    1. Pago en EFECTIVO con financiado residual: sin financiamiento no hay
       comision (regla ya documentada, caso LEIVA GRACIAN CRC-150).
    2. NO ENTREGADO todavia: la activacion se paga recien al entregar
       [decision de Paola, 31-ago-2026]. Una preventa aceptada pero sin
       despachar no activa nada: la bodega aun no recibio producto.

    OJO: el criterio de entrega va por ESTADO, no por `fecha_entregado`.
    El select de `circa_corte_comisiones.fetch_todo` NO pide esa columna, asi
    que llega siempre vacia; usarla marcaria como "no entregado" a TODO el
    corte. (Error cometido y corregido el 31-ago-2026.)
    """
    estado = str(p.get("estado") or "").lower()
    metodo = str(p.get("metodo_pago") or "").lower()
    try:
        fin = float(p.get("monto_financiado") or 0)
    except (TypeError, ValueError):
        return None
    if fin <= 0:
        return None
    # Estados que el script oficial ya excluye: no hace falta ajustarlos ni
    # ensuciar el reporte con ellos.
    if any(f in estado for f in C.ESTADOS_EXCLUIDOS_FRAGMENTOS) or "borrador" in estado:
        return None
    if estado == "pagado_cash" or metodo == "efectivo":
        return "Pago en EFECTIVO, sin financiamiento Circa"
    if estado not in ESTADOS_ENTREGADOS:
        return f"NO ENTREGADO (estado '{estado}'): la activacion se paga al entregar"
    return None


def instalar_parche():
    """Envuelve fetch_todo para neutralizar los pedidos en efectivo."""
    original = C.fetch_todo

    def fetch_todo_parcheado(base_url, key, tabla, select, filtros=""):
        # Pedimos metodo_pago y fecha_entregado: el select oficial no los trae
        # y los necesitamos para decidir y para dejar trazabilidad.
        if tabla == "pedidos":
            for extra in ("metodo_pago", "fecha_entregado"):
                if extra not in select:
                    select = select + "," + extra
        filas = original(base_url, key, tabla, select, filtros)
        if tabla != "pedidos":
            return filas
        for p in filas:
            motivo = _motivo_ajuste(p)
            if motivo:
                AJUSTADOS.append({
                    "numero": p.get("numero") or "(sin numero)",
                    "bodega_id": p.get("bodega_id"),
                    "estado": p.get("estado"),
                    "metodo_pago": p.get("metodo_pago"),
                    "financiado_original": p.get("monto_financiado"),
                    "contado": p.get("monto_contado"),
                    "entregado": (p.get("fecha_entregado") or "")[:10] or "NO",
                    "motivo": motivo,
                })
                p["monto_financiado"] = 0
        return filas

    C.fetch_todo = fetch_todo_parcheado


def quitar_arrastre_ya_pagado(ruta_xlsx):
    """Elimina TODAS las lineas de (arrastre) del corte.

    REGLA DE NEGOCIO [Confirmada por Paola, 31-ago-2026]: lo que queda
    arrastrando (EN VUELO / EN ESPERA al cierre) se le paga al vendedor
    **los primeros dias del mes siguiente**, cuando las bodegas terminan de
    pagar. Ese pago ocurre FUERA del corte mensual. Por lo tanto el corte del
    mes NO debe volver a incluir esas comisiones: ya estan pagadas.

    Ojo con el agravante del 31-ago-2026: al corregir `parse_ts` cambiaron las
    fechas de pago legibles y, con ellas, la fecha en que cada bodega quedo al
    dia (`lib_bodega`). Eso hizo reaparecer como arrastre comisiones que el
    corte de julio ya habia liberado y pagado. Sin esta limpieza, agosto
    pagaba dos veces.

    Solo se tocan filas de arrastre en estado A PAGAR, que es lo unico que el
    Resumen contabiliza en su columna "A PAGAR S/". Los contadores de
    afiliaciones y recompras no se mueven: `reg_arrastre` nunca los alimenta.
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill

    wb = load_workbook(ruta_xlsx)
    ws = wb["Detalle"]
    quitar, devuelto = [], {}
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not r or not r[3]:
            continue
        if "(arrastre)" not in str(r[5]) or str(r[7]) != "A PAGAR":
            continue
        quitar.append((i, r, ("mes anterior", r[1], float(r[6] or 0))))
        devuelto[r[1]] = devuelto.get(r[1], 0.0) + float(r[6] or 0)

    for i, _, _ in sorted(quitar, reverse=True):
        ws.delete_rows(i)

    # Resumen: descontar de la columna "A PAGAR S/" y del TOTAL EQUIPO.
    wr = wb["Resumen"]
    col_ap = None
    for r in wr.iter_rows():
        vals = [str(c.value or "") for c in r]
        if "A PAGAR S/" in vals:
            col_ap = vals.index("A PAGAR S/") + 1
            break
    if col_ap:
        for r in wr.iter_rows(min_col=1, max_col=col_ap):
            cod = r[1].value
            if cod in devuelto:
                c = wr.cell(row=r[0].row, column=col_ap)
                c.value = round(float(c.value or 0) - devuelto[cod], 2)
            if str(r[0].value or "").startswith("TOTAL"):
                c = wr.cell(row=r[0].row, column=col_ap)
                c.value = round(float(c.value or 0) - sum(devuelto.values()), 2)

    hoja = wb.create_sheet("Arrastre ya pagado")
    hoja["A1"] = "LINEAS QUITADAS — arrastre de meses anteriores, ya pagado"
    hoja["A1"].font = Font(bold=True, size=12, color="C00000")
    hoja["A2"] = ("Lo que queda arrastrando se le paga al vendedor los primeros dias del mes "
                  "siguiente, cuando las bodegas terminan de pagar. Ese pago ocurre fuera del "
                  "corte, asi que estas lineas no se vuelven a pagar aqui.")
    cab = ["Pedido", "Bodega", "Vendedor", "Concepto", "S/ quitado", "Ya pagado en", "Cod."]
    for j, h in enumerate(cab, 1):
        c = hoja.cell(row=4, column=j, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
    for k, (_, r, (etq, vcod, mto)) in enumerate(sorted(quitar, key=lambda x: str(x[1][3])), start=5):
        for j, v in enumerate([r[3], r[2], r[1], r[5], float(r[6] or 0), etq, vcod], 1):
            hoja.cell(row=k, column=j, value=v)
    fin = 5 + len(quitar)
    hoja.cell(row=fin, column=4, value="TOTAL quitado:").font = Font(bold=True)
    t = hoja.cell(row=fin, column=5, value=f"=SUM(E5:E{fin - 1})")
    t.font = Font(bold=True, color="C00000")
    for col, w in zip("ABCDEFG", (12, 36, 13, 34, 12, 14, 20)):
        hoja.column_dimensions[col].width = w
    wb.save(ruta_xlsx)
    return quitar, devuelto


def agregar_hoja_ajustes(ruta_xlsx, nombres_bodega):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill

    wb = load_workbook(ruta_xlsx)
    ws = wb.create_sheet("Ajustes")
    ws["A1"] = "AJUSTE MANUAL — pedidos que no deben generar comision"
    ws["A1"].font = Font(bold=True, size=12, color="C00000")
    ws["A2"] = ("Dos motivos: (1) la bodega pago en EFECTIVO pero el pedido quedo con "
                "monto_financiado > 0 en la base; (2) el pedido AUN NO SE ENTREGA, y la "
                "activacion se paga recien al entregar. Se neutralizaron (financiado = 0).")
    ws["A3"] = "El script oficial NO tiene estas reglas. Mientras no se agreguen, este ajuste hay que rehacerlo cada corte."
    ws["A3"].font = Font(bold=True)

    cab = ["Pedido", "Bodega", "Estado", "Metodo pago", "Financiado en BD", "Contado", "Entregado", "Motivo del ajuste"]
    for j, h in enumerate(cab, 1):
        c = ws.cell(row=5, column=j, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")

    for i, a in enumerate(AJUSTADOS, start=6):
        fila = [a["numero"],
                nombres_bodega.get(a["bodega_id"], a["bodega_id"] or ""),
                a["estado"] or "",
                a["metodo_pago"] or "(null)",
                a["financiado_original"],
                a["contado"],
                a.get("entregado", "?"),
                a["motivo"]]
        for j, v in enumerate(fila, 1):
            ws.cell(row=i, column=j, value=v)

    for col, w in zip("ABCDEFGH", (14, 40, 20, 14, 18, 12, 12, 48)):
        ws.column_dimensions[col].width = w
    wb.save(ruta_xlsx)


def main():
    # Carga el .env del repo antes de cambiar de directorio.
    base_url = C.env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    key = C.env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")
    os.environ["CIRCA_SUPABASE_URL"] = base_url
    os.environ["CIRCA_SUPABASE_KEY"] = key

    instalar_parche()

    # main() del script oficial escribe en el cwd. Lo mandamos a un temporal
    # para no pisar los archivos del corte oficial.
    tmp = tempfile.mkdtemp(prefix="corte_ajustado_")
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        C.main()
    finally:
        os.chdir(cwd)

    # Nombres de bodega para la hoja de trazabilidad. Descartamos las bodegas
    # de prueba: el corte tampoco las considera.
    nombres, reales = {}, set()
    for b in C.fetch_todo(base_url, key, "bodegas", "id,nombre_comercial,razon_social,es_test"):
        nombres[b["id"]] = b.get("nombre_comercial") or b.get("razon_social") or b["id"][:8]
        if b.get("es_test") is not True:
            reales.add(b["id"])
    AJUSTADOS[:] = [a for a in AJUSTADOS if a["bodega_id"] in reales]

    movidos = []
    for f in sorted(os.listdir(tmp)):
        origen = os.path.join(tmp, f)
        raiz, ext = os.path.splitext(f)
        destino = os.path.join(REPO, f"{raiz}_ajustado{ext}")
        shutil.copy2(origen, destino)
        if ext == ".xlsx":
            if AJUSTADOS:
                agregar_hoja_ajustes(destino, nombres)
            quitados, devuelto = quitar_arrastre_ya_pagado(destino)
            if quitados:
                print(f"\nARRASTRE YA PAGADO — {len(quitados)} lineas quitadas "
                      f"(S/{sum(d for d in devuelto.values()):.0f}):")
                for cod, m in sorted(devuelto.items(), key=lambda x: -x[1]):
                    print(f"   · {cod}: -S/{m:.0f}")
        movidos.append(destino)
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    if AJUSTADOS:
        print(f"AJUSTADOS {len(AJUSTADOS)} pedido(s) (financiado -> 0):")
        for a in AJUSTADOS:
            print(f"   · {a['numero']:9} {nombres.get(a['bodega_id'], '')[:32]:34} "
                  f"{a['estado']:19} entregado={a.get('entregado','?'):10} → {a['motivo']}")
    else:
        print("Sin pedidos que ajustar.")
    print("\nArchivos generados:")
    for m in movidos:
        print("   " + os.path.basename(m))
    print("=" * 62)


if __name__ == "__main__":
    main()
