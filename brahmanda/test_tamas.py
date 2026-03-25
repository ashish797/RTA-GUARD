"""
Test suite for Phase 3.3 — Tamas Detection Protocol.

Tests:
  1. TamasState enum and TamasEvent creation
  2. Tamas state transitions (SATTVA → RAJAS → TAMAS → CRITICAL)
  3. Hysteresis (no flapping between states)
  4. Recovery scoring
  5. Escalation rules
  6. Integration with ConscienceMonitor
  7. Scope creep detection
  8. Repetitive response detection
  9. Persistence (SQLite)

Run with: ``python3 -m pytest rta-guard-mvp/brahmanda/test_tamas.py -v``
"""
import sys
import os
import json
import sqlite3
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from brahmanda.tamas import (
        TamasDetector, TamasState, TamasEvent,
        EscalationAction, TamasStore,
        TAMAS_ENTER_DRIFT, TAMAS_ENTER_VIOLATIONS, TAMAS_ENTER_CONFIDENCE,
        TAMAS_EXIT_DRIFT, TAMAS_EXIT_VIOLATIONS, TAMAS_EXIT_CONFIDENCE,
        CRITICAL_DRIFT, CRITICAL_VIOLATIONS, CRITICAL_CONFIDENCE,
    )
    from brahmanda.profiles import AgentProfile
    from brahmanda.conscience import ConscienceMonitor
    HAS_TAMAS = True
except ImportError as e:
    HAS_TAMAS = False
    _import_error = e


# ═══════════════════════════════════════════════════════════════════
# 1. TamasState enum and TamasEvent creation
# ═══════════════════════════════════════════════════════════════════


