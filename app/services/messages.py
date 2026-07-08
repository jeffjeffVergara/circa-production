"""All WhatsApp message templates for Circa."""
from app.config import YAPE_PHONE, PLIN_PHONE

# ── ONBOARDING ──────────────────────────────
def msg_welcome(nombre_bodega: str, monto: float, distribuidor: str) -> str:
    return (
        f"👋 ¡Hola! Soy *Circa*, tu aliado para financiar inventario.\n\n"
        f"🎉 *¡Buenas noticias!*\n"
        f"*{nombre_bodega}* tiene una línea de crédito pre-aprobada de hasta *S/{monto:.2f}* "
        f"para financiar pedidos con *{distribuidor}*.\n\n"
        f"¿Deseas activar tu cuenta?\n"
        f"Escribe *SI* para empezar."
    )

def msg_pedir_ruc() -> str:
    return "📝 Para activar tu cuenta, escribe tu *RUC* (11 dígitos):"

def msg_ruc_verificado(razon_social: str, ruc: str, direccion: str, rep_legal: str) -> str:
    return (
        f"✅ *RUC verificado en SUNAT:*\n\n"
        f"📋 *{razon_social}*\n"
        f"RUC: {ruc}\n"
        f"📍 {direccion}\n"
        f"👤 Rep. Legal: {rep_legal}\n\n"
        f"La dirección fiscal será tu dirección de despacho.\n"
        f"¿Los datos son correctos? Escribe *SI* para continuar."
    )

def msg_pedir_dni() -> str:
    return (
        "🪪 Para verificar tu identidad, envía una *foto de tu DNI* (anverso).\n\n"
        "Esto es solo una vez, para cumplir con los requisitos de seguridad.\n"
        "📷 Envía la foto como imagen en este chat."
    )

def msg_dni_verificado(nombre: str, dni: str) -> str:
    return (
        f"✅ Listo, *{nombre}*. Identidad verificada.\n\n"
        f"DNI: {dni}\n\n"
        f"Escribe *SI* para continuar con los términos."
    )

def msg_contrato(linea: float) -> str:
    return (
        "📋 *Contrato de Línea de Crédito Circa*\n\n"
        "*Resumen de términos:*\n"
        f"• Línea de crédito revolving de hasta S/{linea:.2f}\n"
        "• Se renueva al pagar, sin nuevo contrato\n"
        "• Comisión por plan: 7d 1.4%, 15d 3%, 30d 6% (mín. S/1)\n"
        "• Plazos: 7, 15 o 30 días\n"
        "• El dinero va directo al proveedor\n"
        "• Sin costo de apertura ni mantenimiento\n\n"
        "*Al aceptar autorizas:*\n"
        "✓ Tratamiento de datos personales (Ley 29733)\n"
        "✓ Compartir historial de compras con tu distribuidor\n"
        "✓ Consulta de centrales de riesgo\n\n"
        "Escribe *ACEPTO* para firmar digitalmente."
    )

def msg_contrato_firmado() -> str:
    return "✅ Contrato firmado digitalmente. Tu aceptación ha sido registrada."

def msg_pedir_pin() -> str:
    return (
        "🔐 Crea tu *clave Circa* de 4 dígitos.\n\n"
        "La necesitarás para confirmar cada pedido financiado.\n"
        "⚠️ No uses fechas de nacimiento ni números consecutivos (1234, 1111).\n\n"
        "Escribe tus 4 dígitos:"
    )

def msg_cuenta_activa(linea: float) -> str:
    return (
        f"✅ *¡Cuenta activada!*\n\n"
        f"💰 Tu línea disponible: *S/{linea:.2f}*\n\n"
        f"¿Qué deseas hacer?\n"
        f"1️⃣ *PEDIDO* - Hacer un pedido\n"
        f"2️⃣ *LINEA* - Ver mi línea\n"
        f"3️⃣ *ESTADO* - Mis pedidos\n"
        f"4️⃣ *REPETIR* - Repetir último pedido\n"
        f"5️⃣ *Me olvidé mi clave* - Recuperar clave\n"
        f"6️⃣ *AYUDA* - Soporte"
    )

