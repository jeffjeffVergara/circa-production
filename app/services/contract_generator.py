"""
Generador de Contrato PDF — Circa
app/services/contract_generator.py

Genera el contrato de facilidad de financiamiento con datos del bodeguero.
Uso: generate_contract(bodega_data) → retorna path del PDF generado

SETUP: colocar Logo_3.png en app/static/circa_logo.png
"""
import os
import hashlib
from datetime import datetime

from app.config import now_peru
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib import colors

# --- Colores Circa ---
CIRCA_BLUE = HexColor("#4A90D9")
TEXT_DARK = HexColor("#222222")
TEXT_GRAY = HexColor("#555555")
LIGHT_BG = HexColor("#f5f8fa")

# --- Path del logo (relativo al módulo) ---
LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "circa_logo.png")


def _get_styles():
    """Estilos personalizados para el contrato."""
    styles = getSampleStyleSheet()
    
    custom_styles = {
        "ContractTitle": dict(
            fontName="Helvetica-Bold", fontSize=16, leading=20,
            alignment=TA_CENTER, textColor=TEXT_DARK, spaceAfter=4,
        ),
        "ContractSubtitle": dict(
            fontName="Helvetica", fontSize=11, leading=14,
            alignment=TA_CENTER, textColor=TEXT_GRAY, spaceAfter=2,
        ),
        "VersionDate": dict(
            fontName="Helvetica", fontSize=9, leading=12,
            alignment=TA_CENTER, textColor=TEXT_GRAY,
            spaceBefore=10, spaceAfter=16,
        ),
        "ClauseTitle": dict(
            fontName="Helvetica-Bold", fontSize=11, leading=14,
            textColor=TEXT_DARK, spaceBefore=14, spaceAfter=6,
        ),
        "ClauseBody": dict(
            fontName="Helvetica", fontSize=9.5, leading=13,
            alignment=TA_JUSTIFY, textColor=TEXT_DARK, spaceAfter=4,
        ),
        "FieldLabel": dict(
            fontName="Helvetica-Bold", fontSize=9.5, leading=13,
            textColor=TEXT_DARK,
        ),
        "FieldValue": dict(
            fontName="Helvetica", fontSize=9.5, leading=13,
            textColor=CIRCA_BLUE,
        ),
        "SmallFooter": dict(
            fontName="Helvetica", fontSize=8, leading=10,
            alignment=TA_CENTER, textColor=TEXT_GRAY,
        ),
        "AcceptItem": dict(
            fontName="Helvetica", fontSize=9, leading=12,
            alignment=TA_JUSTIFY, textColor=TEXT_DARK,
            leftIndent=20, spaceAfter=4,
        ),
        "SignatureLabel": dict(
            fontName="Helvetica", fontSize=9.5, leading=13,
            textColor=TEXT_GRAY,
        ),
        "SignatureValue": dict(
            fontName="Helvetica-Bold", fontSize=10, leading=14,
            textColor=TEXT_DARK,
        ),
    }
    
    for name, kwargs in custom_styles.items():
        styles.add(ParagraphStyle(name=name, **kwargs))
    
    return styles


def _build_field_table(fields: list, styles) -> Table:
    """Tabla de datos del bodeguero (label: value)."""
    table_data = []
    for label, value in fields:
        table_data.append([
            Paragraph(f"<b>{label}:</b>", styles["FieldLabel"]),
            Paragraph(str(value) if value else "\u2014", styles["FieldValue"]),
        ])

    t = Table(table_data, colWidths=[140, 310])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (0, -1), 12),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#dddddd")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, HexColor("#eeeeee")),
    ]))
    return t


def _build_rates_table(styles) -> Table:
    """Tabla de plazos y cargos."""
    header = [
        Paragraph("<b>Plazo</b>", styles["ClauseBody"]),
        Paragraph("<b>Cargo</b>", styles["ClauseBody"]),
        Paragraph("<b>M\u00ednimo</b>", styles["ClauseBody"]),
    ]
    rows = [
        header,
        ["7 d\u00edas", "3% del monto financiado", "S/ 5.00"],
        ["15 d\u00edas", "5% del monto financiado", "S/ 5.00"],
        ["30 d\u00edas", "7% del monto financiado", "S/ 5.00"],
    ]

    t = Table(rows, colWidths=[100, 220, 100])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e8f0fe")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# --- Textos de las cláusulas ---
