"""
RTA-GUARD — Tamas Detection Protocol (Phase 3.3)

In Vedic philosophy, Tamas (darkness/ignorance) is the lowest of the three gunas.
In RTA-GUARD, Tamas = the AI entering a degraded state where it consistently
produces low-quality, misleading, or harmful outputs.

Detection criteria:
  - Sustained low confidence (< 0.4 for > 5 interactions)
  - Increasing drift trend (3+ consecutive increases)
  - High violation rate (> 30% of recent interactions)
  - Scope creep (agent working outside authorized domains)
  - Repetitive/patterned responses (hallucination loop)

Hysteresis prevents flapping:
  - Enter Tamas: drift > 0.5 OR (violations > 0.3 AND confidence < 0.4)
  - Exit Tamas:  drift < 0.3 AND violations < 0.15 AND confidence > 0.6
"""
import json
import sqlite3
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ─── Tamas State ──────────────────────────────────────────────────


class TamasState(str, Enum):
    """Guna states for agent behavior."""
    SATTVA = "sattva"       # Pure — normal, healthy behavior
    RAJAS = "rajas"         # Active — elevated activity, mild warning
    TAMAS = "tamas"         # Dark — degraded state, human alert needed
    CRITICAL = "critical"   # Severely degraded, auto-kill warranted


class EscalationAction(str, Enum):
    """Actions triggered by state transitions."""
    NONE = "none"
    LOG_WARNING = "log_warning"
    ALERT_OPERATOR = "alert_operator"
    THROTTLE = "throttle"
    AUTO_KILL = "auto_kill"
    FORENSIC_CAPTURE = "forensic_capture"


# ─── Tamas Event ──────────────────────────────────────────────────


@dataclass
class TamasEvent:
    """Captures a Tamas state transition."""
    agent_id: str = ""
    timestamp: str = ""
    previous_state: TamasState = TamasState.SATTVA
    new_state: TamasState = TamasState.SATTVA
    trigger_reasons: List[str] = field(default_factory=list)
    metrics_snapshot: Dict[str, float] = field(default_factory=dict)
    escalation: EscalationAction = EscalationAction.NONE
    event_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            import hashlib
            raw = f"{self.agent_id}:{self.timestamp}:{self.new_state.value}"
            self.event_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "trigger_reasons": self.trigger_reasons,
            "metrics_snapshot": {k: round(v, 4) for k, v in self.metrics_snapshot.items()},
            "escalation": self.escalation.value,
        }


# ─── Thresholds with Hysteresis ───────────────────────────────────


# Entry thresholds (when to ENTER a worse state)
TAMAS_ENTER_DRIFT = 0.5
TAMAS_ENTER_VIOLATIONS = 0.3
TAMAS_ENTER_CONFIDENCE = 0.4

# Exit thresholds (when to EXIT back to a better state) — harder to satisfy
TAMAS_EXIT_DRIFT = 0.3
TAMAS_EXIT_VIOLATIONS = 0.15
TAMAS_EXIT_CONFIDENCE = 0.6

# CRITICAL thresholds
CRITICAL_DRIFT = 0.7
CRITICAL_VIOLATIONS = 0.5
CRITICAL_CONFIDENCE = 0.2

# RAJAS thresholds (mild warning state)
RAJAS_DRIFT = 0.25
RAJAS_VIOLATIONS = 0.15
RAJAS_CONFIDENCE = 0.6

# Sustained behavior windows
LOW_CONFIDENCE_WINDOW = 5         # interactions below threshold
DRIFT_TREND_WINDOW = 3            # consecutive drift increases
RECENT_INTERACTIONS_WINDOW = 10   # for violation rate calculation


# ─── Tamas Detector ───────────────────────────────────────────────


