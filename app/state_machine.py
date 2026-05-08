"""
Circa WhatsApp State Machine — Full Button UX
──────────────────────────────────────────────
Returns a list of responses. Each response is either:
  - str  → plain text message (sent via send_whatsapp)
  - dict → template signal (dispatched by main.py to the right template sender)

Template signals use the format:
  {"signal": "CATEGORIAS"}
  {"signal": "PRODUCTOS", "categoria": "bebidas"}
  {"signal": "PACK", "nombre": "...", "p6": 9.60, "p12": 18.00, "p24": 34.00}
  {"signal": "CANTIDAD", "nombre": "...", "pack_label": "Pack 12", "precio": 18.00}
  {"signal": "AGREGADO", "cantidad": 2, ...}
  {"signal": "CARRITO", "items_text": "...", "total": 72.0, "financiable": 72.0}
  {"signal": "MONTO", "linea": 500.0, "total": 72.0, "financiable": 72.0}
  {"signal": "PLAZO", "monto": 72.0, ...}
  {"signal": "MENU", "linea": 500.0}
"""
import json, hashlib, unicodedata, os
from datetime import datetime, date, timedelta
from app.services import db, messages as msg, fees
from app.services.representante_comms import nombre_para_comunicar_representante
from app.services.pin import check_pin
from app.services.identity import consultar_ruc_sync, consultar_dni_sync, validate_ruc_format, validate_dni_format, is_ruc_eligible

# Test phones — bypass SUNAT/RENIEC/Vision validation
TEST_PHONES = {"+51954712581", "+51977652871", "+56991291415", "+51955755308", "+51981254477", "+51961276835", "51954712581", "51977652871", "56991291415", "51955755308", "51981254477", "51961276835"}
from app.config import TWILIO_FROM, BIOMETRIA_MODE, circa_soporte_wa_link


def normalize(text: str) -> str:
    text = (text or "").strip().upper()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Palabras clave que en cualquier fase derivan a la misma respuesta que "Contactar a Circa".
_TEXTO_PIDE_CONTACTO_CIRCA = frozenset({
    "AYUDA",
    "HELP",
    "NO ENTIENDO",
    "NO TE ENTIENDO",
    "NO LO ENTIENDO",
    "NO ENTIENDES",
    "CONTACTO",
    "SOPORTE",
    "CONTACTAR",
    "6",
})


def _desvio_contacto_circa_responses() -> list:
    return [{"signal": "CONTACT_CIRCA", "wa_link": circa_soporte_wa_link()}]


def _app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")

def _bot_wa_number() -> str:
    return TWILIO_FROM.replace("whatsapp:", "").replace("+", "").strip()

def get_catalog_url(bodega_id: str) -> str:
    return f"{_app_base_url()}/catalogo-v2?b={bodega_id}"

def get_pin_url(bodega_id: str, mode: str = "confirm") -> str:
    return f"{_app_base_url()}/pin?b={bodega_id}&mode={mode}&to={_bot_wa_number()}"


