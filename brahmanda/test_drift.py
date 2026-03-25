"""
RTA-GUARD — Phase 3.2 Tests: Live An-Rta Drift Scoring

Tests for LiveDriftScorer, drift thresholds, trend detection,
component breakdown, sliding window, EMA smoothing, and
integration with ConscienceMonitor.
"""
import pytest
import json
from brahmanda.profiles import (
    DriftLevel, DriftComponents, classify_drift,
    DRIFT_HEALTHY_MAX, DRIFT_DEGRADED_MAX, DRIFT_UNHEALTHY_MAX,
)
from brahmanda.conscience import LiveDriftScorer, DriftSnapshot, ConscienceMonitor


# ─── Helpers ──────────────────────────────────────────────────────


def make_components(semantic=0.0, alignment=0.0, scope=0.0, confidence=0.0, rule_proximity=0.0):
    """Create DriftComponents with given values."""
    return DriftComponents(
        semantic=semantic,
        alignment=alignment,
        scope=scope,
        confidence=confidence,
        rule_proximity=rule_proximity,
    )


def make_component_dict(semantic=0.0, alignment=0.0, scope=0.0, confidence=0.0, rule_proximity=0.0):
    """Create a component dict (as used by record_drift)."""
    return {
        "semantic": semantic,
        "alignment": alignment,
        "scope": scope,
        "confidence": confidence,
        "rule_proximity": rule_proximity,
    }


# ─── Drift Level Classification ──────────────────────────────────


class TestDriftLevelClassification:
    """Test classify_drift and DriftLevel enum."""

    def test_healthy_threshold(self):
        assert classify_drift(0.0) == DriftLevel.HEALTHY
        assert classify_drift(0.10) == DriftLevel.HEALTHY
        assert classify_drift(0.14) == DriftLevel.HEALTHY

    def test_degraded_threshold(self):
        assert classify_drift(0.15) == DriftLevel.DEGRADED
        assert classify_drift(0.25) == DriftLevel.DEGRADED
        assert classify_drift(0.34) == DriftLevel.DEGRADED

    def test_unhealthy_threshold(self):
        assert classify_drift(0.35) == DriftLevel.UNHEALTHY
        assert classify_drift(0.50) == DriftLevel.UNHEALTHY
        assert classify_drift(0.59) == DriftLevel.UNHEALTHY

    def test_critical_threshold(self):
        assert classify_drift(0.60) == DriftLevel.CRITICAL
        assert classify_drift(0.80) == DriftLevel.CRITICAL
        assert classify_drift(1.0) == DriftLevel.CRITICAL

    def test_boundary_values(self):
        """Exactly at boundary should be the higher severity."""
        assert classify_drift(DRIFT_HEALTHY_MAX) == DriftLevel.DEGRADED
        assert classify_drift(DRIFT_DEGRADED_MAX) == DriftLevel.UNHEALTHY
        assert classify_drift(DRIFT_UNHEALTHY_MAX) == DriftLevel.CRITICAL


# ─── DriftComponents ─────────────────────────────────────────────


class TestDriftComponents:
    """Test DriftComponents weighted scoring."""

    def test_zero_components(self):
        dc = make_components()
        assert dc.weighted_score() == 0.0

    def test_all_ones(self):
        dc = make_components(1.0, 1.0, 1.0, 1.0, 1.0)
        assert dc.weighted_score() == 1.0

    def test_weights_applied(self):
        # Only semantic = 1.0
        dc = make_components(semantic=1.0)
        assert dc.weighted_score() == 0.30  # W1=0.30

        # Only alignment = 1.0
        dc = make_components(alignment=1.0)
        assert dc.weighted_score() == 0.25  # W2=0.25

        # Only scope = 1.0
        dc = make_components(scope=1.0)
        assert dc.weighted_score() == 0.20  # W3=0.20

        # Only confidence = 1.0
        dc = make_components(confidence=1.0)
        assert dc.weighted_score() == 0.15  # W4=0.15

        # Only rule_proximity = 1.0
        dc = make_components(rule_proximity=1.0)
        assert dc.weighted_score() == 0.10  # W5=0.10

    def test_score_clamped_to_one(self):
        dc = make_components(2.0, 2.0, 2.0, 2.0, 2.0)
        assert dc.weighted_score() == 1.0

    def test_to_dict(self):
        dc = make_components(0.1, 0.2, 0.3, 0.4, 0.5)
        d = dc.to_dict()
        assert d["semantic"] == 0.1
        assert d["alignment"] == 0.2
        assert d["scope"] == 0.3
        assert d["confidence"] == 0.4
        assert d["rule_proximity"] == 0.5
        assert "weighted_score" in d

    def test_deterministic(self):
        """Same inputs always produce same score."""
        dc1 = make_components(0.5, 0.3, 0.2, 0.1, 0.4)
        dc2 = make_components(0.5, 0.3, 0.2, 0.1, 0.4)
        assert dc1.weighted_score() == dc2.weighted_score()