class TamasDetector:
    """
    Detects when an AI agent enters a degraded (Tamas) state.

    Uses hysteresis to prevent flapping between states — an agent must
    significantly improve to exit Tamas, not just briefly spike.
    """

    def __init__(self):
        # Per-agent current state
        self._agent_states: Dict[str, TamasState] = {}
        # Per-agent event history
        self._agent_events: Dict[str, List[TamasEvent]] = {}
        # Per-agent consecutive interactions below confidence threshold
        self._low_confidence_streaks: Dict[str, int] = {}
        # Per-agent consecutive drift increases
        self._drift_increase_streaks: Dict[str, int] = {}
        # Per-agent previous drift scores (for trend detection)
        self._prev_drift_scores: Dict[str, float] = {}
        # Per-agent response hash history (for repetition detection)
        self._response_hashes: Dict[str, List[int]] = {}

    def evaluate_agent(
        self,
        agent_id: str,
        agent_profile: Any,  # AgentProfile
    ) -> TamasState:
        """
        Evaluate an agent's current state based on its profile.

        Returns the determined TamasState and records transitions.
        """
        old_state = self._agent_states.get(agent_id, TamasState.SATTVA)

        # Extract metrics from profile
        confidence = getattr(agent_profile, "avg_confidence", 1.0)
        violation_rate = getattr(agent_profile, "violation_rate", 0.0)
        drift_score = getattr(agent_profile, "live_drift_score",
                              getattr(agent_profile, "drift_score", 0.0))
        drift_trend = getattr(agent_profile, "drift_trend", "stable")
        last_confidence = getattr(agent_profile, "last_confidence", confidence)
        domains_seen = getattr(agent_profile, "domains_seen", [])
        authorized_domains = getattr(agent_profile, "authorized_domains", [])

        # Track sustained low confidence
        if last_confidence < TAMAS_ENTER_CONFIDENCE:
            self._low_confidence_streaks[agent_id] = self._low_confidence_streaks.get(agent_id, 0) + 1
        else:
            self._low_confidence_streaks[agent_id] = 0

        # Track consecutive drift increases
        prev_drift = self._prev_drift_scores.get(agent_id, 0.0)
        if drift_score > prev_drift:
            self._drift_increase_streaks[agent_id] = self._drift_increase_streaks.get(agent_id, 0) + 1
        else:
            self._drift_increase_streaks[agent_id] = 0
        self._prev_drift_scores[agent_id] = drift_score

        # Determine new state with hysteresis
        reasons = []
        new_state = self._determine_state(
            agent_id=agent_id,
            old_state=old_state,
            confidence=confidence,
            violation_rate=violation_rate,
            drift_score=drift_score,
            drift_trend=drift_trend,
            low_conf_streak=self._low_confidence_streaks.get(agent_id, 0),
            drift_increase_streak=self._drift_increase_streaks.get(agent_id, 0),
            domains_seen=domains_seen,
            authorized_domains=authorized_domains,
            reasons=reasons,
        )

        # Record transition if state changed
        if new_state != old_state:
            event = self.detect_tamas_transition(
                agent_id=agent_id,
                old_state=old_state,
                new_state=new_state,
                reasons=reasons,
                metrics={
                    "confidence": confidence,
                    "violation_rate": violation_rate,
                    "drift_score": drift_score,
                    "low_confidence_streak": self._low_confidence_streaks.get(agent_id, 0),
                    "drift_increase_streak": self._drift_increase_streaks.get(agent_id, 0),
                },
            )
            if agent_id not in self._agent_events:
                self._agent_events[agent_id] = []
            self._agent_events[agent_id].append(event)

        self._agent_states[agent_id] = new_state
        return new_state

    def _determine_state(
        self,
        agent_id: str,
        old_state: TamasState,
        confidence: float,
        violation_rate: float,
        drift_score: float,
        drift_trend: str,
        low_conf_streak: int,
        drift_increase_streak: int,
        domains_seen: List[str],
        authorized_domains: List[str],
        reasons: List[str],
    ) -> TamasState:
        """
        Determine the agent's state with hysteresis.

        Uses different thresholds for entering vs exiting states
        to prevent rapid flapping.
        """
        # Check for CRITICAL first (worst state)
        critical_signals = []
        if drift_score >= CRITICAL_DRIFT:
            critical_signals.append(f"drift={drift_score:.3f} >= {CRITICAL_DRIFT}")
        if violation_rate >= CRITICAL_VIOLATIONS:
            critical_signals.append(f"violations={violation_rate:.3f} >= {CRITICAL_VIOLATIONS}")
        if confidence <= CRITICAL_CONFIDENCE:
            critical_signals.append(f"confidence={confidence:.3f} <= {CRITICAL_CONFIDENCE}")

        if critical_signals:
            reasons.extend(critical_signals)
            return TamasState.CRITICAL

        # If currently in CRITICAL, need ALL exit conditions to improve
        if old_state == TamasState.CRITICAL:
            if (drift_score < TAMAS_EXIT_DRIFT and
                    violation_rate < TAMAS_EXIT_VIOLATIONS and
                    confidence > TAMAS_EXIT_CONFIDENCE):
                reasons.append("exiting critical: all metrics improved")
                # Drop to RAJAS, not directly to SATTVA
                return TamasState.RAJAS
            return TamasState.CRITICAL

        # Check for TAMAS entry
        tamas_signals = []

        # Hysteresis entry: drift > 0.5 OR (violations > 0.3 AND confidence < 0.4)
        if drift_score >= TAMAS_ENTER_DRIFT:
            tamas_signals.append(f"drift={drift_score:.3f} >= {TAMAS_ENTER_DRIFT}")
        if violation_rate >= TAMAS_ENTER_VIOLATIONS and confidence < TAMAS_ENTER_CONFIDENCE:
            tamas_signals.append(
                f"violations={violation_rate:.3f} >= {TAMAS_ENTER_VIOLATIONS} AND "
                f"confidence={confidence:.3f} < {TAMAS_ENTER_CONFIDENCE}"
            )

        # Additional TAMAS signals
        if low_conf_streak >= LOW_CONFIDENCE_WINDOW:
            tamas_signals.append(f"sustained_low_confidence={low_conf_streak}_interactions")
        if drift_increase_streak >= DRIFT_TREND_WINDOW:
            tamas_signals.append(f"drift_increasing_streak={drift_increase_streak}")
        if drift_trend == "increasing" and drift_score > 0.3:
            tamas_signals.append(f"drift_trend_increasing with drift={drift_score:.3f}")

        # Scope creep detection
        if authorized_domains:
            unauthorized = [d for d in domains_seen if d not in authorized_domains]
            if len(unauthorized) > len(authorized_domains):
                tamas_signals.append(f"scope_creep: {len(unauthorized)} unauthorized domains")

        if tamas_signals:
            reasons.extend(tamas_signals)
            return TamasState.TAMAS

        # If currently in TAMAS, need hysteresis exit conditions
        if old_state == TamasState.TAMAS:
            if (drift_score < TAMAS_EXIT_DRIFT and
                    violation_rate < TAMAS_EXIT_VIOLATIONS and
                    confidence > TAMAS_EXIT_CONFIDENCE):
                reasons.append("exiting tamas: all metrics improved beyond hysteresis thresholds")
                return TamasState.SATTVA
            # Stay in TAMAS if exit conditions not met
            reasons.append("remaining in tamas: hysteresis exit not reached")
            return TamasState.TAMAS

        # Check for RAJAS (mild warning)
        rajas_signals = []
        if drift_score >= RAJAS_DRIFT:
            rajas_signals.append(f"drift={drift_score:.3f} >= {RAJAS_DRIFT}")
        if violation_rate >= RAJAS_VIOLATIONS:
            rajas_signals.append(f"violations={violation_rate:.3f} >= {RAJAS_VIOLATIONS}")
        if confidence < RAJAS_CONFIDENCE:
            rajas_signals.append(f"confidence={confidence:.3f} < {RAJAS_CONFIDENCE}")
        if drift_trend == "increasing":
            rajas_signals.append("drift_trend=increasing")

        if rajas_signals:
            reasons.extend(rajas_signals)
            return TamasState.RAJAS

        # Check for repetitive responses (hallucination loop detection)
        response_hashes = self._response_hashes.get(agent_id, [])
        if len(response_hashes) >= 5:
            unique = len(set(response_hashes[-5:]))
            if unique <= 2:
                reasons.append(f"repetitive_responses: {unique} unique in last 5")
                return TamasState.RAJAS

        return TamasState.SATTVA

    def detect_tamas_transition(
        self,
        agent_id: str,
        old_state: TamasState,
        new_state: TamasState,
        reasons: Optional[List[str]] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> TamasEvent:
        """Create a TamasEvent for a state transition."""
        escalation = self._get_escalation(new_state)

        event = TamasEvent(
            agent_id=agent_id,
            previous_state=old_state,
            new_state=new_state,
            trigger_reasons=reasons or [],
            metrics_snapshot=metrics or {},
            escalation=escalation,
        )

        logger.info(
            "Tamas transition: %s %s → %s (escalation=%s)",
            agent_id, old_state.value, new_state.value, escalation.value,
        )

        return event

    def _get_escalation(self, state: TamasState) -> EscalationAction:
        """Get the escalation action for a given state."""
        if state == TamasState.SATTVA:
            return EscalationAction.NONE
        elif state == TamasState.RAJAS:
            return EscalationAction.LOG_WARNING
        elif state == TamasState.TAMAS:
            return EscalationAction.ALERT_OPERATOR
        elif state == TamasState.CRITICAL:
            return EscalationAction.AUTO_KILL
        return EscalationAction.NONE

    def get_tamas_history(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get Tamas event history for an agent."""
        events = self._agent_events.get(agent_id, [])
        return [e.to_dict() for e in events]

    def get_current_state(self, agent_id: str) -> TamasState:
        """Get the current Tamas state for an agent."""
        return self._agent_states.get(agent_id, TamasState.SATTVA)

    def get_recovery_score(self, agent_id: str) -> float:
        """
        Calculate how well an agent is recovering (0.0-1.0).

        Based on:
        - Time since last Tamas event
        - Trend of state transitions (should be improving)
        - Current metrics vs thresholds
        """
        events = self._agent_events.get(agent_id, [])
        if not events:
            return 1.0  # No events = healthy

        current_state = self._agent_states.get(agent_id, TamasState.SATTVA)

        # Base score from current state
        state_scores = {
            TamasState.SATTVA: 1.0,
            TamasState.RAJAS: 0.6,
            TamasState.TAMAS: 0.3,
            TamasState.CRITICAL: 0.0,
        }
        score = state_scores[current_state]

        # Bonus for recent improvement
        if len(events) >= 2:
            last = events[-1]
            prev = events[-2]
            # Improving
            state_order = {
                TamasState.CRITICAL: 0,
                TamasState.TAMAS: 1,
                TamasState.RAJAS: 2,
                TamasState.SATTVA: 3,
            }
            if state_order[last.new_state] > state_order[prev.new_state]:
                score = min(1.0, score + 0.2)

        return round(score, 4)

    def get_tamas_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get a complete Tamas summary for an agent."""
        current = self.get_current_state(agent_id)
        events = self.get_tamas_history(agent_id)
        recovery = self.get_recovery_score(agent_id)

        state_transitions = [e for e in events if e["new_state"] != e["previous_state"]]

        return {
            "agent_id": agent_id,
            "current_state": current.value,
            "recovery_score": recovery,
            "total_events": len(events),
            "state_transitions": len(state_transitions),
            "escalation": self._get_escalation(current).value,
            "low_confidence_streak": self._low_confidence_streaks.get(agent_id, 0),
            "drift_increase_streak": self._drift_increase_streaks.get(agent_id, 0),
            "recent_events": events[-5:] if events else [],
        }

    def record_response_hash(self, agent_id: str, response_hash: int):
        """Record a response hash for repetition detection."""
        if agent_id not in self._response_hashes:
            self._response_hashes[agent_id] = []
        self._response_hashes[agent_id].append(response_hash)
        if len(self._response_hashes[agent_id]) > 20:
            self._response_hashes[agent_id] = self._response_hashes[agent_id][-20:]


# ─── Persistence (SQLite) ────────────────────────────────────────


TAMAS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tamas_events (
    event_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    trigger_reasons TEXT NOT NULL,
    metrics_snapshot TEXT NOT NULL,
    escalation TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tamas_agent ON tamas_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_tamas_timestamp ON tamas_events(timestamp);
"""


class TamasStore:
    """SQLite persistence for TamasEvents."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.executescript(TAMAS_SCHEMA_SQL)

    def save_event(self, event: TamasEvent):
        """Persist a TamasEvent."""
        self._conn.execute(
            """INSERT OR REPLACE INTO tamas_events
               (event_id, agent_id, timestamp, previous_state, new_state,
                trigger_reasons, metrics_snapshot, escalation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.agent_id,
                event.timestamp,
                event.previous_state.value,
                event.new_state.value,
                json.dumps(event.trigger_reasons),
                json.dumps(event.metrics_snapshot),
                event.escalation.value,
            ),
        )
        self._conn.commit()

    def get_events(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get all Tamas events for an agent."""
        rows = self._conn.execute(
            """SELECT * FROM tamas_events WHERE agent_id = ?
               ORDER BY timestamp ASC""",
            (agent_id,),
        ).fetchall()

        events = []
        for row in rows:
            events.append({
                "event_id": row["event_id"],
                "agent_id": row["agent_id"],
                "timestamp": row["timestamp"],
                "previous_state": row["previous_state"],
                "new_state": row["new_state"],
                "trigger_reasons": json.loads(row["trigger_reasons"]),
                "metrics_snapshot": json.loads(row["metrics_snapshot"]),
                "escalation": row["escalation"],
            })
        return events

    def get_all_events(self) -> List[Dict[str, Any]]:
        """Get all Tamas events."""
        rows = self._conn.execute(
            "SELECT * FROM tamas_events ORDER BY timestamp DESC"
        ).fetchall()

        events = []
        for row in rows:
            events.append({
                "event_id": row["event_id"],
                "agent_id": row["agent_id"],
                "timestamp": row["timestamp"],
                "previous_state": row["previous_state"],
                "new_state": row["new_state"],
                "trigger_reasons": json.loads(row["trigger_reasons"]),
                "metrics_snapshot": json.loads(row["metrics_snapshot"]),
                "escalation": row["escalation"],
            })
        return events
