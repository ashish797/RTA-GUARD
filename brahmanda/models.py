"""
RTA-GUARD — Brahmanda Map Models

Data models for ground truth facts, sources, verification results,
provenance tracking, and audit trail.
"""
import uuid
import hashlib
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple


class SourceAuthority(str, Enum):
    PRIMARY = "primary"    # 0.9-1.0: official records, peer-reviewed papers
    SECONDARY = "secondary" # 0.6-0.9: Wikipedia, textbooks
    TERTIARY = "tertiary"   # 0.3-0.6: blog posts, social media
    UNCERTAIN = "uncertain" # 0.1-0.3: rumor, speculation


class FactType(str, Enum):
    ENTITY = "entity"        # "Paris is the capital of France"
    RELATIONSHIP = "relationship" # "France borders Spain"
    METRIC = "metric"        # "Population is 67 million"
    DEFINITION = "definition" # "A photon is a quantum of light"
    HISTORICAL = "historical" # "The Roman Empire fell in 476 AD"


class VerifyDecision(str, Enum):
    PASS = "pass"   # Claim verified against ground truth
    WARN = "warn"   # Unverifiable or low-confidence match
    BLOCK = "block" # Claim contradicts verified ground truth


class AuditAction(str, Enum):
    """Types of audit actions on facts."""
    CREATE = "create"
    UPDATE = "update"
    RETRACT = "retract"
    SOURCE_CHANGE = "source_change"
    CONFIDENCE_CHANGE = "confidence_change"
    VERIFICATION = "verification"
    EXPIRATION = "expiration"


# ─── Source Confidence Mapping ──────────────────────────────────────

SOURCE_CONFIDENCE_RANGES = {
    SourceAuthority.PRIMARY: (0.9, 1.0),
    SourceAuthority.SECONDARY: (0.6, 0.9),
    SourceAuthority.TERTIARY: (0.3, 0.6),
    SourceAuthority.UNCERTAIN: (0.1, 0.3),
}


def confidence_for_authority(authority: SourceAuthority) -> float:
    """Get the midpoint confidence score for an authority level."""
    low, high = SOURCE_CONFIDENCE_RANGES[authority]
    return round((low + high) / 2, 4)


def confidence_for_authority_score(score: float) -> float:
    """Map a raw authority_score (0-1) to the appropriate authority and confidence."""
    if score >= 0.9:
        return 0.95
    elif score >= 0.6:
        return 0.75
    elif score >= 0.3:
        return 0.45
    return 0.2


# ─── Data Models ────────────────────────────────────────────────────


@dataclass
class Source:
    """A verified source of ground truth with hierarchy support."""
    id: str = field(default_factory=lambda: f"src-{uuid.uuid4().hex[:8]}")
    name: str = ""
    authority: SourceAuthority = SourceAuthority.TERTIARY
    authority_score: float = 0.5  # 0.0-1.0
    url: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""

    # Phase 2.4: Enhanced fields
    version: str = "1.0"
    expires_at: Optional[str] = None  # Source-level expiration
    domain_specialization: Optional[str] = None  # e.g., "medical", "finance"
    parent_source_id: Optional[str] = None  # Hierarchy: WHO > CDC
    tags: List[str] = field(default_factory=list)

    def effective_confidence(self) -> float:
        """Calculate source confidence based on authority level."""
        low, high = SOURCE_CONFIDENCE_RANGES[self.authority]
        # Interpolate within range based on authority_score
        conf = low + (high - low) * (self.authority_score / 1.0)
        return round(min(max(conf, 0.0), 1.0), 4)

    def is_expired(self) -> bool:
        """Check if this source has expired."""
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "authority": self.authority.value,
            "authority_score": self.authority_score,
            "effective_confidence": self.effective_confidence(),
            "url": self.url,
            "version": self.version,
            "domain_specialization": self.domain_specialization,
            "parent_source_id": self.parent_source_id,
            "tags": self.tags,
        }
        if self.expires_at:
            d["expires_at"] = self.expires_at
            d["expired"] = self.is_expired()
        return d