# ─── LiveDriftScorer Basics ──────────────────────────────────────


class TestLiveDriftScorerBasics:
    """Test basic LiveDriftScorer operations."""

    def test_record_creates_snapshot(self):
        scorer = LiveDriftScorer()
        snap = scorer.record_drift("agent-1", "sess-1", make_component_dict(0.5))
        assert snap.weighted_score > 0
        assert snap.level in DriftLevel
        assert snap.agent_id == "agent-1"
        assert snap.session_id == "sess-1"

    def test_empty_session_drift(self):
        scorer = LiveDriftScorer()
        result = scorer.calculate_session_drift("nonexistent")
        assert "error" in result
        assert result["drift_score"] == 0.0

    def test_empty_agent_drift(self):
        scorer = LiveDriftScorer()
        result = scorer.calculate_agent_drift("nonexistent")
        assert "error" in result

    def test_empty_components(self):
        scorer = LiveDriftScorer()
        snap = scorer.record_drift("agent-1", "sess-1", make_component_dict())
        assert snap.weighted_score == 0.0
        assert snap.level == DriftLevel.HEALTHY


# ─── Session Drift Calculation ───────────────────────────────────


class TestSessionDrift:
    """Test session-level drift scoring."""

    def test_increasing_drift(self):
        """Drift scores that increase over time."""
        scorer = LiveDriftScorer()
        for i in range(5):
            val = 0.1 * i
            scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=val))

        result = scorer.calculate_session_drift("sess-1")
        assert result["snapshot_count"] == 5
        assert result["drift_score"] > 0
        assert result["level"] in [l.value for l in DriftLevel]

    def test_decreasing_drift(self):
        """Drift scores that decrease over time."""
        scorer = LiveDriftScorer()
        for i in range(5):
            val = 1.0 - 0.2 * i
            scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=val))

        result = scorer.calculate_session_drift("sess-1")
        assert result["snapshot_count"] == 5

    def test_stable_drift(self):
        """Constant drift scores."""
        scorer = LiveDriftScorer()
        for _ in range(10):
            scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.5))

        result = scorer.calculate_session_drift("sess-1")
        # All values same, smoothed should be consistent
        assert result["drift_score"] == 0.15  # 0.5 * 0.30 weight

    def test_session_drift_has_components(self):
        scorer = LiveDriftScorer()
        scorer.record_drift("agent-1", "sess-1", make_component_dict(0.5, 0.3, 0.2, 0.1, 0.0))
        result = scorer.calculate_session_drift("sess-1")
        assert "components" in result
        assert result["components"]["semantic"] == 0.5


# ─── Agent Drift Accumulation ────────────────────────────────────


class TestAgentDrift:
    """Test agent-level drift accumulation across sessions."""

    def test_multi_session_drift(self):
        """Agent drift accumulates across multiple sessions."""
        scorer = LiveDriftScorer()
        scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.5))
        scorer.record_drift("agent-1", "sess-2", make_component_dict(semantic=0.6))
        scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.4))

        result = scorer.calculate_agent_drift("agent-1")
        assert result["snapshot_count"] == 3
        assert result["sessions_tracked"] == 2
        assert "session_scores" in result

    def test_agent_drift_uses_ema(self):
        """Agent drift uses EMA-smoothed score."""
        scorer = LiveDriftScorer()
        for i in range(10):
            scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.5))

        result = scorer.calculate_agent_drift("agent-1")
        # EMA should converge toward 0.15 (0.5 * 0.30)
        assert abs(result["drift_score"] - 0.15) < 0.01

    def test_agent_drift_components_averaged(self):
        """Agent drift components are averaged across window."""
        scorer = LiveDriftScorer()
        scorer.record_drift("agent-1", "s1", make_component_dict(semantic=1.0))
        scorer.record_drift("agent-1", "s2", make_component_dict(semantic=0.0))

        result = scorer.calculate_agent_drift("agent-1")
        # Average semantic = 0.5
        assert abs(result["components"]["semantic"] - 0.5) < 0.01


