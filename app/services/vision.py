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
    FACE_MATCH_MIN_SCORE,
    FACE_MATCH_SCORE_OVERRIDE,
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
                                "Rechaza (valid=false) solo si: no hay rostro, hay varias personas, o evidencia "
                                "clara de pantalla/foto de foto/deepfake. "
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
_SELFIE_SOFT_REJECT_CODES = frozenset({
    "off_angle",
    "eyes_not_visible",
    "low_quality",
    "occluded_face",
    "uncertain",
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
        elif single_face and reason_code in _SELFIE_SOFT_REJECT_CODES:
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


def verify_selfie_vs_dni(selfie_bytes: bytes, dni_front_bytes: bytes, expected_name: str = "") -> dict:
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
                                "Eres un verificador de identidad peruano (KYC) en un flujo WhatsApp. "
                                "Tu tarea es decidir si la MISMA persona aparece en dos imágenes muy distintas.\n\n"
                                "Imagen 1 = selfie reciente tomada con celular (ahora).\n"
                                "Imagen 2 = foto del rostro en el anverso del DNI peruano (foto oficial del documento).\n"
                                f"Nombre de referencia (opcional): {expected_name or '(no indicado)'}.\n\n"
                                "CONTEXTO CRÍTICO — documento vs selfie (reduce falsos negativos):\n"
                                "- La foto del DNI suele tener años de antigüedad: envejecimiento, más o menos peso, "
                                "barba/bigote, peinado, maquillaje, arrugas o piel NO significan persona distinta "
                                "si la estructura ósea y rasgos principales coinciden.\n"
                                "- El carnet tiene baja resolución, tinte del plástico, reflejos, desgaste e impresión "
                                "offset; la selfie tiene otra luz, ángulo y compresión JPEG. Eso es NORMAL.\n"
                                "- Lentes: si solo una imagen tiene lentes, o monturas distintas, NO rechaces por eso. "
                                "Compara forma de cara, nariz, boca, distancia entre ojos, mentón y pómulos.\n"
                                "- No exijas que ambas fotos se vean iguales en expresión, edad aparente ni iluminación.\n\n"
                                "Cuándo marcar face_match=false (personas distintas):\n"
                                "- Solo con evidencia fuerte de dos identidades (proporciones faciales incompatibles, "
                                "rasgos estructurales claramente diferentes). No por foto vieja, lentes, ángulo o calidad.\n\n"
                                "face_match_score en [0,1] (calibrado documento vs selfie):\n"
                                "- 0.75+ muy probable misma persona\n"
                                "- 0.55-0.74 probable misma persona con variación temporal/accesorios/calidad DNI\n"
                                "- 0.40-0.54 duda; si no hay contradicción fuerte, favorece misma persona\n"
                                "- <0.40 probable persona distinta\n\n"
                                "valid=true si hay rostro usable en ambas imágenes y es razonable que sea la misma persona "
                                "(confianza media basta). Ante duda razonable por diferencia de edad o calidad del DNI, "
                                "favorece valid=true y face_match=true con score acorde.\n"
                                "valid=false solo si falta rostro legible en selfie o en DNI, o hay evidencia clara "
                                "de personas distintas.\n\n"
                                "Responde SOLO JSON valido (sin markdown):\n"
                                '{"valid": true/false, "reason_code": "ok|face_mismatch|no_face_in_selfie|no_face_in_dni|low_quality|uncertain", '
                                '"reason": "explicacion breve en espanol", "face_match": true/false, '
                                '"face_match_score": 0.0, "confidence": "low|medium|high"}'
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
        result["face_match"] = bool(result.get("face_match", False))
        try:
            result["face_match_score"] = float(result.get("face_match_score", 0.0))
        except Exception:
            result["face_match_score"] = 0.0
        score = result["face_match_score"]
        min_s = FACE_MATCH_MIN_SCORE
        override_s = FACE_MATCH_SCORE_OVERRIDE
        reason_code = str(result.get("reason_code", "") or "uncertain")
        effective_min = min_s
        if reason_code in ("uncertain", "low_quality"):
            effective_min = min(min_s, 0.48)
        score_ok = score >= effective_min
        strong_score = score >= override_s
        result["valid"] = score_ok and (result["face_match"] or strong_score)
        result.setdefault("reason_code", "ok" if result["valid"] else "uncertain")
        result.setdefault("reason", "Verificacion facial completada.")
        result.setdefault("confidence", "medium")
        return result

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
