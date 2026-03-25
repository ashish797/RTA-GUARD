"""
RTA-GUARD — SSO Integration Tests (Phase 4.5)

Tests for Single Sign-On integration:
- OIDC provider initialization and configuration
- SAML provider initialization (stub)
- Login URL generation with CSRF state
- Token validation (JWT decode)
- User profile creation from claims
- Multi-provider support per tenant
- SSO manager lifecycle
- Fallback to token auth when SSO not configured
- SSOAuth wrapper integration
"""
import asyncio
import base64
import json
import time
import uuid

import pytest

from brahmanda.sso import (
    SSOProvider,
    SSOProviderType,
    SSOConfig,
    UserProfile,
    OIDCProvider,
    SAMLProvider,
    SSOManager,
    get_sso_manager,
    reset_sso_manager,
    create_oidc_config,
    create_saml_config,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_sso():
    """Reset SSO manager between tests."""
    reset_sso_manager()
    yield
    reset_sso_manager()


def _uid(prefix="test"):
    """Generate unique test ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_oidc_config(**overrides) -> SSOConfig:
    """Create a test OIDC config."""
    defaults = {
        "provider_type": SSOProviderType.OIDC,
        "issuer_url": "https://accounts.example.com",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "redirect_uri": "https://app.example.com/callback",
        "scopes": ["openid", "profile", "email"],
        "tenant_id": "test-tenant",
        "provider_name": "test-oidc",
        "extra": {
            "authorization_endpoint": "https://accounts.example.com/authorize",
            "token_endpoint": "https://accounts.example.com/token",
            "jwks_uri": "https://accounts.example.com/.well-known/jwks.json",
        },
    }
    defaults.update(overrides)
    return SSOConfig(**defaults)


def _make_saml_config(**overrides) -> SSOConfig:
    """Create a test SAML config."""
    defaults = {
        "provider_type": SSOProviderType.SAML,
        "issuer_url": "https://idp.example.com",
        "client_id": "test-saml-sp",
        "redirect_uri": "https://app.example.com/saml/callback",
        "tenant_id": "test-tenant",
        "provider_name": "test-saml",
        "saml_entity_id": "https://app.example.com/saml/metadata",
        "saml_sso_url": "https://idp.example.com/sso",
    }
    defaults.update(overrides)
    return SSOConfig(**defaults)


# ═══════════════════════════════════════════════════════════════════
# 1. SSO Provider Type Enum
# ═══════════════════════════════════════════════════════════════════


class TestSSOProviderType:
    """Test SSO provider type enum."""

    def test_oidc_value(self):
        assert SSOProviderType.OIDC.value == "oidc"

    def test_saml_value(self):
        assert SSOProviderType.SAML.value == "saml"

    def test_both_types(self):
        assert len(SSOProviderType) == 2


# ═══════════════════════════════════════════════════════════════════
# 2. SSOConfig Dataclass
# ═══════════════════════════════════════════════════════════════════


class TestSSOConfig:
    """Test SSOConfig dataclass."""

    def test_oidc_config_creation(self):
        config = _make_oidc_config()
        assert config.provider_type == SSOProviderType.OIDC
        assert config.client_id == "test-client-id"
        assert config.issuer_url == "https://accounts.example.com"

    def test_saml_config_creation(self):
        config = _make_saml_config()
        assert config.provider_type == SSOProviderType.SAML
        assert config.saml_sso_url == "https://idp.example.com/sso"

    def test_config_to_dict_hides_secret(self):
        config = _make_oidc_config(client_secret="supersecret")
        d = config.to_dict()
        assert d["client_secret"] == "***"
        assert d["client_id"] == "test-client-id"

    def test_config_to_dict_empty_secret(self):
        config = _make_oidc_config(client_secret="")
        d = config.to_dict()
        assert d["client_secret"] == ""

    def test_config_default_scopes(self):
        config = SSOConfig(
            provider_type=SSOProviderType.OIDC,
            issuer_url="https://example.com",
            client_id="cid",
        )
        assert config.scopes == ["openid", "profile", "email"]

    def test_config_extra_metadata(self):
        config = _make_oidc_config(extra={"custom_field": "custom_value"})
        assert config.extra["custom_field"] == "custom_value"


# ═══════════════════════════════════════════════════════════════════
# 3. UserProfile Dataclass
# ═══════════════════════════════════════════════════════════════════


class TestUserProfile:
    """Test UserProfile dataclass."""

    def test_profile_creation(self):
        profile = UserProfile(
            user_id="user-123",
            email="user@example.com",
            display_name="Test User",
            tenant_id="tenant-1",
            provider="google",
            provider_type=SSOProviderType.OIDC,
            roles=["admin"],
            groups=["engineering"],
        )
        assert profile.user_id == "user-123"
        assert profile.email == "user@example.com"
        assert profile.roles == ["admin"]

    def test_profile_to_dict(self):
        profile = UserProfile(
            user_id="user-1",
            email="u@e.com",
            provider_type=SSOProviderType.OIDC,
        )
        d = profile.to_dict()
        assert d["user_id"] == "user-1"
        assert d["provider_type"] == "oidc"

    def test_profile_defaults(self):
        profile = UserProfile(user_id="u1", email="u@e.com")
        assert profile.display_name == ""
        assert profile.roles == []
        assert profile.groups == []
        assert profile.raw_claims == {}


# ═══════════════════════════════════════════════════════════════════
# 4. OIDC Provider
# ═══════════════════════════════════════════════════════════════════


class TestOIDCProvider:
    """Test OIDC provider initialization and login URL generation."""

    def test_init_with_endpoints(self):
        """OIDC provider initializes with explicit endpoints."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        assert provider.provider_name == "test-oidc"
        assert provider.tenant_id == "test-tenant"

    def test_init_minimal(self):
        """OIDC provider initializes with minimal config (no endpoints)."""
        config = SSOConfig(
            provider_type=SSOProviderType.OIDC,
            issuer_url="https://nonexistent.example.com",
            client_id="cid",
            provider_name="minimal",
        )
        # Should not raise — discovery may fail silently
        provider = OIDCProvider(config)
        assert provider.provider_name == "minimal"

    def test_login_url_generation(self):
        """Login URL contains correct OIDC parameters."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        url = provider.get_login_url()

        assert "response_type=code" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=" in url
        assert "scope=openid+profile+email" in url or "scope=openid%20profile%20email" in url
        assert "state=" in url
        assert "nonce=" in url
        assert "https://accounts.example.com/authorize" in url

    def test_login_url_with_custom_state(self):
        """Login URL uses provided state parameter."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        url = provider.get_login_url(state="my-custom-state")
        assert "state=my-custom-state" in url

    def test_login_url_unique_state_per_call(self):
        """Each login URL gets a unique state."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        url1 = provider.get_login_url()
        url2 = provider.get_login_url()
        # Extract state from URLs
        state1 = dict(p.split("=", 1) for p in url1.split("?")[1].split("&"))["state"]
        state2 = dict(p.split("=", 1) for p in url2.split("?")[1].split("&"))["state"]
        assert state1 != state2

    def test_claims_to_profile(self):
        """Convert JWT claims to UserProfile correctly."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        claims = {
            "sub": "user-42",
            "email": "user@example.com",
            "name": "John Doe",
            "roles": ["admin", "operator"],
            "groups": ["engineering"],
        }
        profile = provider._claims_to_profile(claims)
        assert profile.user_id == "user-42"
        assert profile.email == "user@example.com"
        assert profile.display_name == "John Doe"
        assert "admin" in profile.roles
        assert "engineering" in profile.groups
        assert profile.provider_type == SSOProviderType.OIDC

    def test_claims_keycloak_realm_access(self):
        """Extract roles from Keycloak-style realm_access."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        claims = {
            "sub": "kc-user",
            "email": "kc@example.com",
            "realm_access": {"roles": ["kc-role-1", "kc-role-2"]},
        }
        profile = provider._claims_to_profile(claims)
        assert "kc-role-1" in profile.roles
        assert "kc-role-2" in profile.roles

    def test_claims_string_roles(self):
        """Handle roles as a string (not list)."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        claims = {"sub": "u1", "email": "u@e.com", "roles": "admin"}
        profile = provider._claims_to_profile(claims)
        assert profile.roles == ["admin"]

    def test_state_validation(self):
        """State parameter is validated and consumed."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        state = provider._generate_state()
        assert provider._validate_state(state) is True
        # Second use should fail (consumed)
        assert provider._validate_state(state) is False

    def test_state_expiry(self):
        """Expired state parameters are rejected."""
        config = _make_oidc_config()
        provider = OIDCProvider(config)
        state = "expired-state"
        provider._state_store[state] = time.time() - 700  # > 10 min ago
        assert provider._validate_state(state) is False

    def test_default_provider_name(self):
        """Default provider name from config."""
        config = SSOConfig(
            provider_type=SSOProviderType.OIDC,
            issuer_url="https://example.com",
            client_id="cid",
        )
        provider = OIDCProvider(config)
        assert provider.provider_name == "oidc"


# ═══════════════════════════════════════════════════════════════════
# 5. SAML Provider (Stub)
# ═══════════════════════════════════════════════════════════════════


class TestSAMLProvider:
    """Test SAML provider (stub implementation)."""

    def test_init(self):
        config = _make_saml_config()
        provider = SAMLProvider(config)
        assert provider.provider_name == "test-saml"
        assert provider.tenant_id == "test-tenant"

    def test_login_url(self):
        """SAML login URL is generated with AuthnRequest."""
        config = _make_saml_config()
        provider = SAMLProvider(config)
        url = provider.get_login_url()
        assert "https://idp.example.com/sso" in url
        assert "SAMLRequest=" in url
        assert "RelayState=" in url

    def test_login_url_no_sso_url_raises(self):
        """SAML login without saml_sso_url raises ValueError."""
        config = _make_saml_config(saml_sso_url="")
        provider = SAMLProvider(config)
        with pytest.raises(ValueError, match="SAML SSO URL not configured"):
            provider.get_login_url()

    def test_authenticate_json_payload(self):
        """SAML authenticate with base64 JSON payload."""
        config = _make_saml_config()
        provider = SAMLProvider(config)
        payload = {
            "name_id": "saml-user-1",
            "email": "saml@example.com",
            "display_name": "SAML User",
            "roles": ["viewer"],
        }
        code = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        profile = provider.authenticate(code)
        assert profile.user_id == "saml-user-1"
        assert profile.email == "saml@example.com"
        assert profile.provider_type == SSOProviderType.SAML

    def test_authenticate_invalid_payload_raises(self):
        """SAML authenticate with invalid payload raises ValueError."""
        config = _make_saml_config()
        provider = SAMLProvider(config)
        with pytest.raises(ValueError):
            provider.authenticate("not-valid-base64-json!")

    def test_metadata_generation(self):
        """SAML SP metadata is generated."""
        config = _make_saml_config()
        provider = SAMLProvider(config)
        metadata = provider.get_metadata()
        assert "EntityDescriptor" in metadata
        assert "SPSSODescriptor" in metadata
        assert "https://app.example.com/saml/callback" in metadata

    def test_validate_token(self):
        """SAML token validation."""
        config = _make_saml_config()
        provider = SAMLProvider(config)
        payload = {"name_id": "u1", "email": "u@e.com", "name": "User 1"}
        token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        profile = provider.validate_token(token)
        assert profile.user_id == "u1"


# ═══════════════════════════════════════════════════════════════════
# 6. SSO Manager
# ═══════════════════════════════════════════════════════════════════


class TestSSOManager:
    """Test SSO manager — multi-provider support."""

    def test_register_oidc(self):
        mgr = SSOManager()
        config = _make_oidc_config()
        provider = mgr.register_provider(config)
        assert isinstance(provider, OIDCProvider)

    def test_register_saml(self):
        mgr = SSOManager()
        config = _make_saml_config()
        provider = mgr.register_provider(config)
        assert isinstance(provider, SAMLProvider)

    def test_register_invalid_type_raises(self):
        """Registering unknown provider type raises ValueError."""
        mgr = SSOManager()
        config = SSOConfig(
            provider_type="invalid",  # type: ignore
            issuer_url="https://example.com",
            client_id="cid",
        )
        with pytest.raises(ValueError, match="Unsupported"):
            mgr.register_provider(config)

    def test_get_provider(self):
        mgr = SSOManager()
        config = _make_oidc_config()
        mgr.register_provider(config)
        provider = mgr.get_provider("test-tenant", "test-oidc")
        assert provider is not None
        assert isinstance(provider, OIDCProvider)

    def test_get_provider_not_found(self):
        mgr = SSOManager()
        assert mgr.get_provider("nonexistent", "nope") is None

    def test_multi_provider_per_tenant(self):
        """A tenant can have multiple SSO providers."""
        mgr = SSOManager()
        oidc_config = _make_oidc_config(provider_name="google")
        saml_config = _make_saml_config(provider_name="azure-ad")
        mgr.register_provider(oidc_config)
        mgr.register_provider(saml_config)
        providers = mgr.get_providers_for_tenant("test-tenant")
        assert len(providers) == 2

    def test_list_all_providers(self):
        mgr = SSOManager()
        mgr.register_provider(_make_oidc_config(tenant_id="t1", provider_name="p1"))
        mgr.register_provider(_make_saml_config(tenant_id="t2", provider_name="p2"))
        assert len(mgr.get_all_providers()) == 2

    def test_remove_provider(self):
        mgr = SSOManager()
        mgr.register_provider(_make_oidc_config())
        assert mgr.remove_provider("test-tenant", "test-oidc") is True
        assert mgr.get_provider("test-tenant", "test-oidc") is None

    def test_remove_nonexistent(self):
        mgr = SSOManager()
        assert mgr.remove_provider("no", "no") is False

    def test_is_configured(self):
        mgr = SSOManager()
        assert mgr.is_configured("test-tenant") is False
        mgr.register_provider(_make_oidc_config())
        assert mgr.is_configured("test-tenant") is True

    def test_is_configured_global(self):
        mgr = SSOManager()
        assert mgr.is_configured() is False
        mgr.register_provider(_make_oidc_config(tenant_id=""))
        assert mgr.is_configured() is True


# ═══════════════════════════════════════════════════════════════════
# 7. Singleton Management
# ═══════════════════════════════════════════════════════════════════


class TestSingletons:
    """Test singleton SSO manager."""

    def test_get_sso_manager_creates_instance(self):
        mgr = get_sso_manager()
        assert isinstance(mgr, SSOManager)

    def test_get_sso_manager_returns_same(self):
        mgr1 = get_sso_manager()
        mgr2 = get_sso_manager()
        assert mgr1 is mgr2

    def test_reset_clears_manager(self):
        mgr = get_sso_manager()
        mgr.register_provider(_make_oidc_config())
        reset_sso_manager()
        new_mgr = get_sso_manager()
        assert new_mgr is not mgr
        assert len(new_mgr.get_all_providers()) == 0


# ═══════════════════════════════════════════════════════════════════
# 8. Convenience Factories
# ═══════════════════════════════════════════════════════════════════


class TestFactories:
    """Test convenience config factories."""

    def test_create_oidc_config(self):
        config = create_oidc_config(
            issuer_url="https://example.com",
            client_id="cid",
            client_secret="secret",
            redirect_uri="https://app.com/cb",
            tenant_id="t1",
            provider_name="google",
        )
        assert config.provider_type == SSOProviderType.OIDC
        assert config.issuer_url == "https://example.com"
        assert config.provider_name == "google"

    def test_create_saml_config(self):
        config = create_saml_config(
            issuer_url="https://idp.com",
            client_id="sp-id",
            saml_sso_url="https://idp.com/sso",
            tenant_id="t1",
            provider_name="azure",
        )
        assert config.provider_type == SSOProviderType.SAML
        assert config.saml_sso_url == "https://idp.com/sso"


# ═══════════════════════════════════════════════════════════════════
# 9. SSOAuth Integration
# ═══════════════════════════════════════════════════════════════════

try:
    import fastapi  # noqa: F401
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
class TestSSOAuth:
    """Test SSOAuth wrapper from dashboard.auth."""

    def test_get_login_url_no_providers(self):
        """Returns None when no SSO providers configured."""
        from dashboard.auth import SSOAuth
        sso = SSOAuth()
        url = sso.get_login_url(tenant_id="nonexistent")
        assert url is None

    def test_get_login_url_with_provider(self):
        """Returns login URL when provider is configured."""
        from dashboard.auth import SSOAuth
        sso = SSOAuth()
        # Register a provider via the manager
        mgr = get_sso_manager()
        mgr.register_provider(_make_oidc_config())
        url = sso.get_login_url(tenant_id="test-tenant")
        assert url is not None
        assert "https://accounts.example.com/authorize" in url

    def test_verify_invalid_session(self):
        """Invalid session returns None."""
        from dashboard.auth import SSOAuth
        sso = SSOAuth()
        assert sso.verify_sso_session("nonexistent") is None

    def test_verify_expired_session(self):
        """Expired session returns None."""
        from dashboard.auth import SSOAuth
        sso = SSOAuth()
        sso._sso_sessions["expired"] = {
            "user_id": "u1",
            "email": "u@e.com",
            "created_at": time.time() - 7200,  # 2 hours ago
        }
        assert sso.verify_sso_session("expired") is None

    def test_get_sso_auth_singleton(self):
        """get_sso_auth returns the same instance."""
        from dashboard.auth import get_sso_auth, _sso_auth
        sso1 = get_sso_auth()
        sso2 = get_sso_auth()
        assert sso1 is sso2


# ═══════════════════════════════════════════════════════════════════
# 10. Backward Compatibility — Token Auth Fallback
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
class TestTokenAuthFallback:
    """Ensure existing token auth still works when SSO is not configured."""

    def test_require_auth_still_works(self):
        """require_auth dependency still validates bearer tokens."""
        import asyncio
        from dashboard.auth import require_auth, init_auth, AuthConfig
        init_auth(AuthConfig(enabled=True, api_token="test-token-123"))
        # Should not raise
        async def _check():
            return await require_auth(authorization="Bearer test-token-123")
        result = asyncio.run(_check())
        assert result is True

    def test_require_auth_rejects_bad_token(self):
        """require_auth rejects invalid tokens."""
        import asyncio
        from fastapi import HTTPException
        from dashboard.auth import require_auth, init_auth, AuthConfig
        init_auth(AuthConfig(enabled=True, api_token="correct-token"))
        async def _check():
            return await require_auth(authorization="Bearer wrong-token")
        with pytest.raises(HTTPException):
            asyncio.run(_check())

    def test_require_auth_disabled(self):
        """require_auth allows when auth is disabled."""
        import asyncio
        from dashboard.auth import require_auth, init_auth, AuthConfig
        init_auth(AuthConfig(enabled=False))
        async def _check():
            return await require_auth(authorization=None)
        result = asyncio.run(_check())
        assert result is True

    def test_require_auth_with_sso_no_sso_configured(self):
        """require_auth_with_sso falls back to token auth."""
        import asyncio
        from dashboard.auth import require_auth_with_sso, init_auth, AuthConfig
        init_auth(AuthConfig(enabled=True, api_token="my-token"))
        async def _check():
            return await require_auth_with_sso(
                authorization="Bearer my-token",
                x_tenant_id="t1",
                x_sso_session=None,
            )
        result = asyncio.run(_check())
        assert result["authenticated"] is True
        assert result["source"] == "token"

    def test_require_auth_with_sso_disabled(self):
        """require_auth_with_sso allows when auth disabled."""
        import asyncio
        from dashboard.auth import require_auth_with_sso, init_auth, AuthConfig
        init_auth(AuthConfig(enabled=False))
        async def _check():
            return await require_auth_with_sso(authorization=None, x_tenant_id=None, x_sso_session=None)
        result = asyncio.run(_check())
        assert result["authenticated"] is True
        assert result["source"] == "disabled"
