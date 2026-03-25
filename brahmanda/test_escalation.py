"""
RTA-GUARD — Escalation Protocol Tests (Phase 3.6)

Tests for EscalationChain, EscalationLevel, EscalationDecision,
signal aggregation, handler registration, and integration with
ConscienceMonitor and DiscusGuard.
"""
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from brahmanda.escalation import (
    EscalationLevel,
    EscalationDecision,
    EscalationConfig,
    EscalationChain,
    get_escalation_chain,
    TAMAS_SCORE_MAP,
    TEMPORAL_SCORE_MAP,
)
from brahmanda.conscience import ConscienceMonitor


# ─── EscalationLevel Tests ────────────────────────────────────────


class TestEscalationLevel:
    def test_level_ordering(self):
        assert EscalationLevel.OBSERVE < EscalationLevel.WARN
        assert EscalationLevel.WARN < EscalationLevel.THROTTLE
        assert EscalationLevel.THROTTLE < EscalationLevel.ALERT
        assert EscalationLevel.ALERT < EscalationLevel.KILL

    def test_level_severity(self):
        assert EscalationLevel.OBSERVE.severity == 0
        assert EscalationLevel.WARN.severity == 1
        assert EscalationLevel.THROTTLE.severity == 2
        assert EscalationLevel.ALERT.severity == 3
        assert EscalationLevel.KILL.severity == 4

    def test_level_ge(self):
        assert EscalationLevel.KILL >= EscalationLevel.ALERT
        assert EscalationLevel.ALERT >= EscalationLevel.ALERT
        assert not (EscalationLevel.WARN >= EscalationLevel.THROTTLE)

    def test_level_value(self):
        assert EscalationLevel.OBSERVE.value == "observe"
        assert EscalationLevel.KILL.value == "kill"

    def test_level_max(self):
        levels = [EscalationLevel.WARN, EscalationLevel.ALERT, EscalationLevel.OBSERVE]
        assert max(levels, key=lambda l: l.severity) == EscalationLevel.ALERT


# ─── EscalationDecision Tests ─────────────────────────────────────


class TestEscalationDecision:
    def test_default_decision(self):
        d = EscalationDecision()
        assert d.level == EscalationLevel.OBSERVE
        assert d.reasons == []
        assert d.aggregate_score == 0.0

    def test_to_dict(self):
        d = EscalationDecision(
            level=EscalationLevel.WARN,
            reasons=["test"],
            aggregate_score=0.3,
        )
        d_dict = d.to_dict()
        assert d_dict["level"] == "warn"
        assert d_dict["reasons"] == ["test"]
        assert d_dict["aggregate_score"] == 0.3

    def test_should_kill(self):
        d = EscalationDecision(level=EscalationLevel.KILL)
        assert d.should_kill is True
        assert d.should_alert is True
        assert d.should_throttle is True

    def test_should_alert(self):
        d = EscalationDecision(level=EscalationLevel.ALERT)
        assert d.should_kill is False
        assert d.should_alert is True
        assert d.should_throttle is True

    def test_should_throttle(self):
        d = EscalationDecision(level=EscalationLevel.THROTTLE)
        assert d.should_kill is False
        assert d.should_alert is False
        assert d.should_throttle is True

    def test_observe_properties(self):
        d = EscalationDecision(level=EscalationLevel.OBSERVE)
        assert d.should_kill is False
        assert d.should_alert is False
        assert d.should_throttle is False


# ─── EscalationConfig Tests ───────────────────────────────────────


class TestEscalationConfig:
    def test_default_config(self):
        cfg = EscalationConfig()
        assert cfg.drift_alert_threshold == 0.8
        assert cfg.drift_kill_threshold == 0.95
        assert cfg.weight_drift == 0.25

    def test_custom_config(self):
        cfg = EscalationConfig(
            drift_alert_threshold=0.7,
            aggregate_warn=0.2,
        )
        assert cfg.drift_alert_threshold == 0.7
        assert cfg.aggregate_warn == 0.2
        # Unchanged defaults
        assert cfg.drift_kill_threshold == 0.95

    def test_to_dict(self):
        cfg = EscalationConfig()
        d = cfg.to_dict()
        assert "drift_alert_threshold" in d
        assert "weight_drift" in d
        assert "aggregate_warn" in d


# ─── EscalationChain: Normal Operation ────────────────────────────


