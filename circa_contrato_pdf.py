"""
Circa - Generador del PDF del Contrato de Facilidad de Financiamiento Comercial.
Version 3.0 (20/05/2026). Replica fiel del PDF de referencia.

Uso:
    from circa_contrato_pdf import generar_contrato_pdf
    generar_contrato_pdf(datos, "salida.pdf")

`datos` es un dict con:
    razon_social, ruc, representante_legal, dni, domicilio_fiscal,
    direccion_entrega, email, nombre_firmante, dni_firmante, telefono,
    fecha_aceptacion (dd/mm/aaaa), hora_aceptacion (HH:MM:SS), hash_verificacion
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, Image, HRFlowable, KeepTogether,
)

VERSION_CONTRATO = "3.0"
FECHA_EMISION = "20/05/2026"

AZUL = colors.Color(74 / 255, 144 / 255, 217 / 255)
GRIS_TXT = colors.Color(0.35, 0.35, 0.35)
GRIS_FONDO = colors.Color(0.965, 0.965, 0.965)
GRIS_LINEA = colors.Color(0.85, 0.85, 0.85)

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "circa_logo_contrato.png")

# ---------------------------------------------------------------- estilos
S_TITULO = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=15.5,
                          leading=19, alignment=TA_CENTER, spaceAfter=5)
S_SUBTITULO = ParagraphStyle("subtitulo", fontName="Helvetica", fontSize=10,
                             leading=13, alignment=TA_CENTER, textColor=GRIS_TXT)
S_VERSION = ParagraphStyle("version", fontName="Helvetica", fontSize=8,
                           leading=11, alignment=TA_CENTER, textColor=GRIS_TXT)
S_CLAUSULA = ParagraphStyle("clausula", fontName="Helvetica-Bold", fontSize=10.5,
                            leading=13, spaceBefore=10, spaceAfter=5)
S_CUERPO = ParagraphStyle("cuerpo", fontName="Helvetica", fontSize=9,
                          leading=12.5, alignment=TA_JUSTIFY, spaceAfter=6)
S_CELDA_LBL = ParagraphStyle("celdalbl", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
S_CELDA_VAL = ParagraphStyle("celdaval", fontName="Helvetica", fontSize=8.5,
                             leading=11, textColor=AZUL)
S_TH = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8.5, leading=11)
S_TD = ParagraphStyle("td", fontName="Helvetica", fontSize=8.5, leading=11)
S_PIE = ParagraphStyle("pie", fontName="Helvetica", fontSize=7,
                       leading=9.5, alignment=TA_CENTER, textColor=GRIS_TXT)


def _p(txt, estilo):
    return Paragraph(txt, estilo)


def _pie_de_pagina(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GRIS_TXT)
    canvas.drawCentredString(
        A4[0] / 2, 14 * mm,
        "PALI S.A.C. | RUC 20600627806 | Circa \u2014 Plataforma de cr\u00e9dito embebido")
    canvas.drawCentredString(
        A4[0] / 2, 10 * mm,
        "Cal. Teniente Romanet 120 Dpto 401, San Isidro, Lima | contacto@circa.pe")
    canvas.restoreState()


def _tabla_partes(d):
    filas = [
        ("Nombre / Raz\u00f3n Social:", d.get("razon_social")),
        ("RUC:", d.get("ruc")),
        ("Representante legal:", d.get("representante_legal")),
        ("DNI:", d.get("dni")),
        ("Domicilio fiscal:", d.get("domicilio_fiscal")),
        ("Direcci\u00f3n de entrega:", d.get("direccion_entrega")),
        ("Correo electr\u00f3nico:", d.get("email")),
    ]
    data = [[_p(lbl, S_CELDA_LBL), _p(str(val or "\u2014"), S_CELDA_VAL)] for lbl, val in filas]
    t = Table(data, colWidths=[47 * mm, 98 * mm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRIS_FONDO),
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS_LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    return t


def _tabla_planes():
    data = [
        [_p("Plan de pago", S_TH), _p("Comisi\u00f3n", S_TH), _p("M\u00ednimo", S_TH)],
        [_p("7 d\u00edas", S_TD), _p("1.4% del monto financiado (S/1.40 por cada S/100)", S_TD), _p("S/ 1.00", S_TD)],
        [_p("15 d\u00edas", S_TD), _p("3% del monto financiado (S/3.00 por cada S/100)", S_TD), _p("S/ 1.00", S_TD)],
        [_p("30 d\u00edas", S_TD), _p("6% del monto financiado (S/6.00 por cada S/100)", S_TD), _p("S/ 1.00", S_TD)],
    ]
    t = Table(data, colWidths=[30 * mm, 100 * mm, 25 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GRIS_FONDO),
        ("GRID", (0, 0), (-1, -1), 0.4, GRIS_LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _bloque_firma(d):
    izq = [
        _p("<b>Firma digital del Bodeguero:</b>", S_TD),
        Spacer(1, 4),
        _p("[OK] Aceptado v\u00eda WhatsApp", S_TD),
        Spacer(1, 4),
        _p("<b>Nombre:</b> %s" % (d.get("nombre_firmante") or "\u2014"), S_TD),
        Spacer(1, 4),
        _p("<b>DNI:</b> %s" % (d.get("dni_firmante") or "\u2014"), S_TD),
    ]
    der = [
        _p("<b>Fecha:</b>", S_TD),
        Spacer(1, 4),
        _p(d.get("fecha_aceptacion") or "\u2014", S_TD),
        Spacer(1, 4),
        _p("<b>Hora:</b> %s" % (d.get("hora_aceptacion") or "\u2014"), S_TD),
        Spacer(1, 4),
        _p("<b>Tel:</b> %s" % (d.get("telefono") or "\u2014"), S_TD),
    ]
    t = Table([[izq, der]], colWidths=[95 * mm, 50 * mm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRIS_FONDO),
        ("BOX", (0, 0), (-1, -1), 0.4, GRIS_LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def generar_contrato_pdf(d, salida):
    doc = BaseDocTemplate(
        salida, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=22 * mm,
        title="Contrato de Facilidad de Financiamiento Comercial - Circa",
        author="PALI S.A.C.",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="std", frames=[frame], onPage=_pie_de_pagina)])

    f = []

    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=52 * mm, height=34.7 * mm)
        logo.hAlign = "CENTER"
        f += [Spacer(1, 14), logo, Spacer(1, 10)]
    else:
        f += [Spacer(1, 30)]

    f.append(_p("CONTRATO DE FACILIDAD DE FINANCIAMIENTO COMERCIAL", S_TITULO))
    f.append(_p("Plataforma Circa \u2014 Cr\u00e9dito embebido para bodegas", S_SUBTITULO))
    f.append(Spacer(1, 10))
    f.append(HRFlowable(width="100%", thickness=1.6, color=AZUL, spaceAfter=8))
    f.append(_p("Versi\u00f3n %s | Fecha de emisi\u00f3n: %s" % (VERSION_CONTRATO, FECHA_EMISION), S_VERSION))
    f.append(Spacer(1, 8))

    # ------------------------------------------------------ CLAUSULA 1
    f.append(_p("CL\u00c1USULA 1: PARTES", S_CLAUSULA))
    f.append(_p(
        "<b>CIRCA:</b> CIRCA opera como plataforma tecnol\u00f3gica de facilitaci\u00f3n de financiamiento y gesti\u00f3n "
        "de pagos. CIRCA es un nombre comercial de PALI S.A.C., con RUC N.\u00b0 20600627806.", S_CUERPO))
    f.append(_p(
        "<b>EL BODEGUERO:</b> Es la persona natural o jur\u00eddica titular del negocio que acepta estos t\u00e9rminos "
        "mediante la plataforma de WhatsApp de CIRCA.", S_CUERPO))
    f.append(Spacer(1, 2))
    f.append(_tabla_partes(d))

    # ------------------------------------------------------ CLAUSULA 2
    f.append(_p("CL\u00c1USULA 2: OBJETO", S_CLAUSULA))
    f.append(_p(
        "CIRCA es una plataforma tecnol\u00f3gica que facilita financiamiento comercial, directamente o a trav\u00e9s de "
        "entidades financieras, vinculado a la compra de bienes a la red de distribuidores autorizados por CIRCA. "
        "No capta dinero del p\u00fablico ni es entidad financiera.", S_CUERPO))
    f.append(_p(
        "CIRCA pone a disposici\u00f3n del BODEGUERO una facilidad de financiamiento comercial para la adquisici\u00f3n de "
        "productos a trav\u00e9s de la red de distribuidores autorizados por CIRCA. El monto financiado se acredita "
        "directamente al distribuidor autorizado por CIRCA y permite al BODEGUERO pagar de forma diferida los "
        "pedidos para la adquisici\u00f3n de dichos productos hasta el l\u00edmite de financiamiento.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 3
    f.append(_p("CL\u00c1USULA 3: L\u00cdMITE DE FINANCIAMIENTO", S_CLAUSULA))
    f.append(_p(
        "CIRCA asignar\u00e1 un l\u00edmite de financiamiento basado en evaluaci\u00f3n interna, el cual ser\u00e1 comunicado al "
        "Bodeguero. El l\u00edmite es reutilizable una vez canceladas las obligaciones pendientes. El financiamiento "
        "podr\u00e1 cubrir total o parcialmente el pedido.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 4
    f.append(_p("CL\u00c1USULA 4: PLAZOS Y CARGOS", S_CLAUSULA))
    f.append(_p("Plazos y cargos aplicables:", S_CUERPO))
    f.append(_tabla_planes())
    f.append(Spacer(1, 8))
    f.append(_p(
        "La comisi\u00f3n se fija al confirmar el pedido seg\u00fan el plan elegido (7, 15 o 30 d\u00edas). El pago dentro del "
        "plazo acordado no modifica el monto total de la operaci\u00f3n.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 5
    f.append(_p("CL\u00c1USULA 5: FORMA DE PAGO", S_CLAUSULA))
    f.append(_p(
        "El pago se realiza a CIRCA v\u00eda Yape o Plin al n\u00famero designado por CIRCA. El Bodeguero debe confirmar "
        "el pago por WhatsApp. CIRCA podr\u00e1 validar el pago hasta en 2 d\u00edas h\u00e1biles.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 6
    f.append(_p("CL\u00c1USULA 6: INCUMPLIMIENTO Y MORA", S_CLAUSULA))
    f.append(_p(
        "El BODEGUERO se compromete a realizar el pago dentro del plazo del plan elegido al confirmar el pedido.", S_CUERPO))
    f.append(_p(
        "Si el pago no se realiza dentro de ese plazo, el saldo adeudado (capital financiado m\u00e1s comisi\u00f3n acordada) "
        "ingresar\u00e1 en mora con un cargo diario de 0.03% sobre el monto total adeudado. La mora ser\u00e1 autom\u00e1tica sin "
        "necesidad de interpelaci\u00f3n ni aviso al BODEGUERO.", S_CUERPO))
    f.append(_p(
        "Desde el primer d\u00eda de atraso del pago acordado, CIRCA podr\u00e1 suspender el acceso a nuevas compras a "
        "cr\u00e9dito hasta que el BODEGUERO regularice su situaci\u00f3n.", S_CUERPO))
    f.append(_p(
        "CIRCA podr\u00e1 enviar recordatorios de pago por WhatsApp y notificar al distribuidor asociado sobre el estado "
        "de mora del BODEGUERO. Esta informaci\u00f3n podr\u00e1 ser considerada por el distribuidor para futuras decisiones "
        "comerciales.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 7
    f.append(_p("CL\u00c1USULA 7: SEGURIDAD", S_CLAUSULA))
    f.append(_p(
        "El Bodeguero crear\u00e1 un PIN personal (c\u00f3digo de 4 d\u00edgitos) para acceder a la plataforma de CIRCA. Tras 3 "
        "intentos fallidos, el acceso se bloquea por 1 hora. Para desbloquear antes, el Bodeguero deber\u00e1 "
        "re-enrolarse (verificaci\u00f3n de identidad completa + nuevo PIN).", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 8
    f.append(_p("CL\u00c1USULA 8: PROTECCI\u00d3N DE DATOS", S_CLAUSULA))
    f.append(_p(
        "Se aplica la Ley N.\u00b0 29733. Los datos se usar\u00e1n para evaluaci\u00f3n, operaci\u00f3n y cobranza. El Bodeguero "
        "acepta la utilizaci\u00f3n de sus datos personales para fines comerciales y financieros de CIRCA.", S_CUERPO))

    # ------------------------------------------------------ CLAUSULA 9
    f.append(_p("CL\u00c1USULA 9: MODIFICACIONES", S_CLAUSULA))
    f.append(_p(
        "CIRCA podr\u00e1 modificar las condiciones, incluyendo el l\u00edmite de financiamiento, o poner t\u00e9rmino a la "
        "facilidad en cualquier momento, avisando al Bodeguero con 24 horas de anticipaci\u00f3n.", S_CUERPO))

    # ------------------------------------------------------ ACEPTACIONES
    f.append(_p("ACEPTACIONES DEL BODEGUERO", S_CLAUSULA))
    f.append(_p(
        "Mediante la firma digital del contrato, el Bodeguero autoriza a CIRCA, el distribuidor y la entidad "
        "financiera que:", S_CUERPO))
    f.append(_p(
        "\u25a0 1) El tratamiento de datos personales (Ley 29733) para fines comerciales.", S_CUERPO))
    f.append(_p(
        "\u25a0 2) El distribuidor comparta a CIRCA el historial de compras pasadas y futuras del Bodeguero con fines "
        "comerciales y CIRCA puede transmitir dicha informaci\u00f3n y los datos personales del Bodeguero a terceros, a "
        "su solo criterio.", S_CUERPO))
    f.append(_p(
        "\u25a0 3) CIRCA o las entidades financieras con las que act\u00fae puedan acceder a la informaci\u00f3n del Bodeguero "
        "en las centrales de riesgo.", S_CUERPO))

    # ------------------------------------------------------ FIRMA
    f.append(KeepTogether([
        _p("FIRMA DIGITAL DEL BODEGUERO", S_CLAUSULA),
        _bloque_firma(d),
        Spacer(1, 6),
        _p("Hash de verificaci\u00f3n: %s" % (d.get("hash_verificacion") or "\u2014"), S_VERSION),
    ]))

    doc.build(f)
    return salida


if __name__ == "__main__":
    demo = {
        "razon_social": "VELARDE ARNAEZ PAOLA MARIA",
        "ruc": "10413151070",
        "representante_legal": "VELARDE ARNAEZ, PAOLA MARIA",
        "dni": "41315107",
        "domicilio_fiscal": "- -",
        "direccion_entrega": "CAL. TENIENTE ROMANET 120 Dpto 401, San Isidro",
        "email": "\u2014",
        "nombre_firmante": "VELARDE ARNAEZ, PAOLA MARIA",
        "dni_firmante": "41315107",
        "telefono": "+51993557282",
        "fecha_aceptacion": "18/06/2026",
        "hora_aceptacion": "06:11:03",
        "hash_verificacion": "217d7a95c6199943",
    }
    generar_contrato_pdf(demo, "demo_contrato.pdf")
    print("OK -> demo_contrato.pdf")