def _find_product_by_sku(bodega: dict, sku: str) -> dict | None:
    """Find a catalog item by SKU for the bodega's distributor."""
    rows = (
        db.sb.table("catalogo_distribuidor")
        .select("*, productos_circa(*)")
        .eq("activo", True)
        .eq("distribuidor_id", bodega["distribuidor_id"])
        .eq("sku_distribuidor", sku)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    pc = row.get("productos_circa") or {}
    return {
        "id": pc.get("id"), "nombre": pc.get("nombre", ""), "marca": pc.get("marca", ""),
        "categoria": pc.get("categoria", ""), "unidades": row.get("unidades") or {},
        "sku": row.get("sku_distribuidor", ""), "activo": row.get("activo", True),
    }


def _cart_total(cart: list) -> float:
    return sum(i.get("subtotal", 0) for i in cart)


def _cart_items_text(cart: list) -> str:
    """Format cart items for the carrito template (max ~640 chars for WhatsApp)."""
    lines = []
    for i in cart:
        lines.append(f"{i['cantidad']}x Pk{i['pack_size']} {i['nombre']} — S/{i['subtotal']:.2f}")
    return "\n".join(lines) if lines else "(vacío)"


def handle_message(telefono: str, body: str, media_url: str = None) -> list:
    body_raw = (body or "").strip()
    body_n = normalize(body_raw)

    session = db.get_session(telefono)
    bodega = db.get_bodega_by_phone(telefono)

    if body_n and body_n in _TEXTO_PIDE_CONTACTO_CIRCA:
        return _desvio_contacto_circa_responses()

    # ── NO SESSION ──
    if not session:
        if bodega:
            if bodega["estado"] == "activo":
                db.upsert_session(telefono, "menu", {}, bodega["id"])
                return [{"signal": "MENU", "linea": bodega["linea_disponible"]}]
            else:
                dist = (
                    db.sb.table("distribuidores")
                    .select("nombre_comercial")
                    .eq("id", bodega["distribuidor_id"])
                    .single()
                    .execute()
                    .data
                )
                db.upsert_session(telefono, "welcome", {}, bodega["id"])
                return [{
                    "signal": "WELCOME",
                    "nombre": bodega["nombre_comercial"] or bodega["razon_social"],
                    "linea": bodega["linea_aprobada"],
                    "distribuidor": dist["nombre_comercial"],
                }]
        return ["""¡Hola, Bienvenido a Circa! 👋 Qué bueno que nos escribes.

Te cuento rapidito cómo funciona Circa Lab:

Somos el sistema que ayuda a tu negocio a crecer. Te damos una línea de crédito para que compres tu mercadería sin descapitalizarte — compras hoy, pagas cuando vendes. Sin ir al banco, sin papeleos, sin demoras. Solo necesitamos conocer con que distribuidores trabajas.

Para afiliarte solo necesitas:

1️⃣ Tener un negocio (bodega, minimarket, puesto) con al menos 6 meses de operación - nos envias tu RUC y/o # DNI de representante legal
2️⃣ Enviarnos tu DNI (foto por ambos lados)
3️⃣ Una foto de tu local

En menos de 24 horas validamos tu solicitud y activamos tu línea. Empiezas comprando hasta S/500 y esa línea va creciendo según tu historial con nosotros.

¿Te animas a empezar? Mándame los datos y arrancamos hoy mismo. 🚀"""]

    fase = session["fase"]
    datos = json.loads(session["datos"]) if isinstance(session["datos"], str) else (session["datos"] or {})

    # ═══ WELCOME ═══
    if fase == "welcome":
        if body_n in ("SI", "ACTIVAR", "1", "HOLA", "HI", "MAS_INFO", "MAS INFO"):
            if bodega and bodega.get("solo_dni_sin_ruc"):
                db.upsert_session(
                    telefono,
                    "reg_dni",
                    {"bodega_id": bodega["id"]},
                    bodega["id"],
                )
                return [{"signal": "DNI_ASK"}]
            db.upsert_session(telefono, "reg_ruc", datos, bodega["id"] if bodega else None)
            return [{"signal": "RUC_ASK"}]
        return [{
            "signal": "WELCOME",
            "nombre": bodega["nombre_comercial"] or bodega["razon_social"],
            "linea": bodega["linea_aprobada"],
            "distribuidor": "tu distribuidor",
        }]

    # ═══ RUC ═══
    if fase == "reg_ruc":
        if datos.get("ruc"):
            if body_n in ("SI", "CONFIRMO", "CORRECTO"):
                db.upsert_session(telefono, "reg_dni", datos, datos.get("bodega_id"))
                return [{"signal": "DNI_ASK"}]
            if body_n in ("NO", "CORREGIR"):
                datos.pop("ruc", None)
                datos.pop("bodega_id", None)
                db.upsert_session(telefono, "reg_ruc", datos, None)
                return [{"signal": "RUC_ASK"}]
            return ["Escribe *SI* si los datos son correctos, o *NO* para corregir."]

        ruc = body_raw.replace(" ", "")
        if len(ruc) != 11 or not ruc.isdigit() or ruc[:2] not in ("10", "20"):
            return ["❌ RUC inválido. Debe tener 11 dígitos y empezar con 10 o 20.\n\n📝 Escribe tu RUC:"]

        bodega = db.get_bodega_by_ruc(ruc)
        if not bodega:
            return ["\u274c Este RUC no tiene una l\u00ednea pre-aprobada en Circa.\n\nVerifica el n\u00famero e intenta de nuevo."]

        if bodega["telefono_whatsapp"] != telefono and bodega["telefono_whatsapp"] != f"+{telefono.lstrip('+')}":
            return ["\u274c Este RUC no est\u00e1 asociado a tu n\u00famero de WhatsApp."]

        # Verify with SUNAT via ApiInti (bypass for test phones)
        if telefono in TEST_PHONES:
            sunat = None  # Skip SUNAT for test
        else:
            sunat = consultar_ruc_sync(ruc)
        if sunat:
            eligible, reason = is_ruc_eligible(sunat)
            if not eligible:
                return [f"\u274c {reason}"]
            razon_social = sunat.get("razon_social") or bodega["razon_social"]
            direccion = sunat.get("direccion") or bodega["direccion_fiscal"] or "Sin direcci\u00f3n"
            rep_legal = sunat.get("rep_legal") or bodega.get("representante_legal") or "No disponible"
            # Update bodega with SUNAT data
            db.update_bodega(bodega["id"], {
                "razon_social": razon_social,
                "direccion_fiscal": direccion,
                "representante_legal": rep_legal if rep_legal != "No disponible" else bodega.get("representante_legal"),
            })
        else:
            razon_social = bodega["razon_social"]
            direccion = bodega["direccion_fiscal"] or "Sin direcci\u00f3n"
            rep_legal = bodega.get("representante_legal") or "No disponible"

        datos["ruc"] = ruc
        datos["bodega_id"] = bodega["id"]
        db.upsert_session(telefono, "reg_ruc", datos, bodega["id"])
        return [{
            "signal": "RUC_VERIFIED",
            "razon_social": razon_social,
            "ruc": ruc,
            "direccion": direccion,
            "representante": rep_legal,
        }]

    # \u2550\u2550\u2550 DNI \u2550\u2550\u2550
    if fase == "reg_dni":
        bodega_id = datos.get("bodega_id")
        if not bodega_id:
            db.upsert_session(telefono, "welcome", {}, None)
            return [{"signal": "WELCOME", "nombre": "", "linea": 500, "distribuidor": ""}]

        result = db.sb.table("bodegas").select("*").eq("id", bodega_id).execute()
        bodega_data = result.data[0] if result.data else None
        if not bodega_data:
            db.upsert_session(telefono, "welcome", {}, None)
            return ["\u274c Error al consultar tu bodega. Escribe *Hola* para reiniciar."]

        # ── Step 2: DNI number verified, waiting for photo of physical DNI ──
        if datos.get("dni_verified") and not datos.get("dni_photo_verified"):
            if media_url:
                try:
                    from app.services.vision import download_whatsapp_media_sync, verify_dni_photo
                    image_bytes = download_whatsapp_media_sync(media_url)
                    if image_bytes:
                        if telefono in TEST_PHONES:
                            check = {"valid": True, "matches_expected": True}  # Bypass for test
                        else:
                            check = verify_dni_photo(
                                image_bytes,
                                datos.get("dni_number", ""),
                                datos.get("dni_nombre", ""),
                            )
                        matches_ok = check.get("matches_expected_dni")
                        if matches_ok is None:
                            matches_ok = check.get("matches_expected")
                        if not check.get("valid", False) or matches_ok is False:
                            reason = check.get("reason", "No se pudo verificar el DNI.")
                            db.log_biometria_auditoria(
                                bodega_id=bodega_id,
                                telefono=telefono,
                                etapa="dni_anverso",
                                hit=False,
                                reason=reason,
                                reason_code=check.get("reason_code", ""),
                                confidence=check.get("confidence", ""),
                                provider="anthropic",
                                model="claude-sonnet-4-20250514",
                                metadata={
                                    "dni_found": check.get("dni_found", ""),
                                    "name_found": check.get("name_found", ""),
                                    "matches_expected_dni": check.get("matches_expected_dni"),
                                    "matches_expected_name": check.get("matches_expected_name"),
                                },
                            )
                            return [f"\u274c {reason}\n\nEnv\u00eda una foto clara del *anverso de tu DNI f\u00edsico*."]
                        db.log_biometria_auditoria(
                            bodega_id=bodega_id,
                            telefono=telefono,
                            etapa="dni_anverso",
                            hit=True,
                            reason=check.get("reason", "Documento valido."),
                            reason_code=check.get("reason_code", "ok"),
                            confidence=check.get("confidence", ""),
                            provider="anthropic",
                            model="claude-sonnet-4-20250514",
                            metadata={
                                "dni_found": check.get("dni_found", ""),
                                "name_found": check.get("name_found", ""),
                                "matches_expected_dni": check.get("matches_expected_dni"),
                                "matches_expected_name": check.get("matches_expected_name"),
                            },
                        )
                        datos["dni_photo_verified"] = True
                        datos["dni_photo_media_id"] = media_url
                        db.upsert_session(telefono, "reg_biometria", datos, bodega_id)
                        nombre = datos.get("dni_nombre", "")
                        saludo_rep = nombre_para_comunicar_representante(bodega_data, nombre)
                        return [
                            f"\u2705 *Documento verificado*\nDNI {datos.get('dni_number', '')} \u2014 {nombre}\n\n"
                            f"\U0001f512 Por tu seguridad, ya puedes eliminar la foto de este chat.",
                            {"signal": "BIOMETRIA_ASK", "representante": saludo_rep},
                        ]
                    else:
                        db.log_biometria_auditoria(
                            bodega_id=bodega_id,
                            telefono=telefono,
                            etapa="dni_anverso",
                            hit=False,
                            reason="No se pudo descargar la imagen de WhatsApp.",
                            reason_code="media_download_failed",
                            confidence="low",
                            provider="meta_whatsapp_cloud",
                            model="",
                            metadata={},
                        )
                        return ["\u274c No pude descargar la imagen. Intenta enviarla de nuevo."]
                except Exception as e:
                    import logging
                    logging.getLogger("circa").error(f"DNI photo check error: {e}", exc_info=True)
                    db.log_biometria_auditoria(
                        bodega_id=bodega_id,
                        telefono=telefono,
                        etapa="dni_anverso",
                        hit=False,
                        reason="Error interno en verificacion del DNI.",
                        reason_code="dni_photo_exception",
                        confidence="low",
                        provider="anthropic",
                        model="claude-sonnet-4-20250514",
                        metadata={"error": str(e)[:200]},
                    )
                    datos["dni_photo_verified"] = True
                    db.upsert_session(telefono, "reg_biometria", datos, bodega_id)
                    saludo_rep = nombre_para_comunicar_representante(
                        bodega_data, datos.get("dni_nombre"),
                    )
                    return [{"signal": "BIOMETRIA_ASK", "representante": saludo_rep}]
            return [
                "\U0001f4f8 Env\u00eda una *foto del anverso de tu DNI f\u00edsico* para verificar que lo tienes en tu poder.\n\n"
                "\U0001f512 Tip: env\u00edala como *Vista \u00fanica* (\u2460) para mayor seguridad."
            ]

        # ── Step 1: User types DNI number (8 digits) ──
        dni = body_raw.replace(" ", "")
        valid, error_msg = validate_dni_format(dni)
        if not valid:
            if datos.get("is_reset"):
                return ["Escribe el DNI del representante legal (8 d\u00edgitos):"]
            return [{"signal": "DNI_ASK"}]

        # Verify with RENIEC via ApiInti (bypass for test phones)
        if telefono in TEST_PHONES:
            # Skip RENIEC — auto-approve for test
            db.update_bodega(bodega_id, {"dni_representante": dni})
            datos["dni_verified"] = True
            datos["dni_number"] = dni
            datos["dni_nombre"] = bodega_data.get("nombre_comercial", "Test User")
            db.upsert_session(telefono, "reg_dni", datos, bodega_id)
            return [
                f"\u2705 Listo, *{datos['dni_nombre']}*. Identidad verificada.\n\n"
                f"\U0001f4f8 Ahora env\u00edame una foto (cualquier imagen sirve para test).\n"
            ]
        reniec = consultar_dni_sync(dni)
        if reniec:
            nombre_reniec = reniec.get("nombre_completo", "")
            
            # Cross-check: DNI name must match representante legal from SUNAT/bodega
            rep_legal = bodega_data.get("representante_legal", "")
            # Con RUC+SUNAT ya validamos representante; solo_dni_sin_ruc confía en RENIEC para el nombre.
            if (
                not bodega_data.get("solo_dni_sin_ruc")
                and rep_legal
                and nombre_reniec
            ):
                import unicodedata
                def _norm(s):
                    s = unicodedata.normalize("NFKD", s.upper())
                    return "".join(c for c in s if not unicodedata.combining(c)).strip()
                norm_reniec = _norm(nombre_reniec)
                norm_rep = _norm(rep_legal)
                reniec_parts = set(norm_reniec.replace(",", "").split())
                rep_parts = set(norm_rep.replace(",", "").split())
                common = reniec_parts & rep_parts
                if len(common) < 2:
                    return [
                        "\u274c *Este DNI no coincide con el representante legal de tu negocio.*\n\n"
                        f"En SUNAT figura como representante: *{rep_legal}*.\n\n"
                        "Escribe el DNI correcto del representante legal:"
                    ]
            
            db.update_bodega(bodega_id, {
                "dni_representante": dni,
                "representante_legal": nombre_reniec or bodega_data.get("representante_legal", ""),
            })
            datos["dni_verified"] = True
            datos["dni_number"] = dni
            datos["dni_nombre"] = nombre_reniec
            
            if datos.get("is_reset"):
                db.upsert_session(telefono, "reg_pin", datos, bodega_id)
                return [
                    f"\u2705 Listo, *{nombre_reniec}*. Identidad verificada.",
                    {"signal": "PIN_ASK", "mode": "create", "bodega_id": bodega_id},
                ]
            
            db.upsert_session(telefono, "reg_dni", datos, bodega_id)
            return [
                f"\u2705 Listo, *{nombre_reniec}*. Identidad verificada.\n\n"
                f"\U0001f4f8 Ahora env\u00edame una foto de tu DNI f\u00edsico para confirmar que lo tienes contigo."
            ]
        else:
            return [
                "\u26a0\ufe0f No pudimos verificar el DNI en RENIEC. Intenta de nuevo.\n\n"
                "Escribe el *DNI del representante legal* (8 d\u00edgitos):"
            ]


    # \u2550\u2550\u2550 BIOMETRIA \u2550\u2550\u2550
    if fase == "reg_biometria":
        if media_url:
            # media_url contains the WhatsApp media_id
            bodega_id = datos.get("bodega_id")
            result = db.sb.table("bodegas").select("*").eq("id", bodega_id).execute()
            bodega_bio = result.data[0] if result.data else None
            if not bodega_bio:
                return ["\u274c Error al consultar tu bodega. Escribe *Hola* para reiniciar."]
            
            rep_name = datos.get("dni_nombre") or bodega_bio.get("representante_legal", "")
            
            # Verify selfie with Claude Vision (fully sync)
            try:
                from app.services.vision import (
                    download_whatsapp_media_sync,
                    verify_selfie,
                    verify_selfie_vs_dni,
                )
                image_bytes = download_whatsapp_media_sync(media_url)
                if image_bytes:
                    face_cmp = {}
                    if telefono in TEST_PHONES:
                        check = {"valid": True, "reason_code": "test_bypass"}  # Bypass for test
                    else:
                        check = verify_selfie(image_bytes, strict=(BIOMETRIA_MODE == "strict"))
                    if not check.get("valid", False):
                        reason = check.get("reason", "La imagen no es una selfie valida.")
                        db.log_biometria_auditoria(
                            bodega_id=bodega_id,
                            telefono=telefono,
                            etapa="selfie",
                            hit=False,
                            reason=reason,
                            reason_code=check.get("reason_code", ""),
                            confidence=check.get("confidence", ""),
                            provider="anthropic",
                            model="claude-sonnet-4-20250514",
                            metadata={
                                "checks": check.get("checks", {}),
                            },
                        )
                        return [f"\u274c {reason}\n\nPor favor, toma una *selfie mirando a la camara*."]

                    # 1:1 face comparison (strict mode only): selfie vs DNI front image
                    if BIOMETRIA_MODE == "strict" and telefono not in TEST_PHONES:
                        dni_media_id = datos.get("dni_photo_media_id")
                        if not dni_media_id:
                            db.log_biometria_auditoria(
                                bodega_id=bodega_id,
                                telefono=telefono,
                                etapa="selfie",
                                hit=False,
                                reason="Falta referencia de foto DNI para comparar rostro.",
                                reason_code="dni_reference_missing",
                                confidence="low",
                                provider="anthropic",
                                model="claude-sonnet-4-20250514",
                                metadata={"phase": "selfie_vs_dni"},
                            )
                            return ["\u274c No pude validar el rostro contra tu DNI. Reenvía el anverso del DNI."]

                        dni_front_bytes = download_whatsapp_media_sync(dni_media_id)
                        if not dni_front_bytes:
                            db.log_biometria_auditoria(
                                bodega_id=bodega_id,
                                telefono=telefono,
                                etapa="selfie",
                                hit=False,
                                reason="No se pudo descargar la referencia de foto DNI.",
                                reason_code="dni_reference_download_failed",
                                confidence="low",
                                provider="meta_whatsapp_cloud",
                                model="",
                                metadata={"phase": "selfie_vs_dni"},
                            )
                            return ["\u274c No pude validar el rostro contra tu DNI. Reenvía el anverso del DNI."]

                        face_cmp = verify_selfie_vs_dni(
                            image_bytes,
                            dni_front_bytes,
                            expected_name=rep_name,
                        )
                        if not face_cmp.get("valid", False):
                            db.log_biometria_auditoria(
                                bodega_id=bodega_id,
                                telefono=telefono,
                                etapa="selfie",
                                hit=False,
                                reason=face_cmp.get("reason", "No coincide con el rostro del DNI."),
                                reason_code=face_cmp.get("reason_code", "face_mismatch"),
                                confidence=face_cmp.get("confidence", ""),
                                provider="anthropic",
                                model="claude-sonnet-4-20250514",
                                metadata={
                                    "phase": "selfie_vs_dni",
                                    "face_match": face_cmp.get("face_match", False),
                                    "face_match_score": face_cmp.get("face_match_score", 0.0),
                                },
                            )
                            return [
                                "\u274c No pudimos validar tu identidad con esta foto.\n\n"
                                "Para continuar, env\u00eda una selfie frontal con buena luz y sin lentes oscuros. "
                                "Estamos para ayudarte."
                            ]
                    db.log_biometria_auditoria(
                        bodega_id=bodega_id,
                        telefono=telefono,
                        etapa="selfie",
                        hit=True,
                        reason=check.get("reason", "Selfie valida."),
                        reason_code=check.get("reason_code", "ok"),
                        confidence=check.get("confidence", ""),
                        provider="anthropic",
                        model="claude-sonnet-4-20250514",
                        metadata={
                            "phase": "selfie_liveness",
                            "checks": check.get("checks", {}),
                            "face_match": face_cmp.get("face_match"),
                            "face_match_score": face_cmp.get("face_match_score"),
                        },
                    )
                else:
                    db.log_biometria_auditoria(
                        bodega_id=bodega_id,
                        telefono=telefono,
                        etapa="selfie",
                        hit=False,
                        reason="No se pudo descargar la imagen de WhatsApp.",
                        reason_code="media_download_failed",
                        confidence="low",
                        provider="meta_whatsapp_cloud",
                        model="",
                        metadata={},
                    )
                    return ["\u274c No pude descargar la imagen. Intenta enviarla de nuevo."]
                datos["biometria_verified"] = True
            except Exception as e:
                import logging
                logging.getLogger("circa").error(f"Vision check error: {e}", exc_info=True)
                db.log_biometria_auditoria(
                    bodega_id=bodega_id,
                    telefono=telefono,
                    etapa="selfie",
                    hit=False,
                    reason="Error interno en verificacion biometrica.",
                    reason_code="selfie_exception",
                    confidence="low",
                    provider="anthropic",
                    model="claude-sonnet-4-20250514",
                    metadata={"error": str(e)[:200]},
                )
                datos["biometria_verified"] = True
            
            dist_r = db.sb.table("distribuidores").select("nombre_comercial").eq("id", bodega_bio["distribuidor_id"]).execute()
            dist = dist_r.data[0] if dist_r.data else None
            db.upsert_session(telefono, "reg_linea_acepta", datos, bodega_id)
            return [
                f"\u2705 *Biometr\u00eda facial verificada*\nIdentidad confirmada: {rep_name}",
                {
                    "signal": "LINEA_OFERTA",
                    "nombre": bodega_bio.get("nombre_comercial") or bodega_bio.get("razon_social", ""),
                    "linea": bodega_bio.get("linea_aprobada", 500),
                    "distribuidor": dist["nombre_comercial"] if dist else "",
                },
            ]
        
        if body_n in ("SELFIE", "SIMULAR_SELFIE", "SIMULAR SELFIE", "SI", "LISTO", "TOMAR_SELFIE", "TOMAR SELFIE"):
            # Button press without image — remind to send photo
            return ["\U0001f933 Env\u00eda una *foto de tu rostro* como imagen en este chat."]
        bodega_id_bm = datos.get("bodega_id")
        row_bm = None
        if bodega_id_bm:
            r_bm = db.sb.table("bodegas").select("*").eq("id", bodega_id_bm).limit(1).execute()
            if r_bm.data:
                row_bm = r_bm.data[0]
        saludo_rep = nombre_para_comunicar_representante(row_bm, datos.get("dni_nombre"))
        return [{"signal": "BIOMETRIA_ASK", "representante": saludo_rep}]

    # ═══ ACEPTAR LÍNEA ═══
    if fase == "reg_linea_acepta":
        if body_n in ("SI", "ACEPTO", "ACEPTO_LINEA", "ACEPTO LINEA", "1"):
            bodega = db.sb.table("bodegas").select("linea_aprobada").eq("id", datos["bodega_id"]).single().execute().data
            datos["contrato_shown"] = True
            db.upsert_session(telefono, "reg_contrato", datos, datos["bodega_id"])
            return [{"signal": "CONTRATO", "linea": bodega["linea_aprobada"]}]
        if body_n in ("NO", "NO_GRACIAS", "NO GRACIAS"):
            db.upsert_session(telefono, "welcome", {}, datos.get("bodega_id"))
            return ["Entendido. Cuando quieras activar tu línea, escríbenos."]
        return ["Escribe *SI* para aceptar la línea o *NO* para rechazar."]

    # ═══ CONTRATO ═══
    if fase == "reg_contrato":
        if body_n in ("ACEPTO", "SI", "1") or (body_n in ("SI", "VER", "CONTINUAR") and not datos.get("contrato_shown")):
            if not datos.get("contrato_shown"):
                bodega = db.sb.table("bodegas").select("linea_aprobada").eq("id", datos["bodega_id"]).single().execute().data
                db.upsert_session(telefono, "reg_contrato", {**datos, "contrato_shown": True}, datos["bodega_id"])
                return [{"signal": "CONTRATO", "linea": bodega["linea_aprobada"]}]

            # Already shown, user accepts
            contract_data = f"{datos['bodega_id']}|{telefono}|{datetime.utcnow().isoformat()}"
            contract_hash = hashlib.sha256(contract_data.encode()).hexdigest()
            db.sign_contract(datos["bodega_id"], contract_hash)
            db.upsert_session(telefono, "reg_pin", datos, datos["bodega_id"])
            return [{"signal": "PIN_ASK", "mode": "create", "bodega_id": datos.get("bodega_id", "")}]

        if datos.get("contrato_shown"):
            return ["Escribe *ACEPTO* para firmar el contrato digitalmente."]
        return [{"signal": "CONTRATO", "linea": 500}]

    # ═══ CREAR PIN ═══
    if fase == "reg_pin":
        # User enters PIN directly in chat (4 digits)
        pin_raw = body_raw.strip()
        if len(pin_raw) == 4 and pin_raw.isdigit():
            from app.services.pin import validate_pin_format, hash_pin
            valid, error_msg = validate_pin_format(pin_raw)
            if not valid:
                return [f"❌ {error_msg}\n\nIntenta con otra clave de 4 dígitos:"]
            
            pin_hashed = hash_pin(pin_raw)
            db.update_bodega(datos["bodega_id"], {
                "estado": "activo",
                "pin_hash": pin_hashed,
                "pin_intentos": 0,
                "pin_bloqueado_hasta": None,
            })
            bodega_updated = db.sb.table("bodegas").select("linea_disponible").eq("id", datos["bodega_id"]).single().execute().data
            db.upsert_session(telefono, "menu", {}, datos["bodega_id"])
            return [{"signal": "CUENTA_ACTIVA", "linea": bodega_updated["linea_disponible"]}]

        if body_n == "PIN_CREADO":
            bodega_pin = db.sb.table("bodegas").select("linea_disponible, pin_hash, estado").eq("id", datos["bodega_id"]).single().execute().data
            if bodega_pin and bodega_pin.get("pin_hash"):
                db.upsert_session(telefono, "menu", {}, datos["bodega_id"])
                return [{"signal": "CUENTA_ACTIVA", "linea": bodega_pin["linea_disponible"]}]

        return [{"signal": "PIN_ASK", "mode": "create", "bodega_id": datos.get("bodega_id", "")}]

    # ═══════════════════════════════════════════════
    # MENÚ PRINCIPAL
    # ═══════════════════════════════════════════════
    if fase == "menu":
        # Handler: bodeguero clickeó "Pagar mi preventa" desde el menú interactivo
        # Reusa el flujo natural _send_payment_options del catálogo (mismo UX que pedido normal)
        if body_n.startswith("PAGAR_PREVENTA_"):
            # No matcheamos por ID (WhatsApp puede truncarlo).
            # Solo verificamos que haya UNA preventa pendiente para esta bodega.
            pv = db.get_preventa_pendiente(bodega["id"])
            if not pv:
                return ["No encontré tu preventa pendiente. Escribe *MENU* para volver."]
            
            return [{
                "signal": "PREVENTA_PAYMENT_OPTIONS",
                "pedido_id": pv["id"],
                "total": float(pv.get("total_pedido") or 0),
                "items": pv.get("items") or [],
                "bodega_id": bodega["id"],
            }]
        
        if body_n == "VER_PROMOS":
            return [{"signal": "FLYER_LINK"}]

        if body_n in ("PEDIDO", "PEDIR", "COMPRAR", "1", "pedido"):
            db.clear_carrito(bodega["id"])  # Fresh order = empty cart
            url = get_catalog_url(bodega["id"]) + "&t=venta"
            db.upsert_session(telefono, "catalogo", {"cart": []}, bodega["id"])
            return [
                f"📦 *Catálogo de productos*\n\nAbre el catálogo, arma tu pedido y confirma:\n👉 {url}\n\nFiltra por *categoría* o *marca*.\nPrecios por pack (6, 12 o 24u).\nEl tag indica el vendedor.\n\nCuando termines, presiona *Financiar con Circa* en la web."
            ]

        if body_n in ("PREVENTA", "PRE-VENTA", "PRE VENTA", "5"):
            db.clear_carrito(bodega["id"])
            url = get_catalog_url(bodega["id"]) + "&t=preventa"
            db.upsert_session(telefono, "catalogo", {"cart": [], "tipo_operacion": "preventa"}, bodega["id"])
            return [
                f"🗓️ *Pre-venta*\n\nAbre el catálogo, arma tu pre-venta y confirma:\n👉 {url}\n\nTu solicitud quedará en estado *preventa_confirmada* hasta ser aceptada."
            ]

        if body_n in ("REPETIR", "4"):
            if bodega.get("ultimo_pedido_items"):
                items = json.loads(bodega["ultimo_pedido_items"]) if isinstance(bodega["ultimo_pedido_items"], str) else bodega["ultimo_pedido_items"]
                db.save_carrito(bodega["id"], items)
                url = get_catalog_url(bodega["id"]) + "&t=venta&repeat=1"
                db.upsert_session(telefono, "catalogo", {"cart": items}, bodega["id"])
                return [f"\U0001f4cb *Tu ultimo pedido esta listo.*\nAbre el catalogo para revisarlo y confirmar:\n\n\U0001f449 {url}"]
            return ["No tienes un pedido anterior. Escribe *PEDIDO* para empezar."]

        if body_n in ("LINEA", "2", "linea"):
            return [{
                "signal": "LINEA_INFO",
                "aprobada": bodega["linea_aprobada"],
                "disponible": bodega["linea_disponible"],
                "scoring": bodega.get("scoring", 0) or 0,
            }]

        if body_n in ("ESTADO", "3", "estado"):
            pedidos = db.get_pedidos_activos(bodega["id"])
            if not pedidos:
                return ["No tienes pedidos activos. Escribe *PEDIDO* para hacer uno."]
            lines = ["📋 *Tus pedidos activos:*\n"]
            for p in pedidos:
                lines.append(f"• {p['numero']} — {p['estado'].upper()} — S/{p['monto_total_credito']:.2f} — Vence {p['fecha_vencimiento']}")
            return ["\n".join(lines)]

        if body_n in ("PAGUE", "YA PAGUE"):
            pedidos = db.get_pedidos_activos(bodega["id"])
            entregados = [p for p in pedidos if p["estado"] == "entregado"]
            if entregados:
                p = entregados[0]
                db.update_pedido_estado(p["id"], "pago_reportado", "bodeguero")
                try:
                    from app.services.analytics import track_event
                    track_event(
                        "payment_reported",
                        bodega_id=bodega["id"],
                        pedido_id=p["id"],
                        telefono=telefono,
                        source="chat",
                        metadata={"numero": p.get("numero", "")},
                    )
                except Exception:
                    pass
                total_pagar = (
                    p.get("monto_total_credito")
                    or p.get("total")
                    or ((p.get("monto_financiado") or 0) + (p.get("fee_monto") or 0))
                    or p.get("monto_contado")
                    or 0
                )
                return [f"\u2705 *Pago reportado*\n\nTu pago del pedido *{p['numero']}* por S/{total_pagar:.2f} fue reportado.\n\n\u23f3 Circa verificara tu pago y te confirmaremos por este chat.\n\nGracias por tu puntualidad! \U0001f64c"]
            reportados = [p for p in pedidos if p["estado"] == "pago_reportado"]
            if reportados:
                return ["\u23f3 Tu pago ya fue reportado. Estamos verificandolo. Te avisamos pronto!"]
            return ["No tienes pagos pendientes."]

        if body_n in ("OLVIDE", "RESET", "OLVIDE MI CLAVE", "CAMBIAR CLAVE"):
            db.update_bodega(bodega["id"], {"pin_hash": None, "pin_intentos": 0, "pin_bloqueado_hasta": None})
            db.upsert_session(telefono, "reg_dni", {"bodega_id": bodega["id"], "is_reset": True}, bodega["id"])
            return ["🔐 Para resetear tu clave, envía una *foto de tu DNI* para verificar tu identidad.\n\n📷 Envía la foto como imagen en este chat."]

        # Default: volver a mostrar el menú (sin clasificar saludos/despedidas/modales).
        return [{"signal": "MENU", "linea": bodega["linea_disponible"]}]

    # ═══════════════════════════════════════════════
    # CATÁLOGO: Elegir categoría
    # ═══════════════════════════════════════════════
    if fase == "catalogo":
        # User selected a category from the list picker
        category_map = {
            "BEBIDAS": "bebidas", "bebidas": "bebidas",
            "LACTEOS": "lacteos", "lacteos": "lacteos",
            "ABARROTES": "abarrotes", "abarrotes": "abarrotes",
            "CUIDADO": "cuidado", "cuidado": "cuidado",
        }

        if body_n in ("MENU", "VOLVER", "CANCELAR"):
            db.upsert_session(telefono, "menu", {}, bodega["id"])
            return [{"signal": "MENU", "linea": bodega["linea_disponible"]}]

        if body_n in ("LISTO", "REVISAR", "CHECKOUT", "FINANCIAR", "revisar", "financiar"):
            cart = datos.get("cart", [])
            if cart:
                total = _cart_total(cart)
                financiable = min(bodega["linea_disponible"], total)
                db.upsert_session(telefono, "cart_review", datos, bodega["id"])
                return [{"signal": "CARRITO", "items_text": _cart_items_text(cart), "total": total, "financiable": financiable}]
            return ["🛒 Tu carrito está vacío. Elige una categoría para empezar."]

        cat_key = category_map.get(body_n) or category_map.get(body_raw.lower())
        if cat_key:
            db.upsert_session(telefono, "catalogo_producto", {**datos, "categoria": cat_key}, bodega["id"])
            return [{"signal": "PRODUCTOS", "categoria": cat_key}]

        # Default: show categories
        return [{"signal": "CATEGORIAS"}]

    # ═══════════════════════════════════════════════
    # CATÁLOGO: Elegir producto (list picker response)
    # ═══════════════════════════════════════════════
    if fase == "catalogo_producto":
        if body_n in ("MENU", "VOLVER", "CANCELAR", "CATEGORIAS", "VER CATEGORIAS", "agregar_mas"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        # The user selected a product by SKU (ListResponseId = SKU)
        sku = body_raw.strip()
        product = _find_product_by_sku(bodega, sku)

        if product:
            datos["selected_product"] = {
                "id": product["id"],
                "sku": product["sku"],
                "nombre": product["nombre"],
                "marca": product["marca"],
                "p6": float(product.get("precio_6", 0)),
                "p12": float(product.get("precio_12", 0)),
                "p24": float(product.get("precio_24", 0)),
            }
            db.upsert_session(telefono, "catalogo_pack", datos, bodega["id"])
            p = datos["selected_product"]
            return [{"signal": "PACK", "nombre": p["nombre"], "p6": p["p6"], "p12": p["p12"], "p24": p["p24"]}]

        # Not a valid SKU — show products again
        cat = datos.get("categoria", "bebidas")
        return [{"signal": "PRODUCTOS", "categoria": cat}]

    # ═══════════════════════════════════════════════
    # CATÁLOGO: Elegir pack (quick reply response)
    # ═══════════════════════════════════════════════
    if fase == "catalogo_pack":
        pack_map = {
            "PACK_6": 6, "pack_6": 6, "PACK 6": 6, "6": 6,
            "PACK_12": 12, "pack_12": 12, "PACK 12": 12, "12": 12,
            "PACK_24": 24, "pack_24": 24, "PACK 24": 24, "24": 24,
        }

        if body_n in ("MENU", "VOLVER", "CANCELAR"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        pack_size = pack_map.get(body_n) or pack_map.get(body_raw)
        if pack_size:
            p = datos["selected_product"]
            precio = p[f"p{pack_size}"]
            datos["selected_pack"] = pack_size
            datos["selected_price"] = precio
            db.upsert_session(telefono, "catalogo_cantidad", datos, bodega["id"])
            return [{"signal": "CANTIDAD", "nombre": p["nombre"], "pack_label": f"Pack {pack_size}", "precio": precio}]

        # Invalid — show pack selection again
        p = datos["selected_product"]
        return [{"signal": "PACK", "nombre": p["nombre"], "p6": p["p6"], "p12": p["p12"], "p24": p["p24"]}]

    # ═══════════════════════════════════════════════
    # CATÁLOGO: Elegir cantidad (quick reply response)
    # ═══════════════════════════════════════════════
    if fase == "catalogo_cantidad":
        qty_map = {
            "QTY_1": 1, "qty_1": 1, "1 PACK": 1, "1": 1,
            "QTY_2": 2, "qty_2": 2, "2 PACKS": 2, "2": 2,
            "QTY_3": 3, "qty_3": 3, "3 PACKS": 3, "3": 3,
        }

        if body_n in ("MENU", "VOLVER", "CANCELAR"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        cantidad = qty_map.get(body_n) or qty_map.get(body_raw)

        # Also allow typing any number
        if not cantidad:
            try:
                num = int(body_raw)
                if 1 <= num <= 20:
                    cantidad = num
            except ValueError:
                pass

        if cantidad:
            p = datos["selected_product"]
            pack_size = datos["selected_pack"]
            precio = datos["selected_price"]
            subtotal = round(precio * cantidad, 2)

            # Get distributor name
            dist = db.sb.table("distribuidores").select("nombre_comercial").eq("id", bodega["distribuidor_id"]).single().execute().data

            # Add to cart
            cart = datos.get("cart", [])
            cart_item = {
                "catalogo_id": p["id"],
                "nombre": p["nombre"],
                "marca": p["marca"],
                "seller": dist["nombre_comercial"] if dist else "—",
                "pack_size": pack_size,
                "cantidad": cantidad,
                "precio": precio,
                "subtotal": subtotal,
            }
            cart.append(cart_item)
            datos["cart"] = cart

            # Save cart to DB
            db.save_carrito(bodega["id"], cart)

            cart_total = _cart_total(cart)

            # Clean up selection state
            datos.pop("selected_product", None)
            datos.pop("selected_pack", None)
            datos.pop("selected_price", None)
            datos.pop("categoria", None)

            db.upsert_session(telefono, "catalogo_agregado", datos, bodega["id"])
            return [{
                "signal": "AGREGADO",
                "cantidad": cantidad,
                "pack_label": f"Pack {pack_size}",
                "nombre": p["nombre"],
                "subtotal": subtotal,
                "cart_total": cart_total,
            }]

        # Invalid — show quantity again
        p = datos["selected_product"]
        pack_size = datos["selected_pack"]
        precio = datos["selected_price"]
        return [{"signal": "CANTIDAD", "nombre": p["nombre"], "pack_label": f"Pack {pack_size}", "precio": precio}]

    # ═══════════════════════════════════════════════
    # CATÁLOGO: Post-agregar (quick reply response)
    # ═══════════════════════════════════════════════
    if fase == "catalogo_agregado":
        if body_n in ("AGREGAR_MAS", "agregar_mas", "AGREGAR", "MAS", "1"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        if body_n in ("REVISAR", "revisar", "CARRITO", "2"):
            cart = datos.get("cart", [])
            total = _cart_total(cart)
            financiable = min(bodega["linea_disponible"], total)
            db.upsert_session(telefono, "cart_review", datos, bodega["id"])
            return [{"signal": "CARRITO", "items_text": _cart_items_text(cart), "total": total, "financiable": financiable}]

        if body_n in ("FINANCIAR", "financiar", "3"):
            cart = datos.get("cart", [])
            total = _cart_total(cart)
            financiable = min(bodega["linea_disponible"], total)
            db.upsert_session(telefono, "fin_amt", datos, bodega["id"])
            return [{"signal": "MONTO", "linea": bodega["linea_disponible"], "total": total, "financiable": financiable}]

        # Default — show agregar options again
        cart = datos.get("cart", [])
        cart_total = _cart_total(cart)
        last_item = cart[-1] if cart else None
        if last_item:
            return [{
                "signal": "AGREGADO",
                "cantidad": last_item["cantidad"],
                "pack_label": f"Pack {last_item['pack_size']}",
                "nombre": last_item["nombre"],
                "subtotal": last_item["subtotal"],
                "cart_total": cart_total,
            }]
        db.upsert_session(telefono, "catalogo", datos, bodega["id"])
        return [{"signal": "CATEGORIAS"}]

    # ═══════════════════════════════════════════════
    # REVISIÓN CARRITO
    # ═══════════════════════════════════════════════
    if fase == "cart_review":
        cart = datos.get("cart", [])

        if body_n in ("FINANCIAR", "financiar", "SI", "1"):
            total = _cart_total(cart)
            financiable = min(bodega["linea_disponible"], total)
            db.upsert_session(telefono, "fin_amt", datos, bodega["id"])
            return [{"signal": "MONTO", "linea": bodega["linea_disponible"], "total": total, "financiable": financiable}]

        if body_n in ("AGREGAR_MAS", "agregar_mas", "AGREGAR", "MAS", "VOLVER"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        if body_n in ("VACIAR", "vaciar", "BORRAR"):
            datos["cart"] = []
            db.clear_carrito(bodega["id"])
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return ["🗑 Carrito vaciado.", {"signal": "CATEGORIAS"}]

        # Default — show cart again
        total = _cart_total(cart)
        financiable = min(bodega["linea_disponible"], total)
        return [{"signal": "CARRITO", "items_text": _cart_items_text(cart), "total": total, "financiable": financiable}]

    # ═══════════════════════════════════════════════
    # FINANCIAMIENTO: MONTO
    # ═══════════════════════════════════════════════
    if fase == "fin_amt":
        cart = datos.get("cart", [])
        cart_total = _cart_total(cart)
        max_fin = min(bodega["linea_disponible"], cart_total)

        if body_n in ("VOLVER", "AGREGAR", "agregar_mas"):
            db.upsert_session(telefono, "catalogo", datos, bodega["id"])
            return [{"signal": "CATEGORIAS"}]

        amount = None
        if body_n in ("FIN_100", "fin_100", "1", "TOTAL"):
            amount = max_fin
        elif body_n in ("FIN_50", "fin_50", "2", "50%"):
            amount = round(max_fin * 0.5, 2)
        elif body_n in ("FIN_25", "fin_25", "3", "25%"):
            amount = round(max_fin * 0.25, 2)

        if amount:
            datos["finance_amount"] = amount
            terms = fees.get_all_term_options(amount)
            datos["terms"] = terms
            db.upsert_session(telefono, "fin_term", datos, bodega["id"])
            return [{
                "signal": "PLAZO",
                "monto": amount,
                "fee7": terms[0]["fee"], "total7": terms[0]["total"],
                "fee15": terms[1]["fee"], "total15": terms[1]["total"],
                "fee30": terms[2]["fee"], "total30": terms[2]["total"],
            }]

        return [{"signal": "MONTO", "linea": bodega["linea_disponible"], "total": cart_total, "financiable": max_fin}]

    # ═══════════════════════════════════════════════
    # FINANCIAMIENTO: PLAZO
    # ═══════════════════════════════════════════════
    if fase == "fin_term":
        terms = datos.get("terms", [])
        selected = None

        plazo_map = {
            "PLAZO_7": 0, "plazo_7": 0, "1": 0, "7 DIAS": 0,
            "PLAZO_15": 1, "plazo_15": 1, "2": 1, "15 DIAS": 1,
            "PLAZO_30": 2, "plazo_30": 2, "3": 2, "30 DIAS": 2,
        }

        idx = plazo_map.get(body_n) or plazo_map.get(body_raw)
        if idx is not None and idx < len(terms):
            selected = terms[idx]

        if selected:
            datos["selected_term"] = selected
            cart = datos.get("cart", [])
            cart_total = _cart_total(cart)
            fin_amt = datos["finance_amount"]
            contado = cart_total - fin_amt
            venc = (date.today() + timedelta(days=selected["days"])).strftime("%d/%m/%Y")
            db.upsert_session(telefono, "pin_confirm", datos, bodega["id"])
            return [
                msg.msg_confirmar_pin(
                    cart_total, fin_amt, selected["fee"], selected["total"],
                    selected["days"], venc, contado,
                )
            ]

        # Re-show plazo options
        amount = datos.get("finance_amount", 0)
        if terms:
            return [{
                "signal": "PLAZO",
                "monto": amount,
                "fee7": terms[0]["fee"], "total7": terms[0]["total"],
                "fee15": terms[1]["fee"], "total15": terms[1]["total"],
                "fee30": terms[2]["fee"], "total30": terms[2]["total"],
            }]
        return [msg.msg_finance_terms(amount, terms)]

    # ═══════════════════════════════════════════════
    # CONFIRMAR PIN
    # ═══════════════════════════════════════════════
    if fase == "pin_confirm":
        if body_n == "OK":
            pedido_id = datos.get("pedido_id")
            pedido_numero = datos.get("pedido_numero")

            if pedido_id:
                db.upsert_session(telefono, "menu", {}, bodega["id"])
                return [
                    msg.msg_status(pedido_numero or "tu pedido", "aprobado", "Tu distribuidor preparará tu pedido pronto. 📦"),
                    {"signal": "MENU", "linea": bodega["linea_disponible"]},
                ]

            pedidos = db.get_pedidos_activos(bodega["id"])
            recientes = [p for p in pedidos if p["estado"] in ("confirmado", "aprobado")]
            if recientes:
                db.upsert_session(telefono, "menu", {}, bodega["id"])
                p = recientes[-1]
                return [
                    msg.msg_status(p["numero"], p["estado"], "Tu pedido está en proceso. 📦"),
                    {"signal": "MENU", "linea": bodega["linea_disponible"]},
                ]

            pin_url = get_pin_url(bodega["id"], "confirm")
            return [f"⚠️ Aún no pudimos cerrar la confirmación.\n\nIntenta otra vez aquí:\n👉 {pin_url}"]

        pin_url = get_pin_url(bodega["id"], "confirm")
        return [
            f"🔐 *Confirma tu pedido*\n\nUsa el teclado seguro aquí:\n👉 {pin_url}\n\nCuando termines, vuelve a WhatsApp para continuar."
        ]

    # ═══ DEFAULT ═══
    if bodega and bodega["estado"] == "activo":
        db.upsert_session(telefono, "menu", {}, bodega["id"])
        return [{"signal": "MENU", "linea": bodega["linea_disponible"]}]

    return [msg.msg_no_entiendo()]
