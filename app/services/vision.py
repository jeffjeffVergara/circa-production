"""
Selfie verification using Claude Vision API.
"""
import os
import httpx
import base64
import json
import logging

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


def verify_selfie(image_bytes: bytes) -> dict:
    """
    Use Claude Vision to verify a selfie.
    Returns: {"valid": bool, "reason": str, "confidence": str}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY, skipping vision")
        return {"valid": True, "reason": "Sin API key", "confidence": "low"}
    
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
                "model": "claude-sonnet-4-20250514",
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
                                "Eres un sistema estricto de verificacion biometrica KYC. "
                                "Analiza esta imagen con criterios ESTRICTOS. "
                                "La selfie es VALIDA solo si cumple TODOS estos requisitos: "
                                "1) Hay exactamente UN rostro humano claramente visible. "
                                "2) La persona mira DIRECTAMENTE a la camara (no de perfil, no mirando a otro lado). "
                                "3) El rostro esta centrado y ocupa al menos 30% de la imagen. "
                                "4) Es una foto real tomada en el momento (no foto de foto, no pantalla, no impresion). "
                                "5) El rostro esta bien iluminado, nitido y sin obstrucciones (lentes oscuros, mascarilla, gorro que tape la cara). "
                                "6) Los ojos estan abiertos y visibles. "
                                "Si CUALQUIER requisito falla, responde valid=false. "
                                "Responde SOLO en formato JSON, sin otro texto: "
                                '{"valid": true, "reason": "Selfie valida: rostro frontal, bien iluminado", "confidence": "high"} '
                                "o "
                                '{"valid": false, "reason": "motivo especifico en espanol", "confidence": "high"}'
                            ),
                        },
                    ],
                }],
            },
            timeout=25,
        )
        
        if r.status_code != 200:
            logger.error(f"Claude Vision error: {r.status_code} {r.text[:200]}")
            return {"valid": True, "reason": "Error verificacion", "confidence": "low"}
        
        text = r.json()["content"][0]["text"].strip()
        logger.info(f"Claude Vision raw: {text}")
        
        # Clean markdown
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if text.startswith("{"):
            result = json.loads(text)
            logger.info(f"Selfie result: {result}")
            return result
        
        logger.warning(f"Unexpected vision response: {text}")
        return {"valid": True, "reason": "Respuesta inesperada", "confidence": "low"}
        
    except Exception as e:
        logger.error(f"Selfie verify error: {e}", exc_info=True)
        return {"valid": True, "reason": "Error verificacion", "confidence": "low"}
