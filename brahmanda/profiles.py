"""
RTA-GUARD — Behavioral Profiles (Phase 3.1)

Persistent behavioral profiles for AI agents, sessions, and users.
Tracks confidence trends, violation rates, claim accuracy, and drift
over time for the Conscience Monitor.

Storage: SQLite (data/conscience.db) for persistence, with in-memory fallback.
"""
import json
import math
import sqlite3
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ─── Drift thresholds ──────────────────────────────────────────────

ANOMALY_CONFIDENCE_DROP = 0.15   # avg_confidence drops by >15% from baseline
ANOMALY_VIOLATION_SPIKE = 2.0    # violation_rate > 2x baseline
ANOMALY_DRIFT_THRESHOLD = 0.3   # drift_score > 0.3 is suspicious
MIN_INTERACTIONS_FOR_BASELINE = 5  # Need N interactions before baseline is reliable


class AnomalyType(str, Enum):
    NONE = "none"
    CONFIDENCE_DROP = "confidence_drop"
    VIOLATION_SPIKE = "violation_spike"
    DRIFT_HIGH = "drift_high"
    ACCURACY_DROP = "accuracy_drop"
    COMBINED = "combined"


# ─── Live Drift Thresholds (Phase 3.2) ─────────────────────────────

class DriftLevel(str, Enum):
    """Drift severity levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


DRIFT_HEALTHY_MAX = 0.15
DRIFT_DEGRADED_MAX = 0.35
DRIFT_UNHEALTHY_MAX = 0.60


def classify_drift(score: float) -> DriftLevel:
    """Classify a drift score into a DriftLevel."""
    if score < DRIFT_HEALTHY_MAX:
        return DriftLevel.HEALTHY
    elif score < DRIFT_DEGRADED_MAX:
        return DriftLevel.DEGRADED
    elif score < DRIFT_UNHEALTHY_MAX:
        return DriftLevel.UNHEALTHY
    else:
        return DriftLevel.CRITICAL


@dataclass
class DriftComponents:
    """Breakdown of the 5 drift components (matching AnRtaDriftRule)."""
    semantic: float = 0.0
    alignment: float = 0.0
    scope: float = 0.0
    confidence: float = 0.0
    rule_proximity: float = 0.0

    def weighted_score(self) -> float:
        """Compute weighted chaos score from components."""
        score = (
            0.30 * self.semantic
            + 0.25 * self.alignment
            + 0.20 * self.scope
            + 0.15 * self.confidence
            + 0.10 * self.rule_proximity
        )
        return round(max(0.0, min(score, 1.0)), 4)

    def to_dict(self) -> dict:
        return {
            "semantic": round(self.semantic, 4),
            "alignment": round(self.alignment, 4),
            "scope": round(self.scope, 4),
            "confidence": round(self.confidence, 4),
            "rule_proximity": round(self.rule_proximity, 4),
            "weighted_score": self.weighted_score(),
        }


@dataclass
class AgentProfile:
    """
    Persistent behavioral profile for an AI agent.

    Tracks long-term trends across all sessions and interactions.
    Rolling averages are updated incrementally (online mean).
    """
    agent_id: str = ""
    avg_confidence: float = 1.0
    violation_rate: float = 0.0       # violations / interactions
    claim_accuracy: float = 1.0       # verified claims / total claims
    drift_score: float = 0.0          # 0.0 = stable, 1.0 = maximum drift
    interaction_count: int = 0
    violation_count: int = 0
    claim_total: int = 0
    claim_verified: int = 0
    domains_seen: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    last_confidence: float = 1.0      # Most recent confidence for drift calc
    confidence_history: List[float] = field(default_factory=list)  # Last N confidences
    # Live drift tracking (Phase 3.2)
    live_drift_score: float = 0.0          # EMA-smoothed drift score
    live_drift_level: str = "healthy"      # DriftLevel value
    drift_components: Dict[str, float] = field(default_factory=dict)  # latest component breakdown
    drift_trend: str = "stable"            # "increasing", "stable", "decreasing"
    drift_history: List[float] = field(default_factory=list)  # last N drift scores

    def __post_init__(self):
        if not self.first_seen:
            self.first_seen = datetime.now(timezone.utc).isoformat()
        if not self.last_seen:
            self.last_seen = self.first_seen

    def update_from_verification(
        self,
        confidence: float,
        claims_verified: int = 1,
        claims_total: int = 1,
        domain: str = "general",
    ):
        """Update profile from a verification result."""
        self.interaction_count += 1
        self.claim_total += claims_total
        self.claim_verified += claims_verified

        # Rolling average confidence (online mean)
        n = self.interaction_count
        self.avg_confidence = self.avg_confidence * ((n - 1) / n) + confidence / n

        # Claim accuracy
        if self.claim_total > 0:
            self.claim_accuracy = self.claim_verified / self.claim_total

        # Drift: how much the latest confidence deviates from rolling average
        if n > 1:
            delta = abs(confidence - self.avg_confidence)
            # Exponential moving average for drift
            alpha = 0.3
            self.drift_score = alpha * delta + (1 - alpha) * self.drift_score

        self.last_confidence = confidence
        self.last_seen = datetime.now(timezone.utc).isoformat()

        # Keep last 50 confidences for history
        self.confidence_history.append(confidence)
        if len(self.confidence_history) > 50:
            self.confidence_history = self.confidence_history[-50:]

        # Track domains
        if domain and domain not in self.domains_seen:
            self.domains_seen.append(domain)

    def update_from_violation(
        self,
        violation_type: str = "",
        severity: float = 1.0,
        domain: str = "general",
    ):
        """Update profile from a rule violation."""
        self.violation_count += 1
        if self.interaction_count > 0:
            self.violation_rate = self.violation_count / self.interaction_count

        # Violation increases drift
        self.drift_score = min(1.0, self.drift_score + 0.1 * severity)
        self.last_seen = datetime.now(timezone.utc).isoformat()

        if domain and domain not in self.domains_seen:
            self.domains_seen.append(domain)

    def get_score(self) -> float:
        """
        Overall agent health score (0.0 = bad, 1.0 = healthy).
        Weighted combination of confidence, accuracy, and inverse violation rate.
        """
        if self.interaction_count == 0:
            return 1.0  # No data = assume healthy

        confidence_score = self.avg_confidence
        accuracy_score = self.claim_accuracy
        violation_score = 1.0 - min(1.0, self.violation_rate)
        drift_score = 1.0 - self.drift_score

        # Weighted average: confidence and accuracy matter most
        health = (
            0.35 * confidence_score
            + 0.30 * accuracy_score
            + 0.20 * violation_score
            + 0.15 * drift_score
        )
        return round(max(0.0, min(1.0, health)), 4)

    def is_anomalous(self, baseline: Optional["AgentProfile"] = None) -> Tuple[bool, AnomalyType, str]:
        """
        Check if current behavior is anomalous.

        Without a baseline: check against absolute thresholds.
        With a baseline: compare current behavior to historical baseline.
        """
        if self.interaction_count < MIN_INTERACTIONS_FOR_BASELINE:
            return False, AnomalyType.NONE, "Insufficient data for anomaly detection"

        anomalies = []
        anomaly_types = []

        # Absolute threshold checks
        if self.drift_score > ANOMALY_DRIFT_THRESHOLD:
            anomalies.append(f"drift_score={self.drift_score:.3f} > {ANOMALY_DRIFT_THRESHOLD}")
            anomaly_types.append(AnomalyType.DRIFT_HIGH)

        if self.violation_rate > 0.5:
            anomalies.append(f"violation_rate={self.violation_rate:.3f} > 0.5")
            anomaly_types.append(AnomalyType.VIOLATION_SPIKE)

        if self.avg_confidence < 0.4:
            anomalies.append(f"avg_confidence={self.avg_confidence:.3f} < 0.4")
            anomaly_types.append(AnomalyType.CONFIDENCE_DROP)

        # Baseline comparison
        if baseline and baseline.sample_count >= MIN_INTERACTIONS_FOR_BASELINE:
            baseline_conf = getattr(baseline, "avg_confidence", getattr(baseline, "baseline_confidence", 1.0))
            baseline_vrate = getattr(baseline, "violation_rate", getattr(baseline, "baseline_violation_rate", 0.0))
            baseline_acc = getattr(baseline, "claim_accuracy", getattr(baseline, "baseline_accuracy", 1.0))

            if self.avg_confidence < baseline_conf - ANOMALY_CONFIDENCE_DROP:
                anomalies.append(
                    f"confidence_drop: {self.avg_confidence:.3f} vs baseline {baseline_conf:.3f}"
                )
                anomaly_types.append(AnomalyType.CONFIDENCE_DROP)

            if baseline_vrate > 0 and self.violation_rate > baseline_vrate * ANOMALY_VIOLATION_SPIKE:
                anomalies.append(
                    f"violation_spike: {self.violation_rate:.3f} vs baseline {baseline_vrate:.3f}"
                )
                anomaly_types.append(AnomalyType.VIOLATION_SPIKE)

            if self.claim_accuracy < baseline_acc - ANOMALY_CONFIDENCE_DROP:
                anomalies.append(
                    f"accuracy_drop: {self.claim_accuracy:.3f} vs baseline {baseline_acc:.3f}"
                )
                anomaly_types.append(AnomalyType.ACCURACY_DROP)

        if not anomalies:
            return False, AnomalyType.NONE, "Behavior within normal range"

        # Determine combined vs single type
        if len(anomaly_types) > 1:
            atype = AnomalyType.COMBINED
        else:
            atype = anomaly_types[0]

        return True, atype, "; ".join(anomalies)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "avg_confidence": round(self.avg_confidence, 4),
            "violation_rate": round(self.violation_rate, 4),
            "claim_accuracy": round(self.claim_accuracy, 4),
            "drift_score": round(self.drift_score, 4),
            "interaction_count": self.interaction_count,
            "violation_count": self.violation_count,
            "claim_total": self.claim_total,
            "claim_verified": self.claim_verified,
            "domains_seen": self.domains_seen,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "health_score": self.get_score(),
            "confidence_history_len": len(self.confidence_history),
            # Live drift fields (Phase 3.2)
            "live_drift_score": round(self.live_drift_score, 4),
            "live_drift_level": self.live_drift_level,
            "drift_components": self.drift_components,
            "drift_trend": self.drift_trend,
            "drift_history": self.drift_history[-50:],  # persist last 50
            "drift_history_len": len(self.drift_history),
        }


@dataclass
class SessionProfile:
    """
    Per-session behavioral snapshot.

    Tracks behavior within a single session for intra-session drift detection.
    """
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    start_time: str = ""
    end_time: str = ""
    interaction_count: int = 0
    avg_confidence: float = 1.0
    violation_count: int = 0
    claim_total: int = 0
    claim_verified: int = 0
    domains_seen: List[str] = field(default_factory=list)
    confidence_timeline: List[Tuple[str, float]] = field(default_factory=list)  # (timestamp, confidence)

    def __post_init__(self):
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()

    def update_from_verification(
        self,
        confidence: float,
        claims_verified: int = 1,
        claims_total: int = 1,
        domain: str = "general",
    ):
        """Update session profile from a verification result."""
        self.interaction_count += 1
        self.claim_total += claims_total
        self.claim_verified += claims_verified

        n = self.interaction_count
        self.avg_confidence = self.avg_confidence * ((n - 1) / n) + confidence / n

        self.confidence_timeline.append((
            datetime.now(timezone.utc).isoformat(),
            confidence,
        ))
        self.end_time = datetime.now(timezone.utc).isoformat()

        if domain and domain not in self.domains_seen:
            self.domains_seen.append(domain)

    def update_from_violation(self, domain: str = "general"):
        """Update session profile from a violation."""
        self.violation_count += 1
        if domain and domain not in self.domains_seen:
            self.domains_seen.append(domain)

    def get_drift(self) -> float:
        """
        Calculate intra-session drift.

        Compares first half confidence average to second half.
        Returns 0.0 (no drift) to 1.0 (maximum drift).
        """
        if len(self.confidence_timeline) < 2:
            return 0.0

        confs = [c for _, c in self.confidence_timeline]
        mid = len(confs) // 2
        first_half = sum(confs[:mid]) / mid if mid > 0 else 1.0
        second_half = sum(confs[mid:]) / (len(confs) - mid) if (len(confs) - mid) > 0 else 1.0

        drift = abs(first_half - second_half)
        return round(min(1.0, drift), 4)

    def get_health(self) -> float:
        """Session health score (0.0-1.0)."""
        if self.interaction_count == 0:
            return 1.0

        conf = self.avg_confidence
        violation_factor = 1.0 - min(1.0, self.violation_count / max(1, self.interaction_count))
        drift_factor = 1.0 - self.get_drift()

        return round(0.5 * conf + 0.3 * violation_factor + 0.2 * drift_factor, 4)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "interaction_count": self.interaction_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "violation_count": self.violation_count,
            "claim_total": self.claim_total,
            "claim_verified": self.claim_verified,
            "domains_seen": self.domains_seen,
            "confidence_timeline": self.confidence_timeline,
            "confidence_timeline_len": len(self.confidence_timeline),
        }


@dataclass
class UserProfile:
    """
    Per-user behavioral pattern.

    Aggregates behavior across all sessions for a given user.
    Detects user-level patterns like frequent provocation of violations.
    """
    user_id: str = ""
    session_count: int = 0
    total_interactions: int = 0
    avg_confidence: float = 1.0
    total_violations: int = 0
    violation_rate: float = 0.0
    domains_seen: List[str] = field(default_factory=list)
    agent_ids: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    provocation_score: float = 0.0  # How often user triggers violations

    def __post_init__(self):
        if not self.first_seen:
            self.first_seen = datetime.now(timezone.utc).isoformat()
        if not self.last_seen:
            self.last_seen = self.first_seen

    def update_from_session(self, session: SessionProfile):
        """Update user profile from a completed session."""
        self.session_count += 1
        self.total_interactions += session.interaction_count
        self.total_violations += session.violation_count

        if self.total_interactions > 0:
            self.violation_rate = self.total_violations / self.total_interactions

        # Rolling average confidence
        n = self.total_interactions
        if n > 0:
            old_n = n - session.interaction_count
            if old_n > 0:
                self.avg_confidence = (
                    self.avg_confidence * old_n + session.avg_confidence * session.interaction_count
                ) / n
            else:
                self.avg_confidence = session.avg_confidence

        # Track agent
        if session.agent_id and session.agent_id not in self.agent_ids:
            self.agent_ids.append(session.agent_id)

        # Track domains
        for d in session.domains_seen:
            if d not in self.domains_seen:
                self.domains_seen.append(d)

        # Provocation score: ratio of sessions with violations
        if session.violation_count > 0:
            sessions_with_violations = self.total_violations  # Approximate
            self.provocation_score = min(1.0, sessions_with_violations / max(1, self.session_count))

        self.last_seen = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_count": self.session_count,
            "total_interactions": self.total_interactions,
            "avg_confidence": round(self.avg_confidence, 4),
            "total_violations": self.total_violations,
            "violation_rate": round(self.violation_rate, 4),
            "provocation_score": round(self.provocation_score, 4),
            "domains_seen": self.domains_seen,
            "agent_ids": self.agent_ids,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }
