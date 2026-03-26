"""
Tests for Phase 6.6 — Cost Optimization
Covers: cost_monitor, quotas, efficient_ops, cost_report
"""

import json
import os
import tempfile
import time
import threading
from datetime import datetime, timezone, timedelta

import pytest


# =========================================================================
# cost_monitor tests
# =========================================================================

class TestCostEvent:
    def test_cost_event_creation(self):
        from brahmanda.cost_monitor import CostEvent
        event = CostEvent(
            event_id="", tenant_id="acme", agent_id="gpt4", rule_id="R1",
            category="compute", resource_type="kill_decision",
            unit_cost=50, quantity=1,
        )
        assert event.event_id  # auto-generated
        assert event.total_cost == 50
        assert event.cost_dollars() == pytest.approx(5e-7)

    def test_cost_event_to_dict(self):
        from brahmanda.cost_monitor import CostEvent
        event = CostEvent(
            event_id="test", tenant_id="acme", agent_id=None, rule_id=None,
            category="compute", resource_type="api_call",
            unit_cost=5, quantity=3,
        )
        d = event.to_dict()
        assert d["total_cost"] == 15
        assert "cost_dollars" in d

    def test_cost_event_auto_id(self):
        from brahmanda.cost_monitor import CostEvent
        e1 = CostEvent(event_id="", tenant_id="t1", agent_id=None, rule_id=None,
                       category="compute", resource_type="x", unit_cost=1, quantity=1)
        e2 = CostEvent(event_id="", tenant_id="t1", agent_id=None, rule_id=None,
                       category="compute", resource_type="x", unit_cost=1, quantity=1)
        assert e1.event_id != e2.event_id


class TestCostStore:
    def test_store_record_and_query(self):
        from brahmanda.cost_monitor import CostStore, CostEvent
        store = CostStore(in_memory=True)
        event = CostEvent(
            event_id="evt1", tenant_id="acme", agent_id="gpt4", rule_id="R1",
            category="compute", resource_type="kill_decision",
            unit_cost=50, quantity=1,
        )
        store.record_event(event)
        costs = store.get_tenant_costs("acme", "2020-01-01T00:00:00", "2099-01-01T00:00:00")
        assert len(costs) == 1
        assert costs[0]["resource_type"] == "kill_decision"

    def test_store_cost_summary(self):
        from brahmanda.cost_monitor import CostStore, CostEvent
        store = CostStore(in_memory=True)
        for i in range(5):
            store.record_event(CostEvent(
                event_id=f"e{i}", tenant_id="t1", agent_id="a1", rule_id="R1",
                category="compute", resource_type="kill_decision",
                unit_cost=50, quantity=1,
            ))
        summary = store.get_cost_summary("t1", "2020-01-01", "2099-01-01")
        assert summary["total_cost_micro_cents"] == 250
        assert summary["total_events"] == 5
        assert "compute" in summary["by_category"]

    def test_store_anomalies(self):
        from brahmanda.cost_monitor import CostStore, CostAnomaly
        store = CostStore(in_memory=True)
        anomaly = CostAnomaly(
            anomaly_id="a1", tenant_id="t1", anomaly_type="spike",
            severity="high", description="test",
            current_value=1000, expected_value=100, deviation_pct=900,
        )
        store.record_anomaly(anomaly)
        anomalies = store.get_anomalies("t1")
        assert len(anomalies) == 1


