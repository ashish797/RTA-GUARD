"""
RTA-GUARD Dashboard — Pydantic Response Models

All request/response models for OpenAPI documentation.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ─── Core Guard Models ─────────────────────────────────────────────

class GuardEvent(BaseModel):
    """A single guard event (pass/warn/kill decision)."""
    session_id: str = Field(..., description="Session identifier")
    input_text: str = Field(..., description="Input that was checked")
    decision: str = Field(..., description="Guard decision: pass, warn, or kill")
    violation_type: Optional[str] = Field(None, description="Type of violation detected")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional event details")


class EventsResponse(BaseModel):
    """Response for GET /api/events."""
    events: List[Dict[str, Any]] = Field(..., description="List of guard events")
    total: int = Field(..., description="Total number of events")

    model_config = {"json_schema_extra": {
        "examples": [{
            "events": [{"session_id": "abc123", "decision": "pass", "input_text": "hello"}],
            "total": 1
        }]
    }}


class KilledSessionsResponse(BaseModel):
    """Response for GET /api/killed."""
    killed_sessions: List[str] = Field(..., description="List of killed session IDs")
    total: int = Field(..., description="Total killed sessions")


class StatsResponse(BaseModel):
    """Response for GET /api/stats."""
    total_events: int = Field(..., description="Total events processed")
    total_kills: int = Field(..., description="Total sessions killed")
    total_warnings: int = Field(..., description="Total warnings issued")
    total_passes: int = Field(..., description="Total passes")
    active_killed_sessions: int = Field(..., description="Currently killed sessions")
    violation_types: Dict[str, int] = Field(..., description="Count by violation type")

    model_config = {"json_schema_extra": {
        "examples": [{
            "total_events": 150, "total_kills": 5, "total_warnings": 20,
            "total_passes": 125, "active_killed_sessions": 2,
            "violition_types": {"jailbreak": 3, "hallucination": 2}
        }]
    }}


class CheckResponse(BaseModel):
    """Response for POST /api/check."""
    allowed: bool = Field(..., description="Whether the input was allowed")
    session_id: str = Field(..., description="Session identifier")
    event: Optional[Dict[str, Any]] = Field(None, description="Guard event details")
    message: Optional[str] = Field(None, description="Human-readable message")
    error: Optional[str] = Field(None, description="Error message if check failed")


class ResetResponse(BaseModel):
    """Response for POST /api/reset/{session_id}."""
    status: str = Field(..., description="Operation status")
    session_id: str = Field(..., description="Reset session ID")


# ─── Brahmanda Map Models ──────────────────────────────────────────

class VerifyResponse(BaseModel):
    """Response for Brahmanda verification."""
    verified: bool = Field(..., description="Whether claim was verified")
    confidence: float = Field(..., description="Verification confidence score")
    domain: str = Field(..., description="Verification domain")
    contradictions: List[Dict[str, Any]] = Field(default_factory=list, description="Found contradictions")


class BrahmandaStatusResponse(BaseModel):
    """Response for GET /api/brahmanda/status."""
    backend: str = Field(..., description="Backend type: qdrant or memory")
    fact_count: int = Field(..., description="Number of facts in the map")
    qdrant_url: Optional[str] = Field(None, description="Qdrant URL if using Qdrant backend")


# ─── Tenant Models ─────────────────────────────────────────────────

class TenantCreateResponse(BaseModel):
    """Response for POST /api/tenants."""
    status: str = Field(..., description="Creation status")
    tenant: Dict[str, Any] = Field(..., description="Tenant context details")


class TenantListResponse(BaseModel):
    """Response for GET /api/tenants."""
    tenants: List[Dict[str, Any]] = Field(..., description="List of tenants")
    total: int = Field(..., description="Total number of tenants")


class TenantHealthResponse(BaseModel):
    """Response for GET /api/tenants/{tenant_id}/health."""
    tenant_id: str = Field(..., description="Tenant identifier")
    databases: Dict[str, Dict[str, Any]] = Field(..., description="Database health per module")


# ─── RBAC Models ───────────────────────────────────────────────────

class RoleAssignResponse(BaseModel):
    """Response for POST /api/rbac/assign."""
    status: str = Field(..., description="Assignment status")
    assignment: Dict[str, Any] = Field(..., description="Role assignment details")


class RoleRevokeResponse(BaseModel):
    """Response for POST /api/rbac/revoke."""
    status: str = Field(..., description="Revocation status")
    user_id: str = Field(..., description="User identifier")
    tenant_id: str = Field(..., description="Tenant identifier")


class UserRoleResponse(BaseModel):
    """Response for GET /api/rbac/user/{user_id}/tenant/{tenant_id}."""
    user_id: str = Field(..., description="User identifier")
    tenant_id: str = Field(..., description="Tenant identifier")
    role: Optional[str] = Field(None, description="User's role in the tenant")
    permissions: List[str] = Field(..., description="List of permissions")


class TenantRolesResponse(BaseModel):
    """Response for GET /api/rbac/tenant/{tenant_id}."""
    tenant_id: str = Field(..., description="Tenant identifier")
    assignments: List[Dict[str, Any]] = Field(..., description="Role assignments")
    total: int = Field(..., description="Total assignments")


class RolesListResponse(BaseModel):
    """Response for GET /api/rbac/roles."""
    roles: Dict[str, List[str]] = Field(..., description="Roles mapped to their permissions")
    all_permissions: List[str] = Field(..., description="All available permissions")


# ─── Conscience Monitor Models ─────────────────────────────────────

class ConscienceAgentsResponse(BaseModel):
    """Response for GET /api/conscience/agents."""
    agents: List[Dict[str, Any]] = Field(..., description="List of registered agents")
    total: int = Field(..., description="Total agents")


class AnomalyResponse(BaseModel):
    """Response for GET /api/conscience/anomaly/{agent_id}."""
    agent_id: str = Field(..., description="Agent identifier")
    is_anomalous: bool = Field(..., description="Whether anomaly was detected")
    anomaly_type: str = Field(..., description="Type of anomaly")
    detail: str = Field(..., description="Anomaly details")


class DriftComponentsResponse(BaseModel):
    """Response for drift component breakdown."""
    agent_id: str = Field(..., description="Agent identifier")
    components: Dict[str, float] = Field(..., description="Drift component scores")
    overall_score: float = Field(..., description="Overall drift score")
    level: str = Field(..., description="Drift level: HEALTHY/DEGRADED/UNHEALTHY/CRITICAL")


class TemporalConsistencyResponse(BaseModel):
    """Response for temporal consistency summary."""
    agent_id: str = Field(..., description="Agent identifier")
    consistency_score: float = Field(..., description="Consistency score (0-1)")
    consistency_level: str = Field(..., description="Consistency level")
    contradictions: List[Dict[str, Any]] = Field(default_factory=list, description="Contradictions found")


class EscalationDecisionResponse(BaseModel):
    """Response for escalation evaluation."""
    level: str = Field(..., description="Escalation level: OBSERVE/WARN/THROTTLE/ALERT/KILL")
    reasons: List[str] = Field(..., description="Reasons for the decision")
    signal_scores: Dict[str, float] = Field(..., description="Individual signal scores")
    aggregate_score: float = Field(..., description="Weighted aggregate score")
    triggered_rules: List[str] = Field(..., description="Rules that triggered escalation")


# ─── Report Models ─────────────────────────────────────────────────

class ReportTypesResponse(BaseModel):
    """Response for GET /api/reports/types."""
    report_types: List[str] = Field(..., description="Available report types")
    output_formats: List[str] = Field(..., description="Available output formats")


# ─── Webhook Models ────────────────────────────────────────────────

class WebhookResponse(BaseModel):
    """Webhook configuration details."""
    webhook_id: str = Field(..., description="Webhook identifier")
    url: str = Field(..., description="Webhook endpoint URL")
    events: List[str] = Field(..., description="Subscribed event types")
    tenant_id: str = Field(..., description="Associated tenant ID")
    active: bool = Field(..., description="Whether webhook is active")
    description: str = Field("", description="Webhook description")
    created_at: Optional[str] = Field(None, description="Creation timestamp")


class WebhookListResponse(BaseModel):
    """Response for GET /api/webhooks."""
    webhooks: List[Dict[str, Any]] = Field(..., description="List of webhooks")
    total: int = Field(..., description="Total webhooks")


class WebhookTestResponse(BaseModel):
    """Response for POST /api/webhooks/{id}/test."""
    status: str = Field(..., description="Test status")
    webhook_id: str = Field(..., description="Tested webhook ID")
    event_id: str = Field(..., description="Test event ID")


# ─── Auth Models ───────────────────────────────────────────────────

class LoginSuccessResponse(BaseModel):
    """Response for POST /api/login."""
    session_id: str = Field(..., description="Session token for subsequent requests")
    expires_in: int = Field(..., description="Session TTL in seconds")
    tenant_id: Optional[str] = Field(None, description="Extracted tenant ID from JWT")
    role: Optional[str] = Field(None, description="User role if RBAC configured")


class AuthStatusResponse(BaseModel):
    """Response for GET /api/auth/status."""
    enabled: bool = Field(..., description="Whether auth is enabled")
    token_set: bool = Field(..., description="Whether API token is configured")


# ─── SSO Models ────────────────────────────────────────────────────

class SSOLoginResponse(BaseModel):
    """Response for GET /api/sso/login."""
    login_url: str = Field(..., description="SSO provider login URL")
    tenant_id: str = Field(..., description="Tenant ID for SSO")
    provider_name: str = Field(..., description="SSO provider name")


class SSOCallbackResponse(BaseModel):
    """Response for POST /api/sso/callback."""
    session_id: str = Field(..., description="SSO session ID")
    user: Dict[str, Any] = Field(..., description="User profile from SSO")
    expires_in: int = Field(..., description="Session TTL in seconds")


class SSOProvidersResponse(BaseModel):
    """Response for GET /api/sso/providers."""
    providers: List[Dict[str, Any]] = Field(..., description="List of SSO providers")
    total: int = Field(..., description="Total providers")
    configured: bool = Field(..., description="Whether SSO is configured")


class GenericStatusResponse(BaseModel):
    """Generic status/delete response."""
    status: str = Field(..., description="Operation status")


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error detail message")

    model_config = {"json_schema_extra": {
        "examples": [{"detail": "Invalid token"}]
    }}
