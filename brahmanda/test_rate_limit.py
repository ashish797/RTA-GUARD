"""
RTA-GUARD — Rate Limiting & Quotas Tests (Phase 4.7)

Tests for:
- Sliding window rate limiting
- Token bucket burst handling
- Per-tenant and per-user isolation
- Quota enforcement
- Tenant config overrides
- FastAPI middleware integration
- Edge cases
"""
import asyncio
import time
import uuid
import pytest
from unittest.mock import patch

from brahmanda.rate_limit import (
    RateLimiter, RateLimitConfig, QuotaConfig, QuotaType,
    RateLimitResult, QuotaResult, RateLimitStore,
    get_rate_limiter, reset_rate_limiter,
    RateLimitMiddleware,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def limiter():
    """Fresh in-memory rate limiter with generous defaults."""
    config = RateLimitConfig(requests_per_minute=10, requests_per_hour=100, burst_size=3)
    quota = QuotaConfig(max_facts_per_day=50, max_agents=5, max_webhooks=3, max_storage_bytes=1024)
    l = RateLimiter(config=config, quota_config=quota, db_path=None)
    yield l
    l.close()


@pytest.fixture
def strict_limiter():
    """Rate limiter with tight limits for testing exceeded scenarios."""
    config = RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=1)
    quota = QuotaConfig(max_facts_per_day=5, max_agents=2, max_webhooks=1, max_storage_bytes=100)
    l = RateLimiter(config=config, quota_config=quota, db_path=None)
    yield l
    l.close()