@dataclass
class GroundTruthFact:
    """A verified fact stored in the Brahmanda Map."""
    id: str = field(default_factory=lambda: f"f-{uuid.uuid4().hex[:8]}")
    claim: str = ""
    normalized: str = ""  # Lowercased, trimmed for dedup
    domain: str = "general"
    fact_type: FactType = FactType.ENTITY
    confidence: float = 0.9
    source: Source = field(default_factory=Source)
    source_url: Optional[str] = None
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    version: int = 1
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.normalized:
            self.normalized = self.claim.lower().strip()

    def calculate_effective_confidence(self) -> float:
        """Calculate confidence considering source authority, recency, and expiration."""
        # Base confidence weighted by source
        conf = self.confidence * self.source.effective_confidence()

        # Recency decay: lose 5% per year
        try:
            verified = datetime.fromisoformat(self.verified_at.replace("Z", "+00:00"))
            age_years = (datetime.now(timezone.utc) - verified).total_seconds() / (365.25 * 86400)
            recency_factor = max(0.5, 1.0 - (age_years * 0.05))
            conf *= recency_factor
        except (ValueError, TypeError):
            pass

        # Expiry check — aggressive decay for expired facts
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if now > expires:
                    days_expired = (now - expires).days
                    # Aggressive decay: 0.3 on day 0, then halve every 30 days
                    decay = 0.3 * (0.5 ** (days_expired / 30))
                    conf *= max(decay, 0.01)
            except (ValueError, TypeError):
                pass

        return round(min(conf, 1.0), 4)

    def is_expired(self) -> bool:
        """Check if this fact has passed its expiration date."""
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "claim": self.claim,
            "normalized": self.normalized,
            "domain": self.domain,
            "fact_type": self.fact_type.value,
            "confidence": self.confidence,
            "effective_confidence": self.calculate_effective_confidence(),
            "source": self.source.to_dict(),
            "verified_at": self.verified_at,
            "version": self.version,
            "tags": self.tags,
            "expired": self.is_expired(),
        }
        if self.expires_at:
            d["expires_at"] = self.expires_at
        return d


@dataclass
class FactProvenance:
    """
    Links a fact to its source with chain of trust.

    Provenance chain: A → B → C means C is the ultimate source,
    B verifies C, A verifies B. Chain confidence = product of all links.
    """
    id: str = field(default_factory=lambda: f"prov-{uuid.uuid4().hex[:8]}")
    fact_id: str = ""
    source_id: str = ""
    linked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    linked_by: Optional[str] = None  # Who linked it
    chain: List[str] = field(default_factory=list)  # Ordered list of source IDs in trust chain
    chain_confidence: float = 1.0  # Product of all source confidences in chain
    notes: str = ""

    def calculate_chain_confidence(self, sources: Dict[str, Source]) -> float:
        """Calculate the confidence through the provenance chain."""
        if not self.chain:
            return self.chain_confidence

        conf = 1.0
        for src_id in self.chain:
            src = sources.get(src_id)
            if src:
                conf *= src.effective_confidence()
            else:
                conf *= 0.5  # Unknown source penalty

        self.chain_confidence = round(conf, 4)
        return self.chain_confidence

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fact_id": self.fact_id,
            "source_id": self.source_id,
            "linked_at": self.linked_at,
            "linked_by": self.linked_by,
            "chain": self.chain,
            "chain_confidence": self.chain_confidence,
        }


@dataclass
class AuditEntry:
    """
    Append-only audit log entry. Immutable — no deletes, no modifications.
    Each entry includes a hash of the previous entry for tamper detection.
    """
    id: str = field(default_factory=lambda: f"audit-{uuid.uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action: AuditAction = AuditAction.CREATE
    fact_id: str = ""
    source_id: Optional[str] = None
    actor: str = "system"  # Who performed the action
    previous_hash: Optional[str] = None  # Hash chain for tamper detection
    entry_hash: Optional[str] = field(default=None)
    details: Dict[str, Any] = field(default_factory=dict)
    before: Optional[Dict[str, Any]] = None  # State before change
    after: Optional[Dict[str, Any]] = None  # State after change

    def __post_init__(self):
        if self.entry_hash is None:
            self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash for chain integrity."""
        content = json.dumps({
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "fact_id": self.fact_id,
            "source_id": self.source_id,
            "actor": self.actor,
            "previous_hash": self.previous_hash,
            "details": self.details,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify that this entry hasn't been tampered with."""
        return self.entry_hash == self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "fact_id": self.fact_id,
            "source_id": self.source_id,
            "actor": self.actor,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
            "details": self.details,
        }


@dataclass
class ClaimMatch:
    """A match between an extracted claim and a ground truth fact."""
    claim: str
    matched_fact: Optional[GroundTruthFact] = None
    similarity: float = 0.0
    contradicted: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "matched_fact": self.matched_fact.to_dict() if self.matched_fact else None,
            "similarity": round(self.similarity, 4),
            "contradicted": self.contradicted,
            "reason": self.reason,
        }


@dataclass
class VerifyResult:
    """Result of verifying an AI output against the Brahmanda Map."""
    verified: bool = True
    overall_confidence: float = 1.0
    claims: List[ClaimMatch] = field(default_factory=list)
    decision: VerifyDecision = VerifyDecision.PASS
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "overall_confidence": round(self.overall_confidence, 4),
            "claims": [c.to_dict() for c in self.claims],
            "decision": self.decision.value,
            "details": self.details,
        }