# ── CATÁLOGO ──────────────────────────────────
def msg_catalogo_intro() -> str:
    return (
        "📦 *Catálogo de productos*\n\n"
        "Te enviaré los productos disponibles por categoría.\n"
        "Precios por pack (6, 12 o 24 unidades).\n\n"
        "Escribe:\n"
        "• *BEBIDAS* / *LACTEOS* / *ABARROTES* / *CUIDADO* para filtrar\n"
        "• *MARCA [nombre]* para filtrar por marca (ej: MARCA Gloria)\n"
        "• *TODO* para ver todo\n"
        "• *CARRITO* para ver tu carrito\n"
        "• *LISTO* cuando termines de elegir"
    )

def msg_producto(idx: int, nombre: str, marca: str, seller: str, p6: float, p12: float, p24: float) -> str:
    return (
        f"*{idx}. {nombre}*\n"
        f"🏷 {marca} | 🏪 {seller}\n"
        f"  Pack 6: S/{p6:.2f}\n"
        f"  Pack 12: S/{p12:.2f}\n"
        f"  Pack 24: S/{p24:.2f}\n"
        f"_Escribe: {idx} [pack] [cant]_\n"
        f"_Ej: {idx} 12 3 = 3 packs de 12_"
    )

def msg_agregado_al_carrito(nombre: str, pack: int, cant: int, subtotal: float, cart_total: float) -> str:
    return (
        f"✅ Agregado: {cant}x pack{pack} {nombre} = S/{subtotal:.2f}\n"
        f"🛒 Carrito: *S/{cart_total:.2f}*\n\n"
        f"Sigue agregando o escribe *LISTO* para revisar."
    )

def msg_carrito(items: list, total: float, linea: float) -> str:
    lines = ["🛒 *Tu carrito:*\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['cantidad']}x pk{item['pack_size']} {item['nombre']} [{item['seller']}] — S/{item['subtotal']:.2f}")
    lines.append(f"\n*TOTAL: S/{total:.2f}*")
    
    max_fin = min(linea, total)
    if total > linea:
        contado = total - linea
        lines.append(f"\n💚 Financiable: S/{max_fin:.2f}")
        lines.append(f"🟠 Contado: S/{contado:.2f}")
    
    lines.append(f"\nEscribe *FINANCIAR* para financiar con Circa")
    lines.append(f"Escribe *AGREGAR* para seguir comprando")
    lines.append(f"Escribe *BORRAR [#]* para quitar un item")
    return "\n".join(lines)

# ── FINANCIAMIENTO ────────────────────────────
def msg_finance_amount(linea: float, total: float) -> str:
    max_fin = min(linea, total)
    o50 = round(max_fin * 0.5, 2)
    o25 = round(max_fin * 0.25, 2)
    contado = total - max_fin if total > linea else 0
    
    msg = (
        f"💰 *¿Cuánto deseas financiar?*\n"
        f"Línea disponible: S/{linea:.2f}\n\n"
        f"1️⃣ Total — *S/{max_fin:.2f}*\n"
        f"2️⃣ 50% — *S/{o50:.2f}*\n"
        f"3️⃣ 25% — *S/{o25:.2f}*\n\n"
        f"Escribe *1*, *2* o *3*."
    )
    if contado > 0:
        msg += f"\n\n💵 El resto (S/{contado:.2f}) se paga al contado en la entrega."
    return msg

def msg_finance_terms(amount: float, terms: list) -> str:
    lines = [f"📅 *Elige plazo de pago*\nFinanciar: *S/{amount:.2f}*\n"]
    for i, t in enumerate(terms, 1):
        lines.append(f"{i}️⃣ *{t['days']} días* — Tasa {t['rate_pct']} — Fee S/{t['fee']:.2f} — Total *S/{t['total']:.2f}*")
    lines.append(f"\nEscribe *1*, *2* o *3*.")
    return "\n".join(lines)

