"""
Selfie verification using Claude Vision API.
"""
import os
import httpx
import base64
import json
import logging
import re
import unicodedata

from app.config import (
    ANTHROPIC_VISION_MODEL,
    DNI_PHOTO_RELAXED,
    FACE_MATCH_DNI_GRAYSCALE_RELAXED,
    FACE_MATCH_MIN_SCORE,
    FACE_MATCH_SCORE_OVERRIDE,
    FACE_MATCH_TRUST_DNI_CHAIN,
    SELFIE_LIVENESS_RELAXED,
)

logger = logging.getLogger("circa.vision")


def download_whatsapp_media_sync(media_id: str) -> bytes | None:
    """Download media from WhatsApp Cloud API (sync)."""
    token = os.getenv("META_ACCESS_TOKEN", "")
    
    # Step 1: Get media URL
    r = httpx.get(
        f"https://graph.facebook.com/v23.0/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if r.status_code != 200:
        logger.error(f"Media URL fetch failed: {r.text}")
        return None
    media_url = r.json().get("url")
    if not media_url:
        return None
    
    # Step 2: Download the actual file
    r2 = httpx.get(
        media_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if r2.status_code != 200:
        logger.error(f"Media download failed: {r2.status_code}")
        return None
    
    logger.info(f"Downloaded media {media_id}: {len(r2.content)} bytes")
    return r2.content


def verify_selfie(image_bytes: bytes, strict: bool = True) -> dict:
    """
    Use Claude Vision to verify a selfie.
    Returns: {"valid": bool, "reason": str, "confidence": str}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY, skipping vision")
        if not strict:
            return {"valid": True, "reason": "Sin API key", "confidence": "low", "reason_code": "legacy_no_api_key"}
        return {
            "valid": False,
            "reason_code": "no_api_key",
            "reason": "No se pudo validar la selfie en este momento.",
            "confidence": "low",
        }
    
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_VISION_MODEL,
                "max_tokens": 200,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Eres un verificador KYC pragmático para onboarding por WhatsApp. "
                                "Evalua SOLO esta imagen (selfie reciente del usuario). "
                                "CONTEXTO CLAVE: en el siguiente paso esta selfie se comparará con la foto del "
                                "anverso del DNI peruano (foto oficial del documento, suele ser de hace años, "
                                "baja resolución, impresa en plástico, distinta iluminación). "
                                "Por eso NO exijas calidad de selfie de alta seguridad ni pose de estudio. "
                                "Objetivo de este paso: confirmar que hay UN rostro humano real y reconocible "
                                "en una foto típica de celular. "
                                "Acepta (valid=true) si: "
                                "- Hay un rostro humano visible (aunque no esté perfectamente centrado). "
                                "- Ángulo leve, lentes, sombra, compresión JPEG o calidad media son normales. "
                                "- Ojos no perfectamente abiertos o rostro parcialmente cubierto por cabello/lentes "
                                "NO invalidan si el rostro es identificable. "
                                "Rechaza (valid=false) SOLO si: no hay ningún rostro humano, hay varias personas "
                                "claramente distintas, o evidencia muy fuerte de pantalla/foto de foto. "
                                "En caso de duda, valid=true. "
                                "Responde SOLO JSON valido, sin markdown ni texto adicional, con esta estructura exacta: "
                                '{"valid": true/false, "reason_code": "ok|no_face|multiple_faces|off_angle|eyes_not_visible|low_quality|occluded_face|screen_capture_suspected|photo_of_photo_suspected|spoof_suspected|uncertain", '
                                '"reason": "explicacion breve en espanol", '
                                '"checks": {"single_face": true/false, "frontal_pose": true/false, "eyes_visible": true/false, "well_lit": true/false, "no_spoof_signals": true/false}, '
                                '"confidence": "low|medium|high"}'
                            ),
                        },
                    ],
                }],
            },
            timeout=25,
        )
        
        if r.status_code != 200:
            logger.error(f"Claude Vision error: {r.status_code} {r.text[:200]}")
            if not strict:
                return {"valid": True, "reason": "Error verificacion", "confidence": "low", "reason_code": "legacy_provider_error"}
            return {
                "valid": False,
                "reason_code": "provider_error",
                "reason": "No se pudo validar la selfie en este momento.",
                "confidence": "low",
            }
        
        text = r.json()["content"][0]["text"].strip()
        logger.info(f"Claude Vision raw: {text}")
        
        # Clean markdown
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if text.startswith("{"):
            result = json.loads(text)
            result = _finalize_selfie_result(result)
            logger.info(f"Selfie result: {result}")
            return result
        
        logger.warning(f"Unexpected vision response: {text}")
        if not strict:
            return {"valid": True, "reason": "Respuesta inesperada", "confidence": "low", "reason_code": "legacy_invalid_response"}
        return {
            "valid": False,
            "reason_code": "invalid_response",
            "reason": "No se pudo validar la selfie en este momento.",
            "confidence": "low",
        }
        
    except Exception as e:
        logger.error(f"Selfie verify error: {e}", exc_info=True)
        if not strict:
            return {"valid": True, "reason": "Error verificacion", "confidence": "low", "reason_code": "legacy_exception"}
        return {
            "valid": False,
            "reason_code": "exception",
            "reason": "No se pudo validar la selfie en este momento.",
            "confidence": "low",
        }



_DNI_HARD_REJECT_CODES = frozenset({"not_dni", "tampering_suspected"})
_SELFIE_HARD_REJECT_CODES = frozenset({
    "no_face",
    "multiple_faces",
    "screen_capture_suspected",
    "photo_of_photo_suspected",
    "spoof_suspected",
})
_SELFIE_SOFT_REJECT_CODES = frozenset({
    "off_angle",
    "eyes_not_visible",
    "low_quality",
    "occluded_face",
    "uncertain",
    "invalid_response",
    "provider_error",
    "exception",
})


def _finalize_selfie_result(result: dict) -> dict:
    result.setdefault("reason_code", "ok" if result.get("valid") else "uncertain")
    result.setdefault("reason", "Verificacion completada.")
    result.setdefault("confidence", "medium")
    result.setdefault("checks", {})
    reason_code = str(result.get("reason_code", "") or "uncertain")
    checks = result.get("checks") or {}
    model_valid = bool(result.get("valid", False))
    single_face = checks.get("single_face", True)

    if SELFIE_LIVENESS_RELAXED:
        if model_valid:
            accepted = True
        elif single_face and reason_code not in _SELFIE_HARD_REJECT_CODES:
            accepted = True
            reason_code = "ok"
        elif reason_code in _SELFIE_SOFT_REJECT_CODES:
            accepted = True
            reason_code = "ok"
        else:
            accepted = False
    else:
        accepted = model_valid

    result["valid"] = accepted
    result["reason_code"] = reason_code if accepted else reason_code
    return result


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _dni_digits_match(found: str, expected: str, *, relaxed: bool) -> bool:
    if not expected or len(expected) != 8:
        return False
    if found == expected:
        return True
    if expected in found or found in expected:
        return True
    if not relaxed or len(found) != 8:
        return False
    mismatches = sum(a != b for a, b in zip(found, expected))
    return mismatches <= 1


def _finalize_dni_photo_result(result: dict, expected_dni: str, expected_name: str) -> dict:
    dni_found_raw = str(result.get("dni_found", "") or "")
    dni_found = "".join(ch for ch in dni_found_raw if ch.isdigit())[:8]
    result["dni_found"] = dni_found

    expected_name_n = _norm_name(expected_name)
    name_found_n = _norm_name(str(result.get("name_found", "") or ""))
    common = set(expected_name_n.split()) & set(name_found_n.split())

    matches_expected_dni = _dni_digits_match(
        dni_found, expected_dni, relaxed=DNI_PHOTO_RELAXED,
    )
    if name_found_n:
        matches_expected_name = len(common) >= 2 or expected_name_n == name_found_n
    else:
        matches_expected_name = None

    reason_code = str(result.get("reason_code", "") or "uncertain")
    model_valid = bool(result.get("valid", False))

    if DNI_PHOTO_RELAXED:
        # Prioridad: número correcto aunque haya dudas de ángulo/reflejo/rotación.
        if matches_expected_dni and reason_code not in _DNI_HARD_REJECT_CODES:
            accepted = True
            reason_code = "ok"
        elif model_valid and reason_code not in _DNI_HARD_REJECT_CODES:
            accepted = True
        else:
            accepted = False
    else:
        accepted = model_valid and matches_expected_dni

    result["matches_expected_dni"] = matches_expected_dni
    result["matches_expected_name"] = matches_expected_name
    result["matches_expected"] = matches_expected_dni and (
        matches_expected_name is not False
    )
    result["valid"] = accepted
    result["reason_code"] = reason_code if accepted else (
        reason_code if reason_code != "ok" else "dni_mismatch"
    )
    result.setdefault("confidence", "medium")
    result.setdefault("reason", "Verificacion completada.")
    return result


def verify_dni_photo(image_bytes: bytes, expected_dni: str, expected_name: str) -> dict:
    """
    Use Claude Vision to verify a DNI card photo.
    Checks: real card, extracts number, compares with expected.
    Returns: {"valid": bool, "reason": str, "dni_found": str}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"valid": True, "reason": "Sin API key", "dni_found": ""}
    
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_VISION_MODEL,
                "max_tokens": 300,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Eres un verificador KYC pragmático para fotos de DNI peruano enviadas por WhatsApp. "
                                "Analiza SOLO esta imagen. "
                                f"expected_dni={expected_dni}; expected_name={expected_name}. "
                                "CONTEXTO: fotos de celular suelen tener reflejo en el plástico, compresión, "
                                "ligera rotación, documento al revés o parcialmente tapado por los dedos. "
                                "Eso NO invalida el documento si el anverso del DNI es reconocible. "
                                "Objetivo: confirmar que es un DNI peruano (anverso) y extraer el número cuando sea legible. "
                                "Reglas: "
                                "1) valid=true si el anverso del DNI peruano es reconocible y el número coincide con expected_dni "
                                "(aunque la foto esté rotada, con reflejo o calidad media). "
                                "2) Extrae dni_found con los 8 dígitos si puedes leerlos; si no, cadena vacía. "
                                "3) El nombre es opcional; no rechaces solo por nombre ilegible. "
                                "4) Rechaza (valid=false) solo si claramente NO es un DNI, el número contradice expected_dni, "
                                "o hay evidencia fuerte de manipulación del número. "
                                "5) NO rechaces por photo_of_photo_suspected o screen_capture_suspected si el DNI físico "
                                "es visible y el número coincide. "
                                "Responde SOLO JSON valido, sin markdown ni texto adicional, con esta estructura exacta: "
                                '{"valid": true/false, "reason_code": "ok|not_dni|illegible|dni_mismatch|name_mismatch|screen_capture_suspected|photo_of_photo_suspected|tampering_suspected|uncertain", '
                                '"reason": "explicacion breve en espanol", "dni_found": "numero extraido o vacio", "name_found": "nombre extraido o vacio", '
                                '"matches_expected_dni": true/false, "matches_expected_name": true/false, "matches_expected": true/false, '
                                '"confidence": "low|medium|high"}'
                            ),
                        },
                    ],
                }],
            },
            timeout=25,
        )
        
        if r.status_code != 200:
            logger.error(f"Claude DNI check error: {r.status_code}")
            return {"valid": True, "reason": "Error verificacion", "dni_found": ""}
        
        text = r.json()["content"][0]["text"].strip()
        logger.info(f"Claude DNI raw: {text}")
        
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if text.startswith("{"):
            result = json.loads(text)
            result = _finalize_dni_photo_result(result, expected_dni, expected_name)
            logger.info(f"DNI photo result: {result}")
            return result
        
        return {"valid": True, "reason": "Respuesta inesperada", "dni_found": ""}
        
    except Exception as e:
        logger.error(f"DNI photo verify error: {e}", exc_info=True)
        return {"valid": True, "reason": "Error verificacion", "dni_found": ""}