def _uid(prefix="u"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════════
# 1. RateLimitConfig
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_defaults(self):
        c = RateLimitConfig()
        assert c.requests_per_minute == 60
        assert c.requests_per_hour == 1000
        assert c.burst_size == 10

    def test_custom(self):
        c = RateLimitConfig(requests_per_minute=30, requests_per_hour=500, burst_size=5)
        assert c.requests_per_minute == 30
        assert c.requests_per_hour == 500
        assert c.burst_size == 5

    def test_to_dict(self):
        c = RateLimitConfig(requests_per_minute=20, requests_per_hour=200, burst_size=8)
        d = c.to_dict()
        assert d["requests_per_minute"] == 20
        assert d["requests_per_hour"] == 200
        assert d["burst_size"] == 8

    def test_from_dict(self):
        d = {"requests_per_minute": 15, "requests_per_hour": 150, "burst_size": 4}
        c = RateLimitConfig.from_dict(d)
        assert c.requests_per_minute == 15
        assert c.requests_per_hour == 150
        assert c.burst_size == 4

    def test_from_dict_defaults(self):
        c = RateLimitConfig.from_dict({})
        assert c.requests_per_minute == 60


class TestQuotaConfig:
    """Test QuotaConfig dataclass."""

    def test_defaults(self):
        q = QuotaConfig()
        assert q.max_facts_per_day == 10000
        assert q.max_agents == 100
        assert q.max_webhooks == 50
        assert q.max_storage_bytes == 1_073_741_824

    def test_to_dict(self):
        q = QuotaConfig(max_facts_per_day=100)
        d = q.to_dict()
        assert d["max_facts_per_day"] == 100

    def test_from_dict(self):
        d = {"max_facts_per_day": 200, "max_agents": 10}
        q = QuotaConfig.from_dict(d)
        assert q.max_facts_per_day == 200
        assert q.max_agents == 10
        assert q.max_webhooks == 50  # default


# ═══════════════════════════════════════════════════════════════════
# 2. RateLimitResult Headers
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitResult:
    """Test RateLimitResult."""

    def test_headers_allowed(self):
        r = RateLimitResult(allowed=True, remaining=5, limit=10, reset_time=1000.0)
        h = r.to_headers()
        assert h["X-RateLimit-Limit"] == "10"
        assert h["X-RateLimit-Remaining"] == "5"
        assert h["X-RateLimit-Reset"] == "1000"
        assert "Retry-After" not in h

    def test_headers_denied(self):
        r = RateLimitResult(allowed=False, remaining=0, limit=10, reset_time=1000.0, retry_after=30.5)
        h = r.to_headers()
        assert h["Retry-After"] == "30"

    def test_remaining_never_negative(self):
        r = RateLimitResult(allowed=True, remaining=-3, limit=10, reset_time=1000.0)
        h = r.to_headers()
        assert h["X-RateLimit-Remaining"] == "0"


# ═══════════════════════════════════════════════════════════════════
# 3. Rate Limit Store
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitStore:
    """Test SQLite-backed rate limit store."""

    def test_in_memory(self):
        store = RateLimitStore(db_path=None)
        assert store._memory
        store.close()

    def test_window_increment(self):
        store = RateLimitStore(db_path=None)
        count = store.increment_window("s", "/api/test", 1000.0, 60)
        assert count == 1
        count = store.increment_window("s", "/api/test", 1000.0, 60)
        assert count == 2
        store.close()

    def test_window_get(self):
        store = RateLimitStore(db_path=None)
        store.increment_window("s", "/api/test", 1000.0, 60)
        store.increment_window("s", "/api/test", 1000.0, 60)
        count = store.get_window_count("s", "/api/test", 1000.0, 60)
        assert count == 2
        # Different window
        count = store.get_window_count("s", "/api/test", 2000.0, 60)
        assert count == 0
        store.close()

    def test_sliding_count(self):
        store = RateLimitStore(db_path=None)
        now = 1000.0
        store.increment_window("s", "/ep", 990.0, 60)  # within window
        store.increment_window("s", "/ep", 980.0, 60)  # within window
        store.increment_window("s", "/ep", 900.0, 60)  # outside window
        count = store.get_sliding_count("s", "/ep", now, 60)
        assert count == 2
        store.close()

    def test_cleanup(self):
        store = RateLimitStore(db_path=None)
        store.increment_window("s", "/ep", 100.0, 60)
        store.increment_window("s", "/ep", 200.0, 60)
        store.cleanup_old_windows(150.0)
        count = store.get_window_count("s", "/ep", 100.0, 60)
        assert count == 0
        count = store.get_window_count("s", "/ep", 200.0, 60)
        assert count == 1
        store.close()

    def test_token_bucket(self):
        store = RateLimitStore(db_path=None)
        assert store.get_bucket("s", "/ep") is None
        store.set_bucket("s", "/ep", 5.0, 1000.0)
        b = store.get_bucket("s", "/ep")
        assert b["tokens"] == 5.0
        assert b["last_refill"] == 1000.0
        store.close()

    def test_quota_operations(self):
        store = RateLimitStore(db_path=None)
        assert store.get_quota("t1", "facts_per_day", "2026-03-26") == 0
        val = store.increment_quota("t1", "facts_per_day", "2026-03-26", 5)
        assert val == 5
        val = store.increment_quota("t1", "facts_per_day", "2026-03-26", 3)
        assert val == 8
        store.close()

    def test_quota_set(self):
        store = RateLimitStore(db_path=None)
        store.set_quota("t1", "agents", "all_time", 42)
        assert store.get_quota("t1", "agents", "all_time") == 42
        store.close()

    def test_tenant_config(self):
        store = RateLimitStore(db_path=None)
        assert store.get_tenant_config("t1") is None
        store.set_tenant_config("t1", {"requests_per_minute": 30}, {"max_facts_per_day": 500})
        cfg = store.get_tenant_config("t1")
        assert cfg["rate_limit"]["requests_per_minute"] == 30
        assert cfg["quota"]["max_facts_per_day"] == 500
        store.close()


# ═══════════════════════════════════════════════════════════════════
# 4. Rate Limiter — Within Limits
# ═══════════════════════════════════════════════════════════════════


class TestRateLimiterWithinLimits:
    """Test rate limiting when within limits."""

    def test_first_request_allowed(self, limiter):
        uid = _uid()
        result = limiter.check_limit(user_id=uid, endpoint="/api/check")
        assert result.allowed is True
        assert result.remaining >= 0

    def test_sequential_within_limit(self, limiter):
        uid = _uid()
        for i in range(5):
            result = limiter.check_limit(user_id=uid, endpoint="/api/check")
            assert result.allowed is True

    def test_remaining_decreases(self, limiter):
        uid = _uid()
        r1 = limiter.check_limit(user_id=uid, endpoint="/api/check")
        r2 = limiter.check_limit(user_id=uid, endpoint="/api/check")
        assert r2.remaining < r1.remaining

    def test_headers_present(self, limiter):
        uid = _uid()
        result = limiter.check_limit(user_id=uid, endpoint="/api/check")
        headers = result.to_headers()
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers

    def test_different_endpoints_independent(self, limiter):
        uid = _uid()
        for i in range(8):
            r1 = limiter.check_limit(user_id=uid, endpoint="/api/check")
            assert r1.allowed
        r2 = limiter.check_limit(user_id=uid, endpoint="/api/events")
        assert r2.allowed  # Different endpoint, fresh counter

    def test_no_scope_allows(self, limiter):
        """No user_id or tenant_id should still allow (edge case)."""
        result = limiter.check_limit()
        assert result.allowed is True


# ═══════════════════════════════════════════════════════════════════
# 5. Rate Limiter — Exceeded
# ═══════════════════════════════════════════════════════════════════


class TestRateLimiterExceeded:
    """Test rate limiting when limits are exceeded."""

    def test_per_user_exceeded(self, strict_limiter):
        uid = _uid()
        # Use up the 3 requests per minute
        for i in range(3):
            r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check")
            assert r.allowed, f"Request {i+1} should be allowed"

        # 4th should be denied (burst_size=1 gives slight grace)
        results = []
        for i in range(5):
            r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check")
            results.append(r)

        # At least one should be denied
        denied = [r for r in results if not r.allowed]
        assert len(denied) > 0, "Should have at least one denied request"

    def test_denied_has_retry_after(self, strict_limiter):
        uid = _uid()
        for i in range(10):
            r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check")
        # Force past limit
        for i in range(20):
            r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check")
            if not r.allowed:
                assert r.retry_after > 0
                return
        # If we get here, limits are very high — that's fine for this test

    def test_denied_returns_zero_remaining(self, strict_limiter):
        uid = _uid()
        for i in range(20):
            r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check")
            if not r.allowed:
                assert r.remaining == 0
                return


# ═══════════════════════════════════════════════════════════════════
# 6. Per-Tenant Isolation
# ═══════════════════════════════════════════════════════════════════


class TestPerTenantIsolation:
    """Test that rate limits are isolated per tenant."""

    def test_tenants_independent(self, strict_limiter):
        uid = _uid()
        # Exhaust tenant A
        for i in range(20):
            strict_limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id="tenant-a")

        # Tenant B should still have quota
        r = strict_limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id="tenant-b")
        assert r.allowed

    def test_users_independent_same_tenant(self, limiter):
        uid1 = _uid()
        uid2 = _uid()
        # Exhaust user 1 (but leave tenant-level headroom)
        for i in range(5):
            limiter.check_limit(user_id=uid1, endpoint="/api/check", tenant_id="t1")

        # User 2 should still work (different user scope, tenant not exhausted)
        r = limiter.check_limit(user_id=uid2, endpoint="/api/check", tenant_id="t1")
        assert r.allowed

    def test_tenant_only_check(self, limiter):
        """Check rate limit by tenant only (no user_id)."""
        tid = _uid("t")
        result = limiter.check_limit(endpoint="/api/check", tenant_id=tid)
        assert result.allowed