class TestTamasBasics:
    """Basic types and event creation."""

    def test_tamas_state_values(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        assert TamasState.SATTVA.value == "sattva"
        assert TamasState.RAJAS.value == "rajas"
        assert TamasState.TAMAS.value == "tamas"
        assert TamasState.CRITICAL.value == "critical"

    def test_escalation_action_values(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        assert EscalationAction.NONE.value == "none"
        assert EscalationAction.LOG_WARNING.value == "log_warning"
        assert EscalationAction.ALERT_OPERATOR.value == "alert_operator"
        assert EscalationAction.AUTO_KILL.value == "auto_kill"
        assert EscalationAction.FORENSIC_CAPTURE.value == "forensic_capture"

    def test_tamas_event_creation(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        event = TamasEvent(
            agent_id="agent-001",
            previous_state=TamasState.SATTVA,
            new_state=TamasState.RAJAS,
            trigger_reasons=["drift increasing"],
            metrics_snapshot={"drift": 0.35},
            escalation=EscalationAction.LOG_WARNING,
        )
        assert event.agent_id == "agent-001"
        assert event.new_state == TamasState.RAJAS
        assert len(event.event_id) == 16
        assert event.timestamp is not None

    def test_tamas_event_to_dict(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        event = TamasEvent(
            agent_id="agent-001",
            previous_state=TamasState.SATTVA,
            new_state=TamasState.TAMAS,
            trigger_reasons=["high drift"],
            metrics_snapshot={"drift": 0.6},
            escalation=EscalationAction.ALERT_OPERATOR,
        )
        d = event.to_dict()
        assert d["agent_id"] == "agent-001"
        assert d["previous_state"] == "sattva"
        assert d["new_state"] == "tamas"
        assert d["escalation"] == "alert_operator"
        assert d["metrics_snapshot"]["drift"] == 0.6


# ═══════════════════════════════════════════════════════════════════
# 2. Tamas State Transitions
# ═══════════════════════════════════════════════════════════════════


class TestTamasTransitions:
    """State transitions based on agent metrics."""

    def _make_profile(self, **kwargs):
        """Create an AgentProfile with specified overrides."""
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_healthy_agent_stays_sattva(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9,
            violation_rate=0.0,
            live_drift_score=0.1,
            drift_trend="stable",
            last_confidence=0.9,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.SATTVA

    def test_high_drift_enters_tamas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8,
            violation_rate=0.0,
            live_drift_score=0.55,
            drift_trend="increasing",
            last_confidence=0.8,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.TAMAS

    def test_low_confidence_high_violations_enters_tamas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.3,
            violation_rate=0.35,
            live_drift_score=0.2,
            drift_trend="stable",
            last_confidence=0.3,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.TAMAS

    def test_sustained_low_confidence_enters_tamas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile_low = self._make_profile(
            avg_confidence=0.3,
            violation_rate=0.0,
            live_drift_score=0.1,
            drift_trend="stable",
            last_confidence=0.3,
        )
        # Need 5 interactions to trigger sustained low confidence
        for i in range(6):
            state = detector.evaluate_agent("agent-001", profile_low)
        assert state == TamasState.TAMAS

    def test_critical_drift_enters_critical(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8,
            violation_rate=0.0,
            live_drift_score=0.75,
            drift_trend="increasing",
            last_confidence=0.8,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.CRITICAL

    def test_critical_violations_enters_critical(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8,
            violation_rate=0.55,
            live_drift_score=0.1,
            drift_trend="stable",
            last_confidence=0.8,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.CRITICAL

    def test_critical_low_confidence_enters_critical(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.1,
            violation_rate=0.0,
            live_drift_score=0.1,
            drift_trend="stable",
            last_confidence=0.1,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.CRITICAL

    def test_moderate_drift_enters_rajas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.7,
            violation_rate=0.1,
            live_drift_score=0.26,
            drift_trend="increasing",
            last_confidence=0.7,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.RAJAS

    def test_drift_trend_increasing_enters_rajas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.7,
            violation_rate=0.1,
            live_drift_score=0.1,
            drift_trend="increasing",
            last_confidence=0.7,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.RAJAS

    def test_transition_records_event(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-001", profile_good)

        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile_bad)

        history = detector.get_tamas_history("agent-001")
        assert len(history) == 1
        assert history[0]["previous_state"] == "sattva"
        assert history[0]["new_state"] == "tamas"


# ═══════════════════════════════════════════════════════════════════
# 3. Hysteresis (no flapping)
# ═══════════════════════════════════════════════════════════════════


class TestTamasHysteresis:
    """Hysteresis prevents rapid state changes (flapping)."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_tamas_sticky_on_mild_improvement(self):
        """Agent in TAMAS with mild improvement stays in TAMAS."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        # Enter TAMAS
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        state = detector.evaluate_agent("agent-001", profile_bad)
        assert state == TamasState.TAMAS

        # Mild improvement (drift still > exit threshold)
        profile_mild = self._make_profile(
            avg_confidence=0.7, violation_rate=0.0,
            live_drift_score=0.4, drift_trend="stable", last_confidence=0.7,
        )
        state = detector.evaluate_agent("agent-001", profile_mild)
        assert state == TamasState.TAMAS  # Still stuck in TAMAS

    def test_tamas_exits_only_with_full_recovery(self):
        """Agent exits TAMAS only when all hysteresis conditions met."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        # Enter TAMAS
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile_bad)

        # Full recovery: drift < 0.3 AND violations < 0.15 AND confidence > 0.6
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.05,
            live_drift_score=0.2, drift_trend="stable", last_confidence=0.9,
        )
        state = detector.evaluate_agent("agent-001", profile_good)
        assert state == TamasState.SATTVA

    def test_no_flapping_between_states(self):
        """Rapidly alternating metrics don't cause rapid state changes from TAMAS."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()

        # Enter TAMAS
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile_bad)

        # Mild improvement (doesn't meet hysteresis exit)
        profile_mild = self._make_profile(
            avg_confidence=0.7, violation_rate=0.0,
            live_drift_score=0.4, drift_trend="stable", last_confidence=0.7,
        )
        # Oscillate between bad and mild improvement
        states = []
        for _ in range(4):
            states.append(detector.evaluate_agent("agent-001", profile_bad))
            states.append(detector.evaluate_agent("agent-001", profile_mild))

        # All states should be TAMAS (hysteresis keeps it sticky)
        assert all(s == TamasState.TAMAS for s in states)

    def test_critical_stays_until_full_exit(self):
        """CRITICAL state is sticky until all exit conditions met."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        # Enter CRITICAL
        profile_crit = self._make_profile(
            avg_confidence=0.1, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.1,
        )
        state = detector.evaluate_agent("agent-001", profile_crit)
        assert state == TamasState.CRITICAL

        # Moderate improvement — still CRITICAL
        profile_moderate = self._make_profile(
            avg_confidence=0.5, violation_rate=0.2,
            live_drift_score=0.4, drift_trend="stable", last_confidence=0.5,
        )
        state = detector.evaluate_agent("agent-001", profile_moderate)
        assert state == TamasState.CRITICAL

        # Full exit conditions met
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.05,
            live_drift_score=0.2, drift_trend="stable", last_confidence=0.9,
        )
        state = detector.evaluate_agent("agent-001", profile_good)
        # Critical exits to RAJAS (not directly to SATTVA)
        assert state == TamasState.RAJAS


# ═══════════════════════════════════════════════════════════════════
# 4. Recovery Scoring
# ═══════════════════════════════════════════════════════════════════


class TestRecoveryScoring:
    """Recovery score calculation."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_no_events_perfect_recovery(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        assert detector.get_recovery_score("agent-001") == 1.0

    def test_sattva_high_recovery(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-001", profile)
        assert detector.get_recovery_score("agent-001") == 1.0

    def test_tamas_low_recovery(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile)
        score = detector.get_recovery_score("agent-001")
        assert score == pytest.approx(0.3, abs=0.01)

    def test_critical_zero_recovery(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.1, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.1,
        )
        detector.evaluate_agent("agent-001", profile)
        assert detector.get_recovery_score("agent-001") == 0.0

    def test_improving_state_bonus(self):
        """Transitioning from worse to better state adds recovery bonus."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        # Enter TAMAS
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile_bad)

        # Exit to SATTVA
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-001", profile_good)

        score = detector.get_recovery_score("agent-001")
        assert score > 0.3  # Higher than base SATTVA because of improvement bonus
        assert score <= 1.0

    def test_recovery_score_bounds(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.1, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.1,
        )
        detector.evaluate_agent("agent-001", profile)
        score = detector.get_recovery_score("agent-001")
        assert 0.0 <= score <= 1.0


# ═══════════════════════════════════════════════════════════════════
# 5. Escalation Rules
# ═══════════════════════════════════════════════════════════════════


class TestEscalationRules:
    """Escalation actions per state."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_sattva_no_escalation(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-001", profile)
        summary = detector.get_tamas_summary("agent-001")
        assert summary["escalation"] == "none"

    def test_rajas_log_warning(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.7, violation_rate=0.1,
            live_drift_score=0.26, drift_trend="increasing", last_confidence=0.7,
        )
        detector.evaluate_agent("agent-001", profile)
        summary = detector.get_tamas_summary("agent-001")
        assert summary["escalation"] == "log_warning"

    def test_tamas_alert_operator(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile)
        summary = detector.get_tamas_summary("agent-001")
        assert summary["escalation"] == "alert_operator"

    def test_critical_auto_kill(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.1, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.1,
        )
        detector.evaluate_agent("agent-001", profile)
        summary = detector.get_tamas_summary("agent-001")
        assert summary["escalation"] == "auto_kill"

    def test_transition_event_has_escalation(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        # Start SATTVA
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-001", profile_good)

        # Enter TAMAS
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        detector.evaluate_agent("agent-001", profile_bad)

        events = detector.get_tamas_history("agent-001")
        assert len(events) == 1
        assert events[0]["escalation"] == "alert_operator"


# ═══════════════════════════════════════════════════════════════════
# 6. Integration with ConscienceMonitor
# ═══════════════════════════════════════════════════════════════════


class TestConscienceIntegration:
    """Tamas detection integrated with ConscienceMonitor."""

    def test_conscience_has_tamas_detector(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        assert hasattr(monitor, "tamas_detector")
        assert isinstance(monitor.tamas_detector, TamasDetector)

    def test_conscience_tamas_state_endpoint(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")
        state = monitor.get_tamas_state("agent-001")
        assert state["current_state"] == "sattva"
        assert state["recovery_score"] == 1.0

    def test_conscience_records_tamas_on_interaction(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        # Record interactions that trigger TAMAS
        for _ in range(10):
            r = type("R", (), {"overall_confidence": 0.1, "claims": []})()
            monitor.record_interaction(
                "agent-001", "sess-001", r,
                violation=True, violation_type="hallucination",
            )

        state = monitor.get_tamas_state("agent-001")
        # With very low confidence and high violations, should be in TAMAS or CRITICAL
        assert state["current_state"] in ("tamas", "critical")

    def test_conscience_tamas_history(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        # Start healthy
        r_good = type("R", (), {"overall_confidence": 0.9, "claims": []})()
        for _ in range(3):
            monitor.record_interaction("agent-001", "sess-001", r_good)

        # Then degrade
        r_bad = type("R", (), {"overall_confidence": 0.1, "claims": []})()
        for _ in range(10):
            monitor.record_interaction("agent-001", "sess-001", r_bad,
                                       violation=True, violation_type="hallucination")

        history = monitor.get_tamas_history("agent-001")
        assert len(history) >= 1  # At least one transition

    def test_conscience_recovery_score(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")
        result = monitor.get_recovery_score("agent-001")
        assert "recovery_score" in result
        assert "current_state" in result


# ═══════════════════════════════════════════════════════════════════
# 7. Scope Creep Detection
# ═══════════════════════════════════════════════════════════════════


class TestScopeCreep:
    """Detecting when agents work outside authorized domains."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_scope_creep_detected(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.8,
            domains_seen=["medical", "legal", "finance"],
            authorized_domains=["medical"],
        )
        state = detector.evaluate_agent("agent-001", profile)
        # 2 unauthorized > 1 authorized → scope creep → TAMAS
        assert state == TamasState.TAMAS

    def test_no_scope_creep_within_bounds(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
            domains_seen=["medical"],
            authorized_domains=["medical", "legal"],
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.SATTVA

    def test_no_authorized_domains_skips_check(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
            domains_seen=["anything"],
            authorized_domains=[],
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.SATTVA


# ═══════════════════════════════════════════════════════════════════
# 8. Repetitive Response Detection
# ═══════════════════════════════════════════════════════════════════


class TestRepetitiveResponses:
    """Detecting hallucination loops via response repetition."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_repetitive_responses_detected(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        # Record same hash 5 times
        for _ in range(5):
            detector.record_response_hash("agent-001", 12345)

        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.RAJAS

    def test_varied_responses_no_trigger(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        # Record different hashes
        for i in range(10):
            detector.record_response_hash("agent-001", i * 1000)

        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.SATTVA

    def test_hash_history_capped(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        for i in range(50):
            detector.record_response_hash("agent-001", i)
        assert len(detector._response_hashes["agent-001"]) == 20


# ═══════════════════════════════════════════════════════════════════
# 9. Persistence (SQLite)
# ═══════════════════════════════════════════════════════════════════


class TestTamasPersistence:
    """SQLite persistence for Tamas events."""

    def test_store_creates_schema(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        store = TamasStore(conn)
        # Schema should be created
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tamas_events'"
        ).fetchall()
        assert len(tables) == 1

    def test_save_and_retrieve_event(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        store = TamasStore(conn)

        event = TamasEvent(
            agent_id="agent-001",
            previous_state=TamasState.SATTVA,
            new_state=TamasState.TAMAS,
            trigger_reasons=["high drift"],
            metrics_snapshot={"drift": 0.6},
            escalation=EscalationAction.ALERT_OPERATOR,
        )
        store.save_event(event)

        events = store.get_events("agent-001")
        assert len(events) == 1
        assert events[0]["new_state"] == "tamas"
        assert events[0]["escalation"] == "alert_operator"

    def test_get_all_events(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        store = TamasStore(conn)

        for i in range(3):
            event = TamasEvent(
                agent_id=f"agent-{i:03d}",
                previous_state=TamasState.SATTVA,
                new_state=TamasState.RAJAS,
            )
            store.save_event(event)

        all_events = store.get_all_events()
        assert len(all_events) == 3

    def test_conscience_persists_tamas_events(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        # Use in-memory with persistent connection
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        # Record interactions that trigger state change
        r_good = type("R", (), {"overall_confidence": 0.9, "claims": []})()
        for _ in range(3):
            monitor.record_interaction("agent-001", "sess-001", r_good)

        r_bad = type("R", (), {"overall_confidence": 0.1, "claims": []})()
        for _ in range(10):
            monitor.record_interaction("agent-001", "sess-001", r_bad,
                                       violation=True, violation_type="hallucination")

        # Check that events were persisted
        history = monitor.get_tamas_history("agent-001")
        assert len(history) >= 1


# ═══════════════════════════════════════════════════════════════════
# 10. Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestTamasEdgeCases:
    """Edge cases and boundary conditions."""

    def _make_profile(self, **kwargs):
        profile = AgentProfile(agent_id="agent-test")
        for k, v in kwargs.items():
            setattr(profile, k, v)
        return profile

    def test_unknown_agent_is_sattva(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        assert detector.get_current_state("nonexistent") == TamasState.SATTVA

    def test_empty_tamas_history(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        assert detector.get_tamas_history("nonexistent") == []

    def test_summary_unknown_agent(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        summary = detector.get_tamas_summary("nonexistent")
        assert summary["current_state"] == "sattva"
        assert summary["total_events"] == 0

    def test_multiple_agents_isolated(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()
        profile_bad = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=0.55, drift_trend="increasing", last_confidence=0.8,
        )
        profile_good = self._make_profile(
            avg_confidence=0.9, violation_rate=0.0,
            live_drift_score=0.1, drift_trend="stable", last_confidence=0.9,
        )
        detector.evaluate_agent("agent-bad", profile_bad)
        detector.evaluate_agent("agent-good", profile_good)

        assert detector.get_current_state("agent-bad") == TamasState.TAMAS
        assert detector.get_current_state("agent-good") == TamasState.SATTVA

    def test_event_id_unique(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        e1 = TamasEvent(agent_id="a1", new_state=TamasState.RAJAS)
        e2 = TamasEvent(agent_id="a1", new_state=TamasState.TAMAS)
        assert e1.event_id != e2.event_id

    def test_drift_at_boundary_values(self):
        """Test behavior at exact threshold boundaries."""
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        detector = TamasDetector()

        # Exactly at TAMAS enter threshold
        profile = self._make_profile(
            avg_confidence=0.8, violation_rate=0.0,
            live_drift_score=TAMAS_ENTER_DRIFT,
            drift_trend="stable", last_confidence=0.8,
        )
        state = detector.evaluate_agent("agent-001", profile)
        assert state == TamasState.TAMAS

    def test_conscience_unknown_agent_tamas(self):
        if not HAS_TAMAS:
            pytest.skip(f"tamas module not importable: {_import_error}")
        monitor = ConscienceMonitor(in_memory=True)
        state = monitor.get_tamas_state("nonexistent")
        assert state["current_state"] == "sattva"
