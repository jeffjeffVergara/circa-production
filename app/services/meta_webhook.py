"""
Meta WhatsApp Cloud API — Webhook Handler.

Replaces Twilio's webhook. Meta sends webhooks in a different format.

Incoming message structure:
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "messages": [{
          "from": "51987654321",
          "type": "text|interactive|image|...",
          "text": {"body": "Hola"},
          ...
        }],
        "contacts": [{"profile": {"name": "Juan"}, "wa_id": "51987654321"}]
      }
    }]
  }]
}
"""
import logging
import hmac
import hashlib
import os

logger = logging.getLogger("circa.meta.webhook")


def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    """
    Verify webhook subscription (GET request from Meta).
    Meta sends: hub.mode, hub.verify_token, hub.challenge
    We return the challenge if the token matches.
    """
    verify_token = os.getenv("META_VERIFY_TOKEN", "circa-webhook-verify-2026")
    
    if mode == "subscribe" and token == verify_token:
        logger.info("Webhook verified successfully")
        return challenge
    
    logger.warning(f"Webhook verification failed: mode={mode}")
    return None


def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify the X-Hub-Signature-256 header from Meta.
    """
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_secret:
        logger.warning("META_APP_SECRET not set, skipping signature verification")
        return True
    
    expected = "sha256=" + hmac.new(
        app_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature or "")


def parse_incoming(body: dict) -> list[dict]:
    """
    Parse incoming webhook body and extract messages.
    
    Returns list of parsed messages:
    [{
        "from": "51987654321",       # Phone number (no +)
        "name": "Juan Pérez",        # Contact name
        "type": "text",              # text, interactive, image, button, order, ...
        "body": "Hola",              # Text content
        "message_id": "wamid.xxx",   # Message ID (for read receipts)
        "timestamp": "1234567890",
        
        # For interactive messages:
        "button_id": "PEDIDO",       # Button reply ID
        "button_text": "Hacer pedido",
        "list_id": "item_1",         # List selection ID
        "list_title": "Item 1",
        
        # For Flow responses:
        "flow_token": "abc123",
        "flow_data": {...},          # Submitted flow data
        
        # For images:
        "media_id": "123456",
        "media_url": None,           # Need to fetch separately
        
        # For order messages (catalog cart):
        "order": {...},              # Cart order data
    }]
    """
    messages = []
    
    if body.get("object") != "whatsapp_business_account":
        return messages
    
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            
            # Skip status updates (delivery receipts, etc.)
            if "messages" not in value:
                # Could be a status update
                for status in value.get("statuses", []):
                    logger.debug(f"Status update: {status.get('status')} for {status.get('id')}")
                continue
            
            # Get contact info
            contacts = {c["wa_id"]: c.get("profile", {}).get("name", "")
                       for c in value.get("contacts", [])}
            
            for msg in value.get("messages", []):
                parsed = {
                    "from": msg.get("from", ""),
                    "name": contacts.get(msg.get("from", ""), ""),
                    "type": msg.get("type", ""),
                    "message_id": msg.get("id", ""),
                    "timestamp": msg.get("timestamp", ""),
                    "body": "",
                    "button_id": None,
                    "button_text": None,
                    "list_id": None,
                    "list_title": None,
                    "flow_token": None,
                    "flow_data": None,
                    "media_id": None,
                    "order": None,
                }
                
                msg_type = msg.get("type", "")
                
                # ── Text message ──
                if msg_type == "text":
                    parsed["body"] = msg.get("text", {}).get("body", "")
                
                # ── Interactive response (button or list) ──
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    int_type = interactive.get("type", "")
                    
                    if int_type == "button_reply":
                        reply = interactive.get("button_reply", {})
                        parsed["button_id"] = reply.get("id", "")
                        parsed["button_text"] = reply.get("title", "")
                        parsed["body"] = reply.get("id", "")  # Use ID as body for state machine
                    
                    elif int_type == "list_reply":
                        reply = interactive.get("list_reply", {})
                        parsed["list_id"] = reply.get("id", "")
                        parsed["list_title"] = reply.get("title", "")
                        parsed["body"] = reply.get("id", "")
                    
                    elif int_type == "nfm_reply":
                        # Flow response
                        nfm = interactive.get("nfm_reply", {})
                        parsed["flow_token"] = nfm.get("name", "")
                        try:
                            parsed["flow_data"] = nfm.get("response_json", {})
                            if isinstance(parsed["flow_data"], str):
                                import json
                                parsed["flow_data"] = json.loads(parsed["flow_data"])
                        except Exception:
                            parsed["flow_data"] = {}
                        parsed["body"] = "__FLOW_RESPONSE__"
                
                # ── Button (quick reply from template) ──
                elif msg_type == "button":
                    button = msg.get("button", {})
                    parsed["button_id"] = button.get("payload", "")
                    parsed["button_text"] = button.get("text", "")
                    parsed["body"] = button.get("payload", "")
                
                # ── Image ──
                elif msg_type == "image":
                    image = msg.get("image", {})
                    parsed["media_id"] = image.get("id", "")
                    parsed["body"] = image.get("caption", "") or "__IMAGE__"
                
                # ── Order (from catalog/cart) ──
                elif msg_type == "order":
                    parsed["order"] = msg.get("order", {})
                    parsed["body"] = "__ORDER__"
                
                # ── Location ──
                elif msg_type == "location":
                    loc = msg.get("location", {})
                    parsed["body"] = f"__LOCATION__{loc.get('latitude', '')},{loc.get('longitude', '')}"
                
                # ── Unsupported ──
                else:
                    parsed["body"] = f"__UNSUPPORTED_{msg_type.upper()}__"
                    logger.info(f"Unsupported message type: {msg_type}")
                
                logger.info(
                    f"📩 From: {parsed['from']} | Type: {parsed['type']} | "
                    f"Body: '{parsed['body'][:50]}' | Button: {parsed['button_id']}"
                )
                
                messages.append(parsed)
    
    return messages


async def download_media(media_id: str) -> bytes | None:
    """
    Download media file from Meta's servers.
    First get the URL, then download the file.
    """
    import httpx
    
    access_token = os.getenv("META_ACCESS_TOKEN", "")
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: Get media URL
            r = await client.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}",
                headers=headers
            )
            if r.status_code != 200:
                logger.error(f"Failed to get media URL: {r.text}")
                return None
            
            media_url = r.json().get("url", "")
            
            # Step 2: Download the file
            r = await client.get(media_url, headers=headers)
            if r.status_code != 200:
                return None
            
            return r.content
            
    except Exception as e:
        logger.error(f"Failed to download media {media_id}: {e}")
        return None