CLAUSULAS = [
    ("CL\u00c1USULA 1: PARTES", None),  # Handled specially
    ("CL\u00c1USULA 2: OBJETO", [
        "CIRCA es una plataforma tecnol\u00f3gica que facilita financiamiento comercial, "
        "directamente o a trav\u00e9s de entidades financieras, vinculado a la compra de "
        "bienes a la red de distribuidores autorizados por CIRCA. No capta dinero del "
        "p\u00fablico ni es entidad financiera.",
        "CIRCA pone a disposici\u00f3n del BODEGUERO una facilidad de financiamiento comercial "
        "para la adquisici\u00f3n de productos a trav\u00e9s de la red de distribuidores autorizados "
        "por CIRCA. El monto financiado se acredita directamente al distribuidor autorizado "
        "por CIRCA y permite al BODEGUERO pagar de forma diferida los pedidos para la "
        "adquisici\u00f3n de dichos productos hasta el l\u00edmite de financiamiento.",
    ]),
    ("CL\u00c1USULA 3: L\u00cdMITE DE FINANCIAMIENTO", [
        "CIRCA asignar\u00e1 un l\u00edmite de financiamiento basado en evaluaci\u00f3n interna, el cual "
        "ser\u00e1 comunicado al Bodeguero. El l\u00edmite es reutilizable una vez canceladas las "
        "obligaciones pendientes. El financiamiento podr\u00e1 cubrir total o parcialmente el pedido.",
    ]),
    ("CL\u00c1USULA 4: PLAZOS Y CARGOS", None),  # Handled specially
    ("CL\u00c1USULA 5: FORMA DE PAGO", [
        "El pago se realiza a CIRCA v\u00eda Yape o Plin al n\u00famero designado por CIRCA. "
        "El Bodeguero debe confirmar el pago por WhatsApp. CIRCA podr\u00e1 validar el pago "
        "hasta en 2 d\u00edas h\u00e1biles.",
    ]),
    ("CL\u00c1USULA 6: INCUMPLIMIENTO Y MORA", [
        "Regir\u00e1 la mora autom\u00e1tica sin necesidad de interpelaci\u00f3n o aviso al Bodeguero. "
        "Se podr\u00e1n enviar recordatorios de pago. En caso de morosidad o incumplimiento, "
        "se aplicar\u00e1 un cargo por mora de 0.30% diario sobre el saldo pendiente, incluyendo "
        "los cargos. Se suspender\u00e1 la facilidad y se podr\u00e1n bloquear nuevos pedidos.",
        "En caso de incumplimiento, CIRCA notificar\u00e1 al distribuidor asociado sobre el "
        "estado de mora del BODEGUERO. Esta informaci\u00f3n podr\u00e1 ser considerada por el "
        "distribuidor para futuras decisiones comerciales.",
    ]),
    ("CL\u00c1USULA 7: SEGURIDAD", [
        "El Bodeguero crear\u00e1 un PIN personal (c\u00f3digo de 4 d\u00edgitos) para acceder a la "
        "plataforma de CIRCA. Tras 3 intentos fallidos, el acceso se bloquea por 1 hora. "
        "Para desbloquear antes, el Bodeguero deber\u00e1 re-enrolarse (verificaci\u00f3n de identidad "
        "completa + nuevo PIN).",
    ]),
    ("CL\u00c1USULA 8: PROTECCI\u00d3N DE DATOS", [
        "Se aplica la Ley N.\u00b0 29733. Los datos se usar\u00e1n para evaluaci\u00f3n, operaci\u00f3n y "
        "cobranza. El Bodeguero acepta la utilizaci\u00f3n de sus datos personales para fines "
        "comerciales y financieros de CIRCA.",
    ]),
    ("CL\u00c1USULA 9: MODIFICACIONES", [
        "CIRCA podr\u00e1 modificar las condiciones, incluyendo el l\u00edmite de financiamiento, "
        "o poner t\u00e9rmino a la facilidad en cualquier momento, avisando al Bodeguero con "
        "24 horas de anticipaci\u00f3n.",
    ]),
    ("CL\u00c1USULA 10: JURISDICCI\u00d3N", [
        "El presente contrato se rige por las leyes de la Rep\u00fablica del Per\u00fa. Para "
        "cualquier controversia, las partes se someten a la jurisdicci\u00f3n de los tribunales "
        "de Lima-Cercado.",
    ]),
    ("CL\u00c1USULA 11: ACEPTACI\u00d3N", [
        "La aceptaci\u00f3n digital v\u00eda WhatsApp as\u00ed como las comunicaciones por correo "
        "electr\u00f3nico tienen validez legal.",
    ]),
    ("CL\u00c1USULA 12: USO DEL FINANCIAMIENTO", [
        "La facilidad solo puede ser utilizada para la compra de productos dentro de la "
        "red de distribuidores de CIRCA.",
    ]),
]

