"""
RTA-GUARD Dashboard — Authentication

Token-based auth for the dashboard API with multi-tenant support.
Phase 4.2: RBAC permission enforcement via require_permission decorator.
Phase 4.5: SSO (Single Sign-On) integration — OIDC + SAML, fallback to token auth.
"""
import os
import secrets
import hashlib
import base64
import json
import logging
import time
from typing import Optional, Set, Dict, Any
from functools import wraps

from fastapi import HTTPException, Depends, Header, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AuthConfig(BaseModel):
    """Dashboard auth configuration."""
    enabled: bool = True
    # Set via env var DASHBOARD_TOKEN or auto-generated
    api_token: Optional[str] = None
    # Session expiry in seconds (0 = no expiry)
    session_ttl: int = 3600


class AuthManager:
    """Manages dashboard authentication."""

    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig()
        self._token = self.config.api_token or os.getenv("DASHBOARD_TOKEN")
        self._sessions: dict[str, float] = {}

    @property
    def token(self) -> str:
        """Get or generate the API token."""
        if not self._token:
            self._token = secrets.token_urlsafe(32)
            print(f"\n🔐 Dashboard API Token: {self._token}")
            print("   Save this! Pass it as Authorization: Bearer <token>\n")
        return self._token

    def verify_token(self, provided_token: str) -> bool:
        """Verify a provided token."""
        if not self.config.enabled:
            return True
        return secrets.compare_digest(provided_token, self.token)

    def create_session(self) -> str:
        """Create a session token."""
        session_id = secrets.token_urlsafe(32)
        import time
        self._sessions[session_id] = time.time()
        return session_id

    def verify_session(self, session_id: str) -> bool:
        """Verify a session token."""
        if not self.config.enabled:
            return True
        if session_id not in self._sessions:
            return False
        import time
        if self.config.session_ttl > 0:
            age = time.time() - self._sessions[session_id]
            if age > self.config.session_ttl:
                del self._sessions[session_id]
                return False
        return True


# Global auth manager
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Get or create the global auth manager."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def init_auth(config: Optional[AuthConfig] = None):
    """Initialize auth with config."""
    global _auth_manager
    _auth_manager = AuthManager(config)
    return _auth_manager


async def require_auth(authorization: Optional[str] = Header(None)) -> bool:
    """
    FastAPI dependency for requiring authentication.

    Usage in routes:
        @app.get("/api/protected")
        async def protected(auth: bool = Depends(require_auth)):
            return {"data": "secret"}
    """
    auth = get_auth_manager()

    if not auth.config.enabled:
        return True

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Authorization: Bearer <token>"
        )

    # Support both "Bearer <token>" and raw token
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]

    if not auth.verify_token(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    return True


def _extract_tenant_from_payload(payload: dict) -> Optional[str]:
    """Extract tenant_id from JWT payload dict."""
    # Standard claim names for tenant
    for key in ("tenant_id", "tid", "org_id", "organization_id", "tenant"):
        val = payload.get(key)
        if val and isinstance(val, str):
            return val
    return None


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """
    Decode JWT payload (without signature verification).

    For production, add proper signature verification with a shared secret
    or public key. This is a lightweight extraction for tenant context.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        # Add padding if needed
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:
        return None


async def require_auth_with_tenant(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency for auth with tenant extraction.

    Extracts tenant_id from:
    1. X-Tenant-Id header (highest priority)
    2. JWT payload (tenant_id, tid, org_id claim)
    3. None (single-tenant/legacy mode)

    Returns dict with {"authenticated": True, "tenant_id": Optional[str]}
    """
    auth = get_auth_manager()

    if not auth.config.enabled:
        # Auth disabled — use X-Tenant-Id header if present
        return {"authenticated": True, "tenant_id": x_tenant_id}

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Authorization: Bearer <token>"
        )

    # Support both "Bearer <token>" and raw token
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]

    if not auth.verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Extract tenant_id: explicit header takes priority
    tenant_id = x_tenant_id

    # If no explicit header, try to extract from JWT payload
    if not tenant_id and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]
        payload = _decode_jwt_payload(jwt_token)
        if payload:
            tenant_id = _extract_tenant_from_payload(payload)

    return {"authenticated": True, "tenant_id": tenant_id}


