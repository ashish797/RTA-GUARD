"""
RTA-GUARD — Multi-tenant Isolation Tests (Phase 4.1)

Tests tenant lifecycle, data isolation, backward compatibility,
and integration with all Brahmanda modules.
"""
import os
import json
import shutil
import sqlite3
import tempfile
import pytest
from pathlib import Path

from brahmanda.tenancy import (
    TenantContext,
    TenantManager,
    validate_tenant_id,
    get_legacy_context,
    get_tenant_manager,
    reset_tenant_manager,
    _RESERVED_IDS,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def tmp_data_dir():
    """Create a temporary data directory for testing."""
    d = tempfile.mkdtemp(prefix="rta_test_tenant_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tenant_mgr(tmp_data_dir):
    """Create a TenantManager with a temp data directory."""
    reset_tenant_manager()
    return TenantManager(base_data_dir=tmp_data_dir)


# ─── Tenant ID Validation ─────────────────────────────────────────


class TestTenantIdValidation:
    """Tests for tenant ID validation."""

    def test_valid_ids(self):
        for tid in ["acme-corp", "tenant_001", "ABC123", "my-org-42"]:
            validate_tenant_id(tid)  # Should not raise

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            validate_tenant_id("")

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="non-empty"):
            validate_tenant_id(None)

    def test_rejects_reserved_ids(self):
        for reserved in _RESERVED_IDS:
            with pytest.raises(ValueError, match="reserved"):
                validate_tenant_id(reserved)

    def test_rejects_path_traversal(self):
        for bad in ["../etc", "foo/../../bar", "tenant\\name", "a..b"]:
            with pytest.raises(ValueError):
                validate_tenant_id(bad)

    def test_rejects_short(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_tenant_id("ab")

    def test_rejects_special_chars(self):
        for bad in ["tenant@name", "tenant.name", "tenant name", "tenant/name"]:
            with pytest.raises(ValueError):
                validate_tenant_id(bad)

    def test_rejects_starting_with_hyphen(self):
        with pytest.raises(ValueError):
            validate_tenant_id("-abc")


# ─── Tenant Context ───────────────────────────────────────────────


class TestTenantContext:
    """Tests for TenantContext dataclass."""

    def test_db_paths(self, tmp_data_dir):
        tenant_dir = os.path.join(tmp_data_dir, "tenants", "acme")
        os.makedirs(tenant_dir, exist_ok=True)
        ctx = TenantContext(
            tenant_id="acme",
            tenant_dir=tenant_dir,
        )
        assert ctx.conscience_db_path.endswith("conscience.db")
        assert ctx.attribution_db_path.endswith("attribution.db")
        assert "acme" in ctx.conscience_db_path

    def test_get_db_path(self, tmp_data_dir):
        tenant_dir = os.path.join(tmp_data_dir, "tenants", "acme")
        os.makedirs(tenant_dir, exist_ok=True)
        ctx = TenantContext(tenant_id="acme", tenant_dir=tenant_dir)
        for mod in ("conscience", "attribution", "user_monitor", "temporal"):
            path = ctx.get_db_path(mod)
            assert path.endswith(f"{mod}.db")

    def test_get_db_path_unknown_module(self, tmp_data_dir):
        tenant_dir = os.path.join(tmp_data_dir, "tenants", "acme")
        os.makedirs(tenant_dir, exist_ok=True)
        ctx = TenantContext(tenant_id="acme", tenant_dir=tenant_dir)
        with pytest.raises(ValueError, match="Unknown module"):
            ctx.get_db_path("nonexistent")

    def test_to_dict(self, tmp_data_dir):
        tenant_dir = os.path.join(tmp_data_dir, "tenants", "acme")
        os.makedirs(tenant_dir, exist_ok=True)
        ctx = TenantContext(tenant_id="acme", name="Acme Corp", tenant_dir=tenant_dir)
        d = ctx.to_dict()
        assert d["tenant_id"] == "acme"
        assert d["name"] == "Acme Corp"


# ─── Tenant Manager Lifecycle ─────────────────────────────────────


class TestTenantManagerLifecycle:
    """Tests for creating, listing, getting, and deleting tenants."""

    def test_create_tenant(self, tenant_mgr):
        ctx = tenant_mgr.create_tenant("acme-corp", name="Acme Corporation")
        assert ctx.tenant_id == "acme-corp"
        assert ctx.name == "Acme Corporation"
        assert os.path.isdir(ctx.tenant_dir)

    def test_create_tenant_dedup(self, tenant_mgr):
        tenant_mgr.create_tenant("acme")
        with pytest.raises(ValueError, match="already exists"):
            tenant_mgr.create_tenant("acme")

    def test_list_tenants_empty(self, tenant_mgr):
        assert tenant_mgr.list_tenants() == []

    def test_list_tenants(self, tenant_mgr):
        tenant_mgr.create_tenant("acme")
        tenant_mgr.create_tenant("globex")
        tenants = tenant_mgr.list_tenants()
        assert len(tenants) == 2
        ids = {t["tenant_id"] for t in tenants}
        assert ids == {"acme", "globex"}

    def test_get_tenant(self, tenant_mgr):
        tenant_mgr.create_tenant("acme")
        ctx = tenant_mgr.get_tenant("acme")
        assert ctx.tenant_id == "acme"

    def test_get_tenant_not_found(self, tenant_mgr):
        with pytest.raises(ValueError, match="not found"):
            tenant_mgr.get_tenant("nonexistent")

    def test_delete_tenant(self, tenant_mgr):
        ctx = tenant_mgr.create_tenant("acme")
        tenant_dir = ctx.tenant_dir
        assert os.path.isdir(tenant_dir)
        tenant_mgr.delete_tenant("acme")
        assert not os.path.exists(tenant_dir)
        assert not tenant_mgr.tenant_exists("acme")

    def test_delete_tenant_not_found(self, tenant_mgr):
        with pytest.raises(ValueError, match="not found"):
            tenant_mgr.delete_tenant("nonexistent")

    def test_get_or_create_new(self, tenant_mgr):
        ctx = tenant_mgr.get_or_create_tenant("acme", name="Acme")
        assert ctx.tenant_id == "acme"

    def test_get_or_create_existing(self, tenant_mgr):
        tenant_mgr.create_tenant("acme", name="Original")
        ctx = tenant_mgr.get_or_create_tenant("acme", name="Ignored")
        assert ctx.name == "Original"

    def test_tenant_exists(self, tenant_mgr):
        assert not tenant_mgr.tenant_exists("acme")
        tenant_mgr.create_tenant("acme")
        assert tenant_mgr.tenant_exists("acme")


# ─── Isolated Database Files ──────────────────────────────────────


class TestIsolatedDatabases:
    """Tests that each tenant gets separate database files."""

    def test_creates_separate_dbs(self, tenant_mgr):
        ctx = tenant_mgr.create_tenant("acme")
        # Manually create a SQLite table in each DB
        for mod in ("conscience", "attribution", "user_monitor", "temporal"):
            db_path = ctx.get_db_path(mod)
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()
            conn.close()

        # Verify each DB exists and has the test table
        for mod in ("conscience", "attribution", "user_monitor", "temporal"):
            db_path = ctx.get_db_path(mod)
            assert os.path.exists(db_path)
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT COUNT(*) FROM test").fetchone()
            assert row[0] == 1
            conn.close()

    def test_tenant_isolation(self, tenant_mgr):
        """Facts in tenant A don't appear in tenant B."""
        ctx_a = tenant_mgr.create_tenant("tenant-a")
        ctx_b = tenant_mgr.create_tenant("tenant-b")

        # Write data to tenant-a's DB
        conn_a = sqlite3.connect(ctx_a.conscience_db_path)
        conn_a.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, value TEXT)")
        conn_a.execute("INSERT INTO facts VALUES ('f1', 'secret_a')")
        conn_a.commit()
        conn_a.close()

        # Verify tenant-b doesn't see tenant-a's data
        conn_b = sqlite3.connect(ctx_b.conscience_db_path)
        conn_b.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, value TEXT)")
        conn_b.commit()
        row = conn_b.execute("SELECT COUNT(*) FROM facts").fetchone()
        assert row[0] == 0
        conn_b.close()

    def test_delete_cleans_up_files(self, tenant_mgr):
        ctx = tenant_mgr.create_tenant("doomed")
        # Create some DB files
        for mod in ("conscience", "attribution"):
            conn = sqlite3.connect(ctx.get_db_path(mod))
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.commit()
            conn.close()

        tenant_dir = ctx.tenant_dir
        assert os.path.exists(tenant_dir)
        tenant_mgr.delete_tenant("doomed")
        assert not os.path.exists(tenant_dir)


