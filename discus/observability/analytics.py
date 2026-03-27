"""
RTA-GUARD Observability — Violation Analytics & Cost Tracking

Computes analytics from guard traces: violation rates, trends,
breakdowns by rule/tenant, and token savings from early termination.
"""
import json
import logging
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("discus.observability.analytics")


@dataclass
class ViolationStats:
    """Violation statistics for a time period."""
    total_checks: int = 0
    total_passes: int = 0
    total_warns: int = 0
    total_kills: int = 0
    kill_rate: float = 0.0
    warn_rate: float = 0.0
    violations_by_rule: Dict[str, int] = field(default_factory=dict)
    violations_by_type: Dict[str, int] = field(default_factory=dict)
    avg_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "total_passes": self.total_passes,
            "total_warns": self.total_warns,
            "total_kills": self.total_kills,
            "kill_rate": round(self.kill_rate, 4),
            "warn_rate": round(self.warn_rate, 4),
            "violations_by_rule": self.violations_by_rule,
            "violations_by_type": self.violations_by_type,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


@dataclass
class TrendPoint:
    """A single point in a time series."""
    timestamp: float
    value: float
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"timestamp": self.timestamp, "value": self.value, "label": self.label}


@dataclass
class CostReport:
    """Token cost report."""
    total_tokens_checked: int = 0
    tokens_saved: int = 0
    estimated_cost_saved: float = 0.0
    cost_per_1k_tokens: float = 0.03  # Default GPT-4 pricing
    early_terminations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tokens_checked": self.total_tokens_checked,
            "tokens_saved": self.tokens_saved,
            "estimated_cost_saved": round(self.estimated_cost_saved, 4),
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "early_terminations": self.early_terminations,
        }