class LoginRequest(BaseModel):
    token: str


class LoginResponse(BaseModel):
    session_id: str
    expires_in: int
    tenant_id: Optional[str] = None
    role: Optional[str] = None


# ─── RBAC Integration (Phase 4.2) ─────────────────────────────────


# Lazy import to avoid circular deps — rbac module imported at call time
def _get_rbac():
    """Get the RBAC manager lazily."""
    try:
        from brahmanda.rbac import get_rbac_manager, Permission
        return get_rbac_manager(), Permission
    except ImportError:
        return None, None


def require_permission(permission_name: str):
    """
    FastAPI dependency factory for RBAC permission checks.

    Usage:
        @app.post("/api/rules")
        async def create_rule(
            data: RuleInput,
            auth_ctx: dict = Depends(require_permission("create_rules")),
        ):
            ...

    The dependency:
    1. Authenticates (bearer token)
    2. Extracts tenant_id (header or JWT)
    3. Checks RBAC permission for user_id in tenant_id
    4. Falls back to full access if RBAC not configured (backward compat)

    Returns dict: {"authenticated": True, "tenant_id": ..., "user_id": ..., "role": ...}
    """
    from brahmanda.rbac import Permission as PermEnum, Role

    async def _check(
        authorization: Optional[str] = Header(None),
        x_tenant_id: Optional[str] = Header(None),
        x_user_id: Optional[str] = Header(None),
    ) -> dict:
        # Step 1: Authenticate
        auth_mgr = get_auth_manager()

        if not auth_mgr.config.enabled:
            return {"authenticated": True, "tenant_id": x_tenant_id, "user_id": x_user_id}

        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header. Use: Authorization: Bearer <token>"
            )

        token = authorization
        if authorization.startswith("Bearer "):
            token = authorization[7:]

        if not auth_mgr.verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid token")

        # Step 2: Extract tenant_id
        tenant_id = x_tenant_id
        if not tenant_id and authorization.startswith("Bearer "):
            jwt_token = authorization[7:]
            payload = _decode_jwt_payload(jwt_token)
            if payload:
                tenant_id = _extract_tenant_from_payload(payload)

        # Step 3: Extract user_id (from header or JWT)
        user_id = x_user_id
        if not user_id and authorization.startswith("Bearer "):
            jwt_token = authorization[7:]
            payload = _decode_jwt_payload(jwt_token)
            if payload:
                for key in ("sub", "user_id", "uid", "email"):
                    val = payload.get(key)
                    if val and isinstance(val, str):
                        user_id = val
                        break

        # Step 4: RBAC check (backward compatible — if RBAC not configured, allow)
        rbac_mgr, _ = _get_rbac()
        if rbac_mgr is not None and tenant_id is not None and user_id is not None:
            # Find the permission enum value
            perm = None
            try:
                perm = PermEnum(permission_name)
            except ValueError:
                raise HTTPException(status_code=500, detail=f"Unknown permission: {permission_name}")

            if not rbac_mgr.has_permission(user_id, tenant_id, perm):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission_name}. "
                           f"User {user_id} lacks required permission in tenant {tenant_id}"
                )

            role = rbac_mgr.get_user_role(user_id, tenant_id)
            return {
                "authenticated": True,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": role.value if role else None,
            }

        # Backward compat: RBAC not configured → full access
        return {
            "authenticated": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": None,
        }

    return _check


# ─── SSO Integration (Phase 4.5) ──────────────────────────────────