def msg_confirmar_pin(monto_total: float, monto_fin: float, fee: float, total_credito: float, 
                       plazo: int, vencimiento: str, contado: float) -> str:
    lines = [
        "📋 *Resumen del financiamiento*\n",
        f"🛒 Pedido total: S/{monto_total:.2f}",
        f"━━━━━━━━━━━━━━━━",
        f"💚 Financiar: *S/{monto_fin:.2f}*",
        f"📊 Tasa + Fee: S/{fee:.2f}",
        f"📅 Plazo: {plazo} días",
        f"💚 Total crédito: *S/{total_credito:.2f}*",
        f"📆 Vencimiento: {vencimiento}",
    ]
    if contado > 0:
        lines.append(f"🟠 Contado (entrega): *S/{contado:.2f}*")
    lines.append(f"\n🔐 *Ingresa tu clave Circa de 4 dígitos para confirmar:*")
    lines.append(f"⏱ Tienes 5 minutos.")
    lines.append(f"💡 _Puedes borrar el mensaje con tu clave después de enviarlo._")
    return "\n".join(lines)

# ── CONSTANCIA ────────────────────────────────
def msg_receipt(numero: str, monto_fin: float, fee: float, total: float, 
                plazo: int, vencimiento: str, contado: float) -> str:
    lines = [
        "✅ *¡PEDIDO CONFIRMADO!*",
        f"Financiado con Circa\n",
        f"📄 Nro: *{numero}*",
        f"💚 Financiado: S/{monto_fin:.2f}",
        f"💚 Fee: S/{fee:.2f}",
        f"💚 Total crédito: *S/{total:.2f}*",
        f"📅 Vencimiento: {vencimiento}",
    ]
    if contado > 0:
        lines.append(f"🟠 Contado (entrega): S/{contado:.2f}")
    lines.append(f"\nRecibirás actualizaciones de tu pedido aquí y por email. 📬")
    return "\n".join(lines)

# ── STATUS ────────────────────────────────────
_ESTADO_PEDIDO_LABELS = {
    "borrador": "Borrador",
    "preventa_borrador": "Pre-venta borrador",
    "preventa_confirmada": "Pre-venta pendiente",
    "preventa_aceptada": "Pre-venta aceptada",
    "confirmado": "Confirmado",
    "recibido": "Recibido",
    "en_preparacion": "En preparación",
    "despachado": "Despachado",
    "en_camino": "En camino",
    "entregado": "Entregado",
    "pago_reportado": "Pago reportado",
}


def _fmt_fecha_vencimiento(raw) -> str:
    if not raw:
        return ""
    s = str(raw)[:10]
    if len(s) == 10 and s[4] == "-":
        try:
            y, m, d = s.split("-")
            return f"{d}/{m}/{y}"
        except ValueError:
            pass
    return str(raw)


def format_pedido_activo_line(p: dict) -> str:
    """Una línea legible para ESTADO / pedidos activos (incluye preventas sin número)."""
    estado = (p.get("estado") or "").strip()
    label = _ESTADO_PEDIDO_LABELS.get(estado, estado.replace("_", " ").title() or "—")

    numero = p.get("numero")
    if numero:
        ref = str(numero)
    else:
        lt = (p.get("link_token") or "").strip()
        ref = f"PRV-{lt[:8]}" if lt else "Pre-venta"

    total_pedido = float(p.get("total_pedido") or p.get("monto_productos") or 0)
    monto_credito = float(p.get("monto_total_credito") or 0)
    monto_fin = float(p.get("monto_financiado") or 0)
    fee = float(p.get("fee_monto") or 0)
    monto_contado = float(p.get("monto_contado") or 0)

    if estado in ("preventa_confirmada", "preventa_borrador", "borrador"):
        monto_show = total_pedido
    elif monto_credito > 0:
        monto_show = monto_credito
    elif monto_fin > 0:
        monto_show = monto_fin + fee
    else:
        monto_show = float(p.get("total") or total_pedido or monto_contado or 0)

    vence_raw = p.get("fecha_vencimiento")
    if vence_raw:
        vence_str = f"Vence {_fmt_fecha_vencimiento(vence_raw)}"
    elif estado in ("preventa_confirmada", "preventa_borrador"):
        vence_str = "Pendiente de confirmar"
    else:
        vence_str = "Sin vencimiento"

    line = f"• {ref} — {label} — S/{monto_show:.2f} — {vence_str}"
    if monto_contado > 0 and estado not in ("preventa_confirmada", "preventa_borrador", "borrador"):
        line += f" (+ S/{monto_contado:.2f} contado)"
    return line