_SKIN_TONE_INFERENCE_RE = re.compile(
    r"piel\s+m[aá]s|tono\s+de\s+piel|tez\s+|afrodescend|asi[aá]tic|mestiz|etnia|fenotip|racial|"
    r"moren[ao]|piel\s+clar|piel\s+osc|oscuro.*clar|clar.*oscuro|color\s+de\s+piel|labios\s+m[aá]s\s+grues",
    re.IGNORECASE,
)
_GEOMETRY_HALFTONE_ARTIFACT_RE = re.compile(
    r"mand[ií]bula\s+m[aá]s\s+(ancha|estrecha|redondeada|definida)|"
    r"nariz\s+m[aá]s\s+(ancha|delgada|definida|achatada|prominente)|"
    r"rostro\s+m[aá]s\s+(ancho|alargado|delgado)|p[oó]mulos\s+m[aá]s\s+prominentes|"
    r"proporci[oó]n.*distinta|geometr[ií]a.*(diferente|incompatible|marcada)|"
    r"estructura\s+craneal.*distinta|morfolog[ií]a.*distinta|"
    r"proporciones\s+faciales.*no\s+coinciden|no\s+se\s+(identifican|encontraron).*anclas|"
    r"epic[aá]ntic|pliegue\s+epic",
    re.IGNORECASE,
)


