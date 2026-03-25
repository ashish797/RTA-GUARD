"""
RTA-GUARD — Confidence Scoring System (Phase 2.5)

Multi-dimensional confidence scoring for the Brahmanda Map.
Combines source authority, corroboration, recency, and contradiction
signals into a single confidence score with full explainability.

Scoring modes:
  - Source-based:    trust authority scores from sources
  - Corroboration:  multiple sources agree → higher confidence
  - Recency:        newer facts score higher
  - Contradiction:  if sources disagree, confidence drops

Configurable per domain (medical: source-heavy, news: recency-heavy).

Confidence thresholds:
  HIGH   ≥ 0.85  — strong evidence, multiple sources
  MEDIUM 0.5–0.85 — moderate evidence
  LOW    < 0.5    — weak evidence, single source

Run with: ``python3 -m pytest brahmanda/test_confidence.py -v``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ─── Confidence Level Thresholds ────────────────────────────────────

HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.50


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        if score >= HIGH_CONFIDENCE_THRESHOLD:
            return cls.HIGH
        elif score >= MEDIUM_CONFIDENCE_THRESHOLD:
            return cls.MEDIUM
        return cls.LOW


# ─── Default Domain Weights ─────────────────────────────────────────

# Each tuple: (source_weight, corroboration_weight, recency_weight, contradiction_weight)
# Weights must sum to 1.0

DEFAULT_WEIGHTS: Dict[str, Tuple[float, float, float, float]] = {
    "general":    (0.35, 0.25, 0.20, 0.20),
    "medical":    (0.45, 0.30, 0.10, 0.15),  # source-heavy
    "science":    (0.40, 0.30, 0.15, 0.15),
    "history":    (0.30, 0.25, 0.10, 0.35),  # contradiction-heavy
    "technology": (0.25, 0.20, 0.35, 0.20),  # recency-heavy
    "geography":  (0.35, 0.30, 0.15, 0.20),
    "news":       (0.20, 0.15, 0.45, 0.20),  # recency-heavy
    "mathematics":(0.40, 0.30, 0.05, 0.25),
}

# Recency half-life in years — confidence halves every N years
RECENCY_HALF_LIFE_YEARS = 5.0


# ─── Score Explanation ──────────────────────────────────────────────

@dataclass
class ConfidenceExplanation:
    """Human-readable breakdown of why a confidence score is what it is."""
    final_score: float
    confidence_level: ConfidenceLevel
    domain: str
    source_score: float
    corroboration_score: float
    recency_score: float
    contradiction_penalty: float
    source_weight: float
    corroboration_weight: float
    recency_weight: float
    contradiction_weight: float
    source_count: int
    sources_agree: bool
    fact_age_days: float
    is_expired: bool
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "final_score": round(self.final_score, 4),
            "confidence_level": self.confidence_level.value,
            "domain": self.domain,
            "breakdown": {
                "source": round(self.source_score, 4),
                "corroboration": round(self.corroboration_score, 4),
                "recency": round(self.recency_score, 4),
                "contradiction_penalty": round(self.contradiction_penalty, 4),
            },
            "weights": {
                "source": self.source_weight,
                "corroboration": self.corroboration_weight,
                "recency": self.recency_weight,
                "contradiction": self.contradiction_weight,
            },
            "metadata": {
                "source_count": self.source_count,
                "sources_agree": self.sources_agree,
                "fact_age_days": round(self.fact_age_days, 1),
                "is_expired": self.is_expired,
            },
            "notes": self.notes,
        }

    def __str__(self) -> str:
        lines = [
            f"Confidence: {self.final_score:.3f} ({self.confidence_level.value})",
            f"  Domain: {self.domain}",
            f"  Source authority: {self.source_score:.3f} (w={self.source_weight})",
            f"  Corroboration:    {self.corroboration_score:.3f} (w={self.corroboration_weight})",
            f"  Recency:          {self.recency_score:.3f} (w={self.recency_weight})",
            f"  Contradiction:    {self.contradiction_penalty:.3f} (w={self.contradiction_weight})",
            f"  Sources: {self.source_count} | Agree: {self.sources_agree}",
        ]
        for note in self.notes:
            lines.append(f"  → {note}")
        return "\n".join(lines)


# ─── Confidence Scorer ──────────────────────────────────────────────

class ConfidenceScorer:
    """
    Multi-dimensional confidence scorer.

    Combines four scoring signals with configurable per-domain weights:
      1. Source-based: weighted average of source authority scores
      2. Corroboration: bonus when multiple sources agree
      3. Recency: exponential decay based on fact age
      4. Contradiction: penalty when sources disagree

    Usage:
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.95, 0.85],
            sources_agree=True,
            fact_age_days=30,
            domain="medical",
            is_expired=False,
        )
    """

    def __init__(
        self,
        domain_weights: Optional[Dict[str, Tuple[float, float, float, float]]] = None,
        recency_half_life_years: float = RECENCY_HALF_LIFE_YEARS,
    ):
        self._weights = dict(domain_weights or DEFAULT_WEIGHTS)
        self._half_life = recency_half_life_years

    # ── Public API ──────────────────────────────────────────────────

    def score(
        self,
        source_scores: Optional[List[float]] = None,
        sources_agree: bool = True,
        fact_age_days: float = 0.0,
        domain: str = "general",
        is_expired: bool = False,
        additional_notes: Optional[List[str]] = None,
    ) -> Tuple[float, ConfidenceExplanation]:
        """
        Calculate a composite confidence score.

        Args:
            source_scores: List of source authority scores (0.0-1.0).
                           Empty/None → single default source at 0.5.
            sources_agree: Whether the sources corroborate each other.
            fact_age_days: Age of the fact in days.
            domain: Domain name for weight selection.
            is_expired: Whether the fact has expired.
            additional_notes: Extra notes to include in the explanation.

        Returns:
            (score, explanation) — score is 0.0-1.0, explanation is human-readable.
        """
        source_scores = source_scores or [0.5]
        source_scores = [max(0.0, min(1.0, s)) for s in source_scores]
        notes = list(additional_notes or [])

        weights = self._get_weights(domain)
        w_src, w_cor, w_rec, w_con = weights

        # 1. Source-based score: weighted average of authority scores
        src_score = self._source_score(source_scores)

        # 2. Corroboration score: bonus for multiple agreeing sources
        cor_score = self._corroboration_score(source_scores, sources_agree)

        # 3. Recency score: exponential decay
        rec_score = self._recency_score(fact_age_days)

        # 4. Contradiction penalty: 1.0 if no contradiction, < 1.0 if disagreement
        con_penalty = self._contradiction_score(source_scores, sources_agree)

        # Weighted combination
        raw = (
            w_src * src_score
            + w_cor * cor_score
            + w_rec * rec_score
            + w_con * con_penalty
        )

        # Expired facts: aggressive decay
        if is_expired:
            raw *= 0.2
            notes.append("Fact has expired — confidence decayed aggressively")

        # Single source: cap at MEDIUM unless source is very high authority
        if len(source_scores) == 1 and source_scores[0] < 0.95:
            raw = min(raw, 0.84)
            notes.append("Single source — capped at MEDIUM confidence")

        final = round(max(0.0, min(1.0, raw)), 4)

        explanation = ConfidenceExplanation(
            final_score=final,
            confidence_level=ConfidenceLevel.from_score(final),
            domain=domain,
            source_score=src_score,
            corroboration_score=cor_score,
            recency_score=rec_score,
            contradiction_penalty=con_penalty,
            source_weight=w_src,
            corroboration_weight=w_cor,
            recency_weight=w_rec,
            contradiction_weight=w_con,
            source_count=len(source_scores),
            sources_agree=sources_agree,
            fact_age_days=fact_age_days,
            is_expired=is_expired,
            notes=notes,
        )

        return final, explanation

    def score_fact(
        self,
        fact_confidence: float,
        source_authority_score: float,
        corroboration_sources: int = 1,
        sources_agree: bool = True,
        fact_age_days: float = 0.0,
        domain: str = "general",
        is_expired: bool = False,
    ) -> Tuple[float, ConfidenceExplanation]:
        """
        Convenience method for scoring a fact from the Brahmanda Map.

        Args:
            fact_confidence: Base confidence of the fact (0.0-1.0).
            source_authority_score: Source authority (0.0-1.0).
            corroboration_sources: Number of independent sources.
            sources_agree: Whether corroborating sources agree.
            fact_age_days: Age of the fact in days.
            domain: Domain name.
            is_expired: Whether the fact has expired.

        Returns:
            (score, explanation)
        """
        source_scores = [source_authority_score] * max(1, corroboration_sources)
        return self.score(
            source_scores=source_scores,
            sources_agree=sources_agree,
            fact_age_days=fact_age_days,
            domain=domain,
            is_expired=is_expired,
            additional_notes=[f"Base fact confidence: {fact_confidence:.3f}"],
        )

    def score_verification(
        self,
        similarity: float,
        fact_confidence: float,
        source_authority_score: float = 0.7,
        corroboration_sources: int = 1,
        sources_agree: bool = True,
        fact_age_days: float = 0.0,
        domain: str = "general",
        is_expired: bool = False,
    ) -> Tuple[float, ConfidenceExplanation]:
        """
        Score a verification result combining similarity + fact confidence.

        Args:
            similarity: Claim-to-fact similarity (0.0-1.0).
            fact_confidence: Base fact confidence (0.0-1.0).
            source_authority_score: Source authority (0.0-1.0).
            corroboration_sources: Number of independent sources.
            sources_agree: Whether sources agree.
            fact_age_days: Age of fact in days.
            domain: Domain name.
            is_expired: Whether fact expired.

        Returns:
            (score, explanation)
        """
        base_score, explanation = self.score_fact(
            fact_confidence=fact_confidence,
            source_authority_score=source_authority_score,
            corroboration_sources=corroboration_sources,
            sources_agree=sources_agree,
            fact_age_days=fact_age_days,
            domain=domain,
            is_expired=is_expired,
        )

        # Combine similarity with fact confidence
        # 60% similarity, 40% fact confidence — similar to pipeline weights
        combined = similarity * 0.6 + base_score * 0.4
        combined = round(max(0.0, min(1.0, combined)), 4)

        explanation.notes.insert(0, f"Verification: sim={similarity:.3f} × 0.6 + conf={base_score:.3f} × 0.4 = {combined:.3f}")
        explanation.final_score = combined
        explanation.confidence_level = ConfidenceLevel.from_score(combined)

        return combined, explanation

    # ── Internal Scoring Methods ────────────────────────────────────

    def _source_score(self, source_scores: List[float]) -> float:
        """Weighted average of source authority scores."""
        if not source_scores:
            return 0.5
        return round(sum(source_scores) / len(source_scores), 4)

    def _corroboration_score(self, source_scores: List[float], sources_agree: bool) -> float:
        """
        Corroboration bonus: more sources agreeing → higher score.
        Uses diminishing returns: 1 source = 0.5, 2 = 0.7, 3 = 0.85, 5+ = ~0.95
        If sources disagree, corroboration drops to 0.2.
        """
        n = len(source_scores)
        if n <= 1:
            return 0.5

        if not sources_agree:
            return 0.2

        # Diminishing returns curve: 1 - 1/n gives nice progression
        # 1 src: 0.5, 2: 0.65, 3: 0.77, 4: 0.84, 5: 0.88, 10: 0.95
        score = 0.5 + 0.5 * (1 - 1 / n)
        return round(min(score, 1.0), 4)

    def _recency_score(self, age_days: float) -> float:
        """
        Exponential decay based on age.
        Half-life: score halves every RECENCY_HALF_LIFE_YEARS years.
        score = 0.5 ^ (age_years / half_life)
        """
        if age_days <= 0:
            return 1.0
        age_years = age_days / 365.25
        score = 0.5 ** (age_years / self._half_life)
        return round(max(0.01, score), 4)

    def _contradiction_score(self, source_scores: List[float], sources_agree: bool) -> float:
        """
        Contradiction penalty: 1.0 if no contradiction, lower if disagreement.
        Higher-authority disagreements are penalized more.
        """
        if sources_agree:
            return 1.0

        n = len(source_scores)
        if n <= 1:
            return 1.0

        # Average authority of disagreeing sources
        avg_authority = sum(source_scores) / n
        # Penalty is proportional to authority (high-authority disagreement is worse)
        penalty = 1.0 - (avg_authority * 0.5)
        return round(max(0.1, penalty), 4)

    def _get_weights(self, domain: str) -> Tuple[float, float, float, float]:
        """Get scoring weights for a domain, falling back to general."""
        return self._weights.get(domain, self._weights["general"])

    # ── Configuration ───────────────────────────────────────────────

    def set_domain_weights(
        self,
        domain: str,
        source: float,
        corroboration: float,
        recency: float,
        contradiction: float,
    ) -> None:
        """Set custom weights for a domain. Weights must sum to ~1.0."""
        total = source + corroboration + recency + contradiction
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")
        self._weights[domain] = (
            round(source, 4),
            round(corroboration, 4),
            round(recency, 4),
            round(contradiction, 4),
        )

    def get_domain_weights(self, domain: str) -> Tuple[float, float, float, float]:
        """Get the current weights for a domain."""
        return self._get_weights(domain)

    @property
    def supported_domains(self) -> List[str]:
        """List all domains with configured weights."""
        return list(self._weights.keys())
