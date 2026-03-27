"""
RTA-GUARD Observability Tests

Tests for: TraceCollector, ViolationAnalytics, CostTracker, AlertManager, and ObservabilityManager.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.observability.trace import GuardTrace, TraceCollector
from discus.observability.analytics import ViolationAnalytics, CostTracker, ViolationStats
from discus.observability.alerts import AlertManager, AlertRule, AlertEvent, AlertCondition, AlertChannel
from discus.observability import ObservabilityManager


# ─── TraceCollector Tests ──────────────────────────────────────────

class TestTraceCollector(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mktemp(suffix=".db"))
        self.collector = TraceCollector(db_path=self.db, retention_days=30)

    def tearDown(self):
        if self.db.exists():
            self.db.unlink()

    def _make_trace(self, decision="pass", rule="pii", session_id="s1"):
        return GuardTrace(
            trace_id=f"t-{time.time_ns()}",
            session_id=session_id,
            decision=decision,
            rule_triggered=rule,
            duration_ms=2.5,
            violation_type=decision if decision != "pass" else "",
        )

    def test_record(self):
        trace = self._make_trace()
        self.collector.record(trace)
        results = self.collector.query()
        self.assertEqual(len(results), 1)

    def test_record_many(self):
        traces = [self._make_trace(decision="kill") for _ in range(5)]
        self.collector.record_many(traces)
        self.assertEqual(self.collector.count(), 5)

    def test_query_by_decision(self):
        self.collector.record(self._make_trace(decision="pass"))
        self.collector.record(self._make_trace(decision="kill"))
        kills = self.collector.query(decision="kill")
        self.assertEqual(len(kills), 1)

    def test_query_by_session(self):
        self.collector.record(self._make_trace(session_id="s1"))
        self.collector.record(self._make_trace(session_id="s2"))
        s1_traces = self.collector.query(session_id="s1")
        self.assertEqual(len(s1_traces), 1)

    def test_query_by_rule(self):
        self.collector.record(self._make_trace(rule="pii"))
        self.collector.record(self._make_trace(rule="injection"))
        pii = self.collector.query(rule="pii")
        self.assertEqual(len(pii), 1)

    def test_count(self):
        for i in range(10):
            self.collector.record(self._make_trace(decision="kill" if i % 2 else "pass"))
        self.assertEqual(self.collector.count(decision="kill"), 5)

    def test_export_json(self):
        self.collector.record(self._make_trace())
        json_str = self.collector.export_json()
        self.assertIn("trace_id", json_str)

    def test_export_csv(self):
        self.collector.record(self._make_trace())
        csv_str = self.collector.export_csv()
        self.assertIn("trace_id", csv_str)
        self.assertIn("decision", csv_str)

    def test_cleanup(self):
        self.collector.retention_days = 0
        self.collector.record(self._make_trace())
        time.sleep(0.01)
        cleaned = self.collector.cleanup()
        self.assertEqual(cleaned, 1)

    def test_stats(self):
        self.collector.record(self._make_trace())
        stats = self.collector.get_stats()
        self.assertEqual(stats["total_traces"], 1)


# ─── ViolationAnalytics Tests ──────────────────────────────────────

class TestViolationAnalytics(unittest.TestCase):
    def setUp(self):
        self.analytics = ViolationAnalytics()

    def _make_traces(self):
        return [
            {"decision": "pass", "rule_triggered": "", "duration_ms": 1.0, "violation_type": ""},
            {"decision": "pass", "rule_triggered": "", "duration_ms": 1.5, "violation_type": ""},
            {"decision": "warn", "rule_triggered": "pii", "duration_ms": 2.0, "violation_type": "pii"},
            {"decision": "kill", "rule_triggered": "injection", "duration_ms": 3.0, "violation_type": "injection"},
            {"decision": "kill", "rule_triggered": "pii", "duration_ms": 2.5, "violation_type": "pii"},
        ]

    def test_get_stats(self):
        stats = self.analytics.get_stats(traces=self._make_traces())
        self.assertEqual(stats.total_checks, 5)
        self.assertEqual(stats.total_passes, 2)
        self.assertEqual(stats.total_warns, 1)
        self.assertEqual(stats.total_kills, 2)
        self.assertAlmostEqual(stats.kill_rate, 0.4)

    def test_get_trends(self):
        now = time.time()
        traces = [
            {"decision": "kill", "timestamp": now - 3600},
            {"decision": "pass", "timestamp": now - 1800},
            {"decision": "kill", "timestamp": now},
        ]
        trends = self.analytics.get_trends(traces=traces, last_days=1)
        self.assertGreater(len(trends), 0)

    def test_get_top_violations(self):
        top = self.analytics.get_top_violations(traces=self._make_traces(), limit=5)
        self.assertGreater(len(top), 0)
        self.assertEqual(top[0]["type"], "pii")

    def test_violations_by_rule(self):
        stats = self.analytics.get_stats(traces=self._make_traces())
        self.assertIn("pii", stats.violations_by_rule)
        self.assertIn("injection", stats.violations_by_rule)

    def test_empty_traces(self):
        stats = self.analytics.get_stats(traces=[])
        self.assertEqual(stats.total_checks, 0)

    def test_stats_to_dict(self):
        stats = self.analytics.get_stats(traces=self._make_traces())
        d = stats.to_dict()
        self.assertIn("kill_rate", d)


# ─── CostTracker Tests ─────────────────────────────────────────────

class TestCostTracker(unittest.TestCase):
    def test_estimate_tokens(self):
        tracker = CostTracker(model="gpt-4")
        tokens = tracker.estimate_tokens("Hello world this is a test")
        self.assertGreater(tokens, 0)

    def test_calculate_savings(self):
        tracker = CostTracker(model="gpt-4")
        traces = [
            {"decision": "kill", "metadata": {"input_text": "test input"}},
            {"decision": "pass", "metadata": {"input_text": "another test"}},
        ]
        report = tracker.calculate_savings(traces, avg_output_tokens=100)
        self.assertEqual(report.early_terminations, 1)
        self.assertGreater(report.tokens_saved, 0)
        self.assertGreater(report.estimated_cost_saved, 0)

    def test_report_to_dict(self):
        tracker = CostTracker()
        report = tracker.calculate_savings([])
        d = report.to_dict()
        self.assertIn("tokens_saved", d)


# ─── AlertManager Tests ────────────────────────────────────────────

class TestAlertManager(unittest.TestCase):
    def setUp(self):
        self.manager = AlertManager()

    def test_add_rule(self):
        rule = AlertRule(
            rule_id="test-1", name="High Kill Rate",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
        )
        self.manager.add_rule(rule)
        self.assertEqual(len(self.manager.list_rules()), 1)

    def test_remove_rule(self):
        rule = AlertRule(rule_id="test-2", name="Test", condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.1)
        self.manager.add_rule(rule)
        self.assertTrue(self.manager.remove_rule("test-2"))

    def test_evaluate_triggers(self):
        rule = AlertRule(
            rule_id="high-kill", name="High Kill Rate",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            cooldown_seconds=0,
        )
        self.manager.add_rule(rule)
        stats = {"kill_rate": 0.1, "total_checks": 100, "total_kills": 10}
        fired = self.manager.evaluate(stats)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].rule_id, "high-kill")

    def test_evaluate_no_trigger(self):
        rule = AlertRule(
            rule_id="low-kill", name="Low Kill Rate",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.5,
            cooldown_seconds=0,
        )
        self.manager.add_rule(rule)
        stats = {"kill_rate": 0.1}
        fired = self.manager.evaluate(stats)
        self.assertEqual(len(fired), 0)

    def test_cooldown(self):
        rule = AlertRule(
            rule_id="cooldown-test", name="Test",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            cooldown_seconds=3600,
        )
        self.manager.add_rule(rule)
        stats = {"kill_rate": 0.1}
        fired1 = self.manager.evaluate(stats)
        fired2 = self.manager.evaluate(stats)
        self.assertEqual(len(fired1), 1)
        self.assertEqual(len(fired2), 0)  # Cooldown

    def test_callback(self):
        events = []
        self.manager.on_alert(lambda e: events.append(e))
        rule = AlertRule(
            rule_id="cb-test", name="Test",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            channels=[AlertChannel.CALLBACK], cooldown_seconds=0,
        )
        self.manager.add_rule(rule)
        self.manager.evaluate({"kill_rate": 0.1})
        self.assertEqual(len(events), 1)

    def test_history(self):
        rule = AlertRule(
            rule_id="hist-test", name="Test",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            cooldown_seconds=0,
        )
        self.manager.add_rule(rule)
        self.manager.evaluate({"kill_rate": 0.1})
        history = self.manager.get_history()
        self.assertEqual(len(history), 1)

    def test_acknowledge(self):
        rule = AlertRule(
            rule_id="ack-test", name="Test",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            cooldown_seconds=0,
        )
        self.manager.add_rule(rule)
        fired = self.manager.evaluate({"kill_rate": 0.1})
        self.assertTrue(self.manager.acknowledge(fired[0].alert_id))

    def test_stats(self):
        self.manager.add_rule(AlertRule(
            rule_id="s1", name="Test", condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.1,
        ))
        stats = self.manager.get_stats()
        self.assertEqual(stats["rules_count"], 1)


# ─── ObservabilityManager Integration Tests ────────────────────────

class TestObservabilityManager(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mktemp(suffix=".db"))
        self.obs = ObservabilityManager(db_path=str(self.db))

    def tearDown(self):
        if self.db.exists():
            self.db.unlink()

    def test_trace_decision(self):
        trace = self.obs.trace_decision(
            session_id="s1", decision="kill", rule="pii",
            duration_ms=2.5, input_text="test",
        )
        self.assertEqual(trace.decision, "kill")
        self.assertEqual(trace.rule_triggered, "pii")

    def test_get_stats(self):
        for i in range(5):
            self.obs.trace_decision(session_id=f"s{i}", decision="kill" if i % 2 else "pass")
        stats = self.obs.get_stats()
        self.assertEqual(stats.total_checks, 5)

    def test_get_cost_report(self):
        self.obs.trace_decision(session_id="s1", decision="kill", input_text="test input")
        report = self.obs.get_cost_report()
        self.assertEqual(report.early_terminations, 1)

    def test_query_traces(self):
        self.obs.trace_decision(session_id="s1", decision="kill")
        self.obs.trace_decision(session_id="s2", decision="pass")
        results = self.obs.query_traces(decision="kill")
        self.assertEqual(len(results), 1)

    def test_export_json(self):
        self.obs.trace_decision(session_id="s1", decision="kill")
        json_str = self.obs.export_traces(format="json")
        self.assertIn("kill", json_str)

    def test_alert_integration(self):
        self.obs.add_alert_rule(AlertRule(
            rule_id="test-alert", name="Test",
            condition=AlertCondition.KILL_RATE_ABOVE, threshold=0.05,
            cooldown_seconds=0,
        ))
        # Fire enough to trigger
        for i in range(10):
            self.obs.trace_decision(session_id=f"s{i}", decision="kill")
        history = self.obs.get_alert_history()
        self.assertGreater(len(history), 0)

    def test_cleanup(self):
        self.obs.trace_decision(session_id="s1", decision="pass")
        cleaned = self.obs.cleanup()
        self.assertIsInstance(cleaned, int)

    def test_observability_stats(self):
        stats = self.obs.get_observability_stats()
        self.assertIn("traces", stats)
        self.assertIn("alerts", stats)


if __name__ == "__main__":
    unittest.main()