# ─── Drift Trend Detection ──────────────────────────────────────


class TestDriftTrend:
    """Test drift trend detection."""

    def test_increasing_trend(self):
        scorer = LiveDriftScorer()
        for i in range(10):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.1 * i))

        trend = scorer.get_drift_trend("agent-1")
        assert trend == "increasing"

    def test_decreasing_trend(self):
        scorer = LiveDriftScorer()
        for i in range(10):
            val = 1.0 - 0.1 * i
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=val))

        trend = scorer.get_drift_trend("agent-1")
        assert trend == "decreasing"

    def test_stable_trend(self):
        scorer = LiveDriftScorer()
        for _ in range(10):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.5))

        trend = scorer.get_drift_trend("agent-1")
        assert trend == "stable"

    def test_trend_with_few_data(self):
        """Less than 4 data points should return stable."""
        scorer = LiveDriftScorer()
        scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.9))
        scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.1))
        trend = scorer.get_drift_trend("agent-1")
        assert trend == "stable"


# ─── Drift Components Breakdown ─────────────────────────────────


class TestDriftComponentsBreakdown:
    """Test drift component breakdown."""

    def test_components_returned(self):
        scorer = LiveDriftScorer()
        scorer.record_drift("agent-1", "s1", make_component_dict(0.1, 0.2, 0.3, 0.4, 0.5))

        result = scorer.get_drift_components("agent-1")
        assert "latest" in result
        assert "window_average" in result
        assert result["latest"]["semantic"] == 0.1
        assert result["latest"]["alignment"] == 0.2

    def test_empty_components(self):
        scorer = LiveDriftScorer()
        result = scorer.get_drift_components("agent-1")
        assert "error" in result


# ─── Sliding Window ─────────────────────────────────────────────


class TestSlidingWindow:
    """Test sliding window behavior."""

    def test_window_limits_snapshots(self):
        scorer = LiveDriftScorer(window_size=5)
        for i in range(10):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.1 * i))

        result = scorer.calculate_agent_drift("agent-1")
        assert result["snapshot_count"] == 5  # Only last 5 kept

    def test_window_keeps_latest(self):
        scorer = LiveDriftScorer(window_size=3)
        for i in range(5):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.1 * i))

        result = scorer.calculate_agent_drift("agent-1")
        # Latest score should reflect the last 3 values: 0.2, 0.3, 0.4
        # Average semantic = (0.2+0.3+0.4)/3 = 0.3
        assert abs(result["components"]["semantic"] - 0.3) < 0.01

    def test_session_drift_not_windowed(self):
        """Session snapshots are not window-limited (full history)."""
        scorer = LiveDriftScorer(window_size=3)
        for i in range(10):
            scorer.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.1))

        result = scorer.calculate_session_drift("sess-1")
        assert result["snapshot_count"] == 10  # Session not windowed


# ─── EMA Smoothing ──────────────────────────────────────────────


class TestEMASmoothing:
    """Test exponential moving average behavior."""

    def test_ema_converges(self):
        """With constant input, EMA converges to the input value."""
        scorer = LiveDriftScorer(ema_alpha=0.3)
        target_score = make_component_dict(semantic=0.5)  # weighted = 0.15
        for _ in range(50):
            scorer.record_drift("agent-1", "s1", target_score)

        result = scorer.calculate_agent_drift("agent-1")
        assert abs(result["drift_score"] - 0.15) < 0.001

    def test_ema_responds_to_change(self):
        """EMA should respond to a sudden drift change."""
        scorer = LiveDriftScorer(ema_alpha=0.5)
        # Low drift for a while
        for _ in range(20):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=0.0))

        low_ema = scorer._agent_ema["agent-1"]

        # Sudden spike
        for _ in range(20):
            scorer.record_drift("agent-1", "s1", make_component_dict(semantic=1.0))

        high_ema = scorer._agent_ema["agent-1"]
        assert high_ema > low_ema

    def test_different_alpha(self):
        """Different alpha values produce different smoothing."""
        scorer_fast = LiveDriftScorer(ema_alpha=0.9)
        scorer_slow = LiveDriftScorer(ema_alpha=0.1)

        scorer_fast.record_drift("a", "s", make_component_dict(semantic=1.0))
        scorer_slow.record_drift("a", "s", make_component_dict(semantic=1.0))

        fast_score = scorer_fast._agent_ema["a"]
        slow_score = scorer_slow._agent_ema["a"]
        assert fast_score > slow_score  # Fast EMA reacts more


