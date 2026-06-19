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

from app.config import ANTHROPIC_VISION_MODEL, FACE_MATCH_MIN_SCORE, FACE_MATCH_SCORE_OVERRIDE

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
                                "Eres un verificador biometrico KYC estricto. "
                                "Evalua SOLO esta imagen y decide si es una selfie valida para onboarding. "
                                "Reglas estrictas: "
                                "1) Debe haber exactamente un rostro humano. "
                                "2) Rostro frontal, mirada a camara, ojos visibles y abiertos. "
                                "3) Rostro centrado y visible (aprox >=30% de la imagen). "
                                "4) Imagen nitida y bien iluminada, sin obstrucciones fuertes del rostro. "
                                "5) Debe parecer captura real del momento; si parece pantalla, impresion, foto de otra foto, deepfake o manipulacion, INVALIDA. "
                                "6) Si hay duda razonable, responde valid=false. "
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
            result.setdefault("reason_code", "ok" if result.get("valid") else "uncertain")
            result.setdefault("reason", "Verificacion completada.")
            result.setdefault("confidence", "medium")
            result.setdefault("checks", {})
            result["valid"] = bool(result.get("valid", False))
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
                                "Eres un sistema KYC estricto para validar el anverso de DNI peruano. "
                                "Analiza SOLO esta imagen. "
                                "Objetivo: verificar documento fisico real, extraer DNI/nombre legibles y comparar contra valores esperados. "
                                f"expected_dni={expected_dni}; expected_name={expected_name}. "
                                "Reglas estrictas: "
                                "1) Debe parecer un DNI peruano fisico real (no pantalla, no captura, no foto de otra foto, no impresion, no edicion). "
                                "2) Si el numero de DNI no es legible o hay ambiguedad de digitos, valid=false. "
                                "3) Extrae dni_found y name_found solo si son legibles; si no, devuelve cadena vacia. "
                                "4) matches_expected_dni=true solo si dni_found coincide EXACTAMENTE con expected_dni. "
                                "5) Para nombre, compara normalizado (sin tildes, mayusculas, sin signos, orden flexible por tokens). "
                                "6) Si hay duda razonable, responde valid=false y confidence=low. "
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

            # Defensive normalization in case model omits fields or returns noisy text.
            dni_found_raw = str(result.get("dni_found", "") or "")
            dni_found = "".join(ch for ch in dni_found_raw if ch.isdigit())[:8]
            result["dni_found"] = dni_found

            def _norm_name(s: str) -> str:
                s = unicodedata.normalize("NFKD", (s or "").upper())
                s = "".join(c for c in s if not unicodedata.combining(c))
                s = re.sub(r"[^A-Z0-9\s]", " ", s)
                return re.sub(r"\s+", " ", s).strip()

            expected_name_n = _norm_name(expected_name)
            name_found_n = _norm_name(str(result.get("name_found", "") or ""))
            expected_tokens = set(expected_name_n.split())
            found_tokens = set(name_found_n.split())
            common = expected_tokens & found_tokens

            matches_expected_dni = (dni_found == expected_dni)
            # Name match is optional when OCR cannot read a name, but strict when it can.
            if name_found_n:
                matches_expected_name = len(common) >= 2 or expected_name_n == name_found_n
            else:
                matches_expected_name = False

            # Final acceptance prioritizes exact DNI match and document validity.
            valid_flag = bool(result.get("valid", False))
            matches_expected = matches_expected_dni and (matches_expected_name or not name_found_n)

            result.setdefault("reason_code", "ok" if valid_flag and matches_expected else "uncertain")
            result["matches_expected_dni"] = matches_expected_dni
            result["matches_expected_name"] = matches_expected_name
            result["matches_expected"] = matches_expected
            result["valid"] = valid_flag and matches_expected_dni
            result.setdefault("confidence", "medium")
            result.setdefault("reason", "Verificacion completada.")

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
                                "Eres un verificador de identidad peruano (KYC). Comparas si la MISMA persona aparece en dos imagenes.\n"
                                "Imagen 1 = selfie reciente del usuario. Imagen 2 = anverso del DNI (foto oficial, suele ser mas antigua).\n"
                                f"Nombre de referencia (opcional, no es prueba definitiva): {expected_name or '(no indicado)'}.\n\n"
                                "CONTEXTO IMPORTANTE (reduce falsos negativos):\n"
                                "- El DNI puede tener anos de antiguedad: envejecimiento, cambio de peso, barba/bigote, peinado, "
                                "cejas o piel NO implican persona distinta si la estructura facial y rasgos clave coinciden.\n"
                                "- Lentes: si solo una foto tiene lentes, o distinto tipo de montura, NO descartes por eso. "
                                "Compara forma de cara, nariz, boca, distancia entre ojos, menton y arco cigomatico cuando sea visible.\n"
                                "- Iluminacion, angulo, compresion JPEG, reflejos en el plastico del DNI y baja resolucion del carnet "
                                "pueden alterar apariencia; ante duda razonable, favorece 'misma persona'.\n\n"
                                "Cuando marcar face_match=false (personas distintas):\n"
                                "- Solo si hay evidencia fuerte de dos identidades distintas (proporciones incompatibles, rasgos "
                                "estructurales claramente diferentes), no por maquillaje leve, lentes, barba o foto vieja.\n\n"
                                "face_match_score en [0,1]: 0.85+ casi seguro misma persona; 0.65-0.84 probable misma persona con variacion temporal/accesorios; "
                                "0.45-0.64 duda; por debajo de 0.45 probable distinta.\n"
                                "valid=true si rostros legibles en ambas y (misma persona con confianza media-alta). "
                                "Si una cara es ilegible o el documento no muestra rostro usable, valid=false.\n\n"
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
        # Decisión en backend: no depender solo del booleano "valid" del modelo (puede contradecir el score).
        score_ok = score >= min_s
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
