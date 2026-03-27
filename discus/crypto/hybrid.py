"""
RTA-GUARD Crypto — Hybrid Mode

Combines classical + PQC signatures for defense in depth.
Both must verify for a signature to be valid.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .config import CryptoConfig, CryptoMode
from .classical import ClassicalCrypto, ClassicalKeyPair
from .pqc import PQCCrypto, PQCKeyPair

logger = logging.getLogger("discus.crypto.hybrid")


@dataclass
class HybridSignature:
    """A signature containing both classical and PQC components."""
    classical_sig: bytes
    pqc_sig: bytes
    algorithm: str  # "RSA+ML-DSA-65"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        import base64
        return {
            "classical_sig": base64.b64encode(self.classical_sig).decode(),
            "pqc_sig": base64.b64encode(self.pqc_sig).decode(),
            "algorithm": self.algorithm,
            "timestamp": self.timestamp,
        }

    def serialize(self) -> bytes:
        """Serialize for storage/transmission."""
        return json.dumps(self.to_dict()).encode()

    @classmethod
    def deserialize(cls, data: bytes) -> "HybridSignature":
        import base64
        d = json.loads(data)
        return cls(
            classical_sig=base64.b64decode(d["classical_sig"]),
            pqc_sig=base64.b64decode(d["pqc_sig"]),
            algorithm=d["algorithm"],
            timestamp=d.get("timestamp", 0),
        )


@dataclass
class HybridKeySet:
    """Complete key set for hybrid mode."""
    classical: ClassicalKeyPair
    pqc_signing: PQCKeyPair      # ML-DSA for signatures
    pqc_kem: PQCKeyPair          # ML-KEM for key exchange
    pqc_backup: PQCKeyPair       # SLH-DSA backup signatures
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classical": self.classical.to_dict(),
            "pqc_signing": self.pqc_signing.to_dict(),
            "pqc_kem": self.pqc_kem.to_dict(),
            "pqc_backup": self.pqc_backup.to_dict(),
            "created_at": self.created_at,
        }


class HybridCrypto:
    """
    Hybrid classical + PQC cryptographic operations.

    In hybrid mode:
    - Signatures include BOTH RSA + ML-DSA components
    - Both must verify for the signature to be valid
    - If one algorithm is broken, the other still protects
    """

    def __init__(self, config: Optional[CryptoConfig] = None):
        self.config = config or CryptoConfig()
        self.classical = ClassicalCrypto()
        self.pqc = PQCCrypto(
            mlkem_level=self.config.mlkem_level,
            mldsa_level=self.config.mldsa_level,
            slhdsa_variant=self.config.slhdsa_variant,
        )

    def generate_keys(self) -> HybridKeySet:
        """Generate a complete hybrid key set."""
        import time
        classical = self.classical.generate_keypair()
        pqc_signing = self.pqc.mldsa_keygen()
        pqc_kem = self.pqc.mlkem_keygen()
        pqc_backup = self.pqc.slhdsa_keygen()

        return HybridKeySet(
            classical=classical,
            pqc_signing=pqc_signing,
            pqc_kem=pqc_kem,
            pqc_backup=pqc_backup,
            created_at=time.time(),
        )

    def sign(self, data: bytes, keys: HybridKeySet) -> HybridSignature:
        """Sign data with both classical and PQC algorithms."""
        classical_sig = self.classical.sign(data, keys.classical.private_key)
        pqc_sig = self.pqc.mldsa_sign(data, keys.pqc_signing.secret_key)

        return HybridSignature(
            classical_sig=classical_sig,
            pqc_sig=pqc_sig,
            algorithm=f"RSA-{keys.classical.key_size}+{keys.pqc_signing.algorithm}",
        )

    def verify(self, data: bytes, signature: HybridSignature,
               classical_pubkey: bytes, pqc_pubkey: bytes) -> Dict[str, bool]:
        """
        Verify hybrid signature. Returns component results.
        In hybrid mode, BOTH must pass for full verification.
        """
        classical_ok = self.classical.verify(data, signature.classical_sig, classical_pubkey)
        pqc_ok = self.pqc.mldsa_verify(data, signature.pqc_sig, pqc_pubkey)

        return {
            "classical_valid": classical_ok,
            "pqc_valid": pqc_ok,
            "fully_valid": classical_ok and pqc_ok,
            "classical_only": classical_ok and not pqc_ok,
            "pqc_only": pqc_ok and not classical_ok,
        }

    def sign_classical_only(self, data: bytes, keys: HybridKeySet) -> HybridSignature:
        """Sign with classical only (for mode=classical)."""
        classical_sig = self.classical.sign(data, keys.classical.private_key)
        return HybridSignature(
            classical_sig=classical_sig,
            pqc_sig=b"",  # Empty — not signed with PQC
            algorithm=f"RSA-{keys.classical.key_size}",
        )

    def sign_pqc_only(self, data: bytes, keys: HybridKeySet) -> HybridSignature:
        """Sign with PQC only (for mode=pqc-only)."""
        pqc_sig = self.pqc.mldsa_sign(data, keys.pqc_signing.secret_key)
        return HybridSignature(
            classical_sig=b"",  # Empty — not signed with classical
            pqc_sig=pqc_sig,
            algorithm=keys.pqc_signing.algorithm,
        )

    def key_exchange(self, recipient_pqc_pubkey: bytes) -> Tuple[bytes, bytes]:
        """PQC key exchange. Returns (ciphertext, shared_secret)."""
        return self.pqc.mlkem_encapsulate(recipient_pqc_pubkey)

    def key_decapsulate(self, ciphertext: bytes, keys: HybridKeySet) -> bytes:
        """Recover shared secret from key exchange ciphertext."""
        return self.pqc.mlkem_decapsulate(ciphertext, keys.pqc_kem.secret_key)
