"""
RTA-GUARD Dashboard — Authentication

Simple token-based auth for the dashboard API.
"""
import os
import secrets
import hashlib
from typing import Optional
from functools import wraps

from fastapi import HTTPException, Depends, Header
from pydantic import BaseModel


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


class LoginRequest(BaseModel):
    token: str


class LoginResponse(BaseModel):
    session_id: str
    expires_in: int
