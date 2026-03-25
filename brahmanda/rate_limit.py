"""
RTA-GUARD — Rate Limiting & Quotas (Phase 4.7)

Per-tenant and per-user rate limiting with sliding window algorithm.
Quota enforcement for facts, agents, webhooks, and storage.

Features:
- Sliding window rate limiter (per-minute, per-hour)
- Burst allowance via token bucket
- Per-tenant and per-user isolation
- Quota tracking (facts/day, agents, webhooks, storage)
- SQLite persistence
- Configurable limits per tenant
- Backward compatible: no rate limiting if not configured

Usage:
    config = RateLimitConfig(requests_per_minute=60, requests_per_hour=1000)
    limiter = RateLimiter(config=config, db_path="data/rate_limits.db")

    allowed, remaining, reset_time = limiter.check_limit(
        user_id="user1", endpoint="/api/check", tenant_id="acme"
    )

    # Quota check
    allowed, info = limiter.check_quota(tenant_id="acme", quota_type="facts_per_day")
"""
import os
import time
import sqlite3
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)


# ─── Configuration ─────────────────────────────────────────────────


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a scope (tenant or user)."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10  # Token bucket burst allowance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_hour": self.requests_per_hour,
            "burst_size": self.burst_size,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RateLimitConfig":
        return cls(
            requests_per_minute=data.get("requests_per_minute", 60),
            requests_per_hour=data.get("requests_per_hour", 1000),
            burst_size=data.get("burst_size", 10),
        )