class TestEscalationNormalOperation:
    def test_all_signals_normal_observe(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals())
        assert decision.level == EscalationLevel.OBSERVE
        assert decision.aggregate_score < 0.25

    def test_low_drift_observe(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.1,
            tamas_state="sattva",
            consistency_level="highly_consistent",
            user_risk_score=0.05,
            violation_rate=0.0,
        ))
        assert decision.level == EscalationLevel.OBSERVE
        assert "normal range" in decision.reasons[0].lower() or decision.level == EscalationLevel.OBSERVE


# ─── EscalationChain: Single Signal Elevated ──────────────────────


class TestEscalationSingleSignal:
    def test_drift_alert(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(drift_score=0.82))
        assert decision.level >= EscalationLevel.ALERT
        assert any("drift" in r.lower() for r in decision.reasons)

    def test_drift_kill(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(drift_score=0.96))
        assert decision.level == EscalationLevel.KILL

    def test_tamas_critical_kill(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(tamas_state="critical"))
        assert decision.level == EscalationLevel.KILL
        assert any("critical" in r.lower() for r in decision.reasons)

    def test_tamas_tamas_alert(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(tamas_state="tamas"))
        assert decision.level >= EscalationLevel.ALERT

    def test_tamas_rajas_warn(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(tamas_state="rajas"))
        assert decision.level >= EscalationLevel.WARN

    def test_temporal_chaotic_throttle(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(consistency_level="chaotic"))
        assert decision.level >= EscalationLevel.THROTTLE

    def test_temporal_inconsistent_warn(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(consistency_level="inconsistent"))
        assert decision.level >= EscalationLevel.WARN

    def test_user_risk_critical_kill(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(user_risk_score=0.9))
        assert decision.level == EscalationLevel.KILL

    def test_violation_rate_warn(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(violation_rate=0.25))
        assert decision.level >= EscalationLevel.WARN

    def test_violation_rate_throttle(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(violation_rate=0.45))
        assert decision.level >= EscalationLevel.THROTTLE

    def test_violation_rate_kill(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(violation_rate=0.65))
        assert decision.level == EscalationLevel.KILL


# ─── EscalationChain: Multiple Signals ────────────────────────────


class TestEscalationMultipleSignals:
    def test_two_moderate_signals_escalate(self):
        chain = EscalationChain()
        # drift=0.5, tamas=rajas(0.3), temporal=inconsistent(0.55), user_risk=0.55, violation=0.0
        # Two signals > 0.5: drift=0.5 (no), tamas=0.3 (no), temporal=0.55 (yes), user_risk=0.55 (yes)
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.55,
            tamas_state="rajas",
            consistency_level="inconsistent",
            user_risk_score=0.55,
            violation_rate=0.0,
        ))
        # Should be at least WARN (possibly higher due to multi-signal)
        assert decision.level >= EscalationLevel.WARN

    def test_high_aggregate_kills(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.7,
            tamas_state="tamas",
            consistency_level="chaotic",
            user_risk_score=0.7,
            violation_rate=0.3,
        ))
        assert decision.level == EscalationLevel.KILL

    def test_critical_independent_kills_despite_low_others(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.1,
            tamas_state="critical",
            consistency_level="highly_consistent",
            user_risk_score=0.0,
            violation_rate=0.0,
        ))
        assert decision.level == EscalationLevel.KILL
        assert any("critical" in r.lower() for r in decision.reasons)

    def test_multiple_kill_triggers(self):
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.96,
            tamas_state="critical",
            consistency_level="highly_consistent",
            user_risk_score=0.9,
            violation_rate=0.0,
        ))
        assert decision.level == EscalationLevel.KILL
        # Should have multiple reasons
        assert len(decision.reasons) >= 3


# ─── EscalationChain: Handler Tests ───────────────────────────────