class ViolationAnalytics:
    """
    Computes violation analytics from traces.

    Usage:
        analytics = ViolationAnalytics(trace_collector)
        stats = analytics.get_stats(last_hours=24)
        trends = analytics.get_trends(last_days=7)
    """

    def __init__(self, trace_collector=None):
        self.collector = trace_collector

    def get_stats(self, traces: Optional[List[Dict]] = None,
                  last_hours: Optional[int] = None,
                  tenant_id: Optional[str] = None) -> ViolationStats:
        """Compute violation statistics."""
        if traces is None and self.collector:
            start = time.time() - (last_hours * 3600) if last_hours else None
            traces = self.collector.query(
                start_time=start, tenant_id=tenant_id, limit=100000
            )
        traces = traces or []

        stats = ViolationStats()
        stats.total_checks = len(traces)
        durations = []

        rule_counts = Counter()
        type_counts = Counter()

        for t in traces:
            decision = t.get("decision", "pass")
            if decision == "pass":
                stats.total_passes += 1
            elif decision == "warn":
                stats.total_warns += 1
            elif decision == "kill":
                stats.total_kills += 1

            rule = t.get("rule_triggered", "")
            if rule:
                rule_counts[rule] += 1

            vtype = t.get("violation_type", "")
            if vtype:
                type_counts[vtype] += 1

            dur = t.get("duration_ms", 0)
            if dur:
                durations.append(dur)

        if stats.total_checks > 0:
            stats.kill_rate = stats.total_kills / stats.total_checks
            stats.warn_rate = stats.total_warns / stats.total_checks

        stats.violations_by_rule = dict(rule_counts.most_common(20))
        stats.violations_by_type = dict(type_counts.most_common(20))
        stats.avg_duration_ms = sum(durations) / len(durations) if durations else 0

        return stats

    def get_trends(self, traces: Optional[List[Dict]] = None,
                   last_days: int = 7,
                   bucket_hours: int = 1) -> List[TrendPoint]:
        """Get violation trends over time."""
        if traces is None and self.collector:
            start = time.time() - (last_days * 86400)
            traces = self.collector.query(start_time=start, limit=100000)
        traces = traces or []

        bucket_seconds = bucket_hours * 3600
        buckets: Dict[float, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "warn": 0, "kill": 0})

        for t in traces:
            ts = t.get("timestamp", 0)
            bucket = math.floor(ts / bucket_seconds) * bucket_seconds
            decision = t.get("decision", "pass")
            buckets[bucket][decision] += 1

        points = []
        for ts in sorted(buckets.keys()):
            b = buckets[ts]
            total = b["pass"] + b["warn"] + b["kill"]
            kill_rate = b["kill"] / total if total > 0 else 0
            points.append(TrendPoint(
                timestamp=ts,
                value=round(kill_rate * 100, 2),
                label=f"{b['kill']} kills / {total} total",
            ))

        return points

    def get_top_violations(self, traces: Optional[List[Dict]] = None,
                           limit: int = 10) -> List[Dict[str, Any]]:
        """Get most common violation types."""
        if traces is None and self.collector:
            traces = self.collector.query(limit=100000)
        traces = traces or []

        type_counts = Counter()
        for t in traces:
            vtype = t.get("violation_type", "")
            if vtype:
                type_counts[vtype] += 1

        return [{"type": k, "count": v} for k, v in type_counts.most_common(limit)]

    def get_tenant_breakdown(self, traces: Optional[List[Dict]] = None) -> Dict[str, ViolationStats]:
        """Get stats broken down by tenant."""
        if traces is None and self.collector:
            traces = self.collector.query(limit=100000)
        traces = traces or []

        by_tenant: Dict[str, List[Dict]] = defaultdict(list)
        for t in traces:
            tenant = t.get("tenant_id", "unknown")
            by_tenant[tenant].append(t)

        return {
            tenant: self.get_stats(traces=tenant_traces)
            for tenant, tenant_traces in by_tenant.items()
        }

    def detect_anomalies(self, traces: Optional[List[Dict]] = None,
                          last_hours: int = 1) -> List[Dict[str, Any]]:
        """Detect anomalous spikes in violations."""
        if traces is None and self.collector:
            start = time.time() - (last_hours * 3600)
            traces = self.collector.query(start_time=start, limit=100000)
        traces = traces or []

        # Compare last hour to previous hours
        now = time.time()
        hour_ago = now - 3600
        two_hours_ago = now - 7200

        recent = [t for t in traces if t.get("timestamp", 0) > hour_ago]
        previous = [t for t in traces if two_hours_ago < t.get("timestamp", 0) <= hour_ago]

        recent_kills = sum(1 for t in recent if t.get("decision") == "kill")
        previous_kills = sum(1 for t in previous if t.get("decision") == "kill")

        anomalies = []
        if previous_kills > 0 and recent_kills > previous_kills * 2:
            anomalies.append({
                "type": "kill_rate_spike",
                "recent_kills": recent_kills,
                "previous_kills": previous_kills,
                "increase_pct": round((recent_kills - previous_kills) / previous_kills * 100, 1),
            })

        return anomalies


class CostTracker:
    """
    Tracks token savings from early termination.

    Estimates how many tokens were NOT generated because
    RTA-GUARD killed the session early.
    """

    # Approximate tokens per character for different models
    TOKEN_RATIOS = {
        "gpt-4": 0.25,
        "gpt-3.5-turbo": 0.25,
        "claude": 0.3,
        "default": 0.25,
    }

    COST_PER_1K = {
        "gpt-4": 0.03,
        "gpt-3.5-turbo": 0.002,
        "claude-3-opus": 0.015,
        "claude-3-sonnet": 0.003,
        "default": 0.01,
    }

    def __init__(self, model: str = "default"):
        self.model = model
        self.token_ratio = self.TOKEN_RATIOS.get(model, 0.25)
        self.cost_per_1k = self.COST_PER_1K.get(model, 0.01)

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text."""
        return int(len(text) * self.token_ratio)

    def calculate_savings(self, traces: List[Dict],
                          avg_output_tokens: int = 500) -> CostReport:
        """Calculate cost savings from early termination."""
        report = CostReport(cost_per_1k_tokens=self.cost_per_1k)

        for t in traces:
            decision = t.get("decision", "pass")
            metadata = t.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            report.total_tokens_checked += self.estimate_tokens(
                metadata.get("input_text", "")
            )

            if decision == "kill":
                report.early_terminations += 1
                # Estimate: we saved the output tokens that would have been generated
                report.tokens_saved += avg_output_tokens

        report.estimated_cost_saved = (report.tokens_saved / 1000) * self.cost_per_1k

        return report
