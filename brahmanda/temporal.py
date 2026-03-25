"""
RTA-GUARD — Temporal Consistency Enforcement (Phase 3.4)

Tracks agent statements over time and detects contradictions between
current and historical claims. Provides consistency scoring that feeds
into drift calculation.

Consistency thresholds:
    HIGHLY_CONSISTENT: score ≥ 0.9
    CONSISTENT:        score 0.7–0.9
    INCONSISTENT:      score 0.4–0.7
    CHAOTIC:           score < 0.4

Usage:
    checker = TemporalConsistencyChecker()
    checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
    contradictions = checker.check_consistency("agent-001", "Berlin is the capital of France")
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

from .verifier import enhanced_check_contradiction

logger = logging.getLogger(__name__)

# ─── Consistency thresholds ───────────────────────────────────────


class ConsistencyLevel(str, Enum):
    """Consistency classification for an agent's temporal behavior."""
    HIGHLY_CONSISTENT = "highly_consistent"  # score ≥ 0.9
    CONSISTENT = "consistent"                # score 0.7–0.9
    INCONSISTENT = "inconsistent"            # score 0.4–0.7
    CHAOTIC = "chaotic"                      # score < 0.4


CONSISTENCY_HIGHLY_CONSISTENT_MIN = 0.9
CONSISTENCY_CONSISTENT_MIN = 0.7
CONSISTENCY_INCONSISTENT_MIN = 0.4


def classify_consistency(score: float) -> ConsistencyLevel:
    """Classify a consistency score into a ConsistencyLevel."""
    if score >= CONSISTENCY_HIGHLY_CONSISTENT_MIN:
        return ConsistencyLevel.HIGHLY_CONSISTENT
    elif score >= CONSISTENCY_CONSISTENT_MIN:
        return ConsistencyLevel.CONSISTENT
    elif score >= CONSISTENCY_INCONSISTENT_MIN:
        return ConsistencyLevel.INCONSISTENT
    else:
        return ConsistencyLevel.CHAOTIC


# ─── Data structures ──────────────────────────────────────────────


@dataclass
class Statement:
    """A single claim made by an agent at a point in time."""
    claim: str
    timestamp: float  # Unix timestamp (time.time())
    confidence: float  # 0.0–1.0
    source: str  # e.g., "user", "system", "inference"
    agent_id: str = ""

    def age_seconds(self) -> float:
        """Age of this statement in seconds."""
        return time.time() - self.timestamp

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).isoformat(),
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "agent_id": self.agent_id,
            "age_seconds": round(self.age_seconds(), 2),
        }


@dataclass
class ContradictionPair:
    """Two statements that contradict each other."""
    statement_a: Statement  # The older statement
    statement_b: Statement  # The newer statement
    similarity: float  # Semantic similarity between the two claims
    reason: str  # Why they contradict

    def to_dict(self) -> dict:
        return {
            "statement_a": self.statement_a.to_dict(),
            "statement_b": self.statement_b.to_dict(),
            "similarity": round(self.similarity, 4),
            "reason": self.reason,
        }


# ─── Similarity helper ────────────────────────────────────────────