class TestEscalationHandlers:
    def test_handler_registration(self):
        chain = EscalationChain()
        mock_handler = MagicMock()
        chain.register_handler(EscalationLevel.KILL, mock_handler)
        assert len(chain._handlers[EscalationLevel.KILL]) == 1

    def test_handler_execution_on_kill(self):
        chain = EscalationChain()
        mock_handler = MagicMock()
        chain.register_handler(EscalationLevel.KILL, mock_handler)

        decision = chain.evaluate(EscalationChain.build_signals(tamas_state="critical"))
        assert decision.level == EscalationLevel.KILL

        results = chain.execute(decision)
        mock_handler.assert_called_once_with(decision)

    def test_handler_execution_cumulative(self):
        """Lower-level handlers also fire when escalated."""
        chain = EscalationChain()
        warn_handler = MagicMock()
        kill_handler = MagicMock()
        chain.register_handler(EscalationLevel.WARN, warn_handler)
        chain.register_handler(EscalationLevel.KILL, kill_handler)

        decision = chain.evaluate(EscalationChain.build_signals(tamas_state="critical"))
        chain.execute(decision)

        kill_handler.assert_called_once()
        warn_handler.assert_called_once()  # Cumulative

    def test_handler_execution_alert_does_not_fire_kill(self):
        """ALERT should fire WARN but not KILL handlers."""
        chain = EscalationChain()
        warn_handler = MagicMock()
        kill_handler = MagicMock()
        chain.register_handler(EscalationLevel.WARN, warn_handler)
        chain.register_handler(EscalationLevel.KILL, kill_handler)

        decision = chain.evaluate(EscalationChain.build_signals(drift_score=0.82))
        assert decision.level == EscalationLevel.ALERT
        chain.execute(decision)

        warn_handler.assert_called_once()
        kill_handler.assert_not_called()

    def test_handler_error_caught(self):
        """Handler errors don't crash the chain."""
        chain = EscalationChain()

        def bad_handler(d):
            raise RuntimeError("handler explosion")

        chain.register_handler(EscalationLevel.WARN, bad_handler)

        decision = chain.evaluate(EscalationChain.build_signals(violation_rate=0.25))
        results = chain.execute(decision)
        assert any("failed" in r for r in results)

    def test_multiple_handlers_per_level(self):
        chain = EscalationChain()
        handler1 = MagicMock()
        handler2 = MagicMock()
        chain.register_handler(EscalationLevel.WARN, handler1)
        chain.register_handler(EscalationLevel.WARN, handler2)

        decision = chain.evaluate(EscalationChain.build_signals(violation_rate=0.25))
        chain.execute(decision)

        handler1.assert_called_once()
        handler2.assert_called_once()


# ─── EscalationChain: Decision History ────────────────────────────


class TestEscalationHistory:
    def test_last_decision(self):
        chain = EscalationChain()
        assert chain.get_last_decision() is None
        d1 = chain.evaluate(EscalationChain.build_signals())
        assert chain.get_last_decision() == d1
        d2 = chain.evaluate(EscalationChain.build_signals(drift_score=0.9))
        assert chain.get_last_decision() == d2

    def test_decision_history(self):
        chain = EscalationChain()
        chain.evaluate(EscalationChain.build_signals())
        chain.evaluate(EscalationChain.build_signals(drift_score=0.5))
        chain.evaluate(EscalationChain.build_signals(drift_score=0.9))

        history = chain.get_decision_history()
        assert len(history) == 3
        assert history[0]["level"] == "observe"
        assert history[2]["level"] == "alert"


# ─── EscalationChain: Custom Config ───────────────────────────────


class TestEscalationCustomConfig:
    def test_lower_drift_threshold(self):
        cfg = EscalationConfig(drift_alert_threshold=0.5)
        chain = EscalationChain(config=cfg)
        decision = chain.evaluate(EscalationChain.build_signals(drift_score=0.55))
        assert decision.level >= EscalationLevel.ALERT

    def test_custom_weights(self):
        cfg = EscalationConfig(
            weight_drift=0.8,
            weight_tamas=0.0,
            weight_temporal=0.0,
            weight_user_risk=0.0,
            weight_violation_rate=0.2,
            aggregate_warn=0.3,
        )
        chain = EscalationChain(config=cfg)
        # High drift, low everything else
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.5,
            violation_rate=0.0,
        ))
        # aggregate = 0.8*0.5 + 0.2*0.0 = 0.4 > 0.3 (warn)
        assert decision.level >= EscalationLevel.WARN

    def test_strict_config_triggers_sooner(self):
        cfg = EscalationConfig(
            aggregate_warn=0.1,
            aggregate_throttle=0.2,
            aggregate_alert=0.3,
            aggregate_kill=0.4,
        )
        chain = EscalationChain(config=cfg)
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=0.5,
            tamas_state="rajas",
        ))
        # With strict thresholds, moderate signals trigger harder
        assert decision.level >= EscalationLevel.THROTTLE


# ─── ConscienceMonitor Integration ────────────────────────────────


