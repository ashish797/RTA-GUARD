"""
RTA-GUARD Observability

Enterprise observability: traces, analytics, cost tracking, alerting,
and OpenTelemetry export.

Usage:
    from discus.observability import ObservabilityManager

    obs = ObservabilityManager()
    obs.trace_decision(session_id="s1", decision="kill", rule="pii")
    stats = obs.get_stats()
    trends = obs.get_trends(last_days=7)
"""
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

from .trace import GuardTrace, TraceCollector
from .analytics import ViolationAnalytics, CostTracker, ViolationStats, CostReport
from .alerts import AlertManager, AlertRule, AlertEvent, AlertCondition, AlertChannel

logger = logging.getLogger("discus.observability")

# Try OTel (optional)
try:
    from .otel import OTelExporter
    HAS_OTEL_EXPORTER = True
except ImportError:
    HAS_OTEL_EXPORTER = False


class ObservabilityManager:
    """
    Unified observability interface.

    Combines tracing, analytics, cost tracking, and alerting.
    """

    def __init__(self, db_path: Optional[str] = None,
                 retention_days: int = 30,
                 model: str = "default",
                 otel_enabled: bool = False,
                 otel_endpoint: Optional[str] = None):
        self.collector = TraceCollector(
            db_path=__import__('pathlib').Path(db_path) if db_path else None,
            retention_days=retention_days,
        )
        self.analytics = ViolationAnalytics(self.collector)
        self.cost_tracker = CostTracker(model=model)
        self.alert_manager = AlertManager()

        # OTel (optional)
        self.otel = None
        if otel_enabled and HAS_OTEL_EXPORTER:
            try:
                self.otel = OTelExporter(endpoint=otel_endpoint)
            except Exception:
                pass

    def trace_decision(self, session_id: str, decision: str,
                       rule: str = "", duration_ms: float = 0,
                       input_text: str = "", violation_type: str = "",
                       profile_name: str = "", tenant_id: str = "",
                       metadata: Optional[Dict] = None) -> GuardTrace:
        """Record a guard decision trace."""
        import hashlib
        trace_id = hashlib.sha256(
            f"{session_id}:{time.time()}:{decision}".encode()
        ).hexdigest()[:16]

        trace = GuardTrace(
            trace_id=trace_id,
            session_id=session_id,
            decision=decision,
            rule_triggered=rule,
            duration_ms=duration_ms,
            input_hash=hashlib.sha256(input_text.encode()).hexdigest(),
            profile_name=profile_name,
            tenant_id=tenant_id,
            violation_type=violation_type,
            metadata=metadata or {},
        )

        self.collector.record(trace)

        # OTel export
        if self.otel:
            tokens_saved = 0
            if decision == "kill":
                tokens_saved = self.cost_tracker.estimate_tokens(input_text) * 10  # Estimate
            self.otel.record_check(
                decision=decision, rule=rule, duration_ms=duration_ms,
                session_id=session_id, tenant_id=tenant_id,
                violation_type=violation_type, tokens_saved=tokens_saved,
            )

        # Check alerts
        stats = self.get_stats(last_hours=1)
        self.alert_manager.evaluate(stats.to_dict(), tenant_id=tenant_id)

        return trace

    def get_stats(self, last_hours: Optional[int] = None,
                  tenant_id: Optional[str] = None) -> ViolationStats:
        """Get violation statistics."""
        return self.analytics.get_stats(last_hours=last_hours, tenant_id=tenant_id)

    def get_trends(self, last_days: int = 7,
                   bucket_hours: int = 1):
        """Get violation trends."""
        return self.analytics.get_trends(last_days=last_days, bucket_hours=bucket_hours)

    def get_cost_report(self, model: str = "default") -> CostReport:
        """Get cost savings report."""
        traces = self.collector.query(limit=100000)
        return self.cost_tracker.calculate_savings(traces)

    def get_tenant_breakdown(self) -> Dict[str, ViolationStats]:
        """Get stats by tenant."""
        return self.analytics.get_tenant_breakdown()

    def get_top_violations(self, limit: int = 10) -> List[Dict]:
        """Get most common violations."""
        return self.analytics.get_top_violations(limit=limit)

    def detect_anomalies(self, last_hours: int = 1) -> List[Dict]:
        """Detect anomalous spikes."""
        return self.analytics.detect_anomalies(last_hours=last_hours)

    def query_traces(self, **kwargs) -> List[Dict]:
        """Query traces with filters."""
        return self.collector.query(**kwargs)

    def export_traces(self, format: str = "json", **kwargs) -> str:
        """Export traces as JSON or CSV."""
        if format == "csv":
            return self.collector.export_csv(**kwargs)
        return self.collector.export_json(**kwargs)

    def add_alert_rule(self, rule: AlertRule) -> None:
        self.alert_manager.add_rule(rule)

    def get_alert_history(self, limit: int = 50) -> List[AlertEvent]:
        return self.alert_manager.get_history(limit=limit)

    def cleanup(self) -> int:
        """Clean up old traces."""
        return self.collector.cleanup()

    def get_observability_stats(self) -> Dict[str, Any]:
        """Get full observability stats."""
        return {
            "traces": self.collector.get_stats(),
            "alerts": self.alert_manager.get_stats(),
            "otel_available": self.otel is not None and self.otel.is_available() if self.otel else False,
        }
