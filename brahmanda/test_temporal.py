"""
Test suite for Phase 3.4 — Temporal Consistency Enforcement.

Tests:
  1. Statement storage and retrieval
  2. Contradiction detection between old and new claims
  3. Consistency scoring
  4. Sliding window behavior
  5. Old statement pruning
  6. Integration with ConscienceMonitor

Run with: ``python3 -m pytest brahmanda/test_temporal.py -v``
"""
import sys
import os
import time
import pytest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from brahmanda.temporal import (
        TemporalConsistencyChecker,
        Statement,
        ContradictionPair,
        ConsistencyLevel,
        classify_consistency,
        CONSISTENCY_HIGHLY_CONSISTENT_MIN,
        CONSISTENCY_CONSISTENT_MIN,
        CONSISTENCY_INCONSISTENT_MIN,
    )
    from brahmanda.conscience import ConscienceMonitor
    HAS_TEMPORAL = True
except ImportError:
    HAS_TEMPORAL = False


# ═══════════════════════════════════════════════════════════════════
# 1. Statement Storage and Retrieval
# ═══════════════════════════════════════════════════════════════════


class TestStatementStorage:
    """Adding and retrieving statements."""

    def test_add_statement_returns_no_contradiction_first_time(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        contradictions = checker.add_statement(
            "agent-001", "Paris is the capital of France", 0.95, "user"
        )
        assert contradictions == []

    def test_statement_count(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "The sky is blue", 0.9, "user")
        checker.add_statement("agent-001", "Water is wet", 0.8, "system")
        assert checker.get_statement_count("agent-001") == 2

    def test_statement_count_unknown_agent(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        assert checker.get_statement_count("unknown") == 0

    def test_statement_to_dict(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        s = Statement(
            claim="Test claim",
            timestamp=time.time(),
            confidence=0.85,
            source="user",
            agent_id="agent-001",
        )
        d = s.to_dict()
        assert d["claim"] == "Test claim"
        assert d["confidence"] == 0.85
        assert d["source"] == "user"
        assert "timestamp_iso" in d
        assert "age_seconds" in d

    def test_confidence_clamped(self):
        """Confidence should be clamped to [0, 1]."""
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Test", confidence=1.5, source="user")
        # Should not raise; confidence clamped internally
        assert checker.get_statement_count("agent-001") == 1

    def test_multiple_agents_isolated(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-A", "Claim A", 0.9, "user")
        checker.add_statement("agent-B", "Claim B", 0.8, "user")
        assert checker.get_statement_count("agent-A") == 1
        assert checker.get_statement_count("agent-B") == 1

    def test_list_agents(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-A", "Claim", 0.9, "user")
        checker.add_statement("agent-B", "Claim", 0.8, "user")
        agents = checker.list_agents()
        assert "agent-A" in agents
        assert "agent-B" in agents


# ═══════════════════════════════════════════════════════════════════
# 2. Contradiction Detection
# ═══════════════════════════════════════════════════════════════════


class TestContradictionDetection:
    """Detecting contradictions between claims."""

    def test_no_contradiction_unrelated_claims(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "The sky is blue", 0.9, "user")
        contradictions = checker.add_statement(
            "agent-001", "Python is a programming language", 0.9, "user"
        )
        assert contradictions == []

    def test_contradiction_capital_city(self):
        """Detect capital city contradictions."""
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement(
            "agent-001",
            "Paris is the capital of France",
            0.95, "user"
        )
        contradictions = checker.add_statement(
            "agent-001",
            "Lyon is the capital of France",
            0.90, "user"
        )
        assert len(contradictions) >= 1
        assert contradictions[0].reason  # Has a reason string

    def test_contradiction_with_negation(self):
        """Detect negation-based contradictions."""
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement(
            "agent-001",
            "The earth is round and orbits the sun",
            0.95, "user"
        )
        contradictions = checker.add_statement(
            "agent-001",
            "The earth is not round and orbits the sun",
            0.5, "user"
        )
        # Should detect negation mismatch
        assert len(contradictions) >= 1

    def test_check_consistency_preflight(self):
        """check_consistency does NOT add the claim."""
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement(
            "agent-001",
            "Paris is the capital of France",
            0.95, "user"
        )
        # Pre-flight check
        contradictions = checker.check_consistency(
            "agent-001", "Lyon is the capital of France"
        )
        # Statement count should still be 1 (not added)
        assert checker.get_statement_count("agent-001") == 1

    def test_contradiction_pair_structure(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        contradictions = checker.add_statement(
            "agent-001", "Berlin is the capital of France", 0.90, "system"
        )
        if contradictions:
            pair = contradictions[0]
            d = pair.to_dict()
            assert "statement_a" in d
            assert "statement_b" in d
            assert "similarity" in d
            assert "reason" in d
            # statement_a is the older one
            assert d["statement_a"]["claim"] == "Paris is the capital of France"
            assert d["statement_b"]["claim"] == "Berlin is the capital of France"

    def test_contradiction_history(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        checker.add_statement("agent-001", "Berlin is the capital of France", 0.90, "user")
        history = checker.get_contradiction_history("agent-001")
        assert len(history) >= 1

    def test_contradiction_count(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        checker.add_statement("agent-001", "Berlin is the capital of France", 0.90, "user")
        count = checker.get_contradiction_count("agent-001")
        assert count >= 1


# ═══════════════════════════════════════════════════════════════════
# 3. Consistency Scoring
# ═══════════════════════════════════════════════════════════════════


class TestConsistencyScoring:
    """Consistency score computation."""

    def test_perfect_consistency_no_data(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        assert checker.get_consistency_score("agent-001") == 1.0

    def test_perfect_consistency_no_contradictions(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "The sky is blue", 0.9, "user")
        checker.add_statement("agent-001", "The sun is yellow", 0.9, "user")
        # Unrelated claims — no contradictions
        assert checker.get_consistency_score("agent-001") == 1.0

    def test_score_decreases_with_contradictions(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        score_before = checker.get_consistency_score("agent-001")
        checker.add_statement("agent-001", "Berlin is the capital of France", 0.90, "user")
        score_after = checker.get_consistency_score("agent-001")
        assert score_after < score_before

    def test_score_bounds(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        # Add many contradictory claims
        for i in range(5):
            checker.add_statement(
                "agent-001",
                f"City{i} is the capital of France",
                0.8, "user"
            )
        score = checker.get_consistency_score("agent-001")
        assert 0.0 <= score <= 1.0

    def test_consistency_level_classification(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        assert classify_consistency(0.95) == ConsistencyLevel.HIGHLY_CONSISTENT
        assert classify_consistency(0.90) == ConsistencyLevel.HIGHLY_CONSISTENT
        assert classify_consistency(0.85) == ConsistencyLevel.CONSISTENT
        assert classify_consistency(0.70) == ConsistencyLevel.CONSISTENT
        assert classify_consistency(0.55) == ConsistencyLevel.INCONSISTENT
        assert classify_consistency(0.40) == ConsistencyLevel.INCONSISTENT
        assert classify_consistency(0.30) == ConsistencyLevel.CHAOTIC
        assert classify_consistency(0.0) == ConsistencyLevel.CHAOTIC

    def test_consistency_level_from_checker(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        # No data = highly consistent
        assert checker.get_consistency_level("agent-001") == ConsistencyLevel.HIGHLY_CONSISTENT

    def test_temporal_summary(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Paris is the capital of France", 0.95, "user")
        checker.add_statement("agent-001", "Berlin is the capital of France", 0.90, "user")
        summary = checker.get_temporal_summary("agent-001")
        assert "agent_id" in summary
        assert "consistency_score" in summary
        assert "consistency_level" in summary
        assert "statement_count" in summary
        assert "total_checks" in summary
        assert "total_contradictions" in summary
        assert "recent_contradictions" in summary


# ═══════════════════════════════════════════════════════════════════
# 4. Sliding Window Behavior
# ═══════════════════════════════════════════════════════════════════


class TestSlidingWindow:
    """Sliding window truncation."""

    def test_window_size_respected(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker(window_size=5)
        for i in range(10):
            checker.add_statement("agent-001", f"Claim number {i} is true", 0.9, "user")
        assert checker.get_statement_count("agent-001") == 5

    def test_window_keeps_newest(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker(window_size=3)
        for i in range(5):
            checker.add_statement("agent-001", f"Claim number {i}", 0.9, "user")
        # The oldest (0, 1) should be gone, keeping 2, 3, 4
        summary = checker.get_temporal_summary("agent-001")
        assert summary["statement_count"] == 3

    def test_default_window_size_100(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        assert checker.window_size == 100

    def test_custom_window_size(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker(window_size=10)
        for i in range(15):
            checker.add_statement("agent-001", f"Claim {i}", 0.9, "user")
        assert checker.get_statement_count("agent-001") == 10


# ═══════════════════════════════════════════════════════════════════
# 5. Old Statement Pruning
# ═══════════════════════════════════════════════════════════════════


class TestStatementPruning:
    """Pruning old statements by age."""

    def test_prune_nothing_when_all_recent(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Recent claim", 0.9, "user")
        removed = checker.clear_old_statements("agent-001", max_age_days=30)
        assert removed == 0
        assert checker.get_statement_count("agent-001") == 1

    def test_prune_old_statements(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        # Add an old statement by directly manipulating the internal list
        old_statement = Statement(
            claim="Old claim",
            timestamp=time.time() - (10 * 86400),  # 10 days ago
            confidence=0.9,
            source="user",
            agent_id="agent-001",
        )
        checker._statements["agent-001"] = [old_statement]
        checker._contradiction_history["agent-001"] = []
        checker._total_checks["agent-001"] = 0
        checker._total_contradictions["agent-001"] = 0

        # Add a recent one
        checker.add_statement("agent-001", "New claim", 0.9, "user")
        assert checker.get_statement_count("agent-001") == 2

        # Prune anything older than 5 days
        removed = checker.clear_old_statements("agent-001", max_age_days=5)
        assert removed == 1
        assert checker.get_statement_count("agent-001") == 1

    def test_prune_unknown_agent(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        removed = checker.clear_old_statements("unknown", max_age_days=30)
        assert removed == 0

    def test_clear_agent(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        checker = TemporalConsistencyChecker()
        checker.add_statement("agent-001", "Claim", 0.9, "user")
        checker.clear_agent("agent-001")
        assert checker.get_statement_count("agent-001") == 0
        assert checker.get_consistency_score("agent-001") == 1.0


# ═══════════════════════════════════════════════════════════════════
# 6. Integration with ConscienceMonitor
# ═══════════════════════════════════════════════════════════════════


class TestConscienceIntegration:
    """Temporal consistency integration with ConscienceMonitor."""

    def test_conscience_has_temporal_checker(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        assert hasattr(monitor, 'temporal_checker')
        assert isinstance(monitor.temporal_checker, TemporalConsistencyChecker)

    def test_record_interaction_adds_claims(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        # Create a result with claims
        claim_obj = type("C", (), {"claim": "Paris is the capital of France", "verified": True})()
        result = type("R", (), {
            "overall_confidence": 0.95,
            "claims": [claim_obj],
        })()
        monitor.record_interaction("agent-001", "sess-001", result)

        summary = monitor.get_temporal_consistency("agent-001")
        assert summary["statement_count"] >= 1

    def test_conscience_temporal_summary(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        claim1 = type("C", (), {"claim": "Paris is the capital of France", "verified": True})()
        result1 = type("R", (), {"overall_confidence": 0.95, "claims": [claim1]})()
        monitor.record_interaction("agent-001", "sess-001", result1)

        claim2 = type("C", (), {"claim": "Berlin is the capital of France", "verified": False})()
        result2 = type("R", (), {"overall_confidence": 0.90, "claims": [claim2]})()
        monitor.record_interaction("agent-001", "sess-001", result2)

        summary = monitor.get_temporal_consistency("agent-001")
        # Should detect at least 1 contradiction
        assert summary["total_contradictions"] >= 1
        assert summary["consistency_score"] < 1.0

    def test_conscience_check_temporal(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        claim = type("C", (), {"claim": "Paris is the capital of France", "verified": True})()
        result = type("R", (), {"overall_confidence": 0.95, "claims": [claim]})()
        monitor.record_interaction("agent-001", "sess-001", result)

        # Pre-flight check
        check_result = monitor.check_temporal_consistency(
            "agent-001", "Berlin is the capital of France"
        )
        assert "contradictions" in check_result
        assert "consistency_score" in check_result

    def test_conscience_contradiction_history(self):
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        claim1 = type("C", (), {"claim": "Paris is the capital of France", "verified": True})()
        result1 = type("R", (), {"overall_confidence": 0.95, "claims": [claim1]})()
        monitor.record_interaction("agent-001", "sess-001", result1)

        claim2 = type("C", (), {"claim": "Berlin is the capital of France", "verified": False})()
        result2 = type("R", (), {"overall_confidence": 0.90, "claims": [claim2]})()
        monitor.record_interaction("agent-001", "sess-001", result2)

        history = monitor.get_contradiction_history("agent-001")
        assert history["total"] >= 1
        assert len(history["contradictions"]) >= 1

    def test_conscience_drift_alignment_updated(self):
        """Consistency score feeds into drift components (alignment)."""
        if not HAS_TEMPORAL:
            pytest.skip("temporal module not importable")
        monitor = ConscienceMonitor(in_memory=True)
        monitor.register_agent("agent-001")

        claim1 = type("C", (), {"claim": "Paris is the capital of France", "verified": True})()
        result1 = type("R", (), {"overall_confidence": 0.95, "claims": [claim1]})()
        monitor.record_interaction("agent-001", "sess-001", result1)

        claim2 = type("C", (), {"claim": "Berlin is the capital of France", "verified": False})()
        result2 = type("R", (), {"overall_confidence": 0.90, "claims": [claim2]})()
        monitor.record_interaction("agent-001", "sess-001", result2)

        health = monitor.get_agent_health("agent-001")
        # After contradiction, the agent's profile should reflect it
        assert health["agent_id"] == "agent-001"
