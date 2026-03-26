"""
RTA-GUARD — Prometheus Metrics (Phase 6.2)

Centralized metrics definitions for Prometheus integration.
All metrics are opt-in: set METRICS_ENABLED=true to enable.

Metrics exported:
    Counters:
        - discus_kill_total              Total sessions killed
        - discus_check_total             Total guard checks performed
        - discus_violation_total         Total violations detected (warn+kill)
        - discus_webhook_sent_total      Total webhook notifications sent

    Gauges:
        - discus_active_sessions         Currently alive sessions
        - discus_drift_score             Current drift score (latest agent)
        - discus_tamas_level             Current Tamas level (numeric)

    Histograms:
        - discus_check_duration_seconds  Duration of guard.check() calls
        - discus_sla_response_time_seconds  SLA-tracked API response time

    Summaries:
        - discus_kill_decision_time_seconds Time from check start to kill decision
"""
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ─── Feature flag ─────────────────────────────────────────────────

METRICS_ENABLED = os.getenv("METRICS_ENABLED", "false").lower() == "true"

# ─── Metric definitions ───────────────────────────────────────────

# Lazy-loaded prometheus_client to avoid import errors when disabled
_prom = None


def _get_prom():
    """Lazily import prometheus_client."""
    global _prom
    if _prom is None:
        try:
            import prometheus_client
            _prom = prometheus_client
        except ImportError:
            logger.warning("prometheus_client not installed — metrics disabled")
            return None
    return _prom


# ─── No-op stubs for when metrics are disabled ─────────────────────

class _NoopCounter:
    def inc(self, amount=1, **kwargs):
        pass
    def labels(self, **kwargs):
        return self


class _NoopGauge:
    def set(self, value, **kwargs):
        pass
    def inc(self, amount=1, **kwargs):
        pass
    def dec(self, amount=1, **kwargs):
        pass
    def labels(self, **kwargs):
        return self


class _NoopHistogram:
    def observe(self, value, **kwargs):
        pass
    def time(self):
        return _NoopTimer()
    def labels(self, **kwargs):
        return self


class _NoopSummary:
    def observe(self, value, **kwargs):
        pass
    def time(self):
        return _NoopTimer()
    def labels(self, **kwargs):
        return self


class _NoopTimer:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


# ─── Metric singletons ────────────────────────────────────────────

# Counters
_discus_kill_total = None
_discus_check_total = None
_discus_violation_total = None
_discus_webhook_sent_total = None

# Gauges
_discus_active_sessions = None
_discus_drift_score = None
_discus_tamas_level = None

# Histograms
_discus_check_duration_seconds = None
_discus_sla_response_time_seconds = None

# Summary
_discus_kill_decision_time_seconds = None

_initialized = False