class TestCostTracker:
    def test_tracker_disabled_by_default(self):
        from brahmanda.cost_monitor import CostTracker, CostStore
        tracker = CostTracker(store=CostStore(in_memory=True))
        assert not tracker.enabled
        result = tracker.track("t1", "kill_decision")
        assert result is None

    def test_tracker_enable_and_track(self):
        from brahmanda.cost_monitor import CostTracker, CostStore
        tracker = CostTracker(store=CostStore(in_memory=True))
        tracker.enable()
        event = tracker.track("t1", "kill_decision", agent_id="a1", rule_id="R1")
        assert event is not None
        assert event.resource_type == "kill_decision"
        assert event.category == "compute"

    def test_tracker_convenience_methods(self):
        from brahmanda.cost_monitor import CostTracker, CostStore
        tracker = CostTracker(store=CostStore(in_memory=True))
        tracker.enable()
        e1 = tracker.track_kill_decision("t1", "a1", "R1")
        e2 = tracker.track_drift_check("t1", "a1")
        e3 = tracker.track_api_call("t1", "/api/check")
        e4 = tracker.track_webhook("t1", "RULE_VIOLATION")
        e5 = tracker.track_storage("t1", mb=10.0, hours=24.0)
        e6 = tracker.track_audit_entry("t1")
        assert all([e1, e2, e3, e4, e5, e6])

    def test_tracker_callbacks(self):
        from brahmanda.cost_monitor import CostTracker, CostStore
        tracker = CostTracker(store=CostStore(in_memory=True))
        tracker.enable()
        events = []
        tracker.on_cost_event(lambda e: events.append(e))
        tracker.track("t1", "kill_decision")
        assert len(events) == 1

    def test_classify_resource(self):
        from brahmanda.cost_monitor import CostTracker
        assert CostTracker._classify_resource("kill_decision") == "compute"
        assert CostTracker._classify_resource("api_call") == "network"
        assert CostTracker._classify_resource("audit_log_entry") == "storage"


class TestCostAnomalyDetector:
    def test_no_anomalies_insufficient_data(self):
        from brahmanda.cost_monitor import CostAnomalyDetector, CostStore
        store = CostStore(in_memory=True)
        detector = CostAnomalyDetector(store=store)
        anomalies = detector.detect_anomalies("t1", lookback_days=7)
        assert anomalies == []


class TestCostOptimizer:
    def test_no_recommendations_empty_data(self):
        from brahmanda.cost_monitor import CostOptimizer, CostStore
        store = CostStore(in_memory=True)
        optimizer = CostOptimizer(store=store)
        recs = optimizer.generate_recommendations("t1", "2020-01-01", "2099-01-01")
        assert recs == []

    def test_batch_recommendation(self):
        from brahmanda.cost_monitor import CostOptimizer, CostStore, CostEvent
        store = CostStore(in_memory=True)
        # Create 10 kill events worth 50 each = 500 μ¢, plus 200 of others = 700 total
        for i in range(10):
            store.record_event(CostEvent(
                event_id=f"kill{i}", tenant_id="t1", agent_id="a1", rule_id="R1",
                category="compute", resource_type="kill_decision",
                unit_cost=50, quantity=1,
            ))
        for i in range(2):
            store.record_event(CostEvent(
                event_id=f"other{i}", tenant_id="t1", agent_id="a1", rule_id=None,
                category="storage", resource_type="audit_log_entry",
                unit_cost=100, quantity=1,
            ))
        optimizer = CostOptimizer(store=store)
        recs = optimizer.generate_recommendations("t1", "2020-01-01", "2099-01-01")
        # Kills are 500/700 > 40%, should trigger batching recommendation
        titles = [r.title for r in recs]
        assert "Batch kill decisions" in titles


# =========================================================================
# quotas tests
# =========================================================================

class TestQuotaLimit:
    def test_basic_limit(self):
        from brahmanda.quotas import QuotaLimit
        limit = QuotaLimit(resource="max_kills_per_hour", hard_limit=100,
                          soft_limit_pct=80.0, period="hour")
        assert limit.soft_limit == 80
        assert limit.usage_pct == 0.0
        assert limit.remaining == 100
        assert not limit.is_soft_exceeded

    def test_unlimited(self):
        from brahmanda.quotas import QuotaLimit
        limit = QuotaLimit(resource="x", hard_limit=-1, soft_limit_pct=80.0, period="hour")
        assert limit.is_unlimited
        assert limit.remaining == -1
        assert not limit.is_soft_exceeded
        assert not limit.is_hard_exceeded

    def test_usage_tracking(self):
        from brahmanda.quotas import QuotaLimit
        limit = QuotaLimit(resource="x", hard_limit=100, soft_limit_pct=80.0, period="hour")
        limit.current_usage = 85
        assert limit.is_soft_exceeded
        assert not limit.is_hard_exceeded
        assert limit.usage_pct == pytest.approx(85.0)

    def test_hard_exceeded(self):
        from brahmanda.quotas import QuotaLimit
        limit = QuotaLimit(resource="x", hard_limit=100, soft_limit_pct=80.0, period="hour")
        limit.current_usage = 100
        assert limit.is_hard_exceeded
        assert limit.remaining == 0