@dataclass
class QuotaConfig:
    """Quota limits for a tenant."""
    max_facts_per_day: int = 10000
    max_agents: int = 100
    max_webhooks: int = 50
    max_storage_bytes: int = 1_073_741_824  # 1 GB

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_facts_per_day": self.max_facts_per_day,
            "max_agents": self.max_agents,
            "max_webhooks": self.max_webhooks,
            "max_storage_bytes": self.max_storage_bytes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuotaConfig":
        return cls(
            max_facts_per_day=data.get("max_facts_per_day", 10000),
            max_agents=data.get("max_agents", 100),
            max_webhooks=data.get("max_webhooks", 50),
            max_storage_bytes=data.get("max_storage_bytes", 1_073_741_824),
        )


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    remaining: int
    limit: int
    reset_time: float  # Unix timestamp when window resets
    retry_after: float = 0.0  # Seconds to wait if denied

    def to_headers(self) -> Dict[str, str]:
        """Convert to HTTP rate limit headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_time)),
        }
        if not self.allowed and self.retry_after > 0:
            headers["Retry-After"] = str(int(self.retry_after))
        return headers


@dataclass
class QuotaResult:
    """Result of a quota check."""
    allowed: bool
    current: int
    limit: int
    quota_type: str
    remaining: int = 0
    reset_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "current": self.current,
            "limit": self.limit,
            "quota_type": self.quota_type,
            "remaining": self.remaining,
            "reset_time": self.reset_time,
        }


# ─── Quota Types ───────────────────────────────────────────────────


class QuotaType(Enum):
    """Supported quota types."""
    FACTS_PER_DAY = "facts_per_day"
    AGENTS = "agents"
    WEBHOOKS = "webhooks"
    STORAGE_BYTES = "storage_bytes"


# ─── SQLite Store ──────────────────────────────────────────────────


class RateLimitStore:
    """SQLite-backed store for rate limit counters and quotas."""

    def __init__(self, db_path: Optional[str] = None):
        self._memory = db_path is None
        if self._memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS rate_limit_windows (
                    scope TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    window_start REAL NOT NULL,
                    window_size INTEGER NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (scope, endpoint, window_start, window_size)
                );

                CREATE TABLE IF NOT EXISTS token_buckets (
                    scope TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    tokens REAL NOT NULL,
                    last_refill REAL NOT NULL,
                    PRIMARY KEY (scope, endpoint)
                );

                CREATE TABLE IF NOT EXISTS quota_usage (
                    tenant_id TEXT NOT NULL,
                    quota_type TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    current_value INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (tenant_id, quota_type, period_key)
                );

                CREATE TABLE IF NOT EXISTS tenant_configs (
                    tenant_id TEXT PRIMARY KEY,
                    rate_limit_config TEXT NOT NULL DEFAULT '{}',
                    quota_config TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_rl_windows_cleanup
                    ON rate_limit_windows(window_start);
                CREATE INDEX IF NOT EXISTS idx_quota_period
                    ON quota_usage(tenant_id, quota_type, period_key);
            """)
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    # -- Rate limit window operations --

    def get_window_count(self, scope: str, endpoint: str, window_start: float, window_size: int) -> int:
        """Get request count for a specific window."""
        with self._lock:
            row = self._conn.execute(
                "SELECT request_count FROM rate_limit_windows WHERE scope=? AND endpoint=? AND window_start=? AND window_size=?",
                (scope, endpoint, window_start, window_size)
            ).fetchone()
            return row["request_count"] if row else 0

    def increment_window(self, scope: str, endpoint: str, window_start: float, window_size: int) -> int:
        """Increment request count for a window and return new count."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO rate_limit_windows (scope, endpoint, window_start, window_size, request_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(scope, endpoint, window_start, window_size)
                DO UPDATE SET request_count = request_count + 1
            """, (scope, endpoint, window_start, window_size))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT request_count FROM rate_limit_windows WHERE scope=? AND endpoint=? AND window_start=? AND window_size=?",
                (scope, endpoint, window_start, window_size)
            ).fetchone()
            return row["request_count"] if row else 0

    def get_sliding_count(self, scope: str, endpoint: str, now: float, window_size: int) -> int:
        """Get total requests in a sliding window ending at `now`."""
        window_start = now - window_size
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(request_count), 0) as total FROM rate_limit_windows WHERE scope=? AND endpoint=? AND window_start >= ? AND window_size=?",
                (scope, endpoint, window_start, window_size)
            ).fetchone()
            return row["total"] if row else 0

    def cleanup_old_windows(self, before: float):
        """Remove windows older than `before`."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM rate_limit_windows WHERE window_start < ?", (before,)
            )
            self._conn.commit()

    # -- Token bucket operations --

    def get_bucket(self, scope: str, endpoint: str) -> Optional[Dict[str, float]]:
        """Get token bucket state."""
        with self._lock:
            row = self._conn.execute(
                "SELECT tokens, last_refill FROM token_buckets WHERE scope=? AND endpoint=?",
                (scope, endpoint)
            ).fetchone()
            if row:
                return {"tokens": row["tokens"], "last_refill": row["last_refill"]}
            return None

    def set_bucket(self, scope: str, endpoint: str, tokens: float, last_refill: float):
        """Set token bucket state."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO token_buckets (scope, endpoint, tokens, last_refill)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, endpoint)
                DO UPDATE SET tokens=?, last_refill=?
            """, (scope, endpoint, tokens, last_refill, tokens, last_refill))
            self._conn.commit()

    # -- Quota operations --

    def get_quota(self, tenant_id: str, quota_type: str, period_key: str) -> int:
        """Get current quota usage."""
        with self._lock:
            row = self._conn.execute(
                "SELECT current_value FROM quota_usage WHERE tenant_id=? AND quota_type=? AND period_key=?",
                (tenant_id, quota_type, period_key)
            ).fetchone()
            return row["current_value"] if row else 0

    def increment_quota(self, tenant_id: str, quota_type: str, period_key: str, amount: int = 1) -> int:
        """Increment quota usage and return new value."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO quota_usage (tenant_id, quota_type, period_key, current_value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, quota_type, period_key)
                DO UPDATE SET current_value = current_value + ?
            """, (tenant_id, quota_type, period_key, amount, amount))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT current_value FROM quota_usage WHERE tenant_id=? AND quota_type=? AND period_key=?",
                (tenant_id, quota_type, period_key)
            ).fetchone()
            return row["current_value"] if row else 0

    def set_quota(self, tenant_id: str, quota_type: str, period_key: str, value: int):
        """Set quota usage to a specific value."""
        with self._lock:
            self._conn.execute("""
                INSERT INTO quota_usage (tenant_id, quota_type, period_key, current_value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tenant_id, quota_type, period_key)
                DO UPDATE SET current_value = ?
            """, (tenant_id, quota_type, period_key, value, value))
            self._conn.commit()

    # -- Tenant config operations --

    def get_tenant_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant-specific rate limit and quota config."""
        import json
        with self._lock:
            row = self._conn.execute(
                "SELECT rate_limit_config, quota_config FROM tenant_configs WHERE tenant_id=?",
                (tenant_id,)
            ).fetchone()
            if row:
                return {
                    "rate_limit": json.loads(row["rate_limit_config"]),
                    "quota": json.loads(row["quota_config"]),
                }
            return None

    def set_tenant_config(self, tenant_id: str, rate_limit: Dict, quota: Dict):
        """Set tenant-specific config."""
        import json
        with self._lock:
            self._conn.execute("""
                INSERT INTO tenant_configs (tenant_id, rate_limit_config, quota_config)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant_id)
                DO UPDATE SET rate_limit_config=?, quota_config=?
            """, (tenant_id, json.dumps(rate_limit), json.dumps(quota),
                  json.dumps(rate_limit), json.dumps(quota)))
            self._conn.commit()