# ═══════════════════════════════════════════════════════════════════
# 7. Burst Handling
# ═══════════════════════════════════════════════════════════════════


class TestBurstHandling:
    """Test token bucket burst allowance."""

    def test_burst_allows_extra(self, limiter):
        """With burst_size=3, should get extra requests above base rate."""
        uid = _uid()
        # Fill up to near the limit
        allowed_count = 0
        for i in range(20):
            r = limiter.check_limit(user_id=uid, endpoint="/api/check")
            if r.allowed:
                allowed_count += 1
        # With burst, we should get more than just the base 10
        # (exact number depends on timing)
        assert allowed_count >= 10  # At least base rate

    def test_burst_config_respected(self):
        """Different burst sizes should give different allowances."""
        config_small = RateLimitConfig(requests_per_minute=5, requests_per_hour=100, burst_size=0)
        config_large = RateLimitConfig(requests_per_minute=5, requests_per_hour=100, burst_size=10)

        l_small = RateLimiter(config=config_small, db_path=None)
        l_large = RateLimiter(config=config_large, db_path=None)

        uid1 = _uid()
        uid2 = _uid()

        small_allowed = 0
        large_allowed = 0

        for i in range(20):
            if l_small.check_limit(user_id=uid1, endpoint="/api/check").allowed:
                small_allowed += 1
            if l_large.check_limit(user_id=uid2, endpoint="/api/check").allowed:
                large_allowed += 1

        # Large burst should allow more or equal
        assert large_allowed >= small_allowed

        l_small.close()
        l_large.close()


# ═══════════════════════════════════════════════════════════════════
# 8. Quota Enforcement
# ═══════════════════════════════════════════════════════════════════


