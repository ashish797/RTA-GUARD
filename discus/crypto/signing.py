"""
RTA-GUARD Crypto — Audit Trail Signing

Signs every kill/warn event with hybrid (classical + PQC) signatures.
Provides tamper-proof audit logs.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import CryptoConfig, CryptoMode, KeyPurpose
from .hybrid import HybridCrypto, HybridKeySet, HybridSignature
from .keys import KeyManager

logger = logging.getLogger("discus.crypto.signing")


@dataclass
class SignedEvent:
    """A guard event with cryptographic signature."""
    event_id: str
    session_id: str
    decision: str
    violation_type: Optional[str]
    timestamp: float
    input_hash: str  # SHA-256 of input (don't store raw input)
    details: Dict[str, Any]
    signature: HybridSignature
    signature_mode: str  # classical, hybrid, pqc-only
    _signed_payload: bytes = b""  # Exact bytes that were signed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "decision": self.decision,
            "violation_type": self.violation_type,
            "timestamp": self.timestamp,
            "input_hash": self.input_hash,
            "details": self.details,
            "signature": self.signature.to_dict(),
            "signature_mode": self.signature_mode,
        }

    def get_signed_payload(self) -> bytes:
        """Get the exact bytes that were signed."""
        return self._signed_payload

    def verify(self, classical_pubkey: bytes, pqc_pubkey: bytes,
               crypto: HybridCrypto) -> Dict[str, bool]:
        """Verify the event signature against the stored payload."""
        return crypto.verify(self._signed_payload, self.signature, classical_pubkey, pqc_pubkey)


class AuditSigner:
    """
    Signs guard events for tamper-proof audit trails.

    Features:
    - Signs kills always, warns always, passes optionally
    - Hybrid signatures (classical + PQC)
    - Event chaining (each event references previous hash)
    - Batch verification
    """

    def __init__(self, key_manager: KeyManager):
        self.key_mgr = key_manager
        self.hybrid = HybridCrypto(key_manager.config)
        self.keys: Optional[HybridKeySet] = None
        self._last_event_hash: str = "genesis"
        self._event_count: int = 0

    def initialize(self):
        """Load or generate audit signing keys."""
        self.keys = self.key_mgr.get_or_generate(KeyPurpose.AUDIT_SIGNING)
        logger.info("Audit signer initialized")

    def sign_event(self, session_id: str, decision: str,
                   violation_type: Optional[str] = None,
                   input_text: str = "",
                   details: Optional[Dict[str, Any]] = None) -> Optional[SignedEvent]:
        """
        Sign a guard event. Returns None if signing is skipped (e.g., pass events).
        """
        if not self.keys:
            self.initialize()

        # Skip pass events unless configured
        if decision == "pass" and not self.key_mgr.config.sign_pass_events:
            return None

        # Build event
        event_id = hashlib.sha256(
            f"{session_id}:{time.time()}:{self._event_count}".encode()
        ).hexdigest()[:16]

        input_hash = hashlib.sha256(input_text.encode()).hexdigest()

        # Serialize for signing
        event_data = {
            "event_id": event_id,
            "session_id": session_id,
            "decision": decision,
            "violation_type": violation_type,
            "timestamp": time.time(),
            "input_hash": input_hash,
            "details": details or {},
            "prev_hash": self._last_event_hash,  # Chain
        }
        signable = json.dumps(event_data, sort_keys=True).encode()

        # Sign based on mode
        mode = self.key_mgr.config.mode
        if mode == CryptoMode.CLASSICAL:
            sig = self.hybrid.sign_classical_only(signable, self.keys)
            mode_str = "classical"
        elif mode == CryptoMode.PQC_ONLY:
            sig = self.hybrid.sign_pqc_only(signable, self.keys)
            mode_str = "pqc-only"
        else:
            sig = self.hybrid.sign(signable, self.keys)
            mode_str = "hybrid"

        # Build signed event
        signed = SignedEvent(
            event_id=event_id,
            session_id=session_id,
            decision=decision,
            violation_type=violation_type,
            timestamp=event_data["timestamp"],
            input_hash=input_hash,
            details={**event_data.get("details", {}), "prev_hash": event_data["prev_hash"]},
            signature=sig,
            signature_mode=mode_str,
            _signed_payload=signable,  # Store exact signed bytes
        )

        # Update chain
        self._last_event_hash = hashlib.sha256(signable).hexdigest()
        self._event_count += 1

        return signed

    def verify_event(self, event: SignedEvent) -> Dict[str, bool]:
        """Verify a signed event's signature."""
        if not self.keys:
            self.keys = self.key_mgr.load_keys(KeyPurpose.AUDIT_SIGNING)

        data = event.get_signed_payload()
        return self.hybrid.verify(
            data, event.signature,
            self.keys.classical.public_key,
            self.keys.pqc_signing.public_key,
        )

    def verify_chain(self, events: List[SignedEvent]) -> Dict[str, Any]:
        """
        Verify a chain of signed events.
        Checks both signature validity and chain integrity.
        """
        results = []
        chain_broken = False

        for i, event in enumerate(events):
            sig_result = self.verify_event(event)
            prev_hash_ok = True

            if i > 0:
                expected_prev = hashlib.sha256(events[i-1].get_signed_payload()).hexdigest()
                actual_prev = event.details.get("prev_hash", "")
                prev_hash_ok = (expected_prev == actual_prev)
                if not prev_hash_ok:
                    chain_broken = True

            results.append({
                "event_id": event.event_id,
                "signature_valid": sig_result.get("fully_valid", False),
                "chain_valid": prev_hash_ok,
            })

        valid_count = sum(1 for r in results if r["signature_valid"] and r["chain_valid"])

        return {
            "total_events": len(events),
            "valid_events": valid_count,
            "chain_intact": not chain_broken,
            "all_valid": valid_count == len(events) and not chain_broken,
            "details": results,
        }

    def get_public_keys(self) -> Dict[str, bytes]:
        """Get public keys for verification."""
        if not self.keys:
            self.initialize()
        return {
            "classical_public_key": self.keys.classical.public_key,
            "pqc_signing_public_key": self.keys.pqc_signing.public_key,
            "pqc_backup_public_key": self.keys.pqc_backup.public_key,
        }