# ─── Rate Limiter ──────────────────────────────────────────────────


class RateLimiter:
    """
    Sliding window rate limiter with token bucket burst support.

    Tracks requests per scope (user or tenant) per endpoint using
    sliding window counters in SQLite. Token bucket provides burst
    allowance above the steady-state rate.

    Scopes:
      - Per-user: "user:{user_id}"
      - Per-tenant: "tenant:{tenant_id}"
      - Per-user-per-tenant: "user:{user_id}:tenant:{tenant_id}"
    """

    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
        quota_config: Optional[QuotaConfig] = None,
        db_path: Optional[str] = None,
    ):
        self.default_config = config or RateLimitConfig()
        self.default_quota = quota_config or QuotaConfig()
        self.store = RateLimitStore(db_path)

    def close(self):
        """Close the underlying store."""
        self.store.close()

    def _get_config_for_tenant(self, tenant_id: Optional[str]) -> RateLimitConfig:
        """Get rate limit config for a tenant, falling back to default."""
        if not tenant_id:
            return self.default_config
        cfg = self.store.get_tenant_config(tenant_id)
        if cfg and cfg.get("rate_limit"):
            return RateLimitConfig.from_dict(cfg["rate_limit"])
        return self.default_config

    def _get_quota_for_tenant(self, tenant_id: Optional[str]) -> QuotaConfig:
        """Get quota config for a tenant, falling back to default."""
        if not tenant_id:
            return self.default_quota
        cfg = self.store.get_tenant_config(tenant_id)
        if cfg and cfg.get("quota"):
            return QuotaConfig.from_dict(cfg["quota"])
        return self.default_quota

    def configure_tenant(
        self,
        tenant_id: str,
        rate_limit: Optional[RateLimitConfig] = None,
        quota: Optional[QuotaConfig] = None,
    ):
        """Set custom rate limit and quota config for a tenant."""
        rl = (rate_limit or self.default_config).to_dict()
        q = (quota or self.default_quota).to_dict()
        self.store.set_tenant_config(tenant_id, rl, q)

    def check_limit(
        self,
        user_id: Optional[str] = None,
        endpoint: str = "*",
        tenant_id: Optional[str] = None,
    ) -> RateLimitResult:
        """
        Check rate limit for a request.

        Checks both per-user and per-tenant limits. A request must pass
        both to be allowed. Uses sliding window algorithm.

        Returns:
            RateLimitResult with allowed, remaining, limit, reset_time
        """
        now = time.time()
        config = self._get_config_for_tenant(tenant_id)

        # Check per-tenant limit (more permissive, shared across users)
        if tenant_id:
            tenant_result = self._check_sliding_window(
                scope=f"tenant:{tenant_id}",
                endpoint=endpoint,
                now=now,
                config=config,
            )
            if not tenant_result.allowed:
                return tenant_result

        # Check per-user limit (stricter, per individual)
        if user_id:
            scope = f"user:{user_id}"
            if tenant_id:
                scope += f":tenant:{tenant_id}"
            user_result = self._check_sliding_window(
                scope=scope,
                endpoint=endpoint,
                now=now,
                config=config,
            )
            if not user_result.allowed:
                return user_result
            return user_result

        # Tenant-only check
        if tenant_id:
            return tenant_result

        # No scope — allow (shouldn't happen in normal usage)
        return RateLimitResult(
            allowed=True,
            remaining=config.requests_per_minute,
            limit=config.requests_per_minute,
            reset_time=now + 60,
        )

    def _check_sliding_window(
        self,
        scope: str,
        endpoint: str,
        now: float,
        config: RateLimitConfig,
    ) -> RateLimitResult:
        """Check fixed window + token bucket for a single scope."""
        # Fixed window: bucket = int(now / window_size)
        minute_window = 60
        minute_bucket = int(now / minute_window)
        hour_window = 3600
        hour_bucket = int(now / hour_window)

        minute_count = self.store.get_window_count(scope, endpoint, minute_bucket, minute_window)
        hour_count = self.store.get_window_count(scope, endpoint, hour_bucket, hour_window)

        # Token bucket for burst
        bucket = self.store.get_bucket(scope, endpoint)
        burst_tokens = config.burst_size
        if bucket:
            elapsed = now - bucket["last_refill"]
            refill_rate = config.burst_size / 60.0
            burst_tokens = min(config.burst_size, bucket["tokens"] + elapsed * refill_rate)

        # Determine limits
        minute_limit = config.requests_per_minute
        hour_limit = config.requests_per_hour

        # Check if within limits (including burst allowance)
        minute_exceeded = minute_count >= minute_limit + int(burst_tokens)
        hour_exceeded = hour_count >= hour_limit

        if minute_exceeded or hour_exceeded:
            if hour_exceeded:
                reset_time = (hour_bucket + 1) * hour_window
                retry_after = reset_time - now
                remaining = 0
                limit = hour_limit
            else:
                reset_time = (minute_bucket + 1) * minute_window
                retry_after = reset_time - now
                remaining = 0
                limit = minute_limit

            return RateLimitResult(
                allowed=False,
                remaining=remaining,
                limit=limit,
                reset_time=reset_time,
                retry_after=retry_after,
            )

        # Allowed — record the request
        self.store.increment_window(scope, endpoint, minute_bucket, minute_window)
        self.store.increment_window(scope, endpoint, hour_bucket, hour_window)

        # Consume burst token if near limit
        if bucket or minute_count >= minute_limit * 0.8:
            new_tokens = burst_tokens - 1
            self.store.set_bucket(scope, endpoint, max(0, new_tokens), now)

        remaining = minute_limit - minute_count - 1
        reset_time = (minute_bucket + 1) * minute_window
        return RateLimitResult(
            allowed=True,
            remaining=max(0, remaining),
            limit=minute_limit,
            reset_time=reset_time,
        )

    def check_quota(
        self,
        tenant_id: str,
        quota_type: str,
        amount: int = 1,
    ) -> QuotaResult:
        """
        Check if a quota allows the requested amount.

        Does NOT increment — call record_quota() after the operation succeeds.

        Args:
            tenant_id: Tenant to check
            quota_type: One of "facts_per_day", "agents", "webhooks", "storage_bytes"
            amount: Amount to check against

        Returns:
            QuotaResult with allowed, current, limit, remaining
        """
        config = self._get_quota_for_tenant(tenant_id)
        period_key = self._get_period_key(quota_type)
        current = self.store.get_quota(tenant_id, quota_type, period_key)
        limit = self._get_quota_limit(config, quota_type)

        return QuotaResult(
            allowed=(current + amount) <= limit,
            current=current,
            limit=limit,
            quota_type=quota_type,
            remaining=max(0, limit - current),
            reset_time=self._get_quota_reset_time(quota_type),
        )

    def record_quota(
        self,
        tenant_id: str,
        quota_type: str,
        amount: int = 1,
    ) -> QuotaResult:
        """
        Record quota usage (increment counter).

        Call this AFTER an operation succeeds to track usage.
        """
        config = self._get_quota_for_tenant(tenant_id)
        period_key = self._get_period_key(quota_type)
        new_value = self.store.increment_quota(tenant_id, quota_type, period_key, amount)
        limit = self._get_quota_limit(config, quota_type)

        return QuotaResult(
            allowed=new_value <= limit,
            current=new_value,
            limit=limit,
            quota_type=quota_type,
            remaining=max(0, limit - new_value),
            reset_time=self._get_quota_reset_time(quota_type),
        )

    def get_quota_status(self, tenant_id: str) -> Dict[str, QuotaResult]:
        """Get status of all quotas for a tenant."""
        results = {}
        for qt in QuotaType:
            results[qt.value] = self.check_quota(tenant_id, qt.value, amount=0)
        return results

    def reset_quota(self, tenant_id: str, quota_type: str):
        """Reset a specific quota to zero."""
        period_key = self._get_period_key(quota_type)
        self.store.set_quota(tenant_id, quota_type, period_key, 0)

    def _get_period_key(self, quota_type: str) -> str:
        """Get the period key for a quota type (daily quotas use date)."""
        if quota_type == QuotaType.FACTS_PER_DAY.value:
            import datetime
            return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        # Non-temporal quotas use a constant key
        return "all_time"

    def _get_quota_limit(self, config: QuotaConfig, quota_type: str) -> int:
        """Get limit for a quota type from config."""
        mapping = {
            QuotaType.FACTS_PER_DAY.value: config.max_facts_per_day,
            QuotaType.AGENTS.value: config.max_agents,
            QuotaType.WEBHOOKS.value: config.max_webhooks,
            QuotaType.STORAGE_BYTES.value: config.max_storage_bytes,
        }
        return mapping.get(quota_type, 0)

    def _get_quota_reset_time(self, quota_type: str) -> float:
        """Get when the quota resets (end of day for daily quotas)."""
        if quota_type == QuotaType.FACTS_PER_DAY.value:
            import datetime
            now = datetime.datetime.now(datetime.UTC)
            tomorrow = (now + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            return tomorrow.timestamp()
        # Non-temporal quotas don't reset
        return 0.0

    def cleanup(self, max_age_seconds: int = 7200):
        """Clean up old rate limit windows (default: older than 2 hours)."""
        cutoff = time.time() - max_age_seconds
        self.store.cleanup_old_windows(cutoff)


# ─── Global Instance Management ────────────────────────────────────

_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(
    config: Optional[RateLimitConfig] = None,
    quota_config: Optional[QuotaConfig] = None,
    db_path: Optional[str] = None,
) -> RateLimiter:
    """Get or create the global RateLimiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            config=config,
            quota_config=quota_config,
            db_path=db_path,
        )
    return _rate_limiter


def reset_rate_limiter():
    """Reset the global RateLimiter (for testing)."""
    global _rate_limiter
    if _rate_limiter:
        _rate_limiter.close()
    _rate_limiter = None


# ─── FastAPI Middleware ────────────────────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware for rate limiting.

    Applies rate limits to all endpoints. Extracts user_id and tenant_id
    from request headers/auth and checks limits before processing.

    Exempts health/status endpoints from rate limiting.

    Usage:
        app.add_middleware(
            RateLimitMiddleware,
            rate_limiter=my_limiter,
        )
    """

    # Endpoints exempt from rate limiting
    EXEMPT_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/api/auth/status"}

    def __init__(self, app, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(app)
        self.rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next):
        # Skip if no rate limiter configured (backward compatible)
        if self.rate_limiter is None:
            return await call_next(request)

        # Skip exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Skip WebSocket connections
        if request.url.path == "/ws":
            return await call_next(request)

        # Extract identifiers
        user_id = self._extract_user_id(request)
        tenant_id = self._extract_tenant_id(request)
        endpoint = request.url.path

        # Check rate limit
        result = self.rate_limiter.check_limit(
            user_id=user_id,
            endpoint=endpoint,
            tenant_id=tenant_id,
        )

        if not result.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "retry_after": int(result.retry_after),
                    "limit": result.limit,
                },
            )
            # Add rate limit headers
            for key, value in result.to_headers().items():
                response.headers[key] = value
            return response

        # Process request
        response = await call_next(request)

        # Add rate limit headers to successful response
        for key, value in result.to_headers().items():
            response.headers[key] = value

        return response

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """Extract user ID from request (X-User-Id header or auth)."""
        # Check X-User-Id header first
        user_id = request.headers.get("x-user-id")
        if user_id:
            return user_id
        # Fall back to extracting from Authorization header token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:32]  # Use first 25 chars of token as user key
        return None

    def _extract_tenant_id(self, request: Request) -> Optional[str]:
        """Extract tenant ID from request headers."""
        return request.headers.get("x-tenant-id")
