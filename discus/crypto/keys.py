"""
RTA-GUARD Crypto — Key Manager

Manages key lifecycle: generation, storage, rotation, isolation by purpose.
Supports encrypted key storage at rest.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import CryptoConfig, CryptoMode, KeyPurpose
from .classical import ClassicalCrypto, ClassicalKeyPair
from .pqc import PQCCrypto, PQCKeyPair
from .hybrid import HybridCrypto, HybridKeySet

logger = logging.getLogger("discus.crypto.keys")


@dataclass
class KeyRecord:
    """Record of a key in the rotation log."""
    key_id: str
    purpose: str
    algorithm: str
    created_at: float
    expires_at: float
    rotated_at: Optional[float] = None
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key_id": self.key_id,
            "purpose": self.purpose,
            "algorithm": self.algorithm,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "rotated_at": self.rotated_at,
            "active": self.active,
        }


class KeyManager:
    """
    Manages cryptographic keys with:
    - Isolation by purpose (audit, federation, sessions, webhooks)
    - Automatic rotation
    - Encrypted storage at rest
    - Key rotation log
    """

    def __init__(self, config: Optional[CryptoConfig] = None):
        self.config = config or CryptoConfig()
        self.hybrid = HybridCrypto(self.config)

        # In-memory key cache
        self._key_cache: Dict[str, HybridKeySet] = {}

        # Initialize key directories
        self._init_dirs()

    def _init_dirs(self):
        """Create key directories for each purpose."""
        for purpose in KeyPurpose:
            (self.config.keys_dir / purpose.value).mkdir(parents=True, exist_ok=True)

    def _purpose_dir(self, purpose: KeyPurpose) -> Path:
        return self.config.keys_dir / purpose.value

    # ─── Key Generation ─────────────────────────────────────────────

    def generate_keys(self, purpose: KeyPurpose = KeyPurpose.GENERAL,
                      force: bool = False) -> HybridKeySet:
        """
        Generate keys for a specific purpose.
        Skips if keys already exist unless force=True.
        """
        pdir = self._purpose_dir(purpose)
        meta_path = pdir / f"{purpose.value}_hybrid_meta.json"

        if meta_path.exists() and not force:
            logger.info(f"Keys for {purpose.value} already exist, loading")
            return self.load_keys(purpose)

        # Generate new key set
        keys = self.hybrid.generate_keys()
        self._save_hybrid_keys(keys, purpose)

        # Log rotation
        self._log_key_rotation(purpose, keys, action="generated")

        # Cache
        if self.config.cache_keys_in_memory:
            self._key_cache[purpose.value] = keys

        logger.info(f"Generated {purpose.value} keys (mode: {self.config.mode.value})")
        return keys

    def load_keys(self, purpose: KeyPurpose = KeyPurpose.GENERAL) -> HybridKeySet:
        """Load keys for a purpose from disk."""
        if purpose.value in self._key_cache:
            return self._key_cache[purpose.value]

        pdir = self._purpose_dir(purpose)
        classical_priv = ClassicalCrypto.load_private_key(
            pdir / f"{purpose.value}_private.pem",
            self.config.master_passphrase,
        )
        classical_pub = (pdir / f"{purpose.value}_public.pem").read_bytes()
        classical_meta = json.loads((pdir / f"{purpose.value}_meta.json").read_text())

        pqc_sign_pub, pqc_sign_sec = PQCCrypto.load_keypair(pdir, f"{purpose.value}_signing")
        pqc_kem_pub, pqc_kem_sec = PQCCrypto.load_keypair(pdir, f"{purpose.value}_kem")
        pqc_backup_pub, pqc_backup_sec = PQCCrypto.load_keypair(pdir, f"{purpose.value}_backup")

        keys = HybridKeySet(
            classical=ClassicalKeyPair(
                private_key=classical_priv,
                public_key=classical_pub,
                key_size=classical_meta.get("key_size", 2048),
                created_at=classical_meta.get("created_at", 0),
            ),
            pqc_signing=PQCKeyPair(
                public_key=pqc_sign_pub, secret_key=pqc_sign_sec,
                algorithm=f"ML-DSA-{self.config.mldsa_level}",
                level=self.config.mldsa_level,
            ),
            pqc_kem=PQCKeyPair(
                public_key=pqc_kem_pub, secret_key=pqc_kem_sec,
                algorithm=f"ML-KEM-{self.config.mlkem_level}",
                level=self.config.mlkem_level,
            ),
            pqc_backup=PQCKeyPair(
                public_key=pqc_backup_pub, secret_key=pqc_backup_sec,
                algorithm=f"SLH-DSA-{self.config.slhdsa_variant}",
                level=0,
            ),
        )

        if self.config.cache_keys_in_memory:
            self._key_cache[purpose.value] = keys

        return keys

    def get_or_generate(self, purpose: KeyPurpose) -> HybridKeySet:
        """Get existing keys or generate if none exist."""
        pdir = self._purpose_dir(purpose)
        meta_path = pdir / f"{purpose.value}_hybrid_meta.json"
        if meta_path.exists():
            return self.load_keys(purpose)
        return self.generate_keys(purpose)

    # ─── Key Rotation ───────────────────────────────────────────────

    def check_rotation_needed(self, purpose: KeyPurpose) -> bool:
        """Check if keys need rotation."""
        pdir = self._purpose_dir(purpose)
        meta_path = pdir / f"{purpose.value}_hybrid_meta.json"
        if not meta_path.exists():
            return True

        meta = json.loads(meta_path.read_text())
        created = meta.get("created_at", 0)
        age_days = (time.time() - created) / 86400
        return age_days >= self.config.key_rotation_days

    def rotate_keys(self, purpose: KeyPurpose) -> HybridKeySet:
        """Rotate keys for a purpose (archive old, generate new)."""
        pdir = self._purpose_dir(purpose)

        # Archive old keys
        archive_dir = pdir / "archive" / str(int(time.time()))
        archive_dir.mkdir(parents=True, exist_ok=True)

        for f in pdir.glob("*.*"):
            if f.is_file():
                f.rename(archive_dir / f.name)

        # Generate new keys
        keys = self.generate_keys(purpose, force=True)
        self._log_key_rotation(purpose, keys, action="rotated")

        # Remove from cache
        self._key_cache.pop(purpose.value, None)

        logger.info(f"Rotated {purpose.value} keys (old archived to {archive_dir})")
        return keys

    def rotate_all_if_needed(self) -> Dict[str, bool]:
        """Check and rotate keys for all purposes if needed."""
        results = {}
        for purpose in KeyPurpose:
            if self.check_rotation_needed(purpose):
                self.rotate_keys(purpose)
                results[purpose.value] = True
            else:
                results[purpose.value] = False
        return results

    # ─── Key Info ───────────────────────────────────────────────────

    def get_key_info(self, purpose: KeyPurpose) -> Dict[str, Any]:
        """Get metadata about keys for a purpose."""
        pdir = self._purpose_dir(purpose)
        meta_path = pdir / f"{purpose.value}_hybrid_meta.json"
        if not meta_path.exists():
            return {"purpose": purpose.value, "status": "not_generated"}

        meta = json.loads(meta_path.read_text())
        created = meta.get("created_at", 0)
        age_days = (time.time() - created) / 86400
        needs_rotation = age_days >= self.config.key_rotation_days

        return {
            "purpose": purpose.value,
            "status": "active",
            "created_at": created,
            "age_days": round(age_days, 1),
            "needs_rotation": needs_rotation,
            "rotation_threshold_days": self.config.key_rotation_days,
            "max_age_days": self.config.key_max_age_days,
            **meta,
        }

    def get_all_key_info(self) -> List[Dict[str, Any]]:
        """Get info for all key purposes."""
        return [self.get_key_info(p) for p in KeyPurpose]

    # ─── Internal ───────────────────────────────────────────────────

    def _save_hybrid_keys(self, keys: HybridKeySet, purpose: KeyPurpose):
        """Save all components of a hybrid key set."""
        pdir = self._purpose_dir(purpose)

        # Classical keys
        ClassicalCrypto.save_keypair(
            keys.classical, pdir, purpose.value,
            passphrase=self.config.master_passphrase,
        )

        # PQC signing keys
        PQCCrypto.save_keypair(keys.pqc_signing, pdir, f"{purpose.value}_signing")

        # PQC KEM keys
        PQCCrypto.save_keypair(keys.pqc_kem, pdir, f"{purpose.value}_kem")

        # PQC backup keys
        PQCCrypto.save_keypair(keys.pqc_backup, pdir, f"{purpose.value}_backup")

        # Hybrid metadata
        meta_path = pdir / f"{purpose.value}_hybrid_meta.json"
        meta_path.write_text(json.dumps(keys.to_dict(), indent=2))

    def _log_key_rotation(self, purpose: KeyPurpose, keys: HybridKeySet,
                          action: str = "generated"):
        """Log key rotation event."""
        log_path = self.config.keys_dir / "rotation_log.json"
        log = []
        if log_path.exists():
            log = json.loads(log_path.read_text())

        log.append({
            "purpose": purpose.value,
            "action": action,
            "timestamp": time.time(),
            "classical_algo": f"RSA-{keys.classical.key_size}",
            "pqc_signing_algo": keys.pqc_signing.algorithm,
            "pqc_kem_algo": keys.pqc_kem.algorithm,
        })

        log_path.write_text(json.dumps(log, indent=2))