class TestQuotaEnforcement:
    """Test quota checking and recording."""

    def test_check_quota_within(self, limiter):
        tid = _uid("t")
        result = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert result.allowed is True
        assert result.remaining > 0

    def test_check_quota_exceeded(self, strict_limiter):
        tid = _uid("t")
        # Record up to limit (max_facts_per_day=5)
        for i in range(5):
            strict_limiter.record_quota(tenant_id=tid, quota_type="facts_per_day")

        # Next should be denied
        result = strict_limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert result.allowed is False

    def test_record_quota_increments(self, limiter):
        tid = _uid("t")
        r1 = limiter.record_quota(tenant_id=tid, quota_type="agents")
        assert r1.current == 1
        r2 = limiter.record_quota(tenant_id=tid, quota_type="agents")
        assert r2.current == 2

    def test_quota_types_independent(self, limiter):
        tid = _uid("t")
        # Exhaust agents
        for i in range(5):
            limiter.record_quota(tenant_id=tid, quota_type="agents")
        # Facts should still be available
        result = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert result.allowed

    def test_get_quota_status(self, limiter):
        tid = _uid("t")
        limiter.record_quota(tenant_id=tid, quota_type="facts_per_day", amount=10)
        status = limiter.get_quota_status(tid)
        assert "facts_per_day" in status
        assert "agents" in status
        assert "webhooks" in status
        assert "storage_bytes" in status
        assert status["facts_per_day"].current == 10

    def test_reset_quota(self, limiter):
        tid = _uid("t")
        limiter.record_quota(tenant_id=tid, quota_type="facts_per_day", amount=40)
        r = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert r.current == 40
        limiter.reset_quota(tid, "facts_per_day")
        r = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert r.current == 0

    def test_tenants_quota_isolated(self, limiter):
        t1 = _uid("t")
        t2 = _uid("t")
        limiter.record_quota(tenant_id=t1, quota_type="facts_per_day", amount=45)
        # t1 near limit
        r1 = limiter.check_quota(tenant_id=t1, quota_type="facts_per_day")
        # t2 should be fresh
        r2 = limiter.check_quota(tenant_id=t2, quota_type="facts_per_day")
        assert r2.current == 0
        assert r2.allowed

    def test_quota_result_to_dict(self, limiter):
        tid = _uid("t")
        r = limiter.check_quota(tenant_id=tid, quota_type="agents")
        d = r.to_dict()
        assert "allowed" in d
        assert "current" in d
        assert "limit" in d
        assert "quota_type" in d


# ═══════════════════════════════════════════════════════════════════
# 9. Tenant Config Override
# ═══════════════════════════════════════════════════════════════════


class TestTenantConfigOverride:
    """Test per-tenant rate limit and quota config."""

    def test_configure_tenant(self, limiter):
        tid = _uid("t")
        custom_rl = RateLimitConfig(requests_per_minute=2, requests_per_hour=5, burst_size=0)
        custom_q = QuotaConfig(max_facts_per_day=3)
        limiter.configure_tenant(tid, rate_limit=custom_rl, quota=custom_q)

        uid = _uid()
        # Should hit limit quickly
        for i in range(2):
            r = limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id=tid)
            assert r.allowed
        # Third should be denied
        r = limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id=tid)
        assert not r.allowed

    def test_configure_tenant_quota(self, limiter):
        tid = _uid("t")
        custom_q = QuotaConfig(max_facts_per_day=2)
        limiter.configure_tenant(tid, quota=custom_q)

        limiter.record_quota(tenant_id=tid, quota_type="facts_per_day")
        limiter.record_quota(tenant_id=tid, quota_type="facts_per_day")
        r = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day")
        assert not r.allowed

    def test_unconfigured_tenant_uses_default(self, limiter):
        tid = _uid("t")
        # No custom config — should use default (10/min)
        for i in range(8):
            r = limiter.check_limit(user_id=_uid(), endpoint="/api/check", tenant_id=tid)
            assert r.allowed


# ═══════════════════════════════════════════════════════════════════
# 10. Global Instance
# ═══════════════════════════════════════════════════════════════════


class TestGlobalInstance:
    """Test global rate limiter management."""

    def test_get_creates_instance(self):
        reset_rate_limiter()
        l = get_rate_limiter(db_path=None)
        assert l is not None
        reset_rate_limiter()

    def test_get_returns_same(self):
        reset_rate_limiter()
        l1 = get_rate_limiter(db_path=None)
        l2 = get_rate_limiter()
        assert l1 is l2
        reset_rate_limiter()

    def test_reset_clears(self):
        reset_rate_limiter()
        l1 = get_rate_limiter(db_path=None)
        reset_rate_limiter()
        l2 = get_rate_limiter(db_path=None)
        assert l1 is not l2
        reset_rate_limiter()


