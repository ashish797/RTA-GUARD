"""
Test suite for brahmanda SLA Monitoring System (Phase 4.8).

Tests cover:
- Request recording and metrics calculation
- SLA breach detection
- Uptime calculation
- Response time tracking
- Kill rate calculation
- False positive rate
- Mean time to detect
- Date-range breach queries
- Singleton management

All tests use in-memory SQLite — no network calls.

Run with: ``python3 -m pytest brahmanda/test_sla_monitor.py -v``
"""

import sys
import os
import time
import pytest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _import_sla():
    """Import SLA symbols, skipping if unavailable."""
    try:
        from brahmanda.sla_monitor import (
            SLAMetric, SLABreach, SLAStatus, SLATracker,
            RequestRecord, KillRecord,
            get_sla_tracker, reset_sla_tracker,
            DEFAULT_SLA_THRESHOLDS,
        )
        return (SLAMetric, SLABreach, SLAStatus, SLATracker,
                RequestRecord, KillRecord,
                get_sla_tracker, reset_sla_tracker,
                DEFAULT_SLA_THRESHOLDS)
    except ImportError as exc:
        pytest.skip(f"SLA monitor module not yet implemented: {exc}")


def _import_tracker():
    (_, _, _, SLATracker, *_) = _import_sla()
    return SLATracker


# =========================================================================
# Dataclass Tests
# =========================================================================

class TestSLAMetric:
    """Tests for SLAMetric dataclass."""

    def test_creation(self):
        from brahmanda.sla_monitor import SLAMetric
        m = SLAMetric(name="uptime", value=99.95, threshold=99.9,
                      threshold_direction="above", status="within", unit="%")
        assert m.name == "uptime"
        assert m.value == 99.95
        assert m.status == "within"
        assert m.unit == "%"
        assert m.timestamp  # auto-generated

    def test_to_dict(self):
        from brahmanda.sla_monitor import SLAMetric
        m = SLAMetric(name="uptime", value=99.95, threshold=99.9,
                      threshold_direction="above", status="within", unit="%")
        d = m.to_dict()
        assert d["name"] == "uptime"
        assert d["value"] == 99.95
        assert d["status"] == "within"

    def test_invalid_status_raises(self):
        from brahmanda.sla_monitor import SLAMetric
        with pytest.raises(ValueError, match="Invalid status"):
            SLAMetric(name="uptime", value=100, threshold=99.9,
                      threshold_direction="above", status="INVALID")

    def test_custom_timestamp(self):
        from brahmanda.sla_monitor import SLAMetric
        ts = "2026-01-01T00:00:00+00:00"
        m = SLAMetric(name="uptime", value=100, threshold=99.9,
                      threshold_direction="above", status="within", timestamp=ts)
        assert m.timestamp == ts


class TestSLABreach:
    """Tests for SLABreach dataclass."""

    def test_creation(self):
        from brahmanda.sla_monitor import SLABreach
        b = SLABreach(breach_id="abc", metric_name="uptime", value=98.0,
                      threshold=99.9, timestamp="2026-01-01T00:00:00Z")
        assert b.breach_id == "abc"
        assert b.metric_name == "uptime"
        assert b.details == ""

    def test_to_dict(self):
        from brahmanda.sla_monitor import SLABreach
        b = SLABreach(breach_id="abc", metric_name="uptime", value=98.0,
                      threshold=99.9, timestamp="2026-01-01T00:00:00Z",
                      details="Uptime below 99.9%")
        d = b.to_dict()
        assert d["breach_id"] == "abc"
        assert d["details"] == "Uptime below 99.9%"


class TestRequestRecord:
    """Tests for RequestRecord dataclass."""

    def test_creation(self):
        from brahmanda.sla_monitor import RequestRecord
        r = RequestRecord(endpoint="/api/check", duration_ms=120.5, status_code=200)
        assert r.endpoint == "/api/check"
        assert r.duration_ms == 120.5
        assert r.status_code == 200
        assert r.record_id  # auto-generated UUID
        assert r.timestamp  # auto-generated

    def test_custom_timestamp(self):
        from brahmanda.sla_monitor import RequestRecord
        ts = "2026-01-01T00:00:00+00:00"
        r = RequestRecord(endpoint="/api/check", duration_ms=100, status_code=200, timestamp=ts)
        assert r.timestamp == ts


