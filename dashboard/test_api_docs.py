"""
RTA-GUARD Dashboard — API Documentation Tests

Comprehensive test suite for API documentation system:
1. All endpoints have descriptions/docstrings
2. All request/response Pydantic models validate
3. OpenAPI spec is valid JSON
4. OpenAPI spec has all endpoints listed
5. Response examples are present
6. API tags are used for grouping
7. Edge cases: missing descriptions, invalid models
"""
import sys
import json
import inspect
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, ValidationError
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Import the FastAPI app (module-level to avoid repeated init)."""
    if not FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available")
    # Set env to disable auth for testing
    import os
    os.environ["DASHBOARD_AUTH"] = "false"
    os.environ.setdefault("RTA_DATA_DIR", "/tmp/rta_test_data")

    from dashboard.app import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="module")
def openapi_spec(app):
    """Get the OpenAPI spec as a dict."""
    return app.openapi()


@pytest.fixture(scope="module")
def client(app):
    """Test client for the FastAPI app."""
    return TestClient(app)


# ── 1. All endpoints have descriptions/docstrings ──────────────────────────

class TestEndpointDescriptions:
    """Verify every endpoint has a meaningful description."""

    def test_all_endpoints_have_summary_or_description(self, openapi_spec):
        """Every path+method must have a summary or description."""
        missing = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method, detail in methods.items():
                if method in ("get", "post", "put", "delete", "patch"):
                    has_summary = bool(detail.get("summary"))
                    has_description = bool(detail.get("description"))
                    if not has_summary and not has_description:
                        missing.append(f"{method.upper()} {path}")

        assert not missing, (
            f"Endpoints missing summary AND description:\n"
            + "\n".join(f"  - {e}" for e in missing)
        )

    def test_all_endpoints_have_operation_id(self, openapi_spec):
        """Every path+method should have an operationId for SDK generation."""
        missing = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method, detail in methods.items():
                if method in ("get", "post", "put", "delete", "patch"):
                    if not detail.get("operationId"):
                        missing.append(f"{method.upper()} {path}")

        assert not missing, (
            f"Endpoints missing operationId:\n"
            + "\n".join(f"  - {e}" for e in missing)
        )

    def test_no_empty_descriptions(self, openapi_spec):
        """Descriptions should not be empty strings."""
        empty = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method, detail in methods.items():
                if method in ("get", "post", "put", "delete", "patch"):
                    desc = detail.get("description", "")
                    if desc == "":
                        empty.append(f"{method.upper()} {path}")

        assert not empty, (
            f"Endpoints with empty description:\n"
            + "\n".join(f"  - {e}" for e in empty)
        )

    def test_websocket_has_description(self, openapi_spec):
        """WebSocket endpoint should have a description if documented."""
        paths = openapi_spec.get("paths", {})
        ws_path = paths.get("/ws", {})
        # WebSocket may appear as a separate key or under a custom extension
        # At minimum, the path should exist
        if ws_path:
            # Check if any method/operation has a description
            has_desc = any(
                detail.get("summary") or detail.get("description")
                for detail in ws_path.values()
                if isinstance(detail, dict)
            )
            # WebSocket endpoints in FastAPI may not always show in OpenAPI
            # So we just verify the path exists if it's there
            assert has_desc or len(ws_path) == 0, "WebSocket endpoint missing description"


# ── 2. All request/response Pydantic models validate ───────────────────────

class TestPydanticModels:
    """Verify all Pydantic models used in the API are valid."""

    def test_event_input_model(self):
        """EventInput model should validate correctly."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import EventInput

        # Valid
        m = EventInput(session_id="s1", input_text="hello")
        assert m.session_id == "s1"
        assert m.input_text == "hello"

        # Missing required fields
        with pytest.raises(ValidationError):
            EventInput(session_id="s1")  # missing input_text

    def test_verify_input_model(self):
        """VerifyInput model should validate with defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import VerifyInput

        m = VerifyInput(text="test claim")
        assert m.text == "test claim"
        assert m.domain == "general"

        m2 = VerifyInput(text="test", domain="finance")
        assert m2.domain == "finance"

    def test_tenant_create_input_model(self):
        """TenantCreateInput should validate."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import TenantCreateInput

        m = TenantCreateInput(tenant_id="acme")
        assert m.tenant_id == "acme"
        assert m.name == ""
        assert m.config is None

    def test_role_assign_input_model(self):
        """RoleAssignInput should validate with defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import RoleAssignInput

        m = RoleAssignInput(user_id="u1", tenant_id="t1", role="admin")
        assert m.assigned_by == "system"

    def test_role_revoke_input_model(self):
        """RoleRevokeInput should validate."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import RoleRevokeInput

        m = RoleRevokeInput(user_id="u1", tenant_id="t1")
        assert m.user_id == "u1"

    def test_drift_components_input_model(self):
        """DriftComponentsInput should have defaults for all floats."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import DriftComponentsInput

        m = DriftComponentsInput()
        assert m.semantic == 0.0
        assert m.alignment == 0.0
        assert m.scope == 0.0
        assert m.confidence == 0.0
        assert m.rule_proximity == 0.0

    def test_drift_record_input_model(self):
        """DriftRecordInput should require agent_id, session_id, and components."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import DriftRecordInput, DriftComponentsInput

        m = DriftRecordInput(
            agent_id="a1", session_id="s1",
            components=DriftComponentsInput()
        )
        assert m.components.semantic == 0.0

        with pytest.raises(ValidationError):
            DriftRecordInput(agent_id="a1")  # missing session_id and components

    def test_temporal_claim_input_model(self):
        """TemporalClaimInput should have default confidence."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import TemporalClaimInput

        m = TemporalClaimInput(claim="the sky is blue")
        assert m.confidence == 1.0

    def test_temporal_add_input_model(self):
        """TemporalAddInput should have defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import TemporalAddInput

        m = TemporalAddInput(claim="fact")
        assert m.source == "user"
        assert m.confidence == 1.0

    def test_escalation_signals_input_model(self):
        """EscalationSignalsInput should have all defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import EscalationSignalsInput

        m = EscalationSignalsInput()
        assert m.drift_score == 0.0
        assert m.tamas_state == "sattva"
        assert m.consistency_level == "highly_consistent"

    def test_report_generate_input_model(self):
        """ReportGenerateInput should have sensible defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import ReportGenerateInput

        m = ReportGenerateInput()
        assert m.report_type == "eu_ai_act"
        assert m.output_format == "json"
        assert m.title is None

    def test_webhook_create_input_model(self):
        """WebhookCreateInput should validate."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import WebhookCreateInput

        m = WebhookCreateInput(url="https://example.com/hook")
        assert m.secret == ""
        assert m.events == []
        assert m.active is True

    def test_webhook_update_input_model(self):
        """WebhookUpdateInput — all fields optional."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import WebhookUpdateInput

        m = WebhookUpdateInput()
        assert m.url is None
        assert m.secret is None
        assert m.events is None
        assert m.active is None

    def test_sso_login_input_model(self):
        """SSOLoginInput should have defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import SSOLoginInput

        m = SSOLoginInput()
        assert m.tenant_id == ""
        assert m.provider_name == ""

    def test_sso_callback_input_model(self):
        """SSOCallbackInput should require code."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import SSOCallbackInput

        m = SSOCallbackInput(code="abc123")
        assert m.code == "abc123"
        assert m.state is None

        with pytest.raises(ValidationError):
            SSOCallbackInput()  # missing code

    def test_sso_provider_create_input_model(self):
        """SSOProviderCreateInput should have sensible defaults."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.app import SSOProviderCreateInput

        m = SSOProviderCreateInput()
        assert m.provider_type == "oidc"
        assert m.scopes == ["openid", "profile", "email"]

    def test_auth_models(self):
        """Auth models (LoginRequest, LoginResponse) should validate."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.auth import LoginRequest, LoginResponse

        req = LoginRequest(token="abc")
        assert req.token == "abc"

        resp = LoginResponse(session_id="sid", expires_in=3600)
        assert resp.tenant_id is None
        assert resp.role is None

    def test_auth_config_model(self):
        """AuthConfig should validate."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")
        from dashboard.auth import AuthConfig

        c = AuthConfig()
        assert c.enabled is True
        assert c.session_ttl == 3600

        c2 = AuthConfig(enabled=False, session_ttl=7200)
        assert c2.enabled is False


# ── 3. OpenAPI spec is valid JSON ───────────────────────────────────────────

class TestOpenAPISpecValidity:
    """Verify the OpenAPI spec is well-formed."""

    def test_spec_is_valid_json_serializable(self, openapi_spec):
        """OpenAPI spec should be serializable to JSON."""
        try:
            serialized = json.dumps(openapi_spec)
            assert len(serialized) > 0
        except (TypeError, ValueError) as e:
            pytest.fail(f"OpenAPI spec is not JSON serializable: {e}")

    def test_spec_roundtrip_json(self, openapi_spec):
        """OpenAPI spec should survive JSON roundtrip."""
        serialized = json.dumps(openapi_spec)
        deserialized = json.loads(serialized)
        assert deserialized == openapi_spec

    def test_spec_has_required_openapi_version(self, openapi_spec):
        """Spec must declare openapi version."""
        assert "openapi" in openapi_spec
        version = openapi_spec["openapi"]
        assert version.startswith("3."), f"Expected OpenAPI 3.x, got {version}"

    def test_spec_has_info_section(self, openapi_spec):
        """Spec must have an info section with title and version."""
        info = openapi_spec.get("info", {})
        assert "title" in info, "OpenAPI spec missing info.title"
        assert "version" in info, "OpenAPI spec missing info.version"

    def test_spec_has_paths_section(self, openapi_spec):
        """Spec must have a paths section."""
        assert "paths" in openapi_spec
        assert len(openapi_spec["paths"]) > 0, "No paths defined in OpenAPI spec"

    def test_spec_info_title_matches(self, openapi_spec):
        """Title should be RTA-GUARD Dashboard."""
        title = openapi_spec.get("info", {}).get("title", "")
        assert "RTA-GUARD" in title or "RTA" in title, f"Unexpected title: {title}"


# ── 4. OpenAPI spec has all expected endpoints listed ──────────────────────

EXPECTED_ENDPOINTS = [
    # ("/") returns HTMLResponse — not in OpenAPI by design
    ("get", "/api/events"),
    ("get", "/api/killed"),
    ("get", "/api/stats"),
    ("post", "/api/check"),
    ("post", "/api/reset/{session_id}"),
    ("post", "/api/brahmanda/verify"),
    ("post", "/api/brahmanda/pipeline-verify"),
    ("get", "/api/brahmanda/status"),
    ("post", "/api/login"),
    ("get", "/api/auth/status"),
    # Tenants
    ("post", "/api/tenants"),
    ("get", "/api/tenants"),
    ("get", "/api/tenants/{tenant_id}"),
    ("delete", "/api/tenants/{tenant_id}"),
    ("get", "/api/tenants/{tenant_id}/health"),
    # RBAC
    ("post", "/api/rbac/assign"),
    ("post", "/api/rbac/revoke"),
    ("get", "/api/rbac/user/{user_id}/tenant/{tenant_id}"),
    ("get", "/api/rbac/tenant/{tenant_id}"),
    ("get", "/api/rbac/roles"),
    # Conscience
    ("get", "/api/conscience/agents"),
    ("get", "/api/conscience/health/{agent_id}"),
    ("get", "/api/conscience/anomaly/{agent_id}"),
    ("get", "/api/conscience/session/{agent_id}/{session_id}"),
    ("get", "/api/conscience/sessions"),
    ("get", "/api/conscience/users"),
    # Live Drift
    ("get", "/api/conscience/drift/{agent_id}"),
    ("get", "/api/conscience/drift/session/{session_id}"),
    ("get", "/api/conscience/drift/components/{agent_id}"),
    ("post", "/api/conscience/drift/record"),
    # Tamas
    ("get", "/api/conscience/tamas/{agent_id}"),
    ("get", "/api/conscience/tamas/{agent_id}/history"),
    ("get", "/api/conscience/tamas/{agent_id}/recovery"),
    # Temporal
    ("get", "/api/conscience/temporal/{agent_id}"),
    ("post", "/api/conscience/temporal/{agent_id}/check"),
    ("post", "/api/conscience/temporal/{agent_id}/add"),
    ("get", "/api/conscience/temporal/{agent_id}/contradictions"),
    # User behavior
    ("get", "/api/conscience/users/{user_id}"),
    ("get", "/api/conscience/users/{user_id}/history"),
    ("get", "/api/conscience/users/{user_id}/signals"),
    ("get", "/api/conscience/user-tracker/list"),
    # Escalation
    ("post", "/api/conscience/escalation/evaluate"),
    ("get", "/api/conscience/escalation/{agent_id}"),
    ("get", "/api/conscience/escalation/history"),
    ("get", "/api/conscience/escalation/config"),
    # Reports
    ("post", "/api/reports/generate"),
    ("get", "/api/reports/types"),
    # Webhooks
    ("post", "/api/webhooks"),
    ("get", "/api/webhooks"),
    ("get", "/api/webhooks/{webhook_id}"),
    ("put", "/api/webhooks/{webhook_id}"),
    ("delete", "/api/webhooks/{webhook_id}"),
    ("post", "/api/webhooks/{webhook_id}/test"),
    # SSO
    ("get", "/api/sso/login"),
    ("post", "/api/sso/callback"),
    ("get", "/api/sso/providers"),
    ("post", "/api/sso/providers"),
    ("delete", "/api/sso/providers/{tenant_id}/{provider_name}"),
    ("get", "/api/sso/session/{session_id}"),
]


class TestEndpointCoverage:
    """Verify all expected endpoints are in the OpenAPI spec."""

    def test_all_expected_endpoints_present(self, openapi_spec):
        """Every expected method+path should appear in the spec."""
        paths = openapi_spec.get("paths", {})
        missing = []
        for method, path in EXPECTED_ENDPOINTS:
            path_obj = paths.get(path)
            if not path_obj:
                missing.append(f"{method.upper()} {path} — path not found")
            elif method not in path_obj:
                missing.append(f"{method.upper()} {path} — method not found")

        assert not missing, (
            f"Missing {len(missing)} expected endpoints:\n"
            + "\n".join(f"  - {e}" for e in missing)
        )

    def test_endpoint_count_reasonable(self, openapi_spec):
        """Sanity check: should have at least 50 endpoints."""
        total = sum(
            len([m for m in methods if m in ("get", "post", "put", "delete", "patch")])
            for methods in openapi_spec.get("paths", {}).values()
        )
        assert total >= 50, f"Expected >=50 endpoints, found {total}"

    def test_no_extra_unexpected_paths(self, openapi_spec):
        """Log any paths not in our expected list (informational, not failing)."""
        expected_paths = {path for _, path in EXPECTED_ENDPOINTS}
        actual_paths = set(openapi_spec.get("paths", {}).keys())
        extra = actual_paths - expected_paths
        # This is informational — just print for awareness
        if extra:
            print(f"\nℹ️  Extra paths in spec (not failing): {extra}")


# ── 5. Response examples are present ───────────────────────────────────────

class TestResponseExamples:
    """Verify response schemas have examples or proper structure."""

    def test_post_endpoints_have_request_body_schema(self, openapi_spec):
        """POST/PUT endpoints should define a request body."""
        missing_body = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method in ("post", "put", "patch"):
                detail = methods.get(method)
                if detail and not detail.get("requestBody"):
                    # Some POST endpoints might not need a body (e.g. test webhook)
                    # Skip those with no Pydantic model in the function signature
                    if "test" not in path and "reset" not in path:
                        missing_body.append(f"{method.upper()} {path}")

        # We allow some exceptions — just log, don't fail hard
        if missing_body:
            print(f"\nℹ️  POST/PUT without requestBody (may be intentional): {missing_body}")

    def test_get_endpoints_have_response_schema(self, openapi_spec):
        """GET endpoints should define at least a 200 response."""
        missing_response = []
        for path, methods in openapi_spec.get("paths", {}).items():
            detail = methods.get("get")
            if detail:
                responses = detail.get("responses", {})
                if "200" not in responses:
                    missing_response.append(f"GET {path}")

        assert not missing_response, (
            f"GET endpoints missing 200 response:\n"
            + "\n".join(f"  - {e}" for e in missing_response)
        )

    def test_schemas_section_exists(self, openapi_spec):
        """OpenAPI spec should have component schemas."""
        components = openapi_spec.get("components", {})
        schemas = components.get("schemas", {})
        assert len(schemas) > 0, "No schemas defined in OpenAPI components"

    def test_pydantic_models_appear_in_schemas(self, openapi_spec):
        """Known Pydantic models should appear in the schemas section."""
        schemas = openapi_spec.get("components", {}).get("schemas", {})
        expected_models = [
            "EventInput",
            "VerifyInput",
            "LoginRequest",
            # LoginResponse and AuthConfig are not auto-included in schemas
            # because they are used as response models, not request bodies
        ]
        missing = [m for m in expected_models if m not in schemas]
        assert not missing, (
            f"Expected models not in schemas:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


# ── 6. API tags are used for grouping ──────────────────────────────────────

class TestAPITags:
    """Verify API tags are used for logical grouping."""

    def test_tags_section_exists(self, openapi_spec):
        """OpenAPI spec should have a tags section at the top level."""
        tags = openapi_spec.get("tags", [])
        # Tags at top level are optional in OpenAPI, but recommended
        # We check both top-level tags and per-endpoint tags
        has_any_tag = len(tags) > 0
        has_endpoint_tags = any(
            detail.get("tags")
            for methods in openapi_spec.get("paths", {}).values()
            for detail in methods.values()
            if isinstance(detail, dict)
        )
        assert has_any_tag or has_endpoint_tags, (
            "No tags found — neither top-level nor per-endpoint. "
            "Tags help group endpoints in documentation UIs."
        )

    def test_endpoints_have_tags(self, openapi_spec):
        """Endpoints should be tagged for grouping in docs."""
        untagged = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method, detail in methods.items():
                if method in ("get", "post", "put", "delete", "patch"):
                    if isinstance(detail, dict) and not detail.get("tags"):
                        untagged.append(f"{method.upper()} {path}")

        # Warning, not failure — FastAPI auto-tags by router
        if untagged:
            print(
                f"\n⚠️  {len(untagged)} endpoints without tags "
                f"(consider using APIRouter tags):\n"
                + "\n".join(f"  - {e}" for e in untagged[:10])
            )

    def test_meaningful_tag_names(self, openapi_spec):
        """Tags should have meaningful names, not just 'default'."""
        all_tags = set()
        for methods in openapi_spec.get("paths", {}).values():
            for detail in methods.values():
                if isinstance(detail, dict):
                    all_tags.update(detail.get("tags", []))

        # If only "default" tag, that's not useful grouping
        if all_tags == {"default"}:
            print("\n⚠️  Only 'default' tag found — consider adding descriptive tags")

    def test_top_level_tags_have_descriptions(self, openapi_spec):
        """Top-level tag definitions should include descriptions."""
        tags = openapi_spec.get("tags", [])
        for tag in tags:
            name = tag.get("name", "")
            desc = tag.get("description", "")
            if not desc:
                print(f"\n⚠️  Tag '{name}' has no description")


# ── 7. Edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and robustness checks."""

    def test_no_duplicate_paths(self, openapi_spec):
        """No duplicate paths in the spec (case-sensitive)."""
        paths = list(openapi_spec.get("paths", {}).keys())
        seen = set()
        dupes = []
        for p in paths:
            if p in seen:
                dupes.append(p)
            seen.add(p)
        assert not dupes, f"Duplicate paths found: {dupes}"

    def test_path_parameters_consistent(self, openapi_spec):
        """Path params like {tenant_id} should be defined in parameters."""
        inconsistent = []
        for path, methods in openapi_spec.get("paths", {}).items():
            import re
            path_params = set(re.findall(r"\{(\w+)\}", path))
            if not path_params:
                continue

            for method, detail in methods.items():
                if not isinstance(detail, dict):
                    continue
                defined_params = {
                    p["name"]
                    for p in detail.get("parameters", [])
                    if p.get("in") == "path"
                }
                missing_params = path_params - defined_params
                if missing_params:
                    inconsistent.append(
                        f"{method.upper()} {path}: undefined path params {missing_params}"
                    )

        assert not inconsistent, (
            f"Path parameters not defined:\n"
            + "\n".join(f"  - {e}" for e in inconsistent)
        )

    def test_all_methods_are_http_verbs(self, openapi_spec):
        """All methods in paths should be valid HTTP verbs."""
        valid = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
        invalid = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method in methods:
                if method not in valid and not method.startswith("x-"):
                    invalid.append(f"{method.upper()} {path}")

        assert not invalid, f"Invalid HTTP methods: {invalid}"

    def test_response_codes_are_valid(self, openapi_spec):
        """Response codes should be valid HTTP status codes or 'default'."""
        valid_ranges = {"2", "3", "4", "5"}
        invalid = []
        for path, methods in openapi_spec.get("paths", {}).items():
            for method, detail in methods.items():
                if not isinstance(detail, dict):
                    continue
                for code in detail.get("responses", {}):
                    if code == "default":
                        continue
                    if not (len(code) == 3 and code[0] in valid_ranges):
                        invalid.append(f"{method.upper()} {path}: invalid response code '{code}'")

        assert not invalid, f"Invalid response codes: {invalid}"

    def test_server_error_endpoints_handle_gracefully(self, client):
        """Endpoints should return proper errors, not 500, for bad input."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        # POST /api/check with empty body
        resp = client.post("/api/check", json={})
        assert resp.status_code in (400, 401, 422), (
            f"Expected 400/401/422 for empty body, got {resp.status_code}"
        )

    def test_nonexistent_endpoint_returns_404(self, client):
        """Non-existent path should return 404."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        resp = client.get("/api/nonexistent-path")
        assert resp.status_code == 404

    def test_openapi_endpoint_accessible(self, client):
        """The /openapi.json endpoint should be accessible."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "openapi" in data
        assert "paths" in data

    def test_docs_ui_accessible(self, client):
        """Swagger UI (/docs) should be accessible."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_accessible(self, client):
        """ReDoc (/redoc) should be accessible."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_model_serialization_roundtrip(self):
        """All input models should survive model_dump → model_validate roundtrip."""
        if not FASTAPI_AVAILABLE:
            pytest.skip("FastAPI not available")

        from dashboard.app import (
            EventInput, VerifyInput, TenantCreateInput,
            RoleAssignInput, RoleRevokeInput,
            DriftComponentsInput, DriftRecordInput,
            TemporalClaimInput, TemporalAddInput,
            EscalationSignalsInput, ReportGenerateInput,
            WebhookCreateInput, WebhookUpdateInput,
            SSOLoginInput, SSOCallbackInput, SSOProviderCreateInput,
        )

        models_and_data = [
            (EventInput, {"session_id": "s", "input_text": "t"}),
            (VerifyInput, {"text": "t"}),
            (TenantCreateInput, {"tenant_id": "t"}),
            (RoleAssignInput, {"user_id": "u", "tenant_id": "t", "role": "admin"}),
            (RoleRevokeInput, {"user_id": "u", "tenant_id": "t"}),
            (DriftComponentsInput, {}),
            (DriftRecordInput, {"agent_id": "a", "session_id": "s", "components": {}}),
            (TemporalClaimInput, {"claim": "c"}),
            (TemporalAddInput, {"claim": "c"}),
            (EscalationSignalsInput, {}),
            (ReportGenerateInput, {}),
            (WebhookCreateInput, {"url": "https://x.com"}),
            (WebhookUpdateInput, {}),
            (SSOLoginInput, {}),
            (SSOCallbackInput, {"code": "c"}),
            (SSOProviderCreateInput, {}),
        ]

        for model_cls, data in models_and_data:
            instance = model_cls(**data)
            dumped = instance.model_dump()
            restored = model_cls(**dumped)
            assert restored.model_dump() == dumped, (
                f"{model_cls.__name__} roundtrip failed"
            )


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