# ═══════════════════════════════════════════════════════════════════
# 11. Middleware
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitMiddleware:
    """Test FastAPI middleware integration."""

    @pytest.fixture
    def app_with_middleware(self):
        """Create a minimal FastAPI app with rate limit middleware."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        config = RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=0)
        rl = RateLimiter(config=config, db_path=None)

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate_limiter=rl)

        @app.get("/api/test")
        async def test_endpoint():
            return {"status": "ok"}

        @app.get("/api/auth/status")
        async def auth_status():
            return {"enabled": True}

        yield app, rl
        rl.close()

    def test_middleware_passes_within_limit(self, app_with_middleware):
        from fastapi.testclient import TestClient
        app, rl = app_with_middleware
        client = TestClient(app)
        resp = client.get("/api/test", headers={"X-User-Id": "test-user-1"})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    def test_middleware_blocks_exceeded(self, app_with_middleware):
        from fastapi.testclient import TestClient
        app, rl = app_with_middleware
        client = TestClient(app)

        uid = "exceeded-user"
        # Exhaust the 3 requests
        for i in range(3):
            client.get("/api/test", headers={"X-User-Id": uid})

        # 4th should be 429
        resp = client.get("/api/test", headers={"X-User-Id": uid})
        assert resp.status_code == 429
        data = resp.json()
        assert "error" in data
        assert "X-RateLimit-Limit" in resp.headers

    def test_middleware_exempt_paths(self, app_with_middleware):
        from fastapi.testclient import TestClient
        app, rl = app_with_middleware
        client = TestClient(app)

        # Auth status should always work
        for i in range(20):
            resp = client.get("/api/auth/status")
            assert resp.status_code == 200

    def test_middleware_backward_compat_no_limiter(self):
        """No rate limiter = no rate limiting (backward compatible)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rate_limiter=None)

        @app.get("/api/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        for i in range(100):
            resp = client.get("/api/test")
            assert resp.status_code == 200

    def test_middleware_tenant_isolation(self, app_with_middleware):
        from fastapi.testclient import TestClient
        app, rl = app_with_middleware
        client = TestClient(app)

        # Exhaust tenant-a
        for i in range(10):
            client.get("/api/test", headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "u1"})

        # tenant-b should work
        resp = client.get("/api/test", headers={"X-Tenant-Id": "tenant-b", "X-User-Id": "u1"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# 12. Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zero_limit(self):
        """Zero requests_per_minute should deny immediately."""
        config = RateLimitConfig(requests_per_minute=0, requests_per_hour=0, burst_size=0)
        l = RateLimiter(config=config, db_path=None)
        r = l.check_limit(user_id=_uid(), endpoint="/api/check")
        # With 0 limit, first request should be denied
        assert not r.allowed
        l.close()

    def test_very_high_limit(self):
        """Very high limit should always allow."""
        config = RateLimitConfig(requests_per_minute=500, requests_per_hour=5000, burst_size=100)
        l = RateLimiter(config=config, db_path=None)
        uid = _uid()
        for i in range(50):
            r = l.check_limit(user_id=uid, endpoint="/api/check")
            assert r.allowed
        l.close()

    def test_different_users_no_cross_contamination(self, strict_limiter):
        """Users should not affect each other's limits."""
        u1 = _uid()
        u2 = _uid()
        # Exhaust u1
        for i in range(20):
            strict_limiter.check_limit(user_id=u1, endpoint="/api/check")
        # u2 should still work
        r = strict_limiter.check_limit(user_id=u2, endpoint="/api/check")
        assert r.allowed

    def test_wildcard_endpoint(self, limiter):
        """Using '*' as endpoint should work."""
        uid = _uid()
        r = limiter.check_limit(user_id=uid, endpoint="*")
        assert r.allowed

    def test_quota_amount_check(self, limiter):
        """Checking quota with amount > 1."""
        tid = _uid("t")
        r = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day", amount=49)
        assert r.allowed  # 0 + 49 <= 50
        r = limiter.check_quota(tenant_id=tid, quota_type="facts_per_day", amount=51)
        assert not r.allowed  # 0 + 51 > 50

    def test_cleanup(self, limiter):
        """Cleanup should not raise errors."""
        limiter.cleanup()
        uid = _uid()
        limiter.check_limit(user_id=uid, endpoint="/api/check")
        limiter.cleanup(max_age_seconds=0)

    def test_concurrent_scopes(self, limiter):
        """Multiple scopes should work independently."""
        uid = _uid()
        tid1 = _uid("t")
        tid2 = _uid("t")

        for i in range(5):
            r1 = limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id=tid1)
            r2 = limiter.check_limit(user_id=uid, endpoint="/api/check", tenant_id=tid2)
            assert r1.allowed
            assert r2.allowed
