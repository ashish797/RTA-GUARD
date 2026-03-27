"""
RTA-GUARD Crypto — Classical Cryptography

Wrappers for RSA/AES/SHA used in classical mode and hybrid fallback.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("discus.crypto.classical")

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding, utils
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("cryptography library not installed — classical crypto unavailable")


@dataclass
class ClassicalKeyPair:
    """Classical RSA key pair."""
    private_key: bytes  # PEM
    public_key: bytes   # PEM
    key_size: int = 2048
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": "RSA",
            "key_size": self.key_size,
            "public_key_hash": hashlib.sha256(self.public_key).hexdigest()[:16],
            "created_at": self.created_at,
        }


class ClassicalCrypto:
    """Classical RSA/AES/SHA cryptographic operations."""

    @staticmethod
    def generate_keypair(key_size: int = 2048) -> ClassicalKeyPair:
        """Generate RSA key pair."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required for classical crypto")

        import time
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend(),
        )
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return ClassicalKeyPair(
            private_key=private_pem,
            public_key=public_pem,
            key_size=key_size,
            created_at=time.time(),
        )

    @staticmethod
    def sign(data: bytes, private_key_pem: bytes) -> bytes:
        """Sign data with RSA private key."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required")

        private_key = serialization.load_pem_private_key(
            private_key_pem, password=None, backend=default_backend()
        )
        signature = private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return signature

    @staticmethod
    def verify(data: bytes, signature: bytes, public_key_pem: bytes) -> bool:
        """Verify RSA signature."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required")

        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem, backend=default_backend()
            )
            public_key.verify(
                signature,
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True
        except Exception:
            return False

    @staticmethod
    def generate_aes_key() -> bytes:
        """Generate random AES-256 key."""
        return os.urandom(32)

    @staticmethod
    def aes_encrypt(plaintext: bytes, key: bytes) -> Tuple[bytes, bytes]:
        """Encrypt with AES-256-GCM. Returns (nonce, ciphertext)."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required")

        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce, ciphertext

    @staticmethod
    def aes_decrypt(nonce: bytes, ciphertext: bytes, key: bytes) -> bytes:
        """Decrypt AES-256-GCM."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required")

        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    @staticmethod
    def sha256(data: bytes) -> str:
        """SHA-256 hash."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def hmac_sha256(data: bytes, key: bytes) -> str:
        """HMAC-SHA256."""
        return hmac.new(key, data, hashlib.sha256).hexdigest()

    @staticmethod
    def derive_key(passphrase: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        """Derive encryption key from passphrase using HKDF."""
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography library required")

        if salt is None:
            salt = os.urandom(16)
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"rta-guard-key-encryption",
            backend=default_backend(),
        )
        key = hkdf.derive(passphrase.encode())
        return key, salt

    @staticmethod
    def encrypt_private_key(key_pem: bytes, passphrase: str) -> Tuple[bytes, bytes]:
        """Encrypt a private key with passphrase. Returns (encrypted, salt)."""
        enc_key, salt = ClassicalCrypto.derive_key(passphrase)
        nonce, encrypted = ClassicalCrypto.aes_encrypt(key_pem, enc_key)
        # Pack as: salt(16) + nonce(12) + encrypted
        return salt + nonce + encrypted, salt

    @staticmethod
    def decrypt_private_key(encrypted_data: bytes, passphrase: str) -> bytes:
        """Decrypt a private key with passphrase."""
        salt = encrypted_data[:16]
        nonce = encrypted_data[16:28]
        ciphertext = encrypted_data[28:]
        enc_key, _ = ClassicalCrypto.derive_key(passphrase, salt)
        return ClassicalCrypto.aes_decrypt(nonce, ciphertext, enc_key)

    @staticmethod
    def save_keypair(keypair: ClassicalKeyPair, dir_path: Path,
                     purpose: str = "general",
                     passphrase: str = "") -> Dict[str, Path]:
        """Save key pair to disk, optionally encrypted."""
        dir_path.mkdir(parents=True, exist_ok=True)
        paths = {}

        # Public key (always unencrypted)
        pub_path = dir_path / f"{purpose}_public.pem"
        pub_path.write_bytes(keypair.public_key)
        paths["public"] = pub_path

        # Private key (encrypted if passphrase provided)
        priv_path = dir_path / f"{purpose}_private.pem"
        if passphrase:
            encrypted, _ = ClassicalCrypto.encrypt_private_key(keypair.private_key, passphrase)
            priv_path.write_bytes(b"ENCRYPTED:" + base64.b64encode(encrypted))
        else:
            priv_path.write_bytes(keypair.private_key)
        paths["private"] = priv_path

        # Metadata
        meta_path = dir_path / f"{purpose}_meta.json"
        meta_path.write_text(json.dumps(keypair.to_dict(), indent=2))
        paths["meta"] = meta_path

        logger.info(f"Saved {purpose} keypair to {dir_path}")
        return paths

    @staticmethod
    def load_private_key(path: Path, passphrase: str = "") -> bytes:
        """Load private key from disk, decrypting if needed."""
        data = path.read_bytes()
        if data.startswith(b"ENCRYPTED:"):
            if not passphrase:
                raise ValueError("Private key is encrypted but no passphrase provided")
            encrypted = base64.b64decode(data[10:])
            return ClassicalCrypto.decrypt_private_key(encrypted, passphrase)
        return data

    @staticmethod
    def load_public_key(path: Path) -> bytes:
        """Load public key from disk."""
        return path.read_bytes()