def _word_similarity(a: str, b: str) -> float:
    """
    Simple word-overlap similarity (Jaccard index on content words).
    Used to find semantically related statements before running
    the full contradiction check.
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    # Remove very common stop words
    stops = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "to", "and", "or", "for", "on", "at", "by"}
    words_a -= stops
    words_b -= stops
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# ─── Temporal Consistency Checker ─────────────────────────────────


class TemporalConsistencyChecker:
    """
    Tracks agent statements over time and detects contradictions.

    Maintains a sliding window of the last N statements per agent.
    When a new claim is added, it checks against all existing statements
    for contradictions using the existing `enhanced_check_contradiction()`
    from the verifier.

    The consistency score is computed as:
        1 - (contradictions / total_checks)

    Where total_checks is the number of statement pairs checked.
    """

    DEFAULT_WINDOW_SIZE = 100
    # Minimum word-overlap similarity to bother checking for contradictions
    RELATEDNESS_THRESHOLD = 0.15

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE):
        self.window_size = window_size
        # Per-agent sliding window of statements
        self._statements: Dict[str, List[Statement]] = {}
        # Per-agent history of detected contradictions
        self._contradiction_history: Dict[str, List[ContradictionPair]] = {}
        # Per-agent counters for consistency scoring
        self._total_checks: Dict[str, int] = {}
        self._total_contradictions: Dict[str, int] = {}

    def add_statement(
        self,
        agent_id: str,
        claim: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> List[ContradictionPair]:
        """
        Record a claim made by an agent.

        Automatically checks the new claim against all existing statements
        for the agent. Returns any contradictions found.

        Args:
            agent_id: The agent making the claim.
            claim: The claim text.
            confidence: Confidence score for this claim (0.0–1.0).
            source: Source of the claim (e.g., "user", "system", "inference").

        Returns:
            List of ContradictionPairs if contradictions detected, else empty list.
        """
        if agent_id not in self._statements:
            self._statements[agent_id] = []
            self._contradiction_history[agent_id] = []
            self._total_checks[agent_id] = 0
            self._total_contradictions[agent_id] = 0

        statement = Statement(
            claim=claim,
            timestamp=time.time(),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            agent_id=agent_id,
        )

        # Check against existing statements BEFORE adding
        contradictions = self._check_against_existing(agent_id, statement)

        # Add to sliding window
        self._statements[agent_id].append(statement)
        if len(self._statements[agent_id]) > self.window_size:
            self._statements[agent_id] = self._statements[agent_id][-self.window_size:]

        # Record contradictions
        if contradictions:
            self._contradiction_history[agent_id].extend(contradictions)
            # Keep contradiction history bounded too
            max_contra = self.window_size * 2
            if len(self._contradiction_history[agent_id]) > max_contra:
                self._contradiction_history[agent_id] = self._contradiction_history[agent_id][-max_contra:]

        return contradictions

    def check_consistency(
        self,
        agent_id: str,
        new_claim: str,
        new_confidence: float = 1.0,
    ) -> List[ContradictionPair]:
        """
        Check a new claim against existing statements WITHOUT adding it.

        Useful for pre-flight checks before committing a claim.

        Args:
            agent_id: The agent to check against.
            new_claim: The claim to test.
            new_confidence: Confidence for the hypothetical claim.

        Returns:
            List of ContradictionPairs if contradictions detected.
        """
        if agent_id not in self._statements:
            return []

        temp_statement = Statement(
            claim=new_claim,
            timestamp=time.time(),
            confidence=new_confidence,
            source="check",
            agent_id=agent_id,
        )
        return self._check_against_existing(agent_id, temp_statement)

    def get_consistency_score(self, agent_id: str) -> float:
        """
        Get the consistency score for an agent.

        Score = 1 - (contradictions / total_checks)
        Returns 1.0 for agents with no checks (assume consistent).

        Returns:
            Float between 0.0 and 1.0.
        """
        total = self._total_checks.get(agent_id, 0)
        if total == 0:
            return 1.0

        contradictions = self._total_contradictions.get(agent_id, 0)
        score = 1.0 - (contradictions / total)
        return round(max(0.0, min(1.0, score)), 4)

    def get_consistency_level(self, agent_id: str) -> ConsistencyLevel:
        """Get the consistency level classification for an agent."""
        return classify_consistency(self.get_consistency_score(agent_id))

    def get_contradiction_history(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Get all detected contradictions for an agent.

        Returns:
            List of contradiction pair dicts, sorted newest first.
        """
        pairs = self._contradiction_history.get(agent_id, [])
        return [p.to_dict() for p in reversed(pairs)]

    def get_statement_count(self, agent_id: str) -> int:
        """Get the number of statements tracked for an agent."""
        return len(self._statements.get(agent_id, []))

    def get_contradiction_count(self, agent_id: str) -> int:
        """Get total contradictions detected for an agent."""
        return self._total_contradictions.get(agent_id, 0)

    def get_temporal_summary(self, agent_id: str) -> Dict[str, Any]:
        """
        Get a comprehensive temporal consistency summary for an agent.

        Returns:
            Dict with score, level, counts, and recent contradictions.
        """
        statements = self._statements.get(agent_id, [])
        score = self.get_consistency_score(agent_id)
        level = classify_consistency(score)
        contradictions = self._contradiction_history.get(agent_id, [])

        # Recent contradictions (last 10)
        recent = contradictions[-10:] if contradictions else []

        return {
            "agent_id": agent_id,
            "consistency_score": score,
            "consistency_level": level.value,
            "statement_count": len(statements),
            "total_checks": self._total_checks.get(agent_id, 0),
            "total_contradictions": self._total_contradictions.get(agent_id, 0),
            "window_size": self.window_size,
            "recent_contradictions": [c.to_dict() for c in reversed(recent)],
        }

    def clear_old_statements(self, agent_id: str, max_age_days: float) -> int:
        """
        Remove statements older than max_age_days.

        Args:
            agent_id: The agent to prune.
            max_age_days: Maximum age in days.

        Returns:
            Number of statements removed.
        """
        if agent_id not in self._statements:
            return 0

        cutoff = time.time() - (max_age_days * 86400)
        before = len(self._statements[agent_id])
        self._statements[agent_id] = [
            s for s in self._statements[agent_id] if s.timestamp >= cutoff
        ]
        removed = before - len(self._statements[agent_id])

        # Also prune old contradictions
        if agent_id in self._contradiction_history:
            self._contradiction_history[agent_id] = [
                c for c in self._contradiction_history[agent_id]
                if c.statement_a.timestamp >= cutoff or c.statement_b.timestamp >= cutoff
            ]

        if removed > 0:
            logger.info(f"Cleared {removed} old statements for agent {agent_id} (max_age={max_age_days}d)")

        return removed

    def clear_agent(self, agent_id: str):
        """Remove all data for an agent."""
        self._statements.pop(agent_id, None)
        self._contradiction_history.pop(agent_id, None)
        self._total_checks.pop(agent_id, None)
        self._total_contradictions.pop(agent_id, None)

    def list_agents(self) -> List[str]:
        """List all agent IDs with tracked statements."""
        return list(self._statements.keys())

    # ── Internal ──────────────────────────────────────────────────

    def _check_against_existing(
        self,
        agent_id: str,
        new_statement: Statement,
    ) -> List[ContradictionPair]:
        """
        Check a new statement against all existing statements for an agent.

        Uses word-overlap similarity to filter related statements,
        then runs `enhanced_check_contradiction()` on related pairs.
        """
        existing = self._statements.get(agent_id, [])
        if not existing:
            return []

        contradictions: List[ContradictionPair] = []

        for old_statement in existing:
            # Quick relatedness filter
            word_sim = _word_similarity(new_statement.claim, old_statement.claim)
            if word_sim < self.RELATEDNESS_THRESHOLD:
                continue

            # Count this as a check
            self._total_checks[agent_id] = self._total_checks.get(agent_id, 0) + 1

            # Full contradiction check using existing function
            contradicted, reason = enhanced_check_contradiction(
                new_statement.claim,
                old_statement.claim,
                word_sim,
            )

            if contradicted:
                pair = ContradictionPair(
                    statement_a=old_statement,  # older
                    statement_b=new_statement,  # newer
                    similarity=word_sim,
                    reason=reason,
                )
                contradictions.append(pair)
                self._total_contradictions[agent_id] = (
                    self._total_contradictions.get(agent_id, 0) + 1
                )
                logger.warning(
                    f"Temporal contradiction for {agent_id}: "
                    f"'{old_statement.claim}' vs '{new_statement.claim}' "
                    f"({reason})"
                )

        return contradictions
