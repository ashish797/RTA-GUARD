"""
RTA-GUARD Crypto — Federation Authentication

PQC-based authentication for federation nodes.
Nodes exchange PQC public keys and sign messages for mutual authentication.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import CryptoConfig, KeyPurpose
from .hybrid import HybridCrypto, HybridKeySet, HybridSignature
from .keys import KeyManager

logger = logging.getLogger("discus.crypto.federation_auth")


@dataclass
class FederationCertificate:
    """PQC certificate for a federation node."""
    node_id: str
    classical_public_key: bytes
    pqc_signing_public_key: bytes
    pqc_kem_public_key: bytes
    pqc_backup_public_key: bytes
    issued_at: float
    expires_at: float
    issuer: str = "self-signed"  # Future: CA-signed
    algorithm: str = "RSA+ML-DSA-65+ML-KEM-768"

    def to_dict(self) -> Dict[str, Any]:
        import base64
        return {
            "node_id": self.node_id,
            "classical_public_key": base64.b64encode(self.classical_public_key).decode(),
            "pqc_signing_public_key": base64.b64encode(self.pqc_signing_public_key).decode(),
            "pqc_kem_public_key": base64.b64encode(self.pqc_kem_public_key).decode(),
            "pqc_backup_public_key": base64.b64encode(self.pqc_backup_public_key).decode(),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "issuer": self.issuer,
            "algorithm": self.algorithm,
        }

    def fingerprint(self) -> str:
        """Unique fingerprint for this certificate."""
        data = (
            self.node_id.encode() +
            self.classical_public_key +
            self.pqc_signing_public_key +
            self.pqc_kem_public_key
        )
        return hashlib.sha256(data).hexdigest()[:32]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationCertificate":
        import base64
        return cls(
            node_id=data["node_id"],
            classical_public_key=base64.b64decode(data["classical_public_key"]),
            pqc_signing_public_key=base64.b64decode(data["pqc_signing_public_key"]),
            pqc_kem_public_key=base64.b64decode(data["pqc_kem_public_key"]),
            pqc_backup_public_key=base64.b64decode(data["pqc_backup_public_key"]),
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
            issuer=data.get("issuer", "self-signed"),
            algorithm=data.get("algorithm", "RSA+ML-DSA-65+ML-KEM-768"),
        )

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class SignedMessage:
    """A federation message with PQC signature."""
    payload: Dict[str, Any]
    signature: HybridSignature
    sender_cert: FederationCertificate
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload": self.payload,
            "signature": self.signature.to_dict(),
            "sender_cert": self.sender_cert.to_dict(),
            "timestamp": self.timestamp,
        }

    def verify(self, crypto: HybridCrypto) -> Dict[str, bool]:
        """Verify the message signature."""
        data = json.dumps(self.payload, sort_keys=True).encode()
        return crypto.verify(
            data, self.signature,
            self.sender_cert.classical_public_key,
            self.sender_cert.pqc_signing_public_key,
        )


class FederationAuth:
    """
    PQC-based federation node authentication.

    Flow:
    1. Node generates PQC key pair
    2. Node creates self-signed certificate
    3. Node presents certificate to federation
    4. Federation verifies certificate signature
    5. Messages signed with PQC, verified against certificate
    """

    def __init__(self, key_manager: KeyManager):
        self.key_mgr = key_manager
        self.hybrid = HybridCrypto(key_manager.config)
        self.keys: Optional[HybridKeySet] = None

    def initialize(self):
        """Load or generate federation keys."""
        self.keys = self.key_mgr.get_or_generate(KeyPurpose.FEDERATION)

    def create_certificate(self, node_id: str,
                           validity_days: int = 365) -> FederationCertificate:
        """Create a self-signed federation certificate."""
        if not self.keys:
            self.initialize()

        return FederationCertificate(
            node_id=node_id,
            classical_public_key=self.keys.classical.public_key,
            pqc_signing_public_key=self.keys.pqc_signing.public_key,
            pqc_kem_public_key=self.keys.pqc_kem.public_key,
            pqc_backup_public_key=self.keys.pqc_backup.public_key,
            issued_at=time.time(),
            expires_at=time.time() + (validity_days * 86400),
        )

    def sign_message(self, payload: Dict[str, Any],
                     cert: FederationCertificate) -> SignedMessage:
        """Sign a federation message."""
        if not self.keys:
            self.initialize()

        data = json.dumps(payload, sort_keys=True).encode()
        sig = self.hybrid.sign(data, self.keys)

        return SignedMessage(
            payload=payload,
            signature=sig,
            sender_cert=cert,
            timestamp=time.time(),
        )

    def verify_message(self, msg: SignedMessage) -> Dict[str, Any]:
        """Verify a federation message."""
        if msg.sender_cert.is_expired():
            return {"valid": False, "reason": "certificate_expired"}

        result = msg.verify(self.hybrid)
        return {
            "valid": result.get("fully_valid", False),
            "classical_valid": result.get("classical_valid", False),
            "pqc_valid": result.get("pqc_valid", False),
            "sender": msg.sender_cert.node_id,
            "cert_fingerprint": msg.sender_cert.fingerprint(),
        }

    def verify_certificate(self, cert: FederationCertificate) -> Dict[str, Any]:
        """Verify a federation certificate."""
        if cert.is_expired():
            return {"valid": False, "reason": "expired"}

        # Check key sizes are reasonable
        if len(cert.pqc_signing_public_key) < 32:
            return {"valid": False, "reason": "invalid_key_size"}

        return {
            "valid": True,
            "node_id": cert.node_id,
            "fingerprint": cert.fingerprint(),
            "expires_at": cert.expires_at,
            "algorithm": cert.algorithm,
        }
