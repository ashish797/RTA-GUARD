"""
RTA-GUARD — SSO (Single Sign-On) Integration

Phase 4.5: Enterprise-grade authentication via SAML 2.0 and OIDC/OAuth2.
Supports multiple providers per tenant with fallback to token auth.
"""
import os
import time
import uuid
import hashlib
import secrets
import json
import base64
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


# ─── Data Models ───────────────────────────────────────────────────


class SSOProviderType(str, Enum):
    """Supported SSO provider types."""
    OIDC = "oidc"
    SAML = "saml"


@dataclass
class UserProfile:
    """User profile extracted from SSO authentication."""
    user_id: str
    email: str
    display_name: str = ""
    tenant_id: str = ""
    provider: str = ""
    provider_type: SSOProviderType = SSOProviderType.OIDC
    roles: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    raw_claims: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["provider_type"] = self.provider_type.value
        return d


@dataclass
class SSOConfig:
    """Configuration for an SSO provider."""
    provider_type: SSOProviderType
    issuer_url: str
    client_id: str
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: List[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    tenant_id: str = ""  # Which RTA-GUARD tenant this provider maps to
    provider_name: str = ""  # Human-readable name (e.g. "Google", "Azure AD")
    # SAML-specific
    saml_entity_id: str = ""
    saml_sso_url: str = ""
    saml_certificate: str = ""
    # Additional metadata
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["provider_type"] = self.provider_type.value
        # Don't leak the secret
        d["client_secret"] = "***" if self.client_secret else ""
        return d


# ─── Abstract Base ─────────────────────────────────────────────────


class SSOProvider(ABC):
    """Abstract base class for SSO providers."""

    def __init__(self, config: SSOConfig):
        self.config = config

    @abstractmethod
    def get_login_url(self, state: Optional[str] = None) -> str:
        """
        Generate the SSO login URL for redirect.

        Args:
            state: CSRF protection state parameter. Auto-generated if None.

        Returns:
            URL to redirect the user to for authentication.
        """
        ...

    @abstractmethod
    def authenticate(self, code: str, state: Optional[str] = None) -> UserProfile:
        """
        Exchange an authorization code for a user profile.

        Args:
            code: Authorization code from the SSO callback.
            state: State parameter for CSRF validation.

        Returns:
            UserProfile extracted from the SSO response.
        """
        ...

    @abstractmethod
    def validate_token(self, token: str) -> UserProfile:
        """
        Validate an access/ID token and return user profile.

        Args:
            token: JWT access or ID token to validate.

        Returns:
            UserProfile extracted from the validated token.
        """
        ...

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return self.config.provider_name or self.config.provider_type.value

    @property
    def tenant_id(self) -> str:
        """Tenant this provider is linked to."""
        return self.config.tenant_id


# ─── OIDC Provider ─────────────────────────────────────────────────


class OIDCProvider(SSOProvider):
    """
    OpenID Connect provider with JWT validation.

    Supports standard OIDC flows:
    - Authorization Code flow (login_url → callback → authenticate)
    - Direct token validation (validate_token)
    - Discovery via .well-known/openid-configuration (lazy)

    For environments without internet access, the JWKS URI and token
    endpoint can be configured explicitly via config.extra.
    """

    def __init__(self, config: SSOConfig):
        super().__init__(config)
        self._jwks_uri: Optional[str] = None
        self._token_endpoint: Optional[str] = None
        self._authorization_endpoint: Optional[str] = None
        self._state_store: Dict[str, float] = {}  # state → timestamp
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_time: float = 0
        self._jwks_cache_ttl: int = 3600  # 1 hour

        # Load from extra config if provided
        if config.extra:
            self._jwks_uri = config.extra.get("jwks_uri")
            self._token_endpoint = config.extra.get("token_endpoint")
            self._authorization_endpoint = config.extra.get("authorization_endpoint")

        # Try discovery if endpoints not set
        if not self._authorization_endpoint:
            self._discover()

    def _discover(self):
        """Attempt OIDC discovery from .well-known endpoint."""
        try:
            import requests
            url = f"{self.config.issuer_url.rstrip('/')}/.well-known/openid-configuration"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                metadata = resp.json()
                self._authorization_endpoint = metadata.get("authorization_endpoint")
                self._token_endpoint = metadata.get("token_endpoint")
                self._jwks_uri = metadata.get("jwks_uri")
                logger.info(f"OIDC discovery succeeded for {self.config.issuer_url}")
        except Exception as e:
            logger.debug(f"OIDC discovery failed for {self.config.issuer_url}: {e}")

    def _generate_state(self) -> str:
        """Generate a CSRF-protecting state parameter."""
        state = secrets.token_urlsafe(32)
        self._state_store[state] = time.time()
        # Prune old states (>10 min)
        cutoff = time.time() - 600
        self._state_store = {s: t for s, t in self._state_store.items() if t > cutoff}
        return state

    def _validate_state(self, state: str) -> bool:
        """Validate a state parameter against stored states."""
        if state not in self._state_store:
            return False
        age = time.time() - self._state_store[state]
        del self._state_store[state]
        return age < 600  # 10 min max

    def get_login_url(self, state: Optional[str] = None) -> str:
        """Generate OIDC authorization URL."""
        if state is None:
            state = self._generate_state()
        else:
            self._state_store[state] = time.time()

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": secrets.token_urlsafe(16),
        }

        auth_endpoint = self._authorization_endpoint or f"{self.config.issuer_url.rstrip('/')}/authorize"
        return f"{auth_endpoint}?{urlencode(params)}"

    def authenticate(self, code: str, state: Optional[str] = None) -> UserProfile:
        """Exchange authorization code for tokens and extract user profile."""
        # Validate state if provided
        if state and not self._validate_state(state):
            raise ValueError("Invalid or expired SSO state parameter (CSRF protection)")

        # Exchange code for tokens
        token_data = self._exchange_code(code)

        # Extract ID token or access token
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")

        if id_token:
            return self._parse_id_token(id_token)
        elif access_token:
            return self.validate_token(access_token)
        else:
            raise ValueError("No id_token or access_token in SSO response")

    def _exchange_code(self, code: str) -> dict:
        """Exchange authorization code for tokens via token endpoint."""
        try:
            import requests
            token_endpoint = self._token_endpoint or f"{self.config.issuer_url.rstrip('/')}/token"
            resp = requests.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.config.redirect_uri,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except ImportError:
            # Fallback: simulate for testing when requests not available
            raise RuntimeError("requests library required for OIDC code exchange")
        except Exception as e:
            raise ValueError(f"OIDC token exchange failed: {e}")

    def validate_token(self, token: str) -> UserProfile:
        """Validate a JWT token using JWKS."""
        try:
            import jwt as pyjwt
            from jwt import PyJWKClient

            # Get JWKS
            jwks_uri = self._jwks_uri or f"{self.config.issuer_url.rstrip('/')}/.well-known/jwks.json"

            # Use PyJWKClient for key fetching and caching
            jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Decode and validate
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384"],
                audience=self.config.client_id,
                issuer=self.config.issuer_url,
                options={
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            return self._claims_to_profile(payload)

        except ImportError:
            # Fallback: decode without signature verification (NOT for production)
            logger.warning("PyJWT not available, decoding without signature verification")
            return self._decode_unverified(token)
        except Exception as e:
            raise ValueError(f"Token validation failed: {e}")

    def _parse_id_token(self, id_token: str) -> UserProfile:
        """Parse an ID token (JWT) into a UserProfile."""
        return self.validate_token(id_token)

    def _decode_unverified(self, token: str) -> UserProfile:
        """Decode JWT without verification (testing fallback)."""
        import jwt as pyjwt
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return self._claims_to_profile(payload)

    def _claims_to_profile(self, claims: dict) -> UserProfile:
        """Convert JWT claims to a UserProfile."""
        user_id = claims.get("sub", claims.get("user_id", ""))
        email = claims.get("email", "")
        name = claims.get("name", claims.get("preferred_username", ""))

        # Extract roles/groups
        roles = []
        groups = []
        if "roles" in claims:
            roles = claims["roles"] if isinstance(claims["roles"], list) else [claims["roles"]]
        if "groups" in claims:
            groups = claims["groups"] if isinstance(claims["groups"], list) else [claims["groups"]]
        # Also check realm_access (Keycloak-style)
        realm_access = claims.get("realm_access", {})
        if isinstance(realm_access, dict) and "roles" in realm_access:
            roles.extend(realm_access["roles"])

        return UserProfile(
            user_id=user_id,
            email=email,
            display_name=name,
            tenant_id=self.config.tenant_id,
            provider=self.provider_name,
            provider_type=SSOProviderType.OIDC,
            roles=roles,
            groups=groups,
            raw_claims=claims,
        )

    def get_jwks(self) -> Optional[dict]:
        """Fetch JWKS keys for manual verification."""
        try:
            import requests
            jwks_uri = self._jwks_uri or f"{self.config.issuer_url.rstrip('/')}/.well-known/jwks.json"
            resp = requests.get(jwks_uri, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"JWKS fetch failed: {e}")
            return None


# ─── SAML Provider (Stub) ──────────────────────────────────────────


class SAMLProvider(SSOProvider):
    """
    SAML 2.0 SSO provider (stub for MVP).

    Full implementation will use python3-saml or onelogin-saml2.
    For now, provides the interface and configuration plumbing.

    Supported (stubbed):
    - SAML metadata generation
    - SP-initiated SSO redirect
    - SAML response parsing (manual XML for MVP)
    """

    def __init__(self, config: SSOConfig):
        super().__init__(config)
        self._state_store: Dict[str, float] = {}

        if not config.saml_sso_url:
            logger.warning(
                f"SAML provider '{self.provider_name}' initialized without saml_sso_url. "
                "SAML login will not work until configured."
            )

    def get_login_url(self, state: Optional[str] = None) -> str:
        """Generate SAML AuthnRequest redirect URL."""
        if state is None:
            state = secrets.token_urlsafe(32)
        self._state_store[state] = time.time()

        if not self.config.saml_sso_url:
            raise ValueError("SAML SSO URL not configured")

        # Simplified AuthnRequest — production would use signed XML
        params = {
            "SAMLRequest": base64.urlsafe_b64encode(
                f'<AuthnRequest ID="{uuid.uuid4()}" '
                f'Version="2.0" '
                f'IssueInstant="{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}" '
                f'AssertionConsumerServiceURL="{self.config.redirect_uri}" '
                f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
                f'<Issuer>{self.config.saml_entity_id or self.config.client_id}</Issuer>'
                f'</AuthnRequest>'.encode()
            ).decode(),
            "RelayState": state,
        }
        return f"{self.config.saml_sso_url}?{urlencode(params)}"

    def authenticate(self, code: str, state: Optional[str] = None) -> UserProfile:
        """
        Process SAML response.

        For MVP, 'code' is expected to be a base64-encoded JSON with user attributes.
        Production will parse actual SAML XML assertions.
        """
        if state and state not in self._state_store:
            raise ValueError("Invalid SAML RelayState (CSRF protection)")
        if state:
            del self._state_store[state]

        try:
            # MVP: expect JSON payload in place of SAML XML
            decoded = base64.urlsafe_b64decode(code + "==").decode()
            data = json.loads(decoded)
        except Exception:
            raise ValueError("Invalid SAML response format (MVP expects base64-encoded JSON)")

        return UserProfile(
            user_id=data.get("name_id", data.get("sub", "")),
            email=data.get("email", ""),
            display_name=data.get("display_name", data.get("name", "")),
            tenant_id=self.config.tenant_id,
            provider=self.provider_name,
            provider_type=SSOProviderType.SAML,
            roles=data.get("roles", []),
            groups=data.get("groups", []),
            raw_claims=data,
        )

    def validate_token(self, token: str) -> UserProfile:
        """
        Validate a SAML assertion token.

        For MVP, expects a base64-encoded JSON assertion.
        Production will validate SAML XML signatures.
        """
        try:
            decoded = base64.urlsafe_b64decode(token + "==").decode()
            data = json.loads(decoded)
        except Exception:
            raise ValueError("Invalid SAML assertion format")

        return UserProfile(
            user_id=data.get("name_id", data.get("sub", "")),
            email=data.get("email", ""),
            display_name=data.get("display_name", data.get("name", "")),
            tenant_id=self.config.tenant_id,
            provider=self.provider_name,
            provider_type=SSOProviderType.SAML,
            roles=data.get("roles", []),
            groups=data.get("groups", []),
            raw_claims=data,
        )

    def get_metadata(self) -> str:
        """Generate SAML SP metadata XML."""
        return (
            f'<?xml version="1.0"?>'
            f'<EntityDescriptor entityID="{self.config.saml_entity_id or self.config.client_id}" '
            f'xmlns="urn:oasis:names:tc:SAML:2.0:metadata">'
            f'<SPSSODescriptor AuthnRequestsSigned="false" '
            f'WantAssertionsSigned="true" '
            f'ProtocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
            f'<NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</NameIDFormat>'
            f'<AssertionConsumerService '
            f'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
            f'Location="{self.config.redirect_uri}" '
            f'index="0" isDefault="true"/>'
            f'</SPSSODescriptor>'
            f'</EntityDescriptor>'
        )


# ─── SSO Manager ───────────────────────────────────────────────────


class SSOManager:
    """
    Manages multiple SSO providers across tenants.

    Each tenant can have multiple SSO providers (e.g., Google OIDC + Azure AD SAML).
    Providers are keyed by (tenant_id, provider_name).
    """

    def __init__(self):
        self._providers: Dict[str, SSOProvider] = {}  # key → provider

    def _key(self, tenant_id: str, provider_name: str) -> str:
        """Generate a storage key for a tenant+provider combo."""
        return f"{tenant_id}:{provider_name}" if tenant_id else provider_name

    def register_provider(self, config: SSOConfig) -> SSOProvider:
        """
        Register a new SSO provider.

        Args:
            config: Provider configuration.

        Returns:
            The created SSOProvider instance.

        Raises:
            ValueError: If provider type is unsupported.
        """
        if config.provider_type == SSOProviderType.OIDC:
            provider = OIDCProvider(config)
        elif config.provider_type == SSOProviderType.SAML:
            provider = SAMLProvider(config)
        else:
            raise ValueError(f"Unsupported SSO provider type: {config.provider_type}")

        key = self._key(config.tenant_id, config.provider_name or config.provider_type.value)
        self._providers[key] = provider
        logger.info(f"SSO provider registered: {key}")
        return provider

    def get_provider(self, tenant_id: str, provider_name: str) -> Optional[SSOProvider]:
        """Get a provider by tenant and name."""
        return self._providers.get(self._key(tenant_id, provider_name))

    def get_providers_for_tenant(self, tenant_id: str) -> List[SSOProvider]:
        """List all SSO providers for a tenant."""
        prefix = f"{tenant_id}:" if tenant_id else ""
        return [p for k, p in self._providers.items() if k.startswith(prefix)]

    def get_all_providers(self) -> List[SSOProvider]:
        """List all registered SSO providers."""
        return list(self._providers.values())

    def remove_provider(self, tenant_id: str, provider_name: str) -> bool:
        """Remove a provider registration."""
        key = self._key(tenant_id, provider_name)
        if key in self._providers:
            del self._providers[key]
            return True
        return False

    def is_configured(self, tenant_id: str = "") -> bool:
        """Check if SSO is configured for a tenant."""
        if tenant_id:
            return len(self.get_providers_for_tenant(tenant_id)) > 0
        return len(self._providers) > 0


# ─── Singleton Management ──────────────────────────────────────────


_sso_manager: Optional[SSOManager] = None


def get_sso_manager() -> SSOManager:
    """Get or create the global SSO manager."""
    global _sso_manager
    if _sso_manager is None:
        _sso_manager = SSOManager()
    return _sso_manager


def reset_sso_manager():
    """Reset the global SSO manager (for testing)."""
    global _sso_manager
    _sso_manager = None


# ─── Convenience Factory ───────────────────────────────────────────


def create_oidc_config(
    issuer_url: str,
    client_id: str,
    client_secret: str = "",
    redirect_uri: str = "",
    tenant_id: str = "",
    provider_name: str = "oidc",
    scopes: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> SSOConfig:
    """Create an OIDC SSOConfig with defaults."""
    return SSOConfig(
        provider_type=SSOProviderType.OIDC,
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes or ["openid", "profile", "email"],
        tenant_id=tenant_id,
        provider_name=provider_name,
        extra=extra or {},
    )


def create_saml_config(
    issuer_url: str,
    client_id: str,
    redirect_uri: str = "",
    tenant_id: str = "",
    provider_name: str = "saml",
    saml_entity_id: str = "",
    saml_sso_url: str = "",
    saml_certificate: str = "",
) -> SSOConfig:
    """Create a SAML SSOConfig with defaults."""
    return SSOConfig(
        provider_type=SSOProviderType.SAML,
        issuer_url=issuer_url,
        client_id=client_id,
        redirect_uri=redirect_uri,
        tenant_id=tenant_id,
        provider_name=provider_name,
        saml_entity_id=saml_entity_id,
        saml_sso_url=saml_sso_url,
        saml_certificate=saml_certificate,
    )