# ─── Backward Compatibility ───────────────────────────────────────


class TestBackwardCompatibility:
    """Tests for single-tenant / legacy mode."""

    def test_legacy_context_is_none(self):
        assert get_legacy_context() is None

    def test_conscience_default_without_tenant(self, tmp_data_dir):
        """ConscienceMonitor without tenant_context uses legacy path."""
        from brahmanda.conscience import ConscienceMonitor
        db_path = os.path.join(tmp_data_dir, "legacy", "conscience.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        monitor = ConscienceMonitor(db_path=db_path, in_memory=False)
        assert monitor._db_path == db_path
        assert monitor._tenant_context is None

    def test_conscience_in_memory_ignores_tenant(self):
        """in_memory=True should still take priority over tenant_context."""
        from brahmanda.conscience import ConscienceMonitor
        ctx = TenantContext(tenant_id="test", tenant_dir="/tmp/test")
        monitor = ConscienceMonitor(in_memory=True, tenant_context=ctx)
        assert monitor._db_path == ":memory:"

    def test_conscience_with_tenant_context(self, tenant_mgr):
        """ConscienceMonitor with tenant_context uses tenant DB."""
        from brahmanda.conscience import ConscienceMonitor
        ctx = tenant_mgr.create_tenant("acme")
        monitor = ConscienceMonitor(tenant_context=ctx)
        assert "acme" in monitor._db_path
        assert monitor._db_path == ctx.conscience_db_path

    def test_attribution_default_without_tenant(self):
        """AttributionManager without tenant_context uses None db_path (in-memory)."""
        from brahmanda.attribution import AttributionManager
        attr = AttributionManager()
        assert attr._tenant_context is None
        assert attr.registry._db_path is None

    def test_attribution_with_tenant_context(self, tenant_mgr):
        """AttributionManager with tenant_context uses tenant DB."""
        from brahmanda.attribution import AttributionManager
        ctx = tenant_mgr.create_tenant("acme")
        attr = AttributionManager(tenant_context=ctx)
        assert attr._tenant_context is ctx
        assert attr.registry._db_path == ctx.attribution_db_path


# ─── ConscienceMonitor Tenant Integration ─────────────────────────


class TestConscienceMonitorTenantIsolation:
    """Tests that ConscienceMonitor respects tenant isolation."""

    def test_separate_agent_profiles(self, tenant_mgr):
        """Agents in tenant A don't appear in tenant B's monitor."""
        from brahmanda.conscience import ConscienceMonitor

        ctx_a = tenant_mgr.create_tenant("tenant-a")
        ctx_b = tenant_mgr.create_tenant("tenant-b")

        monitor_a = ConscienceMonitor(tenant_context=ctx_a)
        monitor_b = ConscienceMonitor(tenant_context=ctx_b)

        # Register agent in tenant A
        monitor_a.register_agent("agent-001")
        agents_a = monitor_a.list_agents()
        assert len(agents_a) == 1
        assert agents_a[0]["agent_id"] == "agent-001"

        # Tenant B should not see agent-001
        agents_b = monitor_b.list_agents()
        assert len(agents_b) == 0

    def test_separate_session_profiles(self, tenant_mgr):
        """Sessions in tenant A don't appear in tenant B."""
        from brahmanda.conscience import ConscienceMonitor

        ctx_a = tenant_mgr.create_tenant("tenant-a")
        ctx_b = tenant_mgr.create_tenant("tenant-b")

        monitor_a = ConscienceMonitor(tenant_context=ctx_a)
        monitor_b = ConscienceMonitor(tenant_context=ctx_b)

        monitor_a.register_agent("agent-001")
        # Record interaction in tenant A
        from brahmanda.models import VerifyResult, VerifyDecision
        result = VerifyResult(decision=VerifyDecision.PASS, overall_confidence=0.9)
        monitor_a.record_interaction("agent-001", "sess-001", result)

        sessions_a = monitor_a.list_sessions()
        sessions_b = monitor_b.list_sessions()

        assert len(sessions_a) >= 1
        assert len(sessions_b) == 0


# ─── AttributionManager Tenant Isolation ──────────────────────────


class TestAttributionTenantIsolation:
    """Tests that AttributionManager respects tenant isolation."""

    def test_separate_sources(self, tenant_mgr):
        """Sources in tenant A don't appear in tenant B."""
        from brahmanda.attribution import AttributionManager
        from brahmanda.models import SourceAuthority

        ctx_a = tenant_mgr.create_tenant("tenant-a")
        ctx_b = tenant_mgr.create_tenant("tenant-b")

        attr_a = AttributionManager(tenant_context=ctx_a)
        attr_b = AttributionManager(tenant_context=ctx_b)

        # Register source in tenant A
        src_a = attr_a.register_source("WHO-A", SourceAuthority.PRIMARY, authority_score=0.98)
        sources_a = attr_a.registry.list_sources()
        assert len(sources_a) == 1

        # Tenant B should have no sources
        sources_b = attr_b.registry.list_sources()
        assert len(sources_b) == 0


# ─── TenantManager Global Instance ────────────────────────────────


class TestGlobalTenantManager:
    """Tests for the global tenant manager singleton."""

    def test_get_tenant_manager_creates_singleton(self, tmp_data_dir):
        reset_tenant_manager()
        mgr1 = get_tenant_manager(base_data_dir=tmp_data_dir)
        mgr2 = get_tenant_manager()
        assert mgr1 is mgr2
        reset_tenant_manager()

    def test_reset_tenant_manager(self, tmp_data_dir):
        reset_tenant_manager()
        mgr1 = get_tenant_manager(base_data_dir=tmp_data_dir)
        reset_tenant_manager()
        mgr2 = get_tenant_manager(base_data_dir=tmp_data_dir)
        assert mgr1 is not mgr2
        reset_tenant_manager()


# ─── Integration: Persistence Across Reloads ──────────────────────


class TestTenantPersistence:
    """Tests that tenant metadata persists across manager reloads."""

    def test_reload_existing_tenants(self, tmp_data_dir):
        """Created tenants are reloaded when manager restarts."""
        mgr1 = TenantManager(base_data_dir=tmp_data_dir)
        mgr1.create_tenant("acme", name="Acme Corp")
        mgr1.create_tenant("globex", name="Globex Inc")

        # Simulate restart
        mgr2 = TenantManager(base_data_dir=tmp_data_dir)
        assert mgr2.tenant_exists("acme")
        assert mgr2.tenant_exists("globex")
        ctx = mgr2.get_tenant("acme")
        assert ctx.name == "Acme Corp"

    def test_corrupted_metadata_skipped(self, tmp_data_dir):
        """Invalid metadata files are gracefully skipped."""
        tenants_dir = os.path.join(tmp_data_dir, "tenants")
        bad_dir = os.path.join(tenants_dir, "bad-tenant")
        os.makedirs(bad_dir, exist_ok=True)
        # Write invalid JSON
        with open(os.path.join(bad_dir, "tenant.json"), "w") as f:
            f.write("{invalid json")

        mgr = TenantManager(base_data_dir=tmp_data_dir)
        assert not mgr.tenant_exists("bad-tenant")


# ─── Dashboard Integration ────────────────────────────────────────


class TestDashboardTenantEndpoints:
    """Tests for tenant management API endpoints."""

    @pytest.fixture
    def client(self, tmp_data_dir):
        """Create a test client with tenant manager using temp dir."""
        import os
        from fastapi.testclient import TestClient

        # Patch the tenant manager before importing app
        reset_tenant_manager()
        test_mgr = TenantManager(base_data_dir=tmp_data_dir)

        # We need to patch the app's tenant_manager variable
        import dashboard.app as app_module
        original_mgr = app_module.tenant_manager
        app_module.tenant_manager = test_mgr

        # Disable auth for testing
        from dashboard.auth import init_auth, AuthConfig
        init_auth(AuthConfig(enabled=False))

        client = TestClient(app_module.app)
        yield client

        # Restore
        app_module.tenant_manager = original_mgr
        reset_tenant_manager()

    def test_create_tenant_endpoint(self, client):
        resp = client.post("/api/tenants", json={"tenant_id": "test-corp", "name": "Test Corp"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["tenant"]["tenant_id"] == "test-corp"

    def test_list_tenants_endpoint(self, client):
        client.post("/api/tenants", json={"tenant_id": "acme"})
        client.post("/api/tenants", json={"tenant_id": "globex"})
        resp = client.get("/api/tenants")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_get_tenant_endpoint(self, client):
        client.post("/api/tenants", json={"tenant_id": "acme"})
        resp = client.get("/api/tenants/acme")
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "acme"

    def test_get_tenant_not_found(self, client):
        resp = client.get("/api/tenants/nonexistent")
        assert resp.status_code == 404

    def test_delete_tenant_endpoint(self, client):
        client.post("/api/tenants", json={"tenant_id": "doomed"})
        resp = client.delete("/api/tenants/doomed")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_tenant_health_endpoint(self, client):
        client.post("/api/tenants", json={"tenant_id": "healthy"})
        resp = client.get("/api/tenants/healthy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "databases" in data
        assert "conscience" in data["databases"]

    def test_create_duplicate_tenant(self, client):
        client.post("/api/tenants", json={"tenant_id": "dup"})
        resp = client.post("/api/tenants", json={"tenant_id": "dup"})
        assert resp.status_code == 400

    def test_invalid_tenant_id(self, client):
        resp = client.post("/api/tenants", json={"tenant_id": "a!"})
        assert resp.status_code == 400


# ─── Auth Tenant Extraction ───────────────────────────────────────


class TestAuthTenantExtraction:
    """Tests for tenant extraction from auth headers."""

    def test_extract_from_header(self):
        from dashboard.auth import require_auth_with_tenant
        # This is async, but we can test the underlying functions
        from dashboard.auth import _decode_jwt_payload, _extract_tenant_from_payload
        payload = {"tenant_id": "acme", "sub": "user123"}
        assert _extract_tenant_from_payload(payload) == "acme"

    def test_extract_from_tid_claim(self):
        from dashboard.auth import _extract_tenant_from_payload
        payload = {"tid": "globex", "sub": "user123"}
        assert _extract_tenant_from_payload(payload) == "globex"

    def test_extract_from_org_id(self):
        from dashboard.auth import _extract_tenant_from_payload
        payload = {"org_id": "org-42"}
        assert _extract_tenant_from_payload(payload) == "org-42"

    def test_extract_returns_none_if_no_tenant(self):
        from dashboard.auth import _extract_tenant_from_payload
        payload = {"sub": "user123"}
        assert _extract_tenant_from_payload(payload) is None

    def test_decode_jwt_payload(self):
        from dashboard.auth import _decode_jwt_payload
        import base64
        # Create a minimal JWT (header.payload.signature)
        payload = {"tenant_id": "test", "sub": "user"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"eyJ.{payload_b64}.sig"
        result = _decode_jwt_payload(token)
        assert result is not None
        assert result["tenant_id"] == "test"

    def test_decode_invalid_jwt(self):
        from dashboard.auth import _decode_jwt_payload
        assert _decode_jwt_payload("not.a.jwt") is None  # Invalid base64
        assert _decode_jwt_payload("invalid") is None     # Not 3 parts
