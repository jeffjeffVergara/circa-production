"""
Selfie verification using Claude Vision API.
Checks if the image is a valid selfie (real person, looking at camera).
"""
import os
import httpx
import base64
import logging

logger = logging.getLogger("circa.vision")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


async def download_whatsapp_media(media_id: str) -> bytes | None:
    """Download media from WhatsApp Cloud API."""
    token = os.getenv("META_ACCESS_TOKEN", "")
    phone_id = os.getenv("META_PHONE_NUMBER_ID", "1076586305533033")
    
    async with httpx.AsyncClient(timeout=15) as client:
        # Step 1: Get media URL
        r = await client.get(
            f"https://graph.facebook.com/v23.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            logger.error(f"Media URL fetch failed: {r.text}")
            return None
        media_url = r.json().get("url")
        if not media_url:
            return None
        
        # Step 2: Download the actual file
        r2 = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        if r2.status_code != 200:
            logger.error(f"Media download failed: {r2.status_code}")
            return None
        
        return r2.content


def verify_selfie_sync(image_bytes: bytes) -> dict:
    """
    Use Claude Vision to verify a selfie.
    
    Returns:
        {
            "valid": True/False,
            "reason": "explanation",
            "confidence": "high/medium/low"
        }
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY set, skipping vision check")
        return {"valid": True, "reason": "Verificacion omitida (sin API key)", "confidence": "low"}
    
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
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
                                "You are a KYC selfie verification system. "
                                "Analyze this image and determine if it is a valid selfie for identity verification. "
                                "Check: 1) Is there exactly one human face clearly visible? "
                                "2) Is the person looking at the camera? "
                                "3) Is it a real photo (not a photo of a photo, not a screen, not a drawing)? "
                                "4) Is the face well-lit and not obscured? "
                                "Respond in this exact JSON format only, no other text: "
                                '{"valid": true/false, "reason": "brief explanation in Spanish", "confidence": "high/medium/low"}'
                            ),
                        },
                    ],
                }],
            },
            timeout=20,
        )
        
        if r.status_code != 200:
            logger.error(f"Claude Vision error: {r.status_code} {r.text}")
            return {"valid": True, "reason": "Error en verificacion, se acepta por defecto", "confidence": "low"}
        
        response_text = r.json()["content"][0]["text"].strip()
        
        # Parse JSON response
        import json
        # Clean markdown if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        
        result = json.loads(response_text)
        logger.info(f"Selfie verification: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Selfie verify error: {e}", exc_info=True)
        return {"valid": True, "reason": "Error en verificacion, se acepta por defecto", "confidence": "low"}
