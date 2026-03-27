"""
RTA-GUARD Crypto — Configuration

Defines crypto modes, key purposes, and configuration.
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
import os


class CryptoMode(Enum):
    """Cryptographic operation modes."""
    CLASSICAL = "classical"  # RSA/AES only (legacy)
    HYBRID = "hybrid"        # Classical + PQC parallel (default)
    PQC_ONLY = "pqc-only"   # PQC only (future-proof)


class KeyPurpose(Enum):
    """Key isolation by purpose."""
    AUDIT_SIGNING = "audit_signing"
    FEDERATION = "federation"
    SESSIONS = "sessions"
    WEBHOOKS = "webhooks"
    GENERAL = "general"


@dataclass
class CryptoConfig:
    """Configuration for the crypto module."""
    mode: CryptoMode = CryptoMode.HYBRID
    keys_dir: Path = Path.home() / ".rta-guard" / "keys"
    key_rotation_days: int = 30
    key_max_age_days: int = 90
    master_passphrase: str = ""  # For encrypting keys at rest
    sign_pass_events: bool = False  # Only sign kills by default (performance)
    cache_keys_in_memory: bool = True
    hsm_enabled: bool = False
    hsm_plugin: str = ""

    # PQC algorithm parameters
    mlkem_level: int = 768     # ML-KEM-512/768/1024
    mldsa_level: int = 65      # ML-DSA-44/65/87
    slhdsa_variant: str = "sha2-128f"  # SLH-DSA variant

    @classmethod
    def from_env(cls) -> "CryptoConfig":
        """Load config from environment variables."""
        mode_str = os.getenv("RTA_CRYPTO_MODE", "hybrid")
        keys_dir = os.getenv("RTA_KEYS_DIR", "")
        passphrase = os.getenv("RTA_MASTER_PASSPHRASE", "")
        rotation = int(os.getenv("RTA_KEY_ROTATION_DAYS", "30"))

        return cls(
            mode=CryptoMode(mode_str),
            keys_dir=Path(keys_dir) if keys_dir else Path.home() / ".rta-guard" / "keys",
            key_rotation_days=rotation,
            master_passphrase=passphrase,
            sign_pass_events=os.getenv("RTA_SIGN_PASS_EVENTS", "false").lower() == "true",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "keys_dir": str(self.keys_dir),
            "key_rotation_days": self.key_rotation_days,
            "key_max_age_days": self.key_max_age_days,
            "sign_pass_events": self.sign_pass_events,
            "cache_keys_in_memory": self.cache_keys_in_memory,
            "mlkem_level": self.mlkem_level,
            "mldsa_level": self.mldsa_level,
            "slhdsa_variant": self.slhdsa_variant,
        }