def _reason_uses_skin_tone_or_ethnicity(reason: str) -> bool:
    """El DNI peruano es monocromo; rechazos basados en tono/etnia son inválidos."""
    return bool(_SKIN_TONE_INFERENCE_RE.search(reason or ""))


def _reason_suggests_halftone_geometry_artifact(reason: str) -> bool:
    """El halftone del DNI distorsiona mandíbula/nariz; el modelo suele alucinar diferencias."""
    return bool(_GEOMETRY_HALFTONE_ARTIFACT_RE.search(reason or ""))


def _accept_grayscale_face_match(result: dict, reason_code: str, reason: str) -> dict:
    result["face_match"] = True
    result["face_match_score"] = max(float(result.get("face_match_score", 0.0)), FACE_MATCH_MIN_SCORE)
    result["valid"] = True
    result["reason_code"] = "ok"
    result["reason"] = reason
    result.setdefault("confidence", "medium")
    return result


def _finalize_face_match_result(result: dict, *, dni_chain_verified: bool = False) -> dict:
    result["face_match"] = bool(result.get("face_match", False))
    try:
        result["face_match_score"] = float(result.get("face_match_score", 0.0))
    except Exception:
        result["face_match_score"] = 0.0

    score = result["face_match_score"]
    reason = str(result.get("reason", "") or "")
    reason_code = str(result.get("reason_code", "") or "uncertain")

    anchors = result.get("matching_anchors") or []
    min_anchors = 1 if (FACE_MATCH_DNI_GRAYSCALE_RELAXED and dni_chain_verified) else 2
    if isinstance(anchors, list) and len(anchors) >= min_anchors:
        logger.info("Face match accepted via %d structural anchors: %s", len(anchors), anchors[:4])
        return _accept_grayscale_face_match(
            result,
            reason_code,
            f"Coincidencia por señales estructurales: {', '.join(str(a) for a in anchors[:3])}.",
        )

    _no_face_codes = frozenset({"no_face_in_selfie", "no_face_in_dni"})
    if (
        FACE_MATCH_DNI_GRAYSCALE_RELAXED
        and FACE_MATCH_TRUST_DNI_CHAIN
        and dni_chain_verified
        and not result["face_match"]
        and reason_code not in _no_face_codes
    ):
        logger.warning(
            "Face match rejected but full DNI chain trusted; overriding (code=%s score=%.2f)",
            reason_code,
            score,
        )
        return _accept_grayscale_face_match(
            result,
            reason_code,
            "Coincidencia aceptada: identidad ya validada con RENIEC y documento; "
            "la foto del DNI en gris no permite comparación facial fiable.",
        )

    if (
        not result["face_match"]
        and reason_code == "face_mismatch"
        and _reason_uses_skin_tone_or_ethnicity(reason)
    ):
        logger.warning(
            "Face match rejection used skin tone/ethnicity from grayscale DNI; overriding: %s",
            reason[:120],
        )
        return _accept_grayscale_face_match(
            result,
            reason_code,
            "Coincidencia aceptada: la foto del DNI es en escala de grises y no permite "
            "inferir tono de piel ni etnia; se comparan rasgos estructurales.",
        )

    if (
        FACE_MATCH_DNI_GRAYSCALE_RELAXED
        and not result["face_match"]
        and reason_code == "face_mismatch"
        and _reason_suggests_halftone_geometry_artifact(reason)
        and score >= 0.0
    ):
        logger.warning(
            "Face match rejection likely halftone geometry artifact; overriding (score=%.2f): %s",
            score,
            reason[:120],
        )
        return _accept_grayscale_face_match(
            result,
            reason_code,
            "Coincidencia aceptada: el halftone y la iluminación plana del DNI suelen "
            "distorsionar mandíbula y nariz; no implican personas distintas.",
        )

    min_s = FACE_MATCH_MIN_SCORE
    override_s = FACE_MATCH_SCORE_OVERRIDE
    effective_min = min(min_s, 0.28) if FACE_MATCH_DNI_GRAYSCALE_RELAXED else min_s
    if reason_code in ("uncertain", "low_quality", "face_mismatch"):
        effective_min = min(effective_min, 0.25)
    if dni_chain_verified and FACE_MATCH_DNI_GRAYSCALE_RELAXED:
        effective_min = min(effective_min, 0.20)
    score_ok = score >= effective_min
    strong_score = score >= override_s
    result["valid"] = score_ok and (result["face_match"] or strong_score)
    result["reason_code"] = "ok" if result["valid"] else reason_code
    result.setdefault("reason", "Verificacion facial completada.")
    result.setdefault("confidence", "medium")
    return result