class TestQuotaStore:
    def test_profile_lifecycle(self):
        from brahmanda.quotas import QuotaStore, TenantQuotaProfile, QuotaLimit
        store = QuotaStore(in_memory=True)
        profile = TenantQuotaProfile(
            tenant_id="t1", tier="pro",
            limits={"x": QuotaLimit(resource="x", hard_limit=100, soft_limit_pct=80, period="hour")},
        )
        store.upsert_profile(profile)
        loaded = store.get_profile("t1")
        assert loaded is not None
        assert loaded.tier == "pro"

    def test_usage_increment(self):
        from brahmanda.quotas import QuotaStore
        store = QuotaStore(in_memory=True)
        store.increment_usage("t1", "max_kills_per_hour", "2026-03-26T13", "2026-03-26T13:00:00")
        store.increment_usage("t1", "max_kills_per_hour", "2026-03-26T13", "2026-03-26T13:00:00", 3)
        usage = store.get_usage("t1", "max_kills_per_hour", "2026-03-26T13")
        assert usage == 4

    def test_usage_reset(self):
        from brahmanda.quotas import QuotaStore
        store = QuotaStore(in_memory=True)
        store.increment_usage("t1", "x", "k", "w")
        store.reset_usage("t1")
        assert store.get_usage("t1", "x", "k") == 0

    def test_violations(self):
        from brahmanda.quotas import QuotaStore, QuotaViolation
        store = QuotaStore(in_memory=True)
        v = QuotaViolation(violation_id="", tenant_id="t1", resource="x",
                          limit_type="hard", current_usage=100, limit_value=100, period="hour")
        store.record_violation(v)
        violations = store.get_violations("t1")
        assert len(violations) == 1