def msg_status(numero: str, estado: str, detalle: str = "") -> str:
    icons = {
        "confirmado": "📋", "aprobado": "✅", "despachado": "📦",
        "en_camino": "🚚", "entregado": "🎉", "pagado": "💚",
    }
    return f"{icons.get(estado, '📌')} *Pedido {numero}*\nEstado: *{estado.upper()}*\n{detalle}"

# ── COBRANZA ──────────────────────────────────
def msg_recordatorio(nombre: str, monto: float, vencimiento: str, dias: int) -> str:
    if dias > 0:
        urgencia = f"vence en *{dias} días*"
    elif dias == 0:
        urgencia = "*vence HOY*"
    else:
        urgencia = f"está *VENCIDO* hace {abs(dias)} día(s)"
    
    return (
        f"🔔 *Recordatorio de pago*\n\n"
        f"Hola {nombre}, tu pago de *S/{monto:.2f}* {urgencia} ({vencimiento}).\n\n"
        f"Paga fácilmente:\n\n"
        f"💜 *Yape*: {YAPE_PHONE}\n"
        f"💚 *Plin*: {PLIN_PHONE}\n"
        f"Nombre: Circa Pagos S.A.C.\n\n"
        f"Una vez pagado, escribe *PAGUE* para confirmar."
    )

def msg_pago_recibido(monto: float, linea_nueva: float) -> str:
    return (
        f"🎉 *¡Pago registrado!*\n\n"
        f"Se recibió tu pago de *S/{monto:.2f}*.\n"
        f"Verificación en las próximas horas.\n\n"
        f"💰 Tu línea disponible ahora es: *S/{linea_nueva:.2f}*\n\n"
        f"Escribe *PEDIDO* cuando necesites reabastecer. 🤝"
    )

# ── ERRORES ───────────────────────────────────
def msg_pin_incorrecto(intentos_restantes: int) -> str:
    return f"❌ Clave incorrecta. Te quedan *{intentos_restantes}* intento(s)."

def msg_pin_bloqueado(minutos: int) -> str:
    return f"🔒 Clave bloqueada por *{minutos} minutos*. Tu carrito se ha guardado."

def msg_timeout() -> str:
    return "⏱ Tiempo agotado. Tu carrito se ha guardado. Escribe *PEDIDO* para retomar."

def msg_no_entiendo() -> str:
    return (
        "🤔 No entendí tu mensaje.\n\n"
        "Escribe:\n"
        "• *PEDIDO* - Hacer un pedido\n"
        "• *LINEA* - Ver mi línea\n"
        "• *ESTADO* - Mis pedidos\n"
        "• *REPETIR* - Repetir último pedido\n"
        "• *Me olvidé mi clave* - Recuperar clave Circa\n"
        "• *AYUDA* - Soporte"
    )

def msg_ruc_invalido() -> str:
    return "❌ RUC no válido. Debe tener 11 dígitos y empezar con 10 o 20. Intenta de nuevo:"

def msg_ruc_no_encontrado() -> str:
    return "❌ No encontramos tu RUC en nuestra base pre-aprobada. Contacta a tu distribuidor."
