#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cargar_bodega.py  v2 - Carga de bodegas para el piloto Circa / DIMAX

QUE HACE
  Lee el/los Excel de historial de bodega(s) de DIMAX y, por cada una:
    - analiza el comportamiento de compra de los ultimos 6 meses
    - calcula la linea de credito con el modelo de riesgo (tier que cubre 7d)
    - en casos limite SIEMPRE asigna el tier conservador (no sube)
    - alerta si el ciclo de compra es largo o irregular (>10 dias o errático)
    - genera el SQL de creacion y el mensaje de WhatsApp de enrolamiento
    - marca solo lo que de verdad necesita criterio humano

DOS MODOS
  1) GENERAR (por defecto, no toca la base):
       python3 -m app.services.cargar_bodega carpeta/
     Crea salida_carga/reporte_bodegas.md y salida_carga/carga_bodegas.sql

  2) EJECUTAR (carga en la base, con confirmacion):
       python3 -m app.services.cargar_bodega carpeta/ --ejecutar
     Pide confirmacion antes de tocar la base. Las bodegas limpias se
     confirman en lote; las marcadas para revisar, una por una.
     Necesita la variable de entorno CIRCA_DB_URL (ver instrucciones abajo).

También disponible en backoffice: pestaña «Modelo líneas».
"""

from __future__ import annotations

import sys

from app.services.credit_model.credit_model_service import (
    correr_modo_ejecutar_cli,
    escribir_salida_cli,
    juntar_archivos,
    process_paths_cli,
)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    modo_ejecutar = "--ejecutar" in sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    archivos = juntar_archivos(args)
    if not archivos:
        print("No se encontraron archivos .xlsx en lo indicado.")
        sys.exit(1)

    procesadas, errores = process_paths_cli(archivos)
    escribir_salida_cli(procesadas)

    print("=" * 60)
    print("PROCESADAS: %d bodega(s)" % len(procesadas))
    print("=" * 60)
    for b in procesadas:
        marca = "  [REVISAR]" if b["avisos"]["revisar"] else ""
        print("  %-40s -> linea S/%d%s" % (
            str(b["cliente"].get("RazonSocial", ""))[:40],
            b["analisis"]["tier"],
            marca,
        ))
    if errores:
        print("\nAVISOS / OMITIDOS:")
        for nombre, msg in errores:
            print("  %s: %s" % (nombre, msg))
    print("\nSalida en  salida_carga/  (reporte_bodegas.md  y  carga_bodegas.sql)")

    if modo_ejecutar:
        if procesadas:
            correr_modo_ejecutar_cli(procesadas)
    else:
        print("\nPara cargar en la base con confirmacion:  agrega  --ejecutar")


if __name__ == "__main__":
    main()