def verify_selfie_vs_dni(
    selfie_bytes: bytes,
    dni_front_bytes: bytes,
    expected_name: str = "",
    *,
    dni_chain_verified: bool = False,
) -> dict:
    """
    Compare selfie face against DNI front face using Claude Vision.
    Returns:
      {
        "valid": bool,
        "reason_code": str,
        "reason": str,
        "face_match": bool,
        "face_match_score": float,
        "confidence": "low|medium|high"
      }
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "valid": False,
            "reason_code": "no_api_key",
            "reason": "No se pudo validar coincidencia facial en este momento.",
            "face_match": False,
            "face_match_score": 0.0,
            "confidence": "low",
        }

    selfie_b64 = base64.standard_b64encode(selfie_bytes).decode("utf-8")
    dni_b64 = base64.standard_b64encode(dni_front_bytes).decode("utf-8")

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_VISION_MODEL,
                "max_tokens": 420,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": selfie_b64,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": dni_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Eres un verificador de identidad peruano (KYC) en WhatsApp. "
                                "Decide si la MISMA persona aparece en dos imágenes muy distintas.\n\n"
                                "Imagen 1 = selfie a color reciente (celular, puede tener barba incipiente, lentes, hoodie).\n"
                                "Imagen 2 = foto del rostro en el anverso del DNI peruano (oficial, impresa en el documento).\n"
                                f"Nombre de referencia: {expected_name or '(no indicado)'}.\n"
                                + (
                                    "CONTEXTO DEL FLUJO: el número de DNI y el anverso del documento YA fueron "
                                    "validados en el paso anterior. Tu rol es confirmar que la selfie muestra "
                                    "a la misma persona titular del DNI, no buscar diferencias artificiales.\n"
                                    "Si hay un rostro humano claro en ambas imágenes y no hay prueba fuerte "
                                    "de otra persona, responde face_match=true y valid=true.\n\n"
                                    if dni_chain_verified
                                    else ""
                                )
                                + "REGLA 1 — DNI SIEMPRE EN ESCALA DE GRISES:\n"
                                "- La foto del DNI es monocroma (blanco y negro / halftone). NO indica color de piel real.\n"
                                "- PROHIBIDO rechazar o describir etnias, tono de piel, tez o raza.\n"
                                "- Las zonas oscuras del halftone en mejillas, nariz y barbilla NO son piel morena: "
                                "son sombras de impresión. No interpretes contraste gris como persona distinta.\n\n"
                                "REGLA 2 — EL DNI DISTORSIONA LA GEOMETRÍA (falsos negativos frecuentes):\n"
                                "- Foto oficial: iluminación plana frontal, baja resolución, puntos halftone, holograma encima.\n"
                                "- Eso hace que mandíbula, nariz y pómulos PAREZCAN más anchos o más estrechos que en la selfie 3D.\n"
                                "- NO rechaces por 'mandíbula más ancha en DNI' o 'nariz más delgada en selfie' si hay otras señales de match.\n"
                                "- Barba o bigote en selfie ausentes en DNI antiguo = NORMAL. Cambio de peso o edad = NORMAL.\n\n"
                                "REGLA 3 — BUSCA ANCLAS DE MISMA PERSONA (prioridad alta):\n"
                                "- Lunares/marcas en mismas zonas (nariz, mejilla, frente).\n"
                                "- Misma distancia entre ojos, misma forma de orejas, mismo contorno de labios.\n"
                                "- Misma estructura general de frente-nariz-mentón aunque el DNI se vea más 'aplanado'.\n"
                                "- Si encuentras 2+ anclas compatibles, face_match=true aunque la calidad del DNI sea mala.\n\n"
                                "REGLA 4 — CUÁNDO RECHAZAR (muy restrictivo):\n"
                                "- Solo si NO hay rostro legible en selfie o en DNI (reason_code no_face_in_*).\n"
                                "- NO rechaces por diferencias de mandíbula, nariz, edad, peso, lentes o halftone.\n\n"
                                "face_match_score [0,1] (sé MUY generoso; DNI gris vs selfie color):\n"
                                "- 0.50+ misma persona | 0.35-0.49 probable misma persona | 0.20-0.34 duda → face_match=true\n"
                                "- <0.20 solo si claramente son dos personas distintas con rostros legibles en ambas\n\n"
                                "DEFAULT: si hay un rostro en cada imagen, face_match=true y valid=true salvo prueba "
                                "contundente de otra persona.\n"
                                "En reason cita solo anclas estructurales observadas; nunca etnia ni tono de piel.\n\n"
                                "Responde SOLO JSON valido (sin markdown):\n"
                                '{"valid": true/false, "reason_code": "ok|face_mismatch|no_face_in_selfie|no_face_in_dni|low_quality|uncertain", '
                                '"reason": "explicacion breve en espanol", "face_match": true/false, '
                                '"face_match_score": 0.0, "matching_anchors": ["ancla1", "ancla2"], '
                                '"confidence": "low|medium|high"}'
                            ),
                        },
                    ],
                }],
            },
            timeout=30,
        )

        if r.status_code != 200:
            logger.error(f"Claude face match error: {r.status_code}")
            return {
                "valid": False,
                "reason_code": "provider_error",
                "reason": "No se pudo validar coincidencia facial en este momento.",
                "face_match": False,
                "face_match_score": 0.0,
                "confidence": "low",
            }

        text = r.json()["content"][0]["text"].strip()
        logger.info(f"Claude face-match raw: {text}")
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not text.startswith("{"):
            return {
                "valid": False,
                "reason_code": "invalid_response",
                "reason": "Respuesta inesperada del verificador facial.",
                "face_match": False,
                "face_match_score": 0.0,
                "confidence": "low",
            }

        result = json.loads(text)
        return _finalize_face_match_result(result, dni_chain_verified=dni_chain_verified)

    except Exception as e:
        logger.error(f"Selfie vs DNI verify error: {e}", exc_info=True)
        return {
            "valid": False,
            "reason_code": "exception",
            "reason": "No se pudo validar coincidencia facial en este momento.",
            "face_match": False,
            "face_match_score": 0.0,
            "confidence": "low",
        }