class SSOAuth:
    """
    SSO authentication wrapper for FastAPI integration.

    Provides:
    - Login URL generation (redirect to SSO provider)
    - Callback processing (exchange code for user profile)
    - Token validation (verify SSO-issued tokens)
    - Session management (map SSO users to local sessions)

    Falls back to token auth if SSO is not configured.
    """

    def __init__(self):
        self._sso_sessions: Dict[str, Dict[str, Any]] = {}  # session_id → user data
        self._session_ttl: int = 3600  # 1 hour

    def get_sso_manager(self):
        """Get the SSO manager lazily."""
        try:
            from brahmanda.sso import get_sso_manager, SSOProviderType
            return get_sso_manager(), SSOProviderType
        except ImportError:
            return None, None

    def get_login_url(self, tenant_id: str = "", provider_name: str = "") -> Optional[str]:
        """
        Get the SSO login URL for a tenant/provider.

        Returns None if SSO is not configured (caller should fall back to token auth).
        """
        manager, _ = self.get_sso_manager()
        if manager is None:
            return None

        providers = manager.get_providers_for_tenant(tenant_id)
        if not providers:
            # Check global (no tenant)
            providers = manager.get_providers_for_tenant("")

        if not providers:
            return None

        # Use specified provider or first available
        provider = None
        if provider_name:
            provider = manager.get_provider(tenant_id, provider_name)
            if not provider:
                provider = manager.get_provider("", provider_name)
        if not provider:
            provider = providers[0]

        try:
            return provider.get_login_url()
        except Exception as e:
            logger.warning(f"SSO login URL generation failed: {e}")
            return None

    def process_callback(self, code: str, state: Optional[str] = None,
                         tenant_id: str = "", provider_name: str = "") -> Dict[str, Any]:
        """
        Process an SSO callback (authorization code exchange).

        Returns a dict with session_id, user profile, and metadata.
        Raises ValueError if SSO processing fails.
        """
        manager, _ = self.get_sso_manager()
        if manager is None:
            raise ValueError("SSO not configured")

        # Find the right provider
        provider = None
        if provider_name:
            provider = manager.get_provider(tenant_id, provider_name)
            if not provider:
                provider = manager.get_provider("", provider_name)
        if not provider:
            providers = manager.get_providers_for_tenant(tenant_id)
            if not providers:
                providers = manager.get_providers_for_tenant("")
            if not providers:
                raise ValueError("No SSO provider found")
            provider = providers[0]

        # Authenticate
        profile = provider.authenticate(code, state=state)

        # Create session
        session_id = secrets.token_urlsafe(32)
        self._sso_sessions[session_id] = {
            "user_id": profile.user_id,
            "email": profile.email,
            "display_name": profile.display_name,
            "tenant_id": profile.tenant_id or tenant_id,
            "roles": profile.roles,
            "groups": profile.groups,
            "provider": profile.provider,
            "provider_type": profile.provider_type.value,
            "created_at": time.time(),
        }

        # Link to RBAC if available
        self._sync_rbac(profile)

        # Link to tenant if available
        self._sync_tenant(profile)

        return {
            "session_id": session_id,
            "user": profile.to_dict(),
            "expires_in": self._session_ttl,
        }

    def verify_sso_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Verify an SSO session and return user data."""
        if session_id not in self._sso_sessions:
            return None
        session = self._sso_sessions[session_id]
        age = time.time() - session["created_at"]
        if age > self._session_ttl:
            del self._sso_sessions[session_id]
            return None
        return session

    def _sync_rbac(self, profile):
        """Assign RBAC roles to SSO user if RBAC is configured."""
        try:
            from brahmanda.rbac import get_rbac_manager, Role
            rbac_mgr = get_rbac_manager()
            if rbac_mgr is None or not profile.tenant_id:
                return

            # If user doesn't have a role yet, assign based on SSO groups/roles
            existing_role = rbac_mgr.get_user_role(profile.user_id, profile.tenant_id)
            if existing_role is not None:
                return  # Already assigned

            # Map SSO roles to RTA-GUARD roles
            role_mapping = {
                "admin": Role.ADMIN,
                "administrator": Role.ADMIN,
                "operator": Role.OPERATOR,
                "viewer": Role.VIEWER,
                "auditor": Role.AUDITOR,
            }

            for sso_role in profile.roles:
                mapped = role_mapping.get(sso_role.lower())
                if mapped:
                    rbac_mgr.assign_role(
                        user_id=profile.user_id,
                        tenant_id=profile.tenant_id,
                        role=mapped,
                        assigned_by="sso",
                    )
                    logger.info(f"SSO auto-assigned role {mapped.value} to {profile.user_id}")
                    return

            # Default: assign viewer for new SSO users
            rbac_mgr.assign_role(
                user_id=profile.user_id,
                tenant_id=profile.tenant_id,
                role=Role.VIEWER,
                assigned_by="sso",
            )
        except (ImportError, Exception) as e:
            logger.debug(f"RBAC sync skipped: {e}")

    def _sync_tenant(self, profile):
        """Ensure the tenant exists for an SSO user."""
        try:
            from brahmanda.tenancy import get_tenant_manager
            tenant_mgr = get_tenant_manager()
            if tenant_mgr is None or not profile.tenant_id:
                return
            # Auto-create tenant if it doesn't exist
            try:
                tenant_mgr.get_tenant(profile.tenant_id)
            except ValueError:
                tenant_mgr.create_tenant(
                    tenant_id=profile.tenant_id,
                    name=f"SSO Tenant: {profile.tenant_id}",
                    config={"source": "sso", "provider": profile.provider},
                )
                logger.info(f"SSO auto-created tenant: {profile.tenant_id}")
        except (ImportError, Exception) as e:
            logger.debug(f"Tenant sync skipped: {e}")


# Global SSO auth instance
_sso_auth: Optional[SSOAuth] = None


def get_sso_auth() -> SSOAuth:
    """Get or create the global SSO auth handler."""
    global _sso_auth
    if _sso_auth is None:
        _sso_auth = SSOAuth()
    return _sso_auth


async def require_auth_with_sso(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
    x_sso_session: Optional[str] = Header(None),
) -> dict:
    """
    FastAPI dependency: authenticate via SSO session or token, with tenant extraction.

    Tries in order:
    1. X-SSO-Session header (SSO session ID)
    2. Bearer token (JWT → extract tenant + user)
    3. No auth (if auth disabled)

    Returns dict: {"authenticated": True, "tenant_id": ..., "user_id": ..., "source": "sso"|"token"}
    """
    auth_mgr = get_auth_manager()

    # Auth disabled
    if not auth_mgr.config.enabled:
        return {"authenticated": True, "tenant_id": x_tenant_id, "user_id": None, "source": "disabled"}

    # Try SSO session first
    if x_sso_session:
        sso = get_sso_auth()
        session = sso.verify_sso_session(x_sso_session)
        if session:
            return {
                "authenticated": True,
                "tenant_id": x_tenant_id or session.get("tenant_id"),
                "user_id": session.get("user_id"),
                "source": "sso",
                "role": None,  # Populated by RBAC check downstream
            }
        # Invalid/expired SSO session — fall through to token auth

    # Token auth
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing auth. Provide Authorization: Bearer <token> or X-SSO-Session header."
        )

    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]

    if not auth_mgr.verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Extract tenant from header or JWT
    tenant_id = x_tenant_id
    user_id = None
    if not tenant_id and authorization.startswith("Bearer "):
        payload = _decode_jwt_payload(authorization[7:])
        if payload:
            tenant_id = _extract_tenant_from_payload(payload)
            for key in ("sub", "user_id", "uid", "email"):
                val = payload.get(key)
                if val and isinstance(val, str):
                    user_id = val
                    break

    return {
        "authenticated": True,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "source": "token",
    }