ACEPTACIONES = [
    "1) El tratamiento de datos personales (Ley 29733) para fines comerciales.",
    "2) El distribuidor comparta a CIRCA el historial de compras pasadas y futuras "
    "del Bodeguero con fines comerciales y CIRCA puede transmitir dicha informaci\u00f3n y "
    "los datos personales del Bodeguero a terceros, a su solo criterio.",
    "3) CIRCA o las entidades financieras con las que act\u00fae puedan acceder a la "
    "informaci\u00f3n del Bodeguero en las centrales de riesgo.",
]


def generate_contract(bodega_data: dict, output_dir: str = "/tmp") -> str:
    """
    Genera el contrato PDF con datos del bodeguero.
    
    bodega_data keys:
        razon_social, ruc, representante_legal, dni_representante,
        direccion_fiscal, direccion_despacho, email,
        linea_aprobada, nombre_comercial, distribuidor_nombre,
        telefono, fecha_firma, hora_firma
    
    Retorna: path absoluto del PDF generado
    """
    styles = _get_styles()
    
    # Datos con defaults
    razon = bodega_data.get("razon_social", "")
    ruc = bodega_data.get("ruc", "")
    rep_legal = bodega_data.get("representante_legal", "")
    dni = bodega_data.get("dni_representante", "")
    dir_fiscal = bodega_data.get("direccion_fiscal", "")
    dir_despacho = bodega_data.get("direccion_despacho", dir_fiscal)
    email = bodega_data.get("email", "\u2014")
    linea = bodega_data.get("linea_aprobada", 500)
    telefono = bodega_data.get("telefono", "")
    
    now = now_peru()
    fecha_firma = bodega_data.get("fecha_firma", now.strftime("%d/%m/%Y"))
    hora_firma = bodega_data.get("hora_firma", now.strftime("%H:%M:%S"))
    
    # Nombre del archivo
    safe_ruc = ruc.replace(" ", "") if ruc else "sin_ruc"
    filename = f"Contrato_Circa_{safe_ruc}_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(output_dir, filename)
    
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=40, bottomMargin=50,
        leftMargin=55, rightMargin=55,
    )
    
    story = []
    
    # ===== LOGO =====
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=180, height=120)
        logo.hAlign = "CENTER"
        story.append(logo)
        story.append(Spacer(1, 12))
    
    # ===== TITULO =====
    story.append(Paragraph(
        "CONTRATO DE FACILIDAD DE FINANCIAMIENTO COMERCIAL",
        styles["ContractTitle"]
    ))
    story.append(Paragraph(
        "Plataforma Circa \u2014 Cr\u00e9dito embebido para bodegas",
        styles["ContractSubtitle"]
    ))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=2, color=CIRCA_BLUE))
    story.append(Paragraph(
        f"Versi\u00f3n 2.0 | Fecha de emisi\u00f3n: 06/04/2026",
        styles["VersionDate"]
    ))
    
    # ===== CLAUSULA 1: PARTES =====
    story.append(Paragraph("CL\u00c1USULA 1: PARTES", styles["ClauseTitle"]))
    story.append(Paragraph(
        "<b>CIRCA:</b> CIRCA opera como plataforma tecnol\u00f3gica de facilitaci\u00f3n de "
        "financiamiento y gesti\u00f3n de pagos. CIRCA es un nombre comercial de "
        "PALI S.A.C., con RUC N.\u00b0 20600627806.",
        styles["ClauseBody"]
    ))
    story.append(Paragraph(
        "<b>EL BODEGUERO:</b> Es la persona natural o jur\u00eddica titular del negocio "
        "que acepta estos t\u00e9rminos mediante la plataforma de WhatsApp de CIRCA.",
        styles["ClauseBody"]
    ))
    story.append(Spacer(1, 4))
    
    fields = [
        ("Nombre / Raz\u00f3n Social", razon),
        ("RUC", ruc),
        ("Representante legal", rep_legal),
        ("DNI", dni),
        ("Domicilio fiscal", dir_fiscal),
        ("Direcci\u00f3n de entrega", dir_despacho),
        ("Correo electr\u00f3nico", email),
    ]
    story.append(_build_field_table(fields, styles))
    story.append(Spacer(1, 6))
    
    # ===== CLAUSULAS 2-12 =====
    for title, paragraphs in CLAUSULAS:
        if title.startswith("CL\u00c1USULA 1"):
            continue  # Ya se manej\u00f3 arriba
        
        story.append(Paragraph(title, styles["ClauseTitle"]))
        
        if title.startswith("CL\u00c1USULA 4"):
            story.append(Paragraph("Plazos y cargos aplicables:", styles["ClauseBody"]))
            story.append(Spacer(1, 4))
            story.append(_build_rates_table(styles))
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "Los cargos corresponden a la tarifa por uso de la plataforma y la facilidad "
                "de pago diferido.", styles["ClauseBody"]
            ))
            continue
        
        if paragraphs:
            for p in paragraphs:
                story.append(Paragraph(p, styles["ClauseBody"]))
    
    # ===== ACEPTACIONES =====
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc"), spaceAfter=8))
    story.append(Paragraph("ACEPTACIONES DEL BODEGUERO", styles["ClauseTitle"]))
    story.append(Paragraph(
        "Mediante la firma digital del contrato, el Bodeguero autoriza a CIRCA, "
        "el distribuidor y la entidad financiera que:",
        styles["ClauseBody"]
    ))
    for acc in ACEPTACIONES:
        story.append(Paragraph(f"\u25a0  {acc}", styles["AcceptItem"]))
    
    # ===== FIRMA DIGITAL =====
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=CIRCA_BLUE, spaceAfter=12))
    story.append(Paragraph("FIRMA DIGITAL DEL BODEGUERO", styles["ClauseTitle"]))
    story.append(Spacer(1, 8))
    
    sig_data = [
        [
            Paragraph("<b>Firma digital del Bodeguero:</b>", styles["SignatureLabel"]),
            Paragraph("<b>Fecha:</b>", styles["SignatureLabel"]),
        ],
        [
            Paragraph("[OK] Aceptado v\u00eda WhatsApp", styles["SignatureValue"]),
            Paragraph(fecha_firma, styles["SignatureValue"]),
        ],
        [
            Paragraph(f"Nombre: {rep_legal}", styles["SignatureLabel"]),
            Paragraph(f"Hora: {hora_firma}", styles["SignatureLabel"]),
        ],
        [
            Paragraph(f"DNI: {dni}", styles["SignatureLabel"]),
            Paragraph(f"Tel: +51{telefono}", styles["SignatureLabel"]),
        ],
    ]
    
    sig_table = Table(sig_data, colWidths=[280, 180])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, HexColor("#dddddd")),
    ]))
    story.append(sig_table)
    
    # Hash de verificación
    contract_text = f"{ruc}|{dni}|{fecha_firma}|{hora_firma}|{linea}"
    contract_hash = hashlib.sha256(contract_text.encode()).hexdigest()[:16]
    
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Hash de verificaci\u00f3n: {contract_hash}",
        ParagraphStyle("Hash", fontName="Courier", fontSize=8,
                       textColor=TEXT_GRAY, alignment=TA_CENTER)
    ))
    
    # Footer
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.3, color=HexColor("#dddddd"), spaceAfter=6))
    story.append(Paragraph(
        "PALI S.A.C. | RUC 20600627806 | Circa \u2014 Plataforma de cr\u00e9dito embebido",
        styles["SmallFooter"]
    ))
    story.append(Paragraph(
        "Cal. Teniente Romanet 120 Dpto 401, San Isidro, Lima | contacto@circa.pe",
        styles["SmallFooter"]
    ))
    
    doc.build(story)
    return output_path, contract_hash