def _init_metrics():
    """Initialize all Prometheus metrics. Idempotent."""
    global _initialized
    global _discus_kill_total, _discus_check_total, _discus_violation_total
    global _discus_webhook_sent_total, _discus_active_sessions, _discus_drift_score
    global _discus_tamas_level, _discus_check_duration_seconds
    global _discus_sla_response_time_seconds, _discus_kill_decision_time_seconds

    if _initialized:
        return

    prom = _get_prom()
    if prom is None:
        # Fallback to no-ops
        _discus_kill_total = _NoopCounter()
        _discus_check_total = _NoopCounter()
        _discus_violation_total = _NoopCounter()
        _discus_webhook_sent_total = _NoopCounter()
        _discus_active_sessions = _NoopGauge()
        _discus_drift_score = _NoopGauge()
        _discus_tamas_level = _NoopGauge()
        _discus_check_duration_seconds = _NoopHistogram()
        _discus_sla_response_time_seconds = _NoopHistogram()
        _discus_kill_decision_time_seconds = _NoopSummary()
        _initialized = True
        return

    REGISTRY = prom.REGISTRY

    # Counters
    _discus_kill_total = prom.Counter(
        "discus_kill_total",
        "Total number of sessions killed by the guard",
        registry=REGISTRY,
    )
    _discus_check_total = prom.Counter(
        "discus_check_total",
        "Total number of guard checks performed",
        labelnames=["result"],  # pass, warn, kill
        registry=REGISTRY,
    )
    _discus_violation_total = prom.Counter(
        "discus_violation_total",
        "Total number of violations detected (warn + kill)",
        labelnames=["severity"],  # low, medium, high, critical
        registry=REGISTRY,
    )
    _discus_webhook_sent_total = prom.Counter(
        "discus_webhook_sent_total",
        "Total webhook notifications sent",
        labelnames=["event_type"],
        registry=REGISTRY,
    )

    # Gauges
    _discus_active_sessions = prom.Gauge(
        "discus_active_sessions",
        "Number of currently alive (non-killed) sessions",
        registry=REGISTRY,
    )
    _discus_drift_score = prom.Gauge(
        "discus_drift_score",
        "Current EMA-smoothed drift score",
        labelnames=["agent_id"],
        registry=REGISTRY,
    )
    _discus_tamas_level = prom.Gauge(
        "discus_tamas_level",
        "Current Tamas level (0=sattva, 1=rajas, 2=tamas, 3=critical)",
        labelnames=["agent_id"],
        registry=REGISTRY,
    )

    # Histograms
    _discus_check_duration_seconds = prom.Histogram(
        "discus_check_duration_seconds",
        "Duration of guard.check() calls in seconds",
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
        registry=REGISTRY,
    )
    _discus_sla_response_time_seconds = prom.Histogram(
        "discus_sla_response_time_seconds",
        "SLA-tracked API response time in seconds",
        buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
        labelnames=["endpoint"],
        registry=REGISTRY,
    )

    # Summary
    _discus_kill_decision_time_seconds = prom.Summary(
        "discus_kill_decision_time_seconds",
        "Time from check start to kill decision in seconds",
        registry=REGISTRY,
    )

    _initialized = True
    logger.info("Prometheus metrics initialized")


def init_metrics():
    """Public initializer — call once at startup if METRICS_ENABLED."""
    if METRICS_ENABLED:
        _init_metrics()
        logger.info("Metrics ENABLED — Prometheus endpoint available at /metrics")
    else:
        # Still init no-ops so callers don't need to check
        _init_metrics()
        logger.info("Metrics DISABLED (set METRICS_ENABLED=true to enable)")


# ─── Accessors ────────────────────────────────────────────────────

def get_kill_counter():
    return _discus_kill_total

def get_check_counter():
    return _discus_check_total

def get_violation_counter():
    return _discus_violation_total

def get_webhook_counter():
    return _discus_webhook_sent_total

def get_active_sessions_gauge():
    return _discus_active_sessions

def get_drift_gauge():
    return _discus_drift_score

def get_tamas_gauge():
    return _discus_tamas_level

def get_check_duration_histogram():
    return _discus_check_duration_seconds

def get_sla_response_histogram():
    return _discus_sla_response_time_seconds

def get_kill_decision_summary():
    return _discus_kill_decision_time_seconds


# ─── Convenience recording functions ───────────────────────────────

def record_kill():
    """Record a session kill event."""
    _discus_kill_total.inc()

def record_check(result: str = "pass"):
    """Record a guard check. result: pass|warn|kill."""
    _discus_check_total.labels(result=result).inc()

def record_violation(severity: str = "medium"):
    """Record a violation. severity: low|medium|high|critical."""
    _discus_violation_total.labels(severity=severity).inc()

def record_webhook(event_type: str = "session_kill"):
    """Record a webhook delivery."""
    _discus_webhook_sent_total.labels(event_type=event_type).inc()

def set_active_sessions(count: int):
    """Set the number of active sessions."""
    _discus_active_sessions.set(count)

def set_drift_score(agent_id: str, score: float):
    """Set drift score for an agent."""
    _discus_drift_score.labels(agent_id=agent_id).set(score)

def set_tamas_level(agent_id: str, level: int):
    """Set Tamas level for an agent (0-3)."""
    _discus_tamas_level.labels(agent_id=agent_id).set(level)

def observe_check_duration(seconds: float):
    """Record a guard check duration."""
    _discus_check_duration_seconds.observe(seconds)

def observe_sla_response(endpoint: str, seconds: float):
    """Record an SLA-tracked response time."""
    _discus_sla_response_time_seconds.labels(endpoint=endpoint).observe(seconds)

def observe_kill_decision_time(seconds: float):
    """Record time to kill decision."""
    _discus_kill_decision_time_seconds.observe(seconds)
