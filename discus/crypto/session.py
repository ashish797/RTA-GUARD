"""
RTA-GUARD Crypto — Session Tokens

PQC-protected session tokens using ML-KEM key exchange.
Session IDs are wrapped with PQC for confidentiality.
"""
import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .config import CryptoConfig, KeyPurpose
from .hybrid import HybridCrypto, HybridKeySet
from .keys import KeyManager

logger = logging.getLogger("discus.crypto.session")


@dataclass
class SecureSessionToken:
    """A session token with PQC protection."""
    session_id: str
    created_at: float
    expires_at: float
    kem_ciphertext: bytes       # ML-KEM ciphertext wrapping the session key
    encrypted_payload: bytes     # AES-encrypted session metadata
    nonce: bytes
    node_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "kem_ct": base64.b64encode(self.kem_ciphertext).decode(),
            "payload": base64.b64encode(self.encrypted_payload).decode(),
            "nonce": base64.b64encode(self.nonce).decode(),
            "node_id": self.node_id,
        }

    def to_token_string(self) -> str:
        """Encode as a compact token string."""
        data = json.dumps(self.to_dict(), separators=(",", ":"))
        return base64.urlsafe_b64encode(data.encode()).decode()

    @classmethod
    def from_token_string(cls, token_str: str) -> "SecureSessionToken":
        """Decode from token string."""
        data = json.loads(base64.urlsafe_b64decode(token_str))
        return cls(
            session_id=data["session_id"],
            created_at=data["created_at"],
            expires_at=data["expires_at"],
            kem_ciphertext=base64.b64decode(data["kem_ct"]),
            encrypted_payload=base64.b64decode(data["payload"]),
            nonce=base64.b64decode(data["nonce"]),
            node_id=data.get("node_id", ""),
        )

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class SessionTokenManager:
    """
    Creates and validates PQC-protected session tokens.

    Token structure:
    1. Generate random AES key per session
    2. Wrap AES key with ML-KEM using recipient's public key
    3. Encrypt session metadata with AES
    4. Package as compact token string
    """

    def __init__(self, key_manager: KeyManager):
        self.key_mgr = key_manager
        self.hybrid = HybridCrypto(key_manager.config)
        self.keys: Optional[HybridKeySet] = None

    def initialize(self):
        """Load or generate session keys."""
        self.keys = self.key_mgr.get_or_generate(KeyPurpose.SESSIONS)

    def create_token(self, session_id: str, ttl_seconds: int = 3600,
                     node_id: str = "") -> SecureSessionToken:
        """Create a PQC-protected session token."""
        if not self.keys:
            self.initialize()

        # Generate random AES session key
        from .classical import ClassicalCrypto
        session_key = ClassicalCrypto.generate_aes_key()

        # Wrap session key with ML-KEM
        kem_ct, shared_secret = self.hybrid.key_exchange(self.keys.pqc_kem.public_key)

        # Encrypt session metadata
        payload = json.dumps({
            "session_id": session_id,
            "key": base64.b64encode(session_key).decode(),
            "node_id": node_id,
        }).encode()

        nonce, encrypted = ClassicalCrypto.aes_encrypt(payload, session_key)

        return SecureSessionToken(
            session_id=session_id,
            created_at=time.time(),
            expires_at=time.time() + ttl_seconds,
            kem_ciphertext=kem_ct,
            encrypted_payload=encrypted,
            nonce=nonce,
            node_id=node_id,
        )

    def validate_token(self, token: SecureSessionToken) -> Dict[str, Any]:
        """Validate a session token."""
        if not self.keys:
            self.keys = self.key_mgr.load_keys(KeyPurpose.SESSIONS)

        if token.is_expired():
            return {"valid": False, "reason": "expired"}

        # Decapsulate to get shared secret
        try:
            shared_secret = self.hybrid.key_decapsulate(
                token.kem_ciphertext, self.keys
            )
            return {
                "valid": True,
                "session_id": token.session_id,
                "node_id": token.node_id,
                "created_at": token.created_at,
                "expires_at": token.expires_at,
            }
        except Exception as e:
            return {"valid": False, "reason": f"decapsulation_failed: {e}"}

    def validate_token_string(self, token_str: str) -> Dict[str, Any]:
        """Validate a token from its string representation."""
        try:
            token = SecureSessionToken.from_token_string(token_str)
            return self.validate_token(token)
        except Exception as e:
            return {"valid": False, "reason": f"decode_failed: {e}"}
