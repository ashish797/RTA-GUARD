"""
RTA-GUARD — Brahmanda Map Models

Data models for ground truth facts, sources, and verification results.
"""
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


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


@dataclass
class Source:
    """A verified source of ground truth."""
    id: str = field(default_factory=lambda: f"src-{uuid.uuid4().hex[:8]}")
    name: str = ""
    authority: SourceAuthority = SourceAuthority.TERTIARY
    authority_score: float = 0.5  # 0.0-1.0
    url: Optional[str] = None
    verified_by: Optional[str] = None
    verified_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    notes: str = ""


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
    verified_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    version: int = 1
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.normalized:
            self.normalized = self.claim.lower().strip()

    def calculate_effective_confidence(self) -> float:
        """Calculate confidence considering source authority and recency."""
        # Base confidence
        conf = self.confidence * self.source.authority_score

        # Recency decay: lose 5% per year
        try:
            verified = datetime.fromisoformat(self.verified_at.replace("Z", "+00:00"))
            age_years = (datetime.utcnow() - verified.replace(tzinfo=None)).days / 365.25
            recency_factor = max(0.5, 1.0 - (age_years * 0.05))
            conf *= recency_factor
        except (ValueError, TypeError):
            pass

        # Expiry check
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                if datetime.utcnow() > expires.replace(tzinfo=None):
                    conf *= 0.3  # Heavily penalize expired facts
            except (ValueError, TypeError):
                pass

        return round(min(conf, 1.0), 4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "claim": self.claim,
            "normalized": self.normalized,
            "domain": self.domain,
            "fact_type": self.fact_type.value,
            "confidence": self.confidence,
            "effective_confidence": self.calculate_effective_confidence(),
            "source": {
                "id": self.source.id,
                "name": self.source.name,
                "authority": self.source.authority.value,
                "url": self.source.url,
            },
            "verified_at": self.verified_at,
            "version": self.version,
            "tags": self.tags,
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
