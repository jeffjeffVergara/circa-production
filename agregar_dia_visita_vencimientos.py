#!/usr/bin/env python3
"""
AGREGA LA COLUMNA "Dia visita" AL EXCEL DE VENCIMIENTOS  (solo lectura en la base)
=================================================================================

Pedido por Paola el 06-oct-2026: el Excel de vencidos tal como lo deja
`circa_cobranzas_diario.py`, con una columna mas.

NO regenera el archivo y NO toca `circa_cobranzas_diario.py`. Abre el .xlsx del
dia, inserta la columna justo despues de "Bodega" en las TRES hojas y guarda
una copia nueva con sufijo `_con_dia_visita`. El original queda intacto.

DE DONDE SALE EL DIA
--------------------
Del mapeo ACTIVO de la bodega en `bodega_vendedores`. Se cruza por NUMERO DE
PEDIDO (CRC-xxx): numero -> bodega_id -> mapeo. Verificado el 06-oct-2026 que
los numeros de pedido DIMAX son unicos, asi que el cruce es exacto.

NO se empareja por nombre de bodega: el CLAUDE.md lo prohibe porque los nombres
difieren entre tablas ("PECEROS ANDIA, GRACIELA" en `bodegas` vs "PECEROS ANDIA
RICARDO ELEUTERIO" en `historico_zoom` son bodegas DISTINTAS).

Se excluyen las bodegas `es_test`: el 06-oct entraron 91 mapeos de prueba
(VWTEST-*) y son los unicos con mas de un mapeo activo por bodega.

OJO AL LEERLO
-------------
La visita ocurre un dia ANTES del despacho, y los 7 dias de plazo corren desde
la ENTREGA, no desde la visita. El dia de esta columna sirve para saber cuando
el vendedor pasa por la bodega a cobrar, no para calcular el vencimiento.

Uso:
    python3 agregar_dia_visita_vencimientos.py [YYYY-MM-DD]
"""
import copy
import importlib.util
import os
import sys
from datetime import date

RUTA = os.path.dirname(os.path.abspath(__file__))
COL_NUEVA = "Dia visita"


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


def mapa_dia_visita(base, key):
    """numero de pedido -> dia_visita de su bodega."""
    test = {b["id"] for b in C.fetch_todo(base, key, "bodegas", "id,es_test")
            if b.get("es_test") is True}

    ruta, choque = {}, set()
    for m in C.fetch_todo(base, key, "bodega_vendedores",
                          "bodega_id,dia_visita,activo", "activo=eq.true"):
        bid = m["bodega_id"]
        if bid in test:
            continue
        dv = m.get("dia_visita")
        if bid in ruta and ruta[bid] != dv:
            choque.add(bid)          # ambiguo: no se elige solo
            continue
        ruta[bid] = dv

    por_numero = {}
    for p in C.fetch_todo(base, key, "pedidos", "numero,bodega_id",
                          f"distribuidor_id=eq.{C.DIMAX_DISTRIBUIDOR_ID}"):
        if p.get("numero"):
            por_numero[p["numero"]] = ruta.get(p["bodega_id"])
    return por_numero, choque


def fila_cabecera(ws):
    """Devuelve (fila, {titulo: columna}) de la cabecera de la hoja."""
    for f in range(1, min(12, ws.max_row) + 1):
        titulos = {str(c.value).strip(): c.column
                   for c in ws[f] if c.value is not None}
        if "Pedido" in titulos and "Bodega" in titulos:
            return f, titulos
    return None, {}


def procesar(ws, dia_por_numero):
    cab, titulos = fila_cabecera(ws)
    if cab is None:
        return 0, 0, []
    if COL_NUEVA in titulos:
        return 0, 0, []

    col_ped, col_bod = titulos["Pedido"], titulos["Bodega"]
    destino = col_bod + 1
    ws.insert_cols(destino)

    # La cabecera hereda el estilo de la columna "Bodega" (misma franja azul).
    modelo = ws.cell(row=cab, column=col_bod)
    nueva = ws.cell(row=cab, column=destino, value=COL_NUEVA)
    nueva._style = copy.copy(modelo._style)

    # Si "Pedido" estaba despues de "Bodega", su indice se corrio una posicion.
    if col_ped >= destino:
        col_ped += 1

    puestos = sin_dia = 0
    faltan = []
    for f in range(cab + 1, ws.max_row + 1):
        numero = ws.cell(row=f, column=col_ped).value
        # Solo filas de pedido de verdad. La hoja "Vencimientos" trae debajo un
        # bloque "RESUMEN POR SUPERVISOR" cuyas columnas caen justo donde van
        # Pedido y Bodega: sin este filtro se le pegaria un dia de visita a
        # "Vencidos / 9 / 3 / 1", que no son pedidos.
        if not isinstance(numero, str) or not numero.strip().startswith("CRC-"):
            continue
        bodega = ws.cell(row=f, column=col_bod).value
        dv = dia_por_numero.get(str(numero).strip())
        celda = ws.cell(row=f, column=destino, value=dv or "— sin dia —")
        celda._style = copy.copy(ws.cell(row=f, column=col_bod)._style)
        celda.number_format = "General"
        if dv:
            puestos += 1
        else:
            sin_dia += 1
            faltan.append((str(numero), str(bodega)))

    ws.column_dimensions[ws.cell(row=cab, column=destino).column_letter].width = 13
    return puestos, sin_dia, faltan


def main():
    dia = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    origen = os.path.join(RUTA, f"CIRCA_Vencimientos_{dia}.xlsx")
    if not os.path.exists(origen):
        sys.exit(f"ERROR: no existe {os.path.basename(origen)}. "
                 f"Corre primero circa_cobranzas_diario.py.")
    salida = origen.replace(".xlsx", "_con_dia_visita.xlsx")

    base = C.env_o_falla("CIRCA_SUPABASE_URL", "SUPABASE_URL").rstrip("/")
    key = C.env_o_falla("CIRCA_SUPABASE_KEY", "SUPABASE_KEY")

    print(f"Agregando '{COL_NUEVA}' a {os.path.basename(origen)}  (el original no se toca)\n")
    dia_por_numero, choque = mapa_dia_visita(base, key)
    print(f"  Pedidos DIMAX con numero: {len(dia_por_numero)}")
    if choque:
        print(f"  ⚠️  {len(choque)} bodega(s) real(es) con mapeo activo ambiguo")

    from openpyxl import load_workbook
    wb = load_workbook(origen)
    total_sin, faltan_todo = 0, []
    for nombre in wb.sheetnames:
        puestos, sin_dia, faltan = procesar(wb[nombre], dia_por_numero)
        total_sin += sin_dia
        faltan_todo += [(nombre,) + f for f in faltan]
        marca = "" if sin_dia == 0 else f"  ⚠️ {sin_dia} sin dia"
        print(f"  · {nombre}: {puestos} fila(s) con dia de visita{marca}")
    wb.save(salida)

    print(f"\nLISTO: {os.path.basename(salida)}")
    if faltan_todo:
        print("\n⚠️  Filas sin dia de visita (revisar el mapeo de esas bodegas):")
        for hoja, numero, bodega in faltan_todo:
            print(f"   · [{hoja}] {numero} · {bodega}")
    else:
        print("  Todas las filas quedaron con su dia de visita.")


if __name__ == "__main__":
    main()