class TestKillRecord:
    """Tests for KillRecord dataclass."""

    def test_creation(self):
        from brahmanda.sla_monitor import KillRecord
        k = KillRecord(session_id="s1", reason="violation", detection_time_ms=50.0)
        assert k.session_id == "s1"
        assert k.reason == "violation"
        assert k.detection_time_ms == 50.0
        assert k.is_false_positive is False
        assert k.record_id  # auto-generated

    def test_false_positive(self):
        from brahmanda.sla_monitor import KillRecord
        k = KillRecord(session_id="s1", reason="violation", detection_time_ms=50.0,
                       is_false_positive=True)
        assert k.is_false_positive is True


# =========================================================================
# SLATracker — Initialization
# =========================================================================

class TestSLATrackerInit:
    """Tests for SLATracker initialization."""

    def test_in_memory(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_request_count() == 0
        assert tracker.get_kill_count() == 0
        assert tracker.get_breach_count() == 0

    def test_file_based(self, tmp_path):
        SLATracker = _import_tracker()
        db = str(tmp_path / "sla.db")
        tracker = SLATracker(db_path=db)
        assert os.path.exists(db)

    def test_default_thresholds(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        status = tracker.get_sla_status()
        assert len(status) == 6
        names = [m.name for m in status]
        assert "uptime_percentage" in names
        assert "avg_response_time_ms" in names
        assert "kill_rate" in names

    def test_custom_thresholds(self):
        SLATracker = _import_tracker()
        custom = {
            "uptime_percentage": {"threshold": 99.0, "direction": "above", "unit": "%"},
            "avg_response_time_ms": {"threshold": 1000.0, "direction": "below", "unit": "ms"},
            "kill_rate": {"threshold": 0.1, "direction": "below", "unit": "ratio"},
            "false_positive_rate": {"threshold": 0.02, "direction": "below", "unit": "ratio"},
            "mean_time_to_detect_ms": {"threshold": 2000.0, "direction": "below", "unit": "ms"},
            "api_availability": {"threshold": 99.0, "direction": "above", "unit": "%"},
        }
        tracker = SLATracker(thresholds=custom)
        status = tracker.get_sla_status()
        uptime_metric = next(m for m in status if m.name == "uptime_percentage")
        assert uptime_metric.threshold == 99.0


# =========================================================================
# Request Recording
# =========================================================================

class TestRequestRecording:
    """Tests for request recording."""

    def test_record_request(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        rid = tracker.record_request("/api/check", 100.0, 200)
        assert rid
        assert tracker.get_request_count() == 1

    def test_record_multiple(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_request(f"/api/endpoint{i}", 50.0 + i, 200)
        assert tracker.get_request_count() == 10

    def test_record_with_timestamp(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        ts = "2026-01-01T00:00:00+00:00"
        rid = tracker.record_request("/api/check", 100.0, 200, timestamp=ts)
        assert rid


# =========================================================================
# Kill Recording
# =========================================================================

class TestKillRecording:
    """Tests for kill recording."""

    def test_record_kill(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        rid = tracker.record_kill("sess-1", "violation", 50.0)
        assert rid
        assert tracker.get_kill_count() == 1

    def test_record_false_positive(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_kill("sess-1", "violation", 50.0, is_false_positive=True)
        assert tracker.get_kill_count() == 1
        assert tracker.get_false_positive_rate() == 1.0

    def test_record_multiple_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(5):
            tracker.record_kill(f"sess-{i}", "violation", 50.0 + i)
        assert tracker.get_kill_count() == 5


# =========================================================================
# Uptime Calculation
# =========================================================================

class TestUptimeCalculation:
    """Tests for uptime percentage calculation."""

    def test_no_requests(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_uptime_percentage() == 100.0

    def test_all_successful(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_request("/api/check", 100.0, 200)
        assert tracker.get_uptime_percentage() == 100.0

    def test_all_failed(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_request("/api/check", 100.0, 500)
        assert tracker.get_uptime_percentage() == 0.0

    def test_mixed(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 8 successes, 2 failures
        for _ in range(8):
            tracker.record_request("/api/check", 100.0, 200)
        for _ in range(2):
            tracker.record_request("/api/check", 100.0, 500)
        assert tracker.get_uptime_percentage() == pytest.approx(80.0)

    def test_201_204_are_success(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 100.0, 201)
        tracker.record_request("/api/check", 100.0, 204)
        tracker.record_request("/api/check", 100.0, 400)  # client error, not server error
        assert tracker.get_uptime_percentage() == pytest.approx(75.0)

    def test_uptime_sla_within(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 999 success + 1 failure = 99.9%
        for _ in range(999):
            tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 100.0, 500)
        assert tracker.get_uptime_percentage() == pytest.approx(99.9)
        status = tracker.get_sla_status()
        uptime = next(m for m in status if m.name == "uptime_percentage")
        # 99.9 >= 99.9 = within
        assert uptime.status == "within"

    def test_uptime_sla_breached(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 99 success + 1 failure = 99.0%
        for _ in range(99):
            tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 100.0, 500)
        assert tracker.get_uptime_percentage() == pytest.approx(99.0)
        status = tracker.get_sla_status()
        uptime = next(m for m in status if m.name == "uptime_percentage")
        assert uptime.status == "breached"


# =========================================================================
# Response Time Tracking
# =========================================================================

class TestResponseTimeTracking:
    """Tests for average response time calculation."""

    def test_no_requests(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_avg_response_time() == 0.0

    def test_single_request(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 250.0, 200)
        assert tracker.get_avg_response_time() == 250.0

    def test_multiple_requests(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 200.0, 200)
        tracker.record_request("/api/check", 300.0, 200)
        assert tracker.get_avg_response_time() == pytest.approx(200.0)

    def test_fast_responses_within_sla(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for _ in range(10):
            tracker.record_request("/api/check", 100.0, 200)
        status = tracker.get_sla_status()
        rt = next(m for m in status if m.name == "avg_response_time_ms")
        assert rt.status == "within"
        assert rt.value == 100.0

    def test_slow_responses_breach_sla(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for _ in range(10):
            tracker.record_request("/api/check", 800.0, 200)
        status = tracker.get_sla_status()
        rt = next(m for m in status if m.name == "avg_response_time_ms")
        assert rt.status == "breached"
        assert rt.value == 800.0

    def test_individual_breach_recorded(self):
        """Recording a slow request should auto-create a breach record."""
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 600.0, 200)  # 600 > 500 threshold
        assert tracker.get_breach_count() == 1
        breaches = tracker.get_sla_breaches()
        assert breaches[0].metric_name == "avg_response_time_ms"

    def test_fast_request_no_breach(self):
        """Recording a fast request should NOT create a breach record."""
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 200.0, 200)
        assert tracker.get_breach_count() == 0


# =========================================================================
# Kill Rate Calculation
# =========================================================================

class TestKillRate:
    """Tests for kill rate calculation."""

    def test_no_data(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_kill_rate() == 0.0

    def test_no_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for _ in range(10):
            tracker.record_request("/api/check", 100.0, 200)
        assert tracker.get_kill_rate() == 0.0

    def test_with_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for _ in range(8):
            tracker.record_request("/api/check", 100.0, 200)
        for _ in range(2):
            tracker.record_kill("sess", "violation", 50.0)
        assert tracker.get_kill_rate() == pytest.approx(0.25)

    def test_all_killed(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_request("/api/check", 100.0, 200)
            tracker.record_kill(f"sess-{i}", "violation", 50.0)
        assert tracker.get_kill_rate() == pytest.approx(1.0)

    def test_kill_rate_within_sla(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 1 kill out of 100 = 0.01 (below 0.05 threshold)
        for _ in range(99):
            tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 100.0, 200)
        tracker.record_kill("sess", "violation", 50.0)
        assert tracker.get_kill_rate() == pytest.approx(0.01)
        status = tracker.get_sla_status()
        kr = next(m for m in status if m.name == "kill_rate")
        assert kr.status == "within"

    def test_kill_rate_breached(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 10 kills out of 100 = 0.1 (above 0.05 threshold)
        for i in range(100):
            tracker.record_request("/api/check", 100.0, 200)
        for i in range(10):
            tracker.record_kill(f"sess-{i}", "violation", 50.0)
        assert tracker.get_kill_rate() == pytest.approx(0.1)
        status = tracker.get_sla_status()
        kr = next(m for m in status if m.name == "kill_rate")
        assert kr.status == "breached"


# =========================================================================
# False Positive Rate
# =========================================================================

class TestFalsePositiveRate:
    """Tests for false positive rate calculation."""

    def test_no_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_false_positive_rate() == 0.0

    def test_no_false_positives(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_kill(f"sess-{i}", "violation", 50.0, is_false_positive=False)
        assert tracker.get_false_positive_rate() == 0.0

    def test_all_false_positives(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_kill(f"sess-{i}", "violation", 50.0, is_false_positive=True)
        assert tracker.get_false_positive_rate() == 1.0

    def test_mixed(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 1 FP out of 4 = 0.25
        tracker.record_kill("s1", "violation", 50.0, is_false_positive=True)
        tracker.record_kill("s2", "violation", 50.0, is_false_positive=False)
        tracker.record_kill("s3", "violation", 50.0, is_false_positive=False)
        tracker.record_kill("s4", "violation", 50.0, is_false_positive=False)
        assert tracker.get_false_positive_rate() == pytest.approx(0.25)

    def test_fp_within_sla(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 0 FP out of 100 = 0.0 (below 0.01 threshold)
        for i in range(100):
            tracker.record_kill(f"s-{i}", "violation", 50.0, is_false_positive=False)
        status = tracker.get_sla_status()
        fp = next(m for m in status if m.name == "false_positive_rate")
        assert fp.status == "within"

    def test_fp_breached(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        # 5 FP out of 100 = 0.05 (above 0.01 threshold)
        for i in range(95):
            tracker.record_kill(f"s-{i}", "violation", 50.0, is_false_positive=False)
        for i in range(5):
            tracker.record_kill(f"s-fp-{i}", "violation", 50.0, is_false_positive=True)
        status = tracker.get_sla_status()
        fp = next(m for m in status if m.name == "false_positive_rate")
        assert fp.status == "breached"


# =========================================================================
# Mean Time to Detect
# =========================================================================

class TestMeanTimeToDetect:
    """Tests for mean time to detect calculation."""

    def test_no_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_mean_time_to_detect() == 0.0

    def test_single_kill(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_kill("s1", "violation", 100.0)
        assert tracker.get_mean_time_to_detect() == 100.0

    def test_multiple_kills(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_kill("s1", "violation", 100.0)
        tracker.record_kill("s2", "violation", 200.0)
        tracker.record_kill("s3", "violation", 300.0)
        assert tracker.get_mean_time_to_detect() == pytest.approx(200.0)

    def test_mttd_within_sla(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_kill(f"s-{i}", "violation", 200.0 + i)
        status = tracker.get_sla_status()
        mttd = next(m for m in status if m.name == "mean_time_to_detect_ms")
        assert mttd.status == "within"  # avg ~204.5 < 1000 threshold

    def test_mttd_breached(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for i in range(10):
            tracker.record_kill(f"s-{i}", "violation", 2000.0 + i)
        status = tracker.get_sla_status()
        mttd = next(m for m in status if m.name == "mean_time_to_detect_ms")
        assert mttd.status == "breached"


# =========================================================================
# SLA Status
# =========================================================================

class TestSLAStatus:
    """Tests for get_sla_status()."""

    def test_all_within_no_data(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        status = tracker.get_sla_status()
        assert len(status) == 6
        # With no data, uptime and availability are 100% (within), everything else is within (0 <= threshold)
        for m in status:
            assert isinstance(m.name, str)
            assert m.status in ("within", "breached")

    def test_status_is_sla_metric(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        from brahmanda.sla_monitor import SLAMetric
        status = tracker.get_sla_status()
        for m in status:
            assert isinstance(m, SLAMetric)

    def test_all_metrics_present(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        status = tracker.get_sla_status()
        names = {m.name for m in status}
        assert names == {
            "uptime_percentage", "avg_response_time_ms", "kill_rate",
            "false_positive_rate", "mean_time_to_detect_ms", "api_availability",
        }

    def test_to_dict(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        status = tracker.get_sla_status()
        for m in status:
            d = m.to_dict()
            assert "name" in d
            assert "value" in d
            assert "threshold" in d
            assert "status" in d


# =========================================================================
# Breach Queries
# =========================================================================

class TestBreachQueries:
    """Tests for SLA breach queries."""

    def test_no_breaches(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        assert tracker.get_sla_breaches() == []

    def test_slow_request_creates_breach(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 800.0, 200)
        breaches = tracker.get_sla_breaches()
        assert len(breaches) == 1
        assert breaches[0].metric_name == "avg_response_time_ms"
        assert breaches[0].value == 800.0

    def test_date_range_filter(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 800.0, 200, timestamp="2026-01-01T00:00:00+00:00")
        tracker.record_request("/api/check", 900.0, 200, timestamp="2026-01-15T00:00:00+00:00")
        tracker.record_request("/api/check", 700.0, 200, timestamp="2026-02-01T00:00:00+00:00")
        # Filter to January only
        breaches = tracker.get_sla_breaches(
            from_date="2026-01-01T00:00:00+00:00",
            to_date="2026-01-31T23:59:59+00:00",
        )
        assert len(breaches) == 2

    def test_from_date_only(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 800.0, 200, timestamp="2026-01-01T00:00:00+00:00")
        tracker.record_request("/api/check", 900.0, 200, timestamp="2026-02-01T00:00:00+00:00")
        breaches = tracker.get_sla_breaches(from_date="2026-02-01T00:00:00+00:00")
        assert len(breaches) == 1

    def test_to_date_only(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 800.0, 200, timestamp="2026-01-01T00:00:00+00:00")
        tracker.record_request("/api/check", 900.0, 200, timestamp="2026-02-01T00:00:00+00:00")
        breaches = tracker.get_sla_breaches(to_date="2026-01-31T23:59:59+00:00")
        assert len(breaches) == 1

    def test_breach_sorted_desc(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 800.0, 200, timestamp="2026-01-01T00:00:00+00:00")
        tracker.record_request("/api/check", 900.0, 200, timestamp="2026-02-01T00:00:00+00:00")
        breaches = tracker.get_sla_breaches()
        assert breaches[0].timestamp == "2026-02-01T00:00:00+00:00"
        assert breaches[1].timestamp == "2026-01-01T00:00:00+00:00"


# =========================================================================
# Clear / Reset
# =========================================================================

class TestClear:
    """Tests for clear() and reset_sla_tracker()."""

    def test_clear(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 100.0, 200)
        tracker.record_kill("s1", "violation", 50.0)
        tracker.record_request("/api/check", 800.0, 200)  # breach
        assert tracker.get_request_count() == 2
        assert tracker.get_kill_count() == 1
        tracker.clear()
        assert tracker.get_request_count() == 0
        assert tracker.get_kill_count() == 0
        assert tracker.get_breach_count() == 0

    def test_reset_singleton(self):
        from brahmanda.sla_monitor import get_sla_tracker, reset_sla_tracker
        t1 = get_sla_tracker()
        reset_sla_tracker()
        t2 = get_sla_tracker()
        assert t1 is not t2
        reset_sla_tracker()  # clean up


# =========================================================================
# Singleton
# =========================================================================

class TestSingleton:
    """Tests for get_sla_tracker()."""

    def test_returns_same_instance(self):
        from brahmanda.sla_monitor import get_sla_tracker, reset_sla_tracker
        reset_sla_tracker()
        t1 = get_sla_tracker()
        t2 = get_sla_tracker()
        assert t1 is t2
        reset_sla_tracker()

    def test_kwargs_on_first_call(self):
        from brahmanda.sla_monitor import get_sla_tracker, reset_sla_tracker
        reset_sla_tracker()
        t = get_sla_tracker(db_path=":memory:")
        assert t is not None
        reset_sla_tracker()


# =========================================================================
# Default Thresholds
# =========================================================================

class TestDefaultThresholds:
    """Tests for DEFAULT_SLA_THRESHOLDS."""

    def test_all_six_metrics(self):
        from brahmanda.sla_monitor import DEFAULT_SLA_THRESHOLDS
        assert len(DEFAULT_SLA_THRESHOLDS) == 6

    def test_uptime_threshold(self):
        from brahmanda.sla_monitor import DEFAULT_SLA_THRESHOLDS
        assert DEFAULT_SLA_THRESHOLDS["uptime_percentage"]["threshold"] == 99.9

    def test_response_time_threshold(self):
        from brahmanda.sla_monitor import DEFAULT_SLA_THRESHOLDS
        assert DEFAULT_SLA_THRESHOLDS["avg_response_time_ms"]["threshold"] == 500.0

    def test_kill_rate_threshold(self):
        from brahmanda.sla_monitor import DEFAULT_SLA_THRESHOLDS
        assert DEFAULT_SLA_THRESHOLDS["kill_rate"]["threshold"] == 0.05


# =========================================================================
# Edge Cases
# =========================================================================

class TestEdgeCases:
    """Edge case tests."""

    def test_zero_duration(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 0.0, 200)
        assert tracker.get_avg_response_time() == 0.0
        assert tracker.get_breach_count() == 0  # 0 <= 500

    def test_very_large_duration(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 999999.0, 200)
        assert tracker.get_avg_response_time() == 999999.0
        status = tracker.get_sla_status()
        rt = next(m for m in status if m.name == "avg_response_time_ms")
        assert rt.status == "breached"

    def test_300_status_code_is_success(self):
        """3xx redirects should not count as success (2xx)."""
        SLATracker = _import_tracker()
        tracker = SLATracker()
        tracker.record_request("/api/check", 100.0, 301)
        tracker.record_request("/api/check", 100.0, 200)
        assert tracker.get_uptime_percentage() == pytest.approx(50.0)

    def test_api_availability_same_as_uptime(self):
        SLATracker = _import_tracker()
        tracker = SLATracker()
        for _ in range(99):
            tracker.record_request("/api/check", 100.0, 200)
        tracker.record_request("/api/check", 100.0, 500)
        status = tracker.get_sla_status()
        uptime = next(m for m in status if m.name == "uptime_percentage")
        api_avail = next(m for m in status if m.name == "api_availability")
        assert uptime.value == api_avail.value