# ─── Threshold Transitions ──────────────────────────────────────


class TestThresholdTransitions:
    """Test that drift level changes correctly at thresholds."""

    def test_healthy_to_degraded(self):
        scorer = LiveDriftScorer(ema_alpha=1.0)  # No smoothing for test
        scorer.record_drift("a", "s", make_component_dict(semantic=0.0))
        assert scorer.get_drift_level("a") == DriftLevel.HEALTHY

        # semantic=0.6 -> weighted=0.18 -> DEGRADED
        scorer = LiveDriftScorer(ema_alpha=1.0)
        scorer.record_drift("a", "s", make_component_dict(semantic=0.6))
        assert scorer.get_drift_level("a") == DriftLevel.DEGRADED

    def test_degraded_to_unhealthy(self):
        # semantic=1.0 -> weighted=0.30 -> DEGRADED
        scorer = LiveDriftScorer(ema_alpha=1.0)
        scorer.record_drift("a", "s", make_component_dict(semantic=1.0))
        assert scorer.get_drift_level("a") == DriftLevel.DEGRADED

        # All components high -> weighted close to 1.0 -> CRITICAL
        scorer = LiveDriftScorer(ema_alpha=1.0)
        scorer.record_drift("a", "s", make_component_dict(1.0, 1.0, 1.0, 1.0, 1.0))
        assert scorer.get_drift_level("a") == DriftLevel.CRITICAL

    def test_critical_drift(self):
        scorer = LiveDriftScorer(ema_alpha=1.0)
        scorer.record_drift("a", "s", make_component_dict(2.0, 2.0, 2.0, 2.0, 2.0))
        assert scorer.get_drift_level("a") == DriftLevel.CRITICAL


# ─── Integration with ConscienceMonitor ─────────────────────────


class TestConscienceMonitorDrift:
    """Test LiveDriftScorer integration with ConscienceMonitor."""

    def _make_monitor(self):
        return ConscienceMonitor(in_memory=True)

    def test_record_drift_via_monitor(self):
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        result = monitor.record_drift("agent-1", "sess-1", make_component_dict(0.5))
        assert result["weighted_score"] > 0
        assert result["level"] in [l.value for l in DriftLevel]

    def test_get_live_drift(self):
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        monitor.record_drift("agent-1", "sess-1", make_component_dict(0.5))

        result = monitor.get_live_drift("agent-1")
        assert result["drift_score"] > 0
        assert "components" in result

    def test_get_live_drift_session(self):
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        monitor.record_drift("agent-1", "sess-1", make_component_dict(0.5))

        result = monitor.get_live_drift_session("sess-1")
        assert result["drift_score"] > 0
        assert result["session_id"] == "sess-1"

    def test_drift_trend_via_monitor(self):
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        for i in range(10):
            monitor.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.1 * i))

        assert monitor.get_drift_trend("agent-1") == "increasing"

    def test_drift_components_via_monitor(self):
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        monitor.record_drift("agent-1", "sess-1", make_component_dict(0.1, 0.2, 0.3, 0.4, 0.5))

        result = monitor.get_drift_components("agent-1")
        assert "latest" in result
        assert result["latest"]["semantic"] == 0.1

    def test_agent_profile_drift_fields_updated(self):
        """Recording drift should update AgentProfile's live drift fields."""
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        monitor.record_drift("agent-1", "sess-1", make_component_dict(0.5))

        agent = monitor._load_agent("agent-1")
        assert agent.live_drift_score > 0
        assert agent.live_drift_level in [l.value for l in DriftLevel]
        assert agent.drift_trend in ("increasing", "stable", "decreasing")
        assert len(agent.drift_history) == 1

    def test_agent_profile_drift_history_limited(self):
        """Drift history should be capped at 50 entries."""
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        for i in range(60):
            monitor.record_drift("agent-1", "sess-1", make_component_dict(semantic=0.5))

        agent = monitor._load_agent("agent-1")
        assert len(agent.drift_history) == 50

    def test_multi_agent_isolation(self):
        """Drift for one agent should not affect another."""
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")
        monitor.register_agent("agent-2")

        monitor.record_drift("agent-1", "sess-1", make_component_dict(semantic=1.0))
        monitor.record_drift("agent-2", "sess-2", make_component_dict(semantic=0.0))

        d1 = monitor.get_live_drift("agent-1")["drift_score"]
        d2 = monitor.get_live_drift("agent-2")["drift_score"]
        assert d1 > d2

    def test_multi_session_agent(self):
        """Agent drift should aggregate across sessions."""
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")

        monitor.record_drift("agent-1", "sess-1", make_component_dict(0.5))
        monitor.record_drift("agent-1", "sess-2", make_component_dict(0.5))

        result = monitor.get_live_drift("agent-1")
        assert result["sessions_tracked"] == 2

    def test_drift_integration_with_anomaly(self):
        """High drift should be detectable via agent profile."""
        monitor = self._make_monitor()
        monitor.register_agent("agent-1")

        # Record many high-drift interactions
        for _ in range(10):
            monitor.record_drift("agent-1", "sess-1", make_component_dict(1.0, 1.0, 1.0, 1.0, 1.0))

        agent = monitor._load_agent("agent-1")
        assert agent.live_drift_score > 0.5
        assert agent.live_drift_level == DriftLevel.CRITICAL.value


