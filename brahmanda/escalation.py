"""
RTA-GUARD — Escalation Protocols (Phase 3.6)

Unified escalation chain that aggregates signals from all Phase 3 subsystems
(drift, Tamas, temporal consistency, user behavior, violation rate) and decides
what action to take.

Escalation Levels:
  OBSERVE  — Log only, continue normal operation
  WARN     — Log warning, notify operator, continue
  THROTTLE — Reduce agent autonomy, log, continue
  ALERT    — Stop agent, require human intervention
  KILL     — Terminate session, trigger forensic capture

Signal Sources:
  - Drift score (LiveDriftScorer / Phase 3.2)
  - Tamas state (TamasDetector / Phase 3.3)
  - Temporal consistency level (TemporalConsistencyChecker / Phase 3.4)
  - User risk level (UserBehaviorTracker / Phase 3.5)
  - Violation rate (AgentProfile / Phase 3.1)

Rules:
  - Drift > 0.8 → ALERT
  - Tamas == CRITICAL → KILL
  - Temporal == CHAOTIC → THROTTLE
  - User risk == CRITICAL → KILL
  - Multiple signals > 0.5 → escalate one level
  - Configurable thresholds per deployment
"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


# ─── Escalation Level ─────────────────────────────────────────────


class EscalationLevel(str, Enum):
    """Escalation levels in order of severity."""
    OBSERVE = "observe"
    WARN = "warn"
    THROTTLE = "throttle"
    ALERT = "alert"
    KILL = "kill"

    @property
    def severity(self) -> int:
        """Numeric severity for comparison."""
        return {
            EscalationLevel.OBSERVE: 0,
            EscalationLevel.WARN: 1,
            EscalationLevel.THROTTLE: 2,
            EscalationLevel.ALERT: 3,
            EscalationLevel.KILL: 4,
        }[self]

    def __ge__(self, other):
        if isinstance(other, EscalationLevel):
            return self.severity >= other.severity
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, EscalationLevel):
            return self.severity > other.severity
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, EscalationLevel):
            return self.severity <= other.severity
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, EscalationLevel):
            return self.severity < other.severity
        return NotImplemented


# ─── Escalation Decision ──────────────────────────────────────────


@dataclass
class EscalationDecision:
    """
    The output of the escalation evaluation.
    Contains what action to take and why.
    """
    level: EscalationLevel = EscalationLevel.OBSERVE
    reasons: List[str] = field(default_factory=list)
    signal_scores: Dict[str, float] = field(default_factory=dict)
    aggregate_score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    agent_id: str = ""
    triggered_rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "reasons": self.reasons,
            "signal_scores": self.signal_scores,
            "aggregate_score": round(self.aggregate_score, 4),
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "triggered_rules": self.triggered_rules,
        }

    @property
    def should_kill(self) -> bool:
        return self.level == EscalationLevel.KILL

    @property
    def should_alert(self) -> bool:
        return self.level >= EscalationLevel.ALERT

    @property
    def should_throttle(self) -> bool:
        return self.level >= EscalationLevel.THROTTLE


# ─── Escalation Config ────────────────────────────────────────────


@dataclass
class EscalationConfig:
    """
    Configurable thresholds for escalation decisions.
    Deployments can override these per-environment.
    """
    # Per-signal kill thresholds (independent KILL triggers)
    drift_alert_threshold: float = 0.8       # Drift > 0.8 → ALERT
    drift_kill_threshold: float = 0.95       # Drift > 0.95 → KILL
    violation_rate_warn: float = 0.2         # Violation rate > 0.2 → WARN
    violation_rate_throttle: float = 0.4     # Violation rate > 0.4 → THROTTLE
    violation_rate_kill: float = 0.6         # Violation rate > 0.6 → KILL
    user_risk_kill: float = 0.85            # User risk > 0.85 → KILL

    # Weighted decision matrix weights
    weight_drift: float = 0.25
    weight_tamas: float = 0.25
    weight_temporal: float = 0.15
    weight_user_risk: float = 0.20
    weight_violation_rate: float = 0.15

    # Aggregate thresholds
    aggregate_warn: float = 0.25
    aggregate_throttle: float = 0.45
    aggregate_alert: float = 0.65
    aggregate_kill: float = 0.85

    # Multi-signal escalation: number of signals > 0.5 to trigger escalation
    multi_signal_threshold: float = 0.5
    multi_signal_count_for_escalation: int = 2

    def to_dict(self) -> dict:
        return {
            "drift_alert_threshold": self.drift_alert_threshold,
            "drift_kill_threshold": self.drift_kill_threshold,
            "violation_rate_warn": self.violation_rate_warn,
            "violation_rate_throttle": self.violation_rate_throttle,
            "violation_rate_kill": self.violation_rate_kill,
            "user_risk_kill": self.user_risk_kill,
            "weight_drift": self.weight_drift,
            "weight_tamas": self.weight_tamas,
            "weight_temporal": self.weight_temporal,
            "weight_user_risk": self.weight_user_risk,
            "weight_violation_rate": self.weight_violation_rate,
            "aggregate_warn": self.aggregate_warn,
            "aggregate_throttle": self.aggregate_throttle,
            "aggregate_alert": self.aggregate_alert,
            "aggregate_kill": self.aggregate_kill,
            "multi_signal_threshold": self.multi_signal_threshold,
            "multi_signal_count_for_escalation": self.multi_signal_count_for_escalation,
        }


# ─── Tamas → Score Mapping ────────────────────────────────────────

TAMAS_SCORE_MAP = {
    "sattva": 0.0,
    "rajas": 0.3,
    "tamas": 0.65,
    "critical": 1.0,
}

# Temporal consistency level → score mapping (inverted: chaos = high score)
TEMPORAL_SCORE_MAP = {
    "highly_consistent": 0.0,
    "consistent": 0.2,
    "inconsistent": 0.55,
    "chaotic": 0.9,
}


# ─── Escalation Chain ─────────────────────────────────────────────


class EscalationChain:
    """
    Orchestrates multi-signal escalation decisions.

    Aggregates signals from all Phase 3 subsystems, applies weighted
    scoring and per-signal override rules, then produces an
    EscalationDecision.

    Usage:
        chain = EscalationChain()
        chain.register_handler(EscalationLevel.KILL, my_kill_callback)
        decision = chain.evaluate({
            "drift_score": 0.7,
            "tamas_state": "tamas",
            "consistency_level": "inconsistent",
            "user_risk_score": 0.3,
            "violation_rate": 0.15,
        })
        chain.execute(decision)
    """

    def __init__(self, config: Optional[EscalationConfig] = None, webhook_manager: Optional[Any] = None):
        self.config = config or EscalationConfig()
        self.webhook_manager = webhook_manager  # WebhookManager (optional, Phase 4.4)
        self._handlers: Dict[EscalationLevel, List[Callable]] = {
            level: [] for level in EscalationLevel
        }
        self._decision_history: List[EscalationDecision] = []
        self._last_decision: Optional[EscalationDecision] = None

    # ── Signal Evaluation ────────────────────────────────────────

    def evaluate(
        self,
        signals: Dict[str, Any],
        session_id: str = "",
        agent_id: str = "",
    ) -> EscalationDecision:
        """
        Evaluate all signals and produce an EscalationDecision.

        Args:
            signals: Dict with optional keys:
                - drift_score: float (0.0 - 1.0)
                - tamas_state: str ("sattva", "rajas", "tamas", "critical")
                - consistency_level: str ("highly_consistent", "consistent", "inconsistent", "chaotic")
                - user_risk_score: float (0.0 - 1.0)
                - violation_rate: float (0.0 - 1.0)
            session_id: Current session ID
            agent_id: Current agent ID

        Returns:
            EscalationDecision with level, reasons, and scores
        """
        decision = EscalationDecision(
            session_id=session_id,
            agent_id=agent_id,
        )

        # ── Extract and normalize signals ──

        drift_score = float(signals.get("drift_score", 0.0) or 0.0)
        tamas_state = str(signals.get("tamas_state", "sattva") or "sattva").lower()
        consistency_level = str(signals.get("consistency_level", "highly_consistent") or "highly_consistent").lower()
        user_risk_score = float(signals.get("user_risk_score", 0.0) or 0.0)
        violation_rate = float(signals.get("violation_rate", 0.0) or 0.0)

        tamas_score = TAMAS_SCORE_MAP.get(tamas_state, 0.0)
        temporal_score = TEMPORAL_SCORE_MAP.get(consistency_level, 0.0)

        # Store signal scores
        decision.signal_scores = {
            "drift": round(drift_score, 4),
            "tamas": round(tamas_score, 4),
            "temporal": round(temporal_score, 4),
            "user_risk": round(user_risk_score, 4),
            "violation_rate": round(violation_rate, 4),
        }

        cfg = self.config

        # ── Step 1: Independent KILL triggers ──

        if tamas_state == "critical":
            decision.level = EscalationLevel.KILL
            decision.reasons.append(f"Tamas state is CRITICAL (auto-kill)")
            decision.triggered_rules.append("tamas_critical_kill")

        if user_risk_score >= cfg.user_risk_kill:
            if decision.level < EscalationLevel.KILL:
                decision.level = EscalationLevel.KILL
            decision.reasons.append(
                f"User risk score {user_risk_score:.2f} >= {cfg.user_risk_kill} (kill threshold)"
            )
            decision.triggered_rules.append("user_risk_critical_kill")

        if drift_score >= cfg.drift_kill_threshold:
            if decision.level < EscalationLevel.KILL:
                decision.level = EscalationLevel.KILL
            decision.reasons.append(
                f"Drift score {drift_score:.2f} >= {cfg.drift_kill_threshold} (kill threshold)"
            )
            decision.triggered_rules.append("drift_critical_kill")

        if violation_rate >= cfg.violation_rate_kill:
            if decision.level < EscalationLevel.KILL:
                decision.level = EscalationLevel.KILL
            decision.reasons.append(
                f"Violation rate {violation_rate:.2f} >= {cfg.violation_rate_kill} (kill threshold)"
            )
            decision.triggered_rules.append("violation_rate_kill")

        # If already KILL from independent triggers, short-circuit
        if decision.level == EscalationLevel.KILL:
            decision.aggregate_score = 1.0
            self._record_decision(decision)
            return decision

        # ── Step 2: Per-signal ALERT triggers ──

        if drift_score >= cfg.drift_alert_threshold:
            decision.level = max(decision.level, EscalationLevel.ALERT)
            decision.reasons.append(
                f"Drift score {drift_score:.2f} >= {cfg.drift_alert_threshold} (alert threshold)"
            )
            decision.triggered_rules.append("drift_alert")

        if tamas_state == "tamas":
            decision.level = max(decision.level, EscalationLevel.ALERT)
            decision.reasons.append("Tamas state is TAMAS (degraded)")
            decision.triggered_rules.append("tamas_alert")

        # ── Step 3: Per-signal THROTTLE triggers ──

        if consistency_level == "chaotic":
            decision.level = max(decision.level, EscalationLevel.THROTTLE)
            decision.reasons.append("Temporal consistency is CHAOTIC")
            decision.triggered_rules.append("temporal_chaotic_throttle")

        if violation_rate >= cfg.violation_rate_throttle:
            decision.level = max(decision.level, EscalationLevel.THROTTLE)
            decision.reasons.append(
                f"Violation rate {violation_rate:.2f} >= {cfg.violation_rate_throttle}"
            )
            decision.triggered_rules.append("violation_rate_throttle")

        # ── Step 4: Per-signal WARN triggers ──

        if violation_rate >= cfg.violation_rate_warn:
            decision.level = max(decision.level, EscalationLevel.WARN)
            decision.reasons.append(
                f"Violation rate {violation_rate:.2f} >= {cfg.violation_rate_warn}"
            )
            decision.triggered_rules.append("violation_rate_warn")

        if tamas_state == "rajas":
            decision.level = max(decision.level, EscalationLevel.WARN)
            decision.reasons.append("Tamas state is RAJAS (elevated)")
            decision.triggered_rules.append("tamas_rajas_warn")

        if consistency_level == "inconsistent":
            decision.level = max(decision.level, EscalationLevel.WARN)
            decision.reasons.append("Temporal consistency is INCONSISTENT")
            decision.triggered_rules.append("temporal_inconsistent_warn")

        # ── Step 5: Weighted aggregate score ──

        aggregate = (
            cfg.weight_drift * drift_score
            + cfg.weight_tamas * tamas_score
            + cfg.weight_temporal * temporal_score
            + cfg.weight_user_risk * user_risk_score
            + cfg.weight_violation_rate * violation_rate
        )
        decision.aggregate_score = round(aggregate, 4)

        # Apply aggregate thresholds (only raise level, never lower from per-signal rules)
        if aggregate >= cfg.aggregate_kill:
            decision.level = max(decision.level, EscalationLevel.KILL)
            decision.reasons.append(f"Aggregate score {aggregate:.2f} >= {cfg.aggregate_kill}")
            decision.triggered_rules.append("aggregate_kill")
        elif aggregate >= cfg.aggregate_alert:
            decision.level = max(decision.level, EscalationLevel.ALERT)
            decision.reasons.append(f"Aggregate score {aggregate:.2f} >= {cfg.aggregate_alert}")
            decision.triggered_rules.append("aggregate_alert")
        elif aggregate >= cfg.aggregate_throttle:
            decision.level = max(decision.level, EscalationLevel.THROTTLE)
            decision.reasons.append(f"Aggregate score {aggregate:.2f} >= {cfg.aggregate_throttle}")
            decision.triggered_rules.append("aggregate_throttle")
        elif aggregate >= cfg.aggregate_warn:
            decision.level = max(decision.level, EscalationLevel.WARN)
            decision.reasons.append(f"Aggregate score {aggregate:.2f} >= {cfg.aggregate_warn}")
            decision.triggered_rules.append("aggregate_warn")

        # ── Step 6: Multi-signal escalation ──
        # If N or more individual signals exceed threshold, escalate one level

        elevated_count = sum(
            1 for score in [
                drift_score, tamas_score, temporal_score,
                user_risk_score, violation_rate,
            ]
            if score >= cfg.multi_signal_threshold
        )
        if elevated_count >= cfg.multi_signal_count_for_escalation:
            if decision.level < EscalationLevel.KILL:
                new_level_idx = min(decision.level.severity + 1, EscalationLevel.KILL.severity)
                new_level = list(EscalationLevel)[new_level_idx]
                if new_level > decision.level:
                    decision.level = new_level
                    decision.reasons.append(
                        f"Multi-signal: {elevated_count} signals >= {cfg.multi_signal_threshold}"
                    )
                    decision.triggered_rules.append("multi_signal_escalation")

        # Ensure at least OBSERVE if nothing triggered
        if not decision.reasons:
            decision.reasons.append("All signals within normal range")

        self._record_decision(decision)
        return decision

    # ── Handler Registration ─────────────────────────────────────

    def register_handler(
        self,
        level: EscalationLevel,
        callback: Callable[[EscalationDecision], None],
    ):
        """
        Register a callback for a specific escalation level.

        Multiple handlers can be registered per level.
        Handlers are called in registration order during execute().
        """
        self._handlers[level].append(callback)

    def execute(self, decision: EscalationDecision) -> List[str]:
        """
        Execute all registered handlers for the decision's level.

        Also executes handlers for all lower levels (cumulative).
        Returns list of handler results or error messages.
        """
        results = []
        for level in EscalationLevel:
            if level.severity <= decision.level.severity:
                for handler in self._handlers[level]:
                    try:
                        handler(decision)
                        results.append(f"Handler for {level.value}: executed")
                    except Exception as e:
                        error_msg = f"Handler for {level.value} failed: {e}"
                        logger.error(error_msg)
                        results.append(error_msg)

        # Log the decision
        logger.info(
            f"Escalation [{decision.level.value.upper()}] "
            f"agent={decision.agent_id} session={decision.session_id} "
            f"score={decision.aggregate_score:.2f} "
            f"reasons={'; '.join(decision.reasons)}"
        )

        return results

    # ── Decision History ─────────────────────────────────────────

    def get_last_decision(self) -> Optional[EscalationDecision]:
        """Get the most recent escalation decision."""
        return self._last_decision

    def get_decision_history(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get recent escalation decisions."""
        return [d.to_dict() for d in self._decision_history[-limit:]]

    def _record_decision(self, decision: EscalationDecision):
        """Record a decision in history and fire webhook if escalation is significant."""
        self._last_decision = decision
        self._decision_history.append(decision)
        if len(self._decision_history) > 500:
            self._decision_history = self._decision_history[-500:]

        # Fire webhook for significant escalations (Phase 4.4)
        if self.webhook_manager and decision.level >= EscalationLevel.ALERT:
            try:
                from brahmanda.webhooks import WebhookEvent, WebhookEventType
                webhook_event = WebhookEvent(
                    event_type=WebhookEventType.ESCALATION,
                    payload=decision.to_dict(),
                    tenant_id=getattr(decision, 'tenant_id', ''),
                )
                self.webhook_manager.fire(webhook_event)
            except Exception as e:
                logger.debug(f"Escalation webhook failed: {e}")

    # ── Convenience: Build signals from subsystem state ──────────

    @staticmethod
    def build_signals(
        drift_score: float = 0.0,
        tamas_state: str = "sattva",
        consistency_level: str = "highly_consistent",
        user_risk_score: float = 0.0,
        violation_rate: float = 0.0,
    ) -> Dict[str, Any]:
        """Build a signals dict from individual component values."""
        return {
            "drift_score": drift_score,
            "tamas_state": tamas_state,
            "consistency_level": consistency_level,
            "user_risk_score": user_risk_score,
            "violation_rate": violation_rate,
        }


# ─── Convenience ──────────────────────────────────────────────────


def get_escalation_chain(config: Optional[EscalationConfig] = None) -> EscalationChain:
    """Get a configured EscalationChain instance."""
    return EscalationChain(config=config)
