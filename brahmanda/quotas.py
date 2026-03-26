"""
RTA-GUARD — Quotas System (Phase 6.6)

Per-tenant resource quotas, tiered pricing, soft/hard limit enforcement.
Quota enforcement is opt-in (disabled by default) — set QUOTA_ENFORCEMENT_ENABLED=true.
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
# Pricing tiers
# ---------------------------------------------------------------------------

class PricingTier(Enum):
    """Rate-based pricing tiers."""
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# Default quota definitions per tier (per hour unless noted)
TIER_QUOTAS = {
    PricingTier.FREE.value: {
        "max_kills_per_hour": 5,
        "max_kills_per_day": 50,
        "max_checks_per_hour": 100,
        "max_checks_per_day": 1000,
        "max_api_calls_per_hour": 200,
        "max_storage_mb": 100,
        "max_agents": 3,
        "max_webhooks_per_hour": 10,
        "max_concurrent_sessions": 10,
        "max_drift_scores_per_hour": 50,
        "monthly_cost_cap_usd": 0.0,
    },
    PricingTier.STARTER.value: {
        "max_kills_per_hour": 50,
        "max_kills_per_day": 500,
        "max_checks_per_hour": 1000,
        "max_checks_per_day": 10000,
        "max_api_calls_per_hour": 2000,
        "max_storage_mb": 1024,
        "max_agents": 20,
        "max_webhooks_per_hour": 100,
        "max_concurrent_sessions": 50,
        "max_drift_scores_per_hour": 500,
        "monthly_cost_cap_usd": 49.0,
    },
    PricingTier.PRO.value: {
        "max_kills_per_hour": 500,
        "max_kills_per_day": 5000,
        "max_checks_per_hour": 10000,
        "max_checks_per_day": 100000,
        "max_api_calls_per_hour": 20000,
        "max_storage_mb": 10240,
        "max_agents": 100,
        "max_webhooks_per_hour": 1000,
        "max_concurrent_sessions": 200,
        "max_drift_scores_per_hour": 5000,
        "monthly_cost_cap_usd": 199.0,
    },
    PricingTier.ENTERPRISE.value: {
        "max_kills_per_hour": -1,     # unlimited
        "max_kills_per_day": -1,
        "max_checks_per_hour": -1,
        "max_checks_per_day": -1,
        "max_api_calls_per_hour": -1,
        "max_storage_mb": -1,
        "max_agents": -1,
        "max_webhooks_per_hour": -1,
        "max_concurrent_sessions": -1,
        "max_drift_scores_per_hour": -1,
        "monthly_cost_cap_usd": -1.0,  # custom billing
    },
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class QuotaLimit:
    """A single quota limit definition."""
    resource: str
    hard_limit: int        # -1 = unlimited
    soft_limit_pct: float  # percentage of hard limit that triggers soft warning (e.g., 80.0)
    period: str            # "hour", "day", "month", "total"
    current_usage: int = 0
    limit_id: str = ""

    def __post_init__(self):
        if not self.limit_id:
            self.limit_id = hashlib.sha256(f"{self.resource}:{self.period}".encode()).hexdigest()[:12]

    @property
    def is_unlimited(self) -> bool:
        return self.hard_limit == -1

    @property
    def soft_limit(self) -> int:
        if self.is_unlimited:
            return -1
        return int(self.hard_limit * self.soft_limit_pct / 100.0)

    @property
    def usage_pct(self) -> float:
        if self.is_unlimited or self.hard_limit == 0:
            return 0.0
        return (self.current_usage / self.hard_limit) * 100.0

    @property
    def is_soft_exceeded(self) -> bool:
        if self.is_unlimited:
            return False
        return self.current_usage >= self.soft_limit

    @property
    def is_hard_exceeded(self) -> bool:
        if self.is_unlimited:
            return False
        return self.current_usage >= self.hard_limit

    @property
    def remaining(self) -> int:
        if self.is_unlimited:
            return -1
        return max(0, self.hard_limit - self.current_usage)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_unlimited"] = self.is_unlimited
        d["soft_limit"] = self.soft_limit
        d["usage_pct"] = self.usage_pct
        d["remaining"] = self.remaining
        d["is_soft_exceeded"] = self.is_soft_exceeded
        d["is_hard_exceeded"] = self.is_hard_exceeded
        return d


@dataclass
class QuotaViolation:
    """Record of a quota limit violation."""
    violation_id: str
    tenant_id: str
    resource: str
    limit_type: str       # "soft" or "hard"
    current_usage: int
    limit_value: int
    period: str
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.violation_id:
            self.violation_id = hashlib.sha256(
                f"{self.tenant_id}:{self.resource}:{self.timestamp}".encode()
            ).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TenantQuotaProfile:
    """Complete quota profile for a tenant."""
    tenant_id: str
    tier: str
    limits: Dict[str, QuotaLimit]     # resource_name -> QuotaLimit
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "tier": self.tier,
            "limits": {k: v.to_dict() for k, v in self.limits.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Quota Store
# ---------------------------------------------------------------------------

class QuotaStore:
    """SQLite persistence for quota profiles and usage counters."""

    def __init__(self, db_path: Optional[str] = None, in_memory: bool = False):
        if in_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path = db_path or os.getenv("QUOTA_DB_PATH", "data/quotas.db")
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS quota_profiles (
                    tenant_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'free',
                    limits_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quota_usage (
                    tenant_id TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    period TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    window_start TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, resource, period)
                );
                CREATE INDEX IF NOT EXISTS idx_usage_tenant ON quota_usage(tenant_id);

                CREATE TABLE IF NOT EXISTS quota_violations (
                    violation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    limit_type TEXT NOT NULL,
                    current_usage INTEGER,
                    limit_value INTEGER,
                    period TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_violation_tenant ON quota_violations(tenant_id);
            """)
            self._conn.commit()

    def upsert_profile(self, profile: TenantQuotaProfile):
        with self._lock:
            limits_json = json.dumps({k: {
                "resource": v.resource, "hard_limit": v.hard_limit,
                "soft_limit_pct": v.soft_limit_pct, "period": v.period,
            } for k, v in profile.limits.items()})
            self._conn.execute(
                """INSERT INTO quota_profiles (tenant_id, tier, limits_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id) DO UPDATE SET
                     tier=?, limits_json=?, updated_at=?""",
                (profile.tenant_id, profile.tier, limits_json,
                 profile.created_at, profile.updated_at,
                 profile.tier, limits_json, profile.updated_at)
            )
            self._conn.commit()

    def get_profile(self, tenant_id: str) -> Optional[TenantQuotaProfile]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM quota_profiles WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        if not row:
            return None
        limits_data = json.loads(row["limits_json"])
        limits = {}
        for k, v in limits_data.items():
            limits[k] = QuotaLimit(
                resource=v["resource"], hard_limit=v["hard_limit"],
                soft_limit_pct=v.get("soft_limit_pct", 80.0), period=v["period"],
            )
        return TenantQuotaProfile(
            tenant_id=row["tenant_id"], tier=row["tier"],
            limits=limits, created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def increment_usage(self, tenant_id: str, resource: str, period_key: str,
                        window_start: str, amount: int = 1):
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """INSERT INTO quota_usage (tenant_id, resource, period, usage_count, window_start, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, resource, period) DO UPDATE SET
                     usage_count = usage_count + ?,
                     updated_at = ?""",
                (tenant_id, resource, period_key, amount, window_start, now,
                 amount, now)
            )
            self._conn.commit()

    def get_usage(self, tenant_id: str, resource: str, period_key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                """SELECT usage_count FROM quota_usage
                   WHERE tenant_id = ? AND resource = ? AND period = ?""",
                (tenant_id, resource, period_key)
            ).fetchone()
        return row["usage_count"] if row else 0

    def reset_usage(self, tenant_id: str, resource: Optional[str] = None):
        with self._lock:
            if resource:
                self._conn.execute(
                    "DELETE FROM quota_usage WHERE tenant_id = ? AND resource = ?",
                    (tenant_id, resource)
                )
            else:
                self._conn.execute(
                    "DELETE FROM quota_usage WHERE tenant_id = ?", (tenant_id,)
                )
            self._conn.commit()

    def record_violation(self, violation: QuotaViolation):
        with self._lock:
            self._conn.execute(
                """INSERT INTO quota_violations
                   (violation_id, tenant_id, resource, limit_type, current_usage,
                    limit_value, period, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (violation.violation_id, violation.tenant_id, violation.resource,
                 violation.limit_type, violation.current_usage, violation.limit_value,
                 violation.period, violation.timestamp, json.dumps(violation.metadata))
            )
            self._conn.commit()

    def get_violations(self, tenant_id: str, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM quota_violations
                   WHERE tenant_id = ? ORDER BY timestamp DESC LIMIT ?""",
                (tenant_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Quota Manager
# ---------------------------------------------------------------------------

class QuotaManager:
    """
    Manages tenant quotas with soft/hard limit enforcement.

    Usage:
        manager = QuotaManager()
        manager.create_tenant("acme", tier="pro")
        allowed = manager.check_and_consume("acme", "kill_decision")
        if not allowed:
            raise QuotaExceededError("Kill quota exceeded")
    """

    def __init__(self, store: Optional[QuotaStore] = None,
                 custom_tiers: Optional[Dict[str, Dict]] = None):
        self._store = store or QuotaStore(in_memory=True)
        self._tiers = dict(TIER_QUOTAS)
        if custom_tiers:
            self._tiers.update(custom_tiers)
        self._enabled = os.getenv("QUOTA_ENFORCEMENT_ENABLED", "false").lower() in ("true", "1", "yes")
        self._violation_callbacks: List[Callable[[QuotaViolation], None]] = []
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def on_violation(self, callback: Callable[[QuotaViolation], None]):
        self._violation_callbacks.append(callback)

    def create_tenant(self, tenant_id: str, tier: str = "free",
                      overrides: Optional[Dict[str, Dict]] = None) -> TenantQuotaProfile:
        """Create a new tenant with the given pricing tier."""
        tier_config = self._tiers.get(tier, self._tiers["free"])
        limits = {}

        for resource, limit_val in tier_config.items():
            resource_name = resource.replace("max_", "").replace("_per_hour", "").replace("_per_day", "")
            period = "total"
            if "_per_hour" in resource:
                period = "hour"
            elif "_per_day" in resource:
                period = "day"

            # Apply overrides if provided
            if overrides and resource in overrides:
                limit_val = overrides[resource].get("hard_limit", limit_val)

            limits[resource] = QuotaLimit(
                resource=resource,
                hard_limit=limit_val if limit_val != -1.0 else -1,
                soft_limit_pct=80.0,
                period=period,
            )

        profile = TenantQuotaProfile(tenant_id=tenant_id, tier=tier, limits=limits)
        self._store.upsert_profile(profile)
        return profile

    def update_tier(self, tenant_id: str, new_tier: str) -> TenantQuotaProfile:
        """Change a tenant's pricing tier."""
        return self.create_tenant(tenant_id, tier=new_tier)

    def check_and_consume(self, tenant_id: str, resource: str,
                           amount: int = 1) -> bool:
        """
        Check if the tenant has quota remaining and consume it.
        Returns True if allowed, False if hard limit exceeded.
        Soft limits trigger callbacks but still allow the operation.
        """
        if not self._enabled:
            return True

        profile = self._store.get_profile(tenant_id)
        if not profile:
            # Auto-create with free tier
            profile = self.create_tenant(tenant_id)

        limit = profile.limits.get(resource)
        if not limit:
            return True  # No limit defined for this resource

        if limit.is_unlimited:
            return True

        # Determine current period window
        now = datetime.now(timezone.utc)
        period_key, window_start = self._get_period_window(limit.period, now)

        # Get current usage
        current = self._store.get_usage(tenant_id, resource, period_key)

        # Check hard limit
        if current + amount > limit.hard_limit:
            violation = QuotaViolation(
                violation_id="",
                tenant_id=tenant_id,
                resource=resource,
                limit_type="hard",
                current_usage=current + amount,
                limit_value=limit.hard_limit,
                period=limit.period,
            )
            self._store.record_violation(violation)
            for cb in self._violation_callbacks:
                try:
                    cb(violation)
                except Exception:
                    pass
            return False

        # Check soft limit (warn but allow)
        if current + amount >= limit.soft_limit and current < limit.soft_limit:
            violation = QuotaViolation(
                violation_id="",
                tenant_id=tenant_id,
                resource=resource,
                limit_type="soft",
                current_usage=current + amount,
                limit_value=limit.soft_limit,
                period=limit.period,
            )
            self._store.record_violation(violation)
            for cb in self._violation_callbacks:
                try:
                    cb(violation)
                except Exception:
                    pass

        # Consume quota
        self._store.increment_usage(tenant_id, resource, period_key, window_start, amount)
        return True

    def get_usage_status(self, tenant_id: str) -> Dict[str, Any]:
        """Get current quota usage status for all resources."""
        profile = self._store.get_profile(tenant_id)
        if not profile:
            return {"tenant_id": tenant_id, "status": "not_found"}

        now = datetime.now(timezone.utc)
        status = {
            "tenant_id": tenant_id,
            "tier": profile.tier,
            "resources": {},
        }

        for resource_name, limit in profile.limits.items():
            if limit.is_unlimited:
                status["resources"][resource_name] = {
                    "limit": -1, "current": 0, "remaining": -1,
                    "usage_pct": 0, "status": "unlimited",
                }
                continue

            period_key, _ = self._get_period_window(limit.period, now)
            current = self._store.get_usage(tenant_id, resource_name, period_key)

            if current >= limit.hard_limit:
                limit_status = "hard_exceeded"
            elif current >= limit.soft_limit:
                limit_status = "soft_exceeded"
            else:
                limit_status = "within"

            status["resources"][resource_name] = {
                "limit": limit.hard_limit,
                "current": current,
                "remaining": max(0, limit.hard_limit - current),
                "usage_pct": round((current / limit.hard_limit) * 100, 1) if limit.hard_limit > 0 else 0,
                "status": limit_status,
            }

        return status

    def get_violations(self, tenant_id: str, limit: int = 50) -> List[dict]:
        return self._store.get_violations(tenant_id, limit)

    def reset_usage(self, tenant_id: str, resource: Optional[str] = None):
        self._store.reset_usage(tenant_id, resource)

    @staticmethod
    def _get_period_window(period: str, now: datetime) -> tuple:
        """Return (period_key, window_start_iso) for the given period."""
        if period == "hour":
            window = now.replace(minute=0, second=0, microsecond=0)
            key = window.strftime("%Y-%m-%dT%H")
        elif period == "day":
            window = now.replace(hour=0, minute=0, second=0, microsecond=0)
            key = window.strftime("%Y-%m-%d")
        elif period == "month":
            window = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            key = window.strftime("%Y-%m")
        else:
            key = "total"
            window = datetime(2000, 1, 1, tzinfo=timezone.utc)
        return key, window.isoformat()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_manager: Optional[QuotaManager] = None
_store: Optional[QuotaStore] = None


def get_quota_manager(db_path: Optional[str] = None) -> QuotaManager:
    global _manager, _store
    if _manager is None:
        _store = QuotaStore(db_path=db_path)
        _manager = QuotaManager(store=_store)
    return _manager


def reset_quota_manager():
    global _manager, _store
    _manager = None
    _store = None