# ─── DriftSnapshot ──────────────────────────────────────────────


class TestDriftSnapshot:
    """Test DriftSnapshot dataclass."""

    def test_snapshot_to_dict(self):
        components = make_components(0.1, 0.2, 0.3, 0.4, 0.5)
        snap = DriftSnapshot(
            session_id="s1",
            agent_id="a1",
            timestamp="2026-01-01T00:00:00",
            components=components,
            weighted_score=components.weighted_score(),
            level=classify_drift(components.weighted_score()),
        )
        d = snap.to_dict()
        assert d["session_id"] == "s1"
        assert d["agent_id"] == "a1"
        assert "components" in d
        assert "level" in d


# ─── Determinism ─────────────────────────────────────────────────


class TestDeterminism:
    """Drift scores must be deterministic given the same history."""

    def test_same_history_same_ema(self):
        scorer1 = LiveDriftScorer(ema_alpha=0.3, window_size=20)
        scorer2 = LiveDriftScorer(ema_alpha=0.3, window_size=20)

        inputs = [0.1, 0.5, 0.3, 0.8, 0.2, 0.6, 0.4, 0.9, 0.7, 0.15]
        for val in inputs:
            scorer1.record_drift("a", "s", make_component_dict(semantic=val))
            scorer2.record_drift("a", "s", make_component_dict(semantic=val))

        assert scorer1._agent_ema["a"] == scorer2._agent_ema["a"]

    def test_same_history_same_trend(self):
        scorer1 = LiveDriftScorer()
        scorer2 = LiveDriftScorer()

        for i in range(10):
            scorer1.record_drift("a", "s", make_component_dict(semantic=0.1 * i))
            scorer2.record_drift("a", "s", make_component_dict(semantic=0.1 * i))

        assert scorer1.get_drift_trend("a") == scorer2.get_drift_trend("a")


# ─── Edge Cases ──────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_snapshot(self):
        scorer = LiveDriftScorer()
        scorer.record_drift("a", "s", make_component_dict(0.5))
        result = scorer.calculate_agent_drift("a")
        assert result["drift_score"] > 0

    def test_zero_drift(self):
        scorer = LiveDriftScorer()
        for _ in range(10):
            scorer.record_drift("a", "s", make_component_dict())
        result = scorer.calculate_agent_drift("a")
        assert result["drift_score"] == 0.0

    def test_partial_components(self):
        """Missing keys default to 0.0."""
        scorer = LiveDriftScorer()
        snap = scorer.record_drift("a", "s", {"semantic": 0.5})
        assert snap.components.semantic == 0.5
        assert snap.components.alignment == 0.0

    def test_negative_components(self):
        """Negative components should be clamped to 0."""
        scorer = LiveDriftScorer()
        snap = scorer.record_drift("a", "s", make_component_dict(semantic=-1.0))
        assert snap.weighted_score == 0.0  # Clamped to 0
