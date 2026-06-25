#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PARTE 2b - Agrega el boton "Subir preventa" al home del vendedor.
Lo inserta como PRIMER boton del menu (antes de "Hacer preventa").
ADITIVO: solo agrega 4 lineas dentro del f-string del home.
Valida ANTES de escribir; aborta si no calza; idempotente.
Correr:  python3 part2b_boton_subir_home.py
Revisar: git diff app/routes/vendedor.py
"""
import sys
import pathlib

ARCHIVO = pathlib.Path("/Users/paolavelarde/Projects/circa-deploy-temp/app/routes/vendedor.py")

ANCHOR = (
    '    <a href="/v/{token}/preventa" class="menu-btn">\n'
    '      Hacer preventa\n'
    '      <span class="desc">Arma un pedido para tu cliente</span>\n'
    '    </a>'
)

BOTON_SUBIR = (
    '    <a href="/v/{token}/preventa/subir" class="menu-btn">\n'
    '      Subir preventa\n'
    '      <span class="desc">Sube el Excel de DIMAX y confirma la bodega</span>\n'
    '    </a>'
)

YA_APLICADO = '<a href="/v/{token}/preventa/subir" class="menu-btn">'


def main():
    if not ARCHIVO.exists():
        print("NO EXISTE: %s" % ARCHIVO); sys.exit(1)
    txt = ARCHIVO.read_text(encoding="utf-8")

    if YA_APLICADO in txt:
        print("Ya estaba aplicado (el boton Subir preventa ya esta en el home). No toco nada.")
        sys.exit(0)

    n = txt.count(ANCHOR)
    if n != 1:
        print("ABORTADO. Esperaba 1 ocurrencia del bloque 'Hacer preventa', encontre %d." % n)
        print("No se escribio nada.")
        sys.exit(1)

    nuevo = BOTON_SUBIR + "\n" + ANCHOR
    txt = txt.replace(ANCHOR, nuevo, 1)
    ARCHIVO.write_text(txt, encoding="utf-8")
    print("PATCH OK. Boton 'Subir preventa' agregado como primer boton del home.")
    print("Revisa con:  git diff app/routes/vendedor.py")


if __name__ == "__main__":
    main()
