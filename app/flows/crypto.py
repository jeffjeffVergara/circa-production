"""
WhatsApp Flows — Encryption/Decryption for Dynamic Endpoint.

Meta encrypts all data sent to dynamic Flow endpoints using AES-GCM.
The AES key is encrypted with the business's RSA public key.
This module handles the full decrypt/encrypt cycle.

Reference: https://developers.facebook.com/docs/whatsapp/flows/guides/implementingyourflowendpoint
"""
import base64
import json
import hashlib
import hmac
import logging
import os
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("circa.flows.crypto")


def _get_private_key():
    """Load RSA private key from environment."""
    pem = os.getenv("FLOW_PRIVATE_KEY", "")
    if not pem:
        raise ValueError("FLOW_PRIVATE_KEY not set")
    # Handle escaped newlines from env vars
    pem = pem.replace("\\n", "\n")
    return serialization.load_pem_private_key(pem.encode(), password=None)


def decrypt_request(encrypted_flow_data_b64: str, encrypted_aes_key_b64: str, initial_vector_b64: str) -> tuple[dict, bytes, bytes]:
    """
    Decrypt incoming WhatsApp Flow request.
    
    Args:
        encrypted_flow_data_b64: Base64-encoded AES-encrypted payload
        encrypted_aes_key_b64: Base64-encoded RSA-encrypted AES key
        initial_vector_b64: Base64-encoded initialization vector
    
    Returns:
        (decrypted_data: dict, aes_key: bytes, iv: bytes)
    """
    private_key = _get_private_key()
    
    # Decode base64
    encrypted_flow_data = base64.b64decode(encrypted_flow_data_b64)
    encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)
    iv = base64.b64decode(initial_vector_b64)
    
    # Decrypt AES key with RSA private key
    aes_key = private_key.decrypt(
        encrypted_aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    
    # Decrypt payload with AES-GCM
    # AES-GCM tag is appended to ciphertext (last 16 bytes)
    aesgcm = AESGCM(aes_key)
    decrypted_data = aesgcm.decrypt(iv, encrypted_flow_data, None)
    
    # Parse JSON
    flow_data = json.loads(decrypted_data.decode("utf-8"))
    
    logger.info(f"Decrypted flow request: screen={flow_data.get('screen')}, action={flow_data.get('action')}")
    
    return flow_data, aes_key, iv


def encrypt_response(response_data: dict, aes_key: bytes, iv: bytes) -> str:
    """
    Encrypt response back to WhatsApp.
    
    Args:
        response_data: Dict to send back to the Flow
        aes_key: Same AES key from the request
        iv: Same IV from the request (flipped for response)
    
    Returns:
        Base64-encoded encrypted response
    """
    # Flip the IV for the response
    flipped_iv = bytes(~b & 0xFF for b in iv)
    
    # Encrypt with AES-GCM
    aesgcm = AESGCM(aes_key)
    plaintext = json.dumps(response_data).encode("utf-8")
    encrypted = aesgcm.encrypt(flipped_iv, plaintext, None)
    
    return base64.b64encode(encrypted).decode("utf-8")


def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify the request signature from Meta (optional but recommended).
    
    Args:
        payload: Raw request body bytes
        signature: X-Hub-Signature-256 header value
    
    Returns:
        True if signature is valid
    """
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_secret:
        logger.warning("META_APP_SECRET not set, skipping signature verification")
        return True
    
    expected = hmac.new(
        app_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Signature format: "sha256=<hex>"
    actual = signature.replace("sha256=", "") if signature else ""
    
    return hmac.compare_digest(expected, actual)