class TestConscienceMonitorIntegration:
    def test_get_signals_from_monitor(self):
        """Verify we can extract signals from a ConscienceMonitor for escalation."""
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("test-agent")

        # Add some interactions
        for i in range(5):
            result = MagicMock()
            result.overall_confidence = 0.8
            result.claims = []
            monitor.record_interaction(
                "test-agent", f"sess-{i}", result,
                violation=(i == 4),
                violation_type="hallucination",
                violation_severity=0.9,
            )

        # Extract signals
        health = monitor.get_agent_health("test-agent")
        tamas = monitor.get_tamas_state("test-agent")
        temporal = monitor.get_temporal_consistency("test-agent")

        signals = {
            "drift_score": health.get("drift_score", 0.0),
            "tamas_state": tamas.get("current_state", "sattva"),
            "consistency_level": temporal.get("consistency_level", "highly_consistent"),
            "user_risk_score": 0.0,
            "violation_rate": health.get("violation_rate", 0.0),
        }

        chain = EscalationChain()
        decision = chain.evaluate(signals, agent_id="test-agent")
        assert decision.agent_id == "test-agent"
        assert decision.level in list(EscalationLevel)


# ─── Build Signals Utility ────────────────────────────────────────


class TestBuildSignals:
    def test_build_signals(self):
        signals = EscalationChain.build_signals(
            drift_score=0.5,
            tamas_state="tamas",
            consistency_level="chaotic",
            user_risk_score=0.7,
            violation_rate=0.3,
        )
        assert signals["drift_score"] == 0.5
        assert signals["tamas_state"] == "tamas"
        assert signals["consistency_level"] == "chaotic"
        assert signals["user_risk_score"] == 0.7
        assert signals["violation_rate"] == 0.3

    def test_build_signals_defaults(self):
        signals = EscalationChain.build_signals()
        assert signals["drift_score"] == 0.0
        assert signals["tamas_state"] == "sattva"


# ─── Edge Cases ───────────────────────────────────────────────────


class TestEscalationEdgeCases:
    def test_none_values_handled(self):
        chain = EscalationChain()
        decision = chain.evaluate({
            "drift_score": None,
            "tamas_state": None,
            "consistency_level": None,
            "user_risk_score": None,
            "violation_rate": None,
        })
        assert decision.level == EscalationLevel.OBSERVE

    def test_empty_signals(self):
        chain = EscalationChain()
        decision = chain.evaluate({})
        assert decision.level == EscalationLevel.OBSERVE

    def test_missing_signals(self):
        chain = EscalationChain()
        decision = chain.evaluate({"drift_score": 0.5})
        assert decision.level in list(EscalationLevel)

    def test_unknown_tamas_state(self):
        chain = EscalationChain()
        decision = chain.evaluate({"tamas_state": "unknown_state"})
        assert decision.level == EscalationLevel.OBSERVE

    def test_score_capping(self):
        """Scores above 1.0 are handled gracefully."""
        chain = EscalationChain()
        decision = chain.evaluate(EscalationChain.build_signals(
            drift_score=1.5,
            user_risk_score=2.0,
            violation_rate=99.0,
        ))
        assert decision.level == EscalationLevel.KILL


# ─── Convenience Function ─────────────────────────────────────────


class TestConvenience:
    def test_get_escalation_chain(self):
        chain = get_escalation_chain()
        assert isinstance(chain, EscalationChain)

    def test_get_escalation_chain_with_config(self):
        cfg = EscalationConfig(drift_alert_threshold=0.5)
        chain = get_escalation_chain(config=cfg)
        assert chain.config.drift_alert_threshold == 0.5


# ─── Score Maps ───────────────────────────────────────────────────


class TestScoreMaps:
    def test_tamas_score_map(self):
        assert TAMAS_SCORE_MAP["sattva"] == 0.0
        assert TAMAS_SCORE_MAP["rajas"] == 0.3
        assert TAMAS_SCORE_MAP["tamas"] == 0.65
        assert TAMAS_SCORE_MAP["critical"] == 1.0

    def test_temporal_score_map(self):
        assert TEMPORAL_SCORE_MAP["highly_consistent"] == 0.0
        assert TEMPORAL_SCORE_MAP["consistent"] == 0.2
        assert TEMPORAL_SCORE_MAP["inconsistent"] == 0.55
        assert TEMPORAL_SCORE_MAP["chaotic"] == 0.9
