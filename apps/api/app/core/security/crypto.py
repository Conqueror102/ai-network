"""AES-GCM envelope for message bodies, with key-id prefix for rotation (08 §5)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _keys() -> dict[str, bytes]:
    s = get_settings()
    keys = {kid: bytes.fromhex(k.get_secret_value()) for kid, k in s.msg_enc_old_keys.items()}
    keys[s.msg_enc_kid] = bytes.fromhex(s.msg_enc_key.get_secret_value())
    return keys


def encrypt(plaintext: str) -> str:
    s = get_settings()
    nonce = os.urandom(12)
    ct = AESGCM(_keys()[s.msg_enc_kid]).encrypt(nonce, plaintext.encode(), None)
    return f"{s.msg_enc_kid}:{base64.b64encode(nonce + ct).decode()}"


def decrypt(token: str) -> str:
    kid, _, blob = token.partition(":")
    raw = base64.b64decode(blob)
    return AESGCM(_keys()[kid]).decrypt(raw[:12], raw[12:], None).decode()