class TestQuotaManager:
    def test_create_tenant(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        profile = manager.create_tenant("t1", tier="pro")
        assert profile.tier == "pro"
        assert "max_kills_per_hour" in profile.limits

    def test_tier_limits(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        free = manager.create_tenant("free_t", tier="free")
        pro = manager.create_tenant("pro_t", tier="pro")
        assert free.limits["max_kills_per_hour"].hard_limit < pro.limits["max_kills_per_hour"].hard_limit

    def test_disabled_allows_all(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        assert not manager.enabled
        assert manager.check_and_consume("t1", "max_kills_per_hour")

    def test_hard_limit_blocks(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        manager.enable()
        manager.create_tenant("t1", tier="free")
        # Free tier: 5 kills/hour
        for _ in range(5):
            assert manager.check_and_consume("t1", "max_kills_per_hour")
        # 6th should be blocked
        assert not manager.check_and_consume("t1", "max_kills_per_hour")

    def test_soft_limit_callback(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        manager.enable()
        manager.create_tenant("t1", tier="free")  # 5 kills, soft at 4
        violations = []
        manager.on_violation(lambda v: violations.append(v))
        for _ in range(4):
            manager.check_and_consume("t1", "max_kills_per_hour")
        assert len(violations) == 1
        assert violations[0].limit_type == "soft"

    def test_usage_status(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        manager.enable()
        manager.create_tenant("t1", tier="starter")
        manager.check_and_consume("t1", "max_kills_per_hour")
        status = manager.get_usage_status("t1")
        assert status["tier"] == "starter"
        assert status["resources"]["max_kills_per_hour"]["current"] == 1

    def test_update_tier(self):
        from brahmanda.quotas import QuotaManager, QuotaStore
        manager = QuotaManager(store=QuotaStore(in_memory=True))
        manager.create_tenant("t1", tier="free")
        manager.update_tier("t1", "enterprise")
        profile = manager.get_usage_status("t1")
        assert profile["tier"] == "enterprise"


# =========================================================================
# efficient_ops tests
# =========================================================================

class TestBatchKillProcessor:
    def test_enqueue_and_flush(self):
        from brahmanda.efficient_ops import BatchKillProcessor, PendingKill
        batches = []
        processor = BatchKillProcessor(max_batch_size=3, handler=lambda b: batches.append(b))
        for i in range(3):
            processor.enqueue(PendingKill(
                tenant_id="t1", agent_id="a1", session_id=f"s{i}",
                rule_id="R1", reason="test", severity="high",
            ))
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_flush_tenant(self):
        from brahmanda.efficient_ops import BatchKillProcessor, PendingKill
        batches = []
        processor = BatchKillProcessor(max_batch_size=100, handler=lambda b: batches.append(b))
        processor.enqueue(PendingKill(tenant_id="t1", agent_id="a1", session_id="s1",
                                      rule_id="R1", reason="test", severity="high"))
        processor.flush_tenant("t1")
        assert len(batches) == 1

    def test_stats(self):
        from brahmanda.efficient_ops import BatchKillProcessor, PendingKill
        processor = BatchKillProcessor(max_batch_size=2, handler=lambda b: None)
        processor.enqueue(PendingKill(tenant_id="t1", agent_id="a1", session_id="s1",
                                      rule_id="R1", reason="t", severity="high"))
        processor.enqueue(PendingKill(tenant_id="t1", agent_id="a1", session_id="s2",
                                      rule_id="R1", reason="t", severity="high"))
        stats = processor.get_stats()
        assert stats["total_enqueued"] == 2
        assert stats["total_flushed"] == 2


class TestLazyDriftScorer:
    def test_cache_miss_no_fn(self):
        from brahmanda.efficient_ops import LazyDriftScorer
        scorer = LazyDriftScorer()
        result = scorer.get_drift_score("agent_1")
        assert result is None

    def test_cache_hit(self):
        from brahmanda.efficient_ops import LazyDriftScorer
        scorer = LazyDriftScorer()
        compute_calls = [0]
        def compute_fn(agent_id):
            compute_calls[0] += 1
            return 0.5, {"semantic": 0.5}
        r1 = scorer.get_drift_score("a1", compute_fn=compute_fn)
        r2 = scorer.get_drift_score("a1", compute_fn=compute_fn)
        assert r1 == r2
        assert compute_calls[0] == 1  # only computed once

    def test_force_recompute(self):
        from brahmanda.efficient_ops import LazyDriftScorer
        scorer = LazyDriftScorer()
        calls = [0]
        def fn(aid):
            calls[0] += 1
            return float(calls[0]), {"x": 1.0}
        scorer.get_drift_score("a1", compute_fn=fn)
        scorer.get_drift_score("a1", compute_fn=fn, force_recompute=True)
        assert calls[0] == 2

    def test_invalidate(self):
        from brahmanda.efficient_ops import LazyDriftScorer
        scorer = LazyDriftScorer()
        scorer.get_drift_score("a1", compute_fn=lambda a: (0.5, {}))
        scorer.invalidate("a1")
        assert scorer.get_drift_score("a1") is None

    def test_stats(self):
        from brahmanda.efficient_ops import LazyDriftScorer
        scorer = LazyDriftScorer()
        scorer.get_drift_score("a1", compute_fn=lambda a: (0.5, {}))
        scorer.get_drift_score("a1")
        stats = scorer.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestCacheWarmer:
    def test_put_and_get(self):
        from brahmanda.efficient_ops import CacheWarmer
        warmer = CacheWarmer()
        warmer.put("R1", "a1", value={"result": 42})
        result = warmer.get("R1", "a1")
        assert result == {"result": 42}

    def test_access_tracking(self):
        from brahmanda.efficient_ops import CacheWarmer
        warmer = CacheWarmer()
        warmer.record_access("R1", "a1", "ctx1")
        warmer.record_access("R1", "a1", "ctx1")
        warmer.record_access("R2", "a1", "")
        stats = warmer.get_stats()
        assert stats["access_patterns"] == 2

    def test_warm(self):
        from brahmanda.efficient_ops import CacheWarmer
        warmer = CacheWarmer()
        warmer.record_access("R1", "a1", "")
        warmer.record_access("R2", "a1", "")
        def compute(rule, agent, ctx):
            return f"computed_{rule}"
        warmer.warm(compute_fn=compute, top_n=10)
        assert warmer.get("R1", "a1") == "computed_R1"
        assert warmer.get("R2", "a1") == "computed_R2"


class TestCompressedAuditLog:
    def test_append_and_read(self):
        from brahmanda.efficient_ops import CompressedAuditLog
        log = CompressedAuditLog(in_memory=True)
        entry_id = log.append({"event": "kill", "agent": "gpt4"}, tenant_id="t1")
        assert entry_id
        entry = log.read(entry_id)
        assert entry["event"] == "kill"

    def test_read_all_with_filter(self):
        from brahmanda.efficient_ops import CompressedAuditLog
        log = CompressedAuditLog(in_memory=True)
        log.append({"data": "a"}, tenant_id="t1", event_type="kill")
        log.append({"data": "b"}, tenant_id="t2", event_type="kill")
        entries = log.read_all(tenant_id="t1")
        assert len(entries) == 1

    def test_compression_stats(self):
        from brahmanda.efficient_ops import CompressedAuditLog
        log = CompressedAuditLog(in_memory=True)
        for i in range(100):
            log.append({"event": "test", "data": "x" * 100, "i": i})
        stats = log.get_compression_stats()
        assert stats["entries"] == 100
        assert stats["compression_ratio"] > 0  # some compression achieved
        assert stats["space_saved_bytes"] > 0


# =========================================================================
# cost_report tests
# =========================================================================

class TestCostBreakdown:
    def test_to_dict(self):
        from brahmanda.cost_report import CostBreakdown
        b = CostBreakdown(resource_type="kill", category="compute",
                         total_cost_micro_cents=1000, event_count=10,
                         avg_cost_per_event=100, pct_of_total=50.0)
        d = b.to_dict()
        assert d["total_cost_dollars"] == pytest.approx(1e-5)


class TestROICalculation:
    def test_to_dict(self):
        from brahmanda.cost_report import ROICalculation
        roi = ROICalculation(
            total_kill_cost_micro_cents=1000,
            estimated_violation_cost_micro_cents=100000,
            violations_prevented=10,
            cost_per_violation_prevented=100,
            roi_ratio=99.0,
            savings_micro_cents=99000,
        )
        d = roi.to_dict()
        assert d["roi_ratio"] == 99.0
        assert d["violations_prevented"] == 10


class TestCostReportGenerator:
    def test_generate_empty_report(self):
        from brahmanda.cost_report import CostReportGenerator
        gen = CostReportGenerator()
        report = gen.generate_report("t1", "2026-03-01", "2026-04-01")
        assert report.total_cost_micro_cents == 0
        assert report.roi is None

    def test_generate_with_tracker(self):
        from brahmanda.cost_monitor import CostTracker, CostStore
        from brahmanda.cost_report import CostReportGenerator
        store = CostStore(in_memory=True)
        tracker = CostTracker(store=store)
        tracker.enable()
        tracker.track_kill_decision("t1", "a1", "R1")
        tracker.track_kill_decision("t1", "a1", "R2")
        gen = CostReportGenerator(cost_tracker=tracker)
        report = gen.generate_report("t1", "2020-01-01", "2099-01-01")
        assert report.total_events == 2
        assert report.roi is not None
        assert report.roi.violations_prevented == 2

    def test_export_csv(self):
        from brahmanda.cost_report import CostReportGenerator, CostReport, CostBreakdown
        gen = CostReportGenerator()
        report = CostReport(
            report_id="r1", tenant_id="t1", period_type="daily",
            period_start="2026-03-26", period_end="2026-03-27",
            total_cost_micro_cents=1000, total_events=10,
            breakdowns=[CostBreakdown(resource_type="kill", category="compute",
                                     total_cost_micro_cents=1000, event_count=10,
                                     avg_cost_per_event=100, pct_of_total=100)],
            roi=None,
        )
        csv_str = gen.export_csv(report)
        assert "kill" in csv_str
        assert "t1" in csv_str

    def test_export_json(self):
        from brahmanda.cost_report import CostReportGenerator, CostReport
        gen = CostReportGenerator()
        report = CostReport(
            report_id="r1", tenant_id="t1", period_type="daily",
            period_start="2026-03-26", period_end="2026-03-27",
            total_cost_micro_cents=1000, total_events=10,
            breakdowns=[], roi=None,
        )
        j = json.loads(gen.export_json(report))
        assert j["tenant_id"] == "t1"

    def test_export_markdown(self):
        from brahmanda.cost_report import CostReportGenerator, CostReport
        gen = CostReportGenerator()
        report = CostReport(
            report_id="r1", tenant_id="acme", period_type="monthly",
            period_start="2026-03-01", period_end="2026-04-01",
            total_cost_micro_cents=5000, total_events=50,
            breakdowns=[], roi=None,
        )
        md = gen.export_markdown(report)
        assert "# Cost Report — acme" in md


class TestBillingAdapter:
    def test_stripe_payload(self):
        from brahmanda.cost_report import BillingAdapter, CostReport, CostBreakdown
        adapter = BillingAdapter(platform="stripe")
        report = CostReport(
            report_id="r1", tenant_id="t1", period_type="daily",
            period_start="2026-03-26", period_end="2026-03-27",
            total_cost_micro_cents=10000, total_events=10,
            breakdowns=[CostBreakdown(resource_type="kill", category="compute",
                                     total_cost_micro_cents=10000, event_count=10,
                                     avg_cost_per_event=1000, pct_of_total=100)],
            roi=None,
        )
        payload = adapter.generate_stripe_payload(report)
        assert payload["customer"] == "t1"
        assert len(payload["lines"]) == 1

    def test_paddle_payload(self):
        from brahmanda.cost_report import BillingAdapter, CostReport, CostBreakdown
        adapter = BillingAdapter(platform="paddle")
        report = CostReport(
            report_id="r1", tenant_id="t1", period_type="daily",
            period_start="2026-03-26", period_end="2026-03-27",
            total_cost_micro_cents=10000, total_events=10,
            breakdowns=[CostBreakdown(resource_type="kill", category="compute",
                                     total_cost_micro_cents=10000, event_count=10,
                                     avg_cost_per_event=1000, pct_of_total=100)],
            roi=None,
        )
        payload = adapter.generate_paddle_payload(report)
        assert payload["customer_id"] == "t1"


# =========================================================================
# __init__ import tests
# =========================================================================

class TestImports:
    def test_cost_monitor_imports(self):
        from brahmanda import (
            CostEvent, CostAnomaly, OptimizationRecommendation,
            CostCategory, AnomalyType,
            CostTracker, CostStore, CostAnomalyDetector, CostOptimizer,
            get_cost_tracker, reset_cost_tracker,
        )

    def test_quotas_imports(self):
        from brahmanda import (
            QuotaLimit, QuotaViolation, TenantQuotaProfile,
            PricingTier, TIER_QUOTAS,
            QuotaManager, QuotaStore,
            get_quota_manager, reset_quota_manager,
        )

    def test_efficient_ops_imports(self):
        from brahmanda import (
            PendingKill, BatchKillProcessor,
            DriftScoreCache, LazyDriftScorer,
            CacheEntry, CacheWarmer,
            CompressedAuditLog,
        )

    def test_cost_report_imports(self):
        from brahmanda import (
            CostBreakdown, ROICalculation, CostReport,
            ReportPeriod, CostReportGenerator, BillingAdapter,
        )
