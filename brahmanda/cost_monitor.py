"""
RTA-GUARD — Cost Monitor (Phase 6.6)

Tracks operational costs for kill decisions, drift checks, API calls, and storage.
Per-tenant cost attribution, anomaly detection, and optimization recommendations.

Cost tracking is opt-in (disabled by default) — set COST_TRACKING_ENABLED=true.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Callable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COST_ENABLED = os.getenv("COST_TRACKING_ENABLED", "false").lower() in ("true", "1", "yes")

# Unit costs (in micro-cents — 1/1,000,000 of a cent)
# These are defaults; tenants can override via pricing config.
DEFAULT_UNIT_COSTS = {
    "kill_decision": 50,        # ~$0.0005 per kill
    "drift_check": 10,          # ~$0.0001 per check
    "api_call": 5,              # ~$0.00005 per API call
    "storage_mb_hour": 2,      # ~$0.00002 per MB-hour
    "webhook_delivery": 15,    # ~$0.00015 per webhook
    "compliance_report": 500,   # ~$0.005 per report
    "drift_score_compute": 20,  # ~$0.0002 per compute
    "audit_log_entry": 1,      # ~$0.00001 per entry
    "session_tracking": 3,     # ~$0.00003 per session tracked
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class CostCategory(Enum):
    """High-level cost categories."""
    COMPUTE = "compute"           # Kill decisions, drift scoring, rule evaluation
    STORAGE = "storage"           # Audit logs, DB entries, state persistence
    NETWORK = "network"           # API calls, webhooks, replication
    REPORTING = "reporting"       # Compliance reports, cost reports
    MONITORING = "monitoring"     # SLA checks, drift checks, session tracking


class AnomalyType(Enum):
    """Types of cost anomalies detected."""
    SPIKE = "spike"               # Sudden increase in cost rate
    DRIFT = "drift"               # Gradual cost increase over time
    THRESHOLD = "threshold"       # Exceeded a budget threshold
    PATTERN = "pattern"           # Unusual cost pattern (e.g., weekend spike)


@dataclass
class CostEvent:
    """A single cost-generating event."""
    event_id: str
    tenant_id: str
    agent_id: Optional[str]
    rule_id: Optional[str]
    category: str          # CostCategory value
    resource_type: str     # e.g., "kill_decision", "drift_check"
    unit_cost: int         # in micro-cents
    quantity: int
    total_cost: int = 0    # auto-computed: unit_cost * quantity (micro-cents)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            self.event_id = hashlib.sha256(
                f"{self.tenant_id}:{self.timestamp}:{self.resource_type}:{time.monotonic_ns()}".encode()
            ).hexdigest()[:16]
        if self.total_cost == 0:
            self.total_cost = self.unit_cost * self.quantity

    def cost_dollars(self) -> float:
        return self.total_cost / 100_000_000  # micro-cents to dollars

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cost_dollars"] = self.cost_dollars()
        return d


@dataclass
class CostAnomaly:
    """A detected cost anomaly."""
    anomaly_id: str
    tenant_id: str
    anomaly_type: str       # AnomalyType value
    severity: str           # "low", "medium", "high", "critical"
    description: str
    current_value: float
    expected_value: float
    deviation_pct: float
    detected_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizationRecommendation:
    """Cost optimization recommendation."""
    recommendation_id: str
    tenant_id: str
    category: str
    title: str
    description: str
    estimated_savings_pct: float   # 0-100
    estimated_savings_usd: float
    priority: str                  # "low", "medium", "high"
    implementation_effort: str     # "easy", "moderate", "complex"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cost Store (SQLite)
# ---------------------------------------------------------------------------

class CostStore:
    """SQLite-backed persistence for cost events and anomalies."""

    def __init__(self, db_path: Optional[str] = None, in_memory: bool = False):
        if in_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path = db_path or os.getenv("COST_DB_PATH", "data/cost.db")
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS cost_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT,
                    rule_id TEXT,
                    category TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    unit_cost INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    total_cost INTEGER NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cost_tenant ON cost_events(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_cost_category ON cost_events(category);
                CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_cost_resource ON cost_events(resource_type);

                CREATE TABLE IF NOT EXISTS cost_anomalies (
                    anomaly_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT,
                    current_value REAL,
                    expected_value REAL,
                    deviation_pct REAL,
                    detected_at TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_anomaly_tenant ON cost_anomalies(tenant_id);

                CREATE TABLE IF NOT EXISTS cost_recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    estimated_savings_pct REAL,
                    estimated_savings_usd REAL,
                    priority TEXT,
                    implementation_effort TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rec_tenant ON cost_recommendations(tenant_id);

                CREATE TABLE IF NOT EXISTS tenant_budgets (
                    tenant_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    budget_micro_cents INTEGER NOT NULL,
                    spent_micro_cents INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, period)
                );
            """)
            self._conn.commit()

    def record_event(self, event: CostEvent):
        with self._lock:
            self._conn.execute(
                """INSERT INTO cost_events
                   (event_id, tenant_id, agent_id, rule_id, category, resource_type,
                    unit_cost, quantity, total_cost, metadata, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.event_id, event.tenant_id, event.agent_id, event.rule_id,
                 event.category, event.resource_type, event.unit_cost,
                 event.quantity, event.total_cost, json.dumps(event.metadata),
                 event.timestamp)
            )
            # Update budget tracking
            period = event.timestamp[:10]  # YYYY-MM-DD
            self._conn.execute(
                """INSERT INTO tenant_budgets (tenant_id, period, budget_micro_cents, spent_micro_cents, updated_at)
                   VALUES (?, ?, 0, ?, ?)
                   ON CONFLICT(tenant_id, period) DO UPDATE SET
                     spent_micro_cents = spent_micro_cents + ?,
                     updated_at = ?""",
                (event.tenant_id, period, event.total_cost, event.timestamp,
                 event.total_cost, event.timestamp)
            )
            self._conn.commit()

    def record_anomaly(self, anomaly: CostAnomaly):
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO cost_anomalies
                   (anomaly_id, tenant_id, anomaly_type, severity, description,
                    current_value, expected_value, deviation_pct, detected_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (anomaly.anomaly_id, anomaly.tenant_id, anomaly.anomaly_type,
                 anomaly.severity, anomaly.description, anomaly.current_value,
                 anomaly.expected_value, anomaly.deviation_pct, anomaly.detected_at,
                 json.dumps(anomaly.metadata))
            )
            self._conn.commit()

    def get_tenant_costs(self, tenant_id: str, start: str, end: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM cost_events
                   WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?
                   ORDER BY timestamp""",
                (tenant_id, start, end)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cost_summary(self, tenant_id: str, start: str, end: str) -> Dict[str, Any]:
        with self._lock:
            # By category
            cat_rows = self._conn.execute(
                """SELECT category, SUM(total_cost) as total, COUNT(*) as count
                   FROM cost_events
                   WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?
                   GROUP BY category""",
                (tenant_id, start, end)
            ).fetchall()

            # By resource type
            res_rows = self._conn.execute(
                """SELECT resource_type, SUM(total_cost) as total, COUNT(*) as count
                   FROM cost_events
                   WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?
                   GROUP BY resource_type""",
                (tenant_id, start, end)
            ).fetchall()

            # By agent
            agent_rows = self._conn.execute(
                """SELECT agent_id, SUM(total_cost) as total, COUNT(*) as count
                   FROM cost_events
                   WHERE tenant_id = ? AND agent_id IS NOT NULL
                     AND timestamp >= ? AND timestamp < ?
                   GROUP BY agent_id""",
                (tenant_id, start, end)
            ).fetchall()

            # By rule
            rule_rows = self._conn.execute(
                """SELECT rule_id, SUM(total_cost) as total, COUNT(*) as count
                   FROM cost_events
                   WHERE tenant_id = ? AND rule_id IS NOT NULL
                     AND timestamp >= ? AND timestamp < ?
                   GROUP BY rule_id""",
                (tenant_id, start, end)
            ).fetchall()

            # Total
            total_row = self._conn.execute(
                """SELECT SUM(total_cost) as total, COUNT(*) as count
                   FROM cost_events
                   WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?""",
                (tenant_id, start, end)
            ).fetchone()

        return {
            "tenant_id": tenant_id,
            "period": {"start": start, "end": end},
            "total_cost_micro_cents": total_row["total"] or 0,
            "total_cost_dollars": (total_row["total"] or 0) / 100_000_000,
            "total_events": total_row["count"] or 0,
            "by_category": {r["category"]: {"total": r["total"], "count": r["count"]} for r in cat_rows},
            "by_resource": {r["resource_type"]: {"total": r["total"], "count": r["count"]} for r in res_rows},
            "by_agent": {r["agent_id"]: {"total": r["total"], "count": r["count"]} for r in agent_rows if r["agent_id"]},
            "by_rule": {r["rule_id"]: {"total": r["total"], "count": r["count"]} for r in rule_rows if r["rule_id"]},
        }

    def get_anomalies(self, tenant_id: str, start: Optional[str] = None, end: Optional[str] = None) -> List[dict]:
        with self._lock:
            if start and end:
                rows = self._conn.execute(
                    """SELECT * FROM cost_anomalies
                       WHERE tenant_id = ? AND detected_at >= ? AND detected_at < ?
                       ORDER BY detected_at DESC""",
                    (tenant_id, start, end)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM cost_anomalies WHERE tenant_id = ? ORDER BY detected_at DESC LIMIT 50",
                    (tenant_id,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_budget_status(self, tenant_id: str, period: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tenant_budgets WHERE tenant_id = ? AND period = ?",
                (tenant_id, period)
            ).fetchone()
        return dict(row) if row else None

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Cost Tracker
# ---------------------------------------------------------------------------

class CostTracker:
    """
    Records cost events and provides per-tenant attribution.

    Usage:
        tracker = CostTracker()
        tracker.track_kill_decision(tenant_id="acme", agent_id="gpt4", rule_id="R1")
        summary = tracker.get_tenant_summary("acme", start="2026-03-01", end="2026-04-01")
    """

    def __init__(self, store: Optional[CostStore] = None, unit_costs: Optional[Dict[str, int]] = None):
        self._store = store or CostStore(in_memory=True)
        self._unit_costs = unit_costs or dict(DEFAULT_UNIT_COSTS)
        self._enabled = COST_ENABLED
        self._callbacks: List[Callable[[CostEvent], None]] = []
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def set_unit_cost(self, resource_type: str, cost_micro_cents: int):
        self._unit_costs[resource_type] = cost_micro_cents

    def on_cost_event(self, callback: Callable[[CostEvent], None]):
        self._callbacks.append(callback)

    def track(self, tenant_id: str, resource_type: str,
              agent_id: Optional[str] = None, rule_id: Optional[str] = None,
              quantity: int = 1, metadata: Optional[Dict[str, Any]] = None) -> Optional[CostEvent]:
        """Record a cost event. Returns None if tracking is disabled."""
        if not self._enabled:
            return None

        unit_cost = self._unit_costs.get(resource_type, 0)
        category = self._classify_resource(resource_type)

        event = CostEvent(
            event_id="",
            tenant_id=tenant_id,
            agent_id=agent_id,
            rule_id=rule_id,
            category=category,
            resource_type=resource_type,
            unit_cost=unit_cost,
            quantity=quantity,
            metadata=metadata or {},
        )

        self._store.record_event(event)

        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass  # Don't let callback errors break cost tracking

        return event

    def track_kill_decision(self, tenant_id: str, agent_id: str, rule_id: str,
                           compute_ms: float = 0, **kwargs) -> Optional[CostEvent]:
        return self.track(tenant_id, "kill_decision",
                         agent_id=agent_id, rule_id=rule_id,
                         metadata={"compute_ms": compute_ms, **kwargs})

    def track_drift_check(self, tenant_id: str, agent_id: str,
                          compute_ms: float = 0, **kwargs) -> Optional[CostEvent]:
        return self.track(tenant_id, "drift_check",
                         agent_id=agent_id,
                         metadata={"compute_ms": compute_ms, **kwargs})

    def track_api_call(self, tenant_id: str, endpoint: str, **kwargs) -> Optional[CostEvent]:
        return self.track(tenant_id, "api_call",
                         metadata={"endpoint": endpoint, **kwargs})

    def track_webhook(self, tenant_id: str, event_type: str, **kwargs) -> Optional[CostEvent]:
        return self.track(tenant_id, "webhook_delivery",
                         metadata={"event_type": event_type, **kwargs})

    def track_storage(self, tenant_id: str, mb: float, hours: float = 1.0, **kwargs) -> Optional[CostEvent]:
        quantity = max(1, int(mb * hours))
        return self.track(tenant_id, "storage_mb_hour",
                         quantity=quantity,
                         metadata={"mb": mb, "hours": hours, **kwargs})

    def track_audit_entry(self, tenant_id: str, **kwargs) -> Optional[CostEvent]:
        return self.track(tenant_id, "audit_log_entry", **kwargs)

    def get_tenant_summary(self, tenant_id: str, start: str, end: str) -> Dict[str, Any]:
        return self._store.get_cost_summary(tenant_id, start, end)

    def get_budget_status(self, tenant_id: str, period: str) -> Optional[dict]:
        return self._store.get_budget_status(tenant_id, period)

    @staticmethod
    def _classify_resource(resource_type: str) -> str:
        mapping = {
            "kill_decision": CostCategory.COMPUTE.value,
            "drift_check": CostCategory.COMPUTE.value,
            "drift_score_compute": CostCategory.COMPUTE.value,
            "api_call": CostCategory.NETWORK.value,
            "webhook_delivery": CostCategory.NETWORK.value,
            "storage_mb_hour": CostCategory.STORAGE.value,
            "audit_log_entry": CostCategory.STORAGE.value,
            "compliance_report": CostCategory.REPORTING.value,
            "session_tracking": CostCategory.MONITORING.value,
        }
        return mapping.get(resource_type, CostCategory.COMPUTE.value)


# ---------------------------------------------------------------------------
# Anomaly Detector
# ---------------------------------------------------------------------------

class CostAnomalyDetector:
    """
    Detects cost anomalies using z-score spike detection and trend analysis.

    Compares current period costs against a rolling baseline.
    """

    def __init__(self, store: Optional[CostStore] = None,
                 spike_threshold: float = 2.0,
                 drift_threshold_pct: float = 30.0):
        self._store = store or CostStore(in_memory=True)
        self._spike_threshold = spike_threshold  # z-score for spike detection
        self._drift_threshold_pct = drift_threshold_pct
        self._lock = threading.Lock()

    def detect_anomalies(self, tenant_id: str, lookback_days: int = 30) -> List[CostAnomaly]:
        """
        Detect cost anomalies for a tenant by comparing recent costs against baseline.
        Uses daily granularity.
        """
        anomalies = []
        now = datetime.now(timezone.utc)

        # Get daily costs for the lookback period
        daily_costs: Dict[str, int] = {}
        for day_offset in range(lookback_days):
            day = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            start = f"{day}T00:00:00"
            end = f"{day}T23:59:59"
            summary = self._store.get_cost_summary(tenant_id, start, end)
            daily_costs[day] = summary["total_cost_micro_cents"]

        costs = list(daily_costs.values())
        if len(costs) < 7:
            return anomalies  # Need at least a week of data

        # Spike detection: compare last 3 days against the previous period
        recent = costs[:3]    # most recent days (index 0 = today)
        baseline = costs[3:]  # older days

        if not baseline:
            return anomalies

        import statistics
        mean = statistics.mean(baseline)
        stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0

        for i, cost in enumerate(recent):
            if stdev > 0 and mean > 0:
                z_score = (cost - mean) / stdev
                if z_score > self._spike_threshold:
                    day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                    anomaly = CostAnomaly(
                        anomaly_id=hashlib.sha256(f"spike:{tenant_id}:{day}".encode()).hexdigest()[:16],
                        tenant_id=tenant_id,
                        anomaly_type=AnomalyType.SPIKE.value,
                        severity="high" if z_score > 3.0 else "medium",
                        description=f"Cost spike on {day}: {z_score:.1f}σ above baseline "
                                    f"(current: ${cost/100_000_000:.4f}, baseline avg: ${mean/100_000_000:.4f})",
                        current_value=float(cost),
                        expected_value=mean,
                        deviation_pct=z_score * 100 / max(mean, 1),
                    )
                    anomalies.append(anomaly)
                    self._store.record_anomaly(anomaly)

        # Drift detection: compare first half vs second half of lookback
        mid = len(costs) // 2
        first_half_avg = statistics.mean(costs[mid:]) if costs[mid:] else 0
        second_half_avg = statistics.mean(costs[:mid]) if costs[:mid] else 0

        if first_half_avg > 0:
            drift_pct = ((second_half_avg - first_half_avg) / first_half_avg) * 100
            if drift_pct > self._drift_threshold_pct:
                anomaly = CostAnomaly(
                    anomaly_id=hashlib.sha256(f"drift:{tenant_id}:{now.isoformat()}".encode()).hexdigest()[:16],
                    tenant_id=tenant_id,
                    anomaly_type=AnomalyType.DRIFT.value,
                    severity="high" if drift_pct > 50 else "medium",
                    description=f"Cost drift: {drift_pct:.1f}% increase over {lookback_days}-day period "
                                f"(first half avg: ${first_half_avg/100_000_000:.4f}/day, "
                                f"second half: ${second_half_avg/100_000_000:.4f}/day)",
                    current_value=second_half_avg,
                    expected_value=first_half_avg,
                    deviation_pct=drift_pct,
                )
                anomalies.append(anomaly)
                self._store.record_anomaly(anomaly)

        return anomalies


# ---------------------------------------------------------------------------
# Optimization Engine
# ---------------------------------------------------------------------------

class CostOptimizer:
    """
    Analyzes cost patterns and generates optimization recommendations.
    """

    def __init__(self, store: Optional[CostStore] = None):
        self._store = store or CostStore(in_memory=True)

    def generate_recommendations(self, tenant_id: str,
                                  start: str, end: str) -> List[OptimizationRecommendation]:
        """Analyze costs and generate actionable optimization recommendations."""
        recommendations = []
        summary = self._store.get_cost_summary(tenant_id, start, end)

        by_resource = summary.get("by_resource", {})
        by_category = summary.get("by_category", {})
        total_cost = summary["total_cost_micro_cents"]

        if total_cost == 0:
            return recommendations

        # 1. Check if kills dominate costs — recommend batching
        kill_cost = by_resource.get("kill_decision", {}).get("total", 0)
        if kill_cost > total_cost * 0.4:  # >40% of costs are kills
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"batch:{tenant_id}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="batching",
                title="Batch kill decisions",
                description="Kill decisions account for >40% of costs. Implement batch processing "
                            "to group kills by tenant and flush in batches, reducing per-decision overhead. "
                            "Estimated 20-30% cost reduction.",
                estimated_savings_pct=25.0,
                estimated_savings_usd=kill_cost * 0.25 / 100_000_000,
                priority="high",
                implementation_effort="moderate",
            ))

        # 2. Check if drift checks dominate — recommend lazy loading
        drift_cost = by_resource.get("drift_check", {}).get("total", 0)
        if drift_cost > total_cost * 0.3:  # >30% on drift checks
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"lazy_drift:{tenant_id}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="lazy_loading",
                title="Lazy load drift scores",
                description="Drift checks account for >30% of costs. Switch to lazy evaluation — "
                            "compute drift scores only when queried rather than on every interaction. "
                            "Reduces compute by 40-60% for infrequently-checked agents.",
                estimated_savings_pct=45.0,
                estimated_savings_usd=drift_cost * 0.45 / 100_000_000,
                priority="high",
                implementation_effort="easy",
            ))

        # 3. Check if audit logs are expensive — recommend compression
        audit_cost = by_resource.get("audit_log_entry", {}).get("total", 0)
        audit_count = by_resource.get("audit_log_entry", {}).get("count", 0)
        if audit_count > 100_000:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"compress:{tenant_id}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="compression",
                title="Compress audit logs",
                description=f"High audit log volume ({audit_count:,} entries). Enable gzip compression "
                            "for audit log storage. Reduces storage costs by 70-80% and improves query "
                            "performance for large datasets.",
                estimated_savings_pct=75.0,
                estimated_savings_usd=audit_cost * 0.75 / 100_000_000,
                priority="medium",
                implementation_effort="easy",
            ))

        # 4. Check webhook costs — recommend rate limiting
        webhook_cost = by_resource.get("webhook_delivery", {}).get("total", 0)
        if webhook_cost > total_cost * 0.2:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"webhook:{tenant_id}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="rate_limiting",
                title="Rate-limit webhook deliveries",
                description="Webhook delivery costs exceed 20% of total. Implement webhook batching "
                            "(combine multiple events per delivery) and rate limiting. "
                            "Reduces webhook volume by 50-70%.",
                estimated_savings_pct=60.0,
                estimated_savings_usd=webhook_cost * 0.60 / 100_000_000,
                priority="medium",
                implementation_effort="moderate",
            ))

        # 5. Cache warming for high-frequency agents
        by_agent = summary.get("by_agent", {})
        expensive_agents = [
            (aid, data["total"]) for aid, data in by_agent.items()
            if data["total"] > total_cost * 0.15  # agent uses >15% of total
        ]
        if expensive_agents:
            top_agent = max(expensive_agents, key=lambda x: x[1])
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"cache:{tenant_id}:{top_agent[0]}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="cache_warming",
                title="Pre-warm rule caches for top agents",
                description=f"Agent '{top_agent[0]}' accounts for ${top_agent[1]/100_000_000:.4f} "
                            f"({top_agent[1]*100//total_cost}% of costs). Pre-compute common rule "
                            "evaluations and warm caches for frequently-hit rules. "
                            "Reduces per-check latency and cost.",
                estimated_savings_pct=20.0,
                estimated_savings_usd=top_agent[1] * 0.20 / 100_000_000,
                priority="medium",
                implementation_effort="moderate",
            ))

        # 6. General: reduce check frequency for low-activity periods
        if total_cost > 0:
            recommendations.append(OptimizationRecommendation(
                recommendation_id=hashlib.sha256(f"schedule:{tenant_id}".encode()).hexdigest()[:16],
                tenant_id=tenant_id,
                category="scheduling",
                title="Reduce check frequency during off-peak",
                description="Schedule drift checks and compliance reports during off-peak hours. "
                            "Reduce check frequency for agents with low activity. "
                            "Typical savings: 10-15% on compute costs.",
                estimated_savings_pct=12.0,
                estimated_savings_usd=total_cost * 0.12 / 100_000_000,
                priority="low",
                implementation_effort="easy",
            ))

        # Sort by estimated savings (descending)
        recommendations.sort(key=lambda r: r.estimated_savings_usd, reverse=True)
        return recommendations


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_tracker: Optional[CostTracker] = None
_store: Optional[CostStore] = None


def get_cost_tracker(db_path: Optional[str] = None) -> CostTracker:
    global _tracker, _store
    if _tracker is None:
        _store = CostStore(db_path=db_path)
        _tracker = CostTracker(store=_store)
    return _tracker


def reset_cost_tracker():
    global _tracker, _store
    _tracker = None
    _store = None
