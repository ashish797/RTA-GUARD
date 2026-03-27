"""
RTA-GUARD Crypto — Quantum-Resistant Cryptography

Post-quantum crypto for audit trails, session tokens, federation auth, and webhooks.
Supports classical, hybrid, and PQC-only modes.
"""
from .config import CryptoConfig, CryptoMode, KeyPurpose
from .classical import ClassicalCrypto, ClassicalKeyPair
from .pqc import PQCCrypto, PQCKeyPair
from .hybrid import HybridCrypto, HybridKeySet, HybridSignature
from .keys import KeyManager, KeyRecord
from .signing import AuditSigner, SignedEvent
from .session import SessionTokenManager, SecureSessionToken
from .federation_auth import FederationAuth, FederationCertificate, SignedMessage
from .benchmark import benchmark

__all__ = [
    "CryptoConfig", "CryptoMode", "KeyPurpose",
    "ClassicalCrypto", "ClassicalKeyPair",
    "PQCCrypto", "PQCKeyPair",
    "HybridCrypto", "HybridKeySet", "HybridSignature",
    "KeyManager", "KeyRecord",
    "AuditSigner", "SignedEvent",
    "SessionTokenManager", "SecureSessionToken",
    "FederationAuth", "FederationCertificate", "SignedMessage",
    "benchmark",
]
