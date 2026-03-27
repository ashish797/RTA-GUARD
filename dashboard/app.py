"""
RTA-GUARD Dashboard — FastAPI Server

Real-time dashboard showing blocked sessions, violations, and events.
Full OpenAPI documentation available at /docs (Swagger UI) and /redoc (ReDoc).
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
import logging
logger = logging.getLogger(__name__)
sys.path.insert(0, str(Path(__file__).parent.parent))
from discus import DiscusGuard, GuardConfig, RtaEngine

# Phase 6.2: Prometheus metrics (opt-in)
_metrics_enabled = os.getenv("METRICS_ENABLED", "false").lower() == "true"
try:
    from brahmanda.metrics import (
        init_metrics, set_drift_score, set_tamas_level,
        observe_sla_response, METRICS_ENABLED as _BR_METRICS_ENABLED,
    )
    if _metrics_enabled:
        init_metrics()
except ImportError:
    _metrics_enabled = False

# Placeholders — initialized properly later in the file
webhook_manager = None
sla_tracker = None

# Initialize Brahmanda Map — Qdrant if QDRANT_URL set, else in-memory
brahmanda_backend = os.getenv("BRAHMANDA_BACKEND", "auto")
if brahmanda_backend == "qdrant" or (brahmanda_backend == "auto" and os.getenv("QDRANT_URL")):
    try:
        from brahmanda.qdrant_client import QdrantBrahmanda
        from brahmanda.verifier import BrahmandaVerifier
        brahmanda_map = QdrantBrahmanda()
        brahmanda_verifier = BrahmandaVerifier(brahmanda_map)
        logger.info(f"Brahmanda Map: Qdrant backend ({os.getenv('QDRANT_URL')})")
    except Exception as e:
        logger.warning(f"Qdrant init failed ({e}), falling back to in-memory")
        from brahmanda.verifier import get_seed_verifier
        brahmanda_verifier = get_seed_verifier()
else:
    from brahmanda.verifier import get_seed_verifier
    brahmanda_verifier = get_seed_verifier()
    logger.info("Brahmanda Map: in-memory backend")

# Initialize VerificationPipeline (Phase 2.3)
try:
    from brahmanda.pipeline import VerificationPipeline
    verification_pipeline = VerificationPipeline(brahmanda_verifier)
    logger.info("VerificationPipeline initialized (Phase 2.3)")
except ImportError:
    verification_pipeline = None
    logger.info("VerificationPipeline not available, using simple verifier")

# Data directory (must be defined before modules that reference it)
data_dir = os.getenv("RTA_DATA_DIR", "data")
os.makedirs(data_dir, exist_ok=True)

# Initialize Rate Limiting (Phase 4.7)
try:
    from brahmanda.rate_limit import (
        RateLimiter, RateLimitConfig, QuotaConfig, QuotaType,
        RateLimitMiddleware, get_rate_limiter, reset_rate_limiter,
    )
    _rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
    if _rate_limit_enabled:
        _rl_rpm = int(os.getenv("RATE_LIMIT_RPM", "60"))
        _rl_rph = int(os.getenv("RATE_LIMIT_RPH", "1000"))
        _rl_burst = int(os.getenv("RATE_LIMIT_BURST", "10"))
        _rl_db = os.getenv("RATE_LIMIT_DB_PATH", os.path.join(data_dir, "rate_limits.db"))
        rate_limiter = get_rate_limiter(
            config=RateLimitConfig(
                requests_per_minute=_rl_rpm,
                requests_per_hour=_rl_rph,
                burst_size=_rl_burst,
            ),
            db_path=_rl_db,
        )
        app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)
        logger.info(f"Rate limiting enabled: {_rl_rpm}/min, {_rl_rph}/hr, burst={_rl_burst}")
    else:
        rate_limiter = None
        logger.info("Rate limiting disabled (set RATE_LIMIT_ENABLED=true to enable)")
except ImportError:
    rate_limiter = None
    logger.warning("Rate limiting module not available")

# Initialize SLA Monitoring (Phase 4.8)
try:
    from brahmanda.sla_monitor import SLATracker, get_sla_tracker, reset_sla_tracker
    _sla_db = os.getenv("SLA_DB_PATH", os.path.join(data_dir, "sla_monitor.db"))
    sla_tracker = get_sla_tracker(db_path=_sla_db)
    logger.info(f"SLA Monitor initialized (Phase 4.8) — db: {_sla_db}")
except ImportError:
    sla_tracker = None
    logger.warning("SLA Monitor module not available")

from dashboard.auth import init_auth, require_auth, require_auth_with_tenant, require_permission, AuthConfig, LoginRequest, LoginResponse, get_auth_manager, get_sso_auth, require_auth_with_sso
from dashboard.models import (
    EventsResponse, KilledSessionsResponse, StatsResponse, CheckResponse,
    ResetResponse, VerifyResponse, BrahmandaStatusResponse,
    TenantCreateResponse, TenantListResponse, TenantHealthResponse,
    RoleAssignResponse, RoleRevokeResponse, UserRoleResponse,
    TenantRolesResponse, RolesListResponse,
    ConscienceAgentsResponse, AnomalyResponse, DriftComponentsResponse,
    TemporalConsistencyResponse, EscalationDecisionResponse,
    ReportTypesResponse, WebhookListResponse, WebhookTestResponse,
    LoginSuccessResponse, AuthStatusResponse, SSOLoginResponse,
    SSOCallbackResponse, SSOProvidersResponse, GenericStatusResponse,
    ErrorResponse,
)

# API Tags for OpenAPI grouping
API_TAGS = [
    {"name": "Guard", "description": "Core guard operations: check inputs, view events, manage sessions"},
    {"name": "Brahmanda Map", "description": "Ground truth verification and Brahmanda Map status"},
    {"name": "Tenants", "description": "Multi-tenant management (create, list, delete, health checks)"},
    {"name": "RBAC", "description": "Role-Based Access Control: assign/revoke roles, check permissions"},
    {"name": "Conscience", "description": "Agent behavioral profiling, health scores, anomaly detection"},
    {"name": "Drift", "description": "Live An-Rta drift scoring with component breakdowns"},
    {"name": "Tamas", "description": "Tamas state detection, history, and recovery scoring"},
    {"name": "Temporal", "description": "Temporal consistency checks and contradiction detection"},
    {"name": "User Behavior", "description": "User behavior anomaly detection and risk profiling"},
    {"name": "Escalation", "description": "Escalation protocol evaluation and decision history"},
    {"name": "Reports", "description": "Compliance report generation (EU AI Act, SOC2, HIPAA)"},
    {"name": "Webhooks", "description": "Webhook registration, management, and testing"},
    {"name": "Auth", "description": "Authentication: login, token auth, SSO integration"},
    {"name": "SSO", "description": "Single Sign-On providers: OIDC and SAML integration"},
]

app = FastAPI(
    title="RTA-GUARD Dashboard API",
    version="1.0.0",
    description="""
## RTA-GUARD — AI Session Kill-Switch

The RTA-GUARD Dashboard API provides real-time monitoring and management
for AI session safety. It includes:

- **Guard**: Check inputs against 13 RTA rules, view events and killed sessions
- **Brahmanda Map**: Ground truth verification with vector search
- **Conscience Monitor**: Behavioral profiling, drift scoring, Tamas detection, temporal consistency
- **Tenants**: Multi-tenant isolation with per-tenant databases
- **RBAC**: Role-based access control (Admin, Operator, Viewer, Auditor)
- **Reports**: EU AI Act, SOC2, HIPAA compliance reports
- **Webhooks**: Event-driven notifications with HMAC signatures
- **SSO**: OIDC and SAML single sign-on integration

### Authentication

All endpoints (except `/api/login`, `/api/auth/status`, and `/api/sso/login`)
require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <your-api-token>
```

Set the `DASHBOARD_TOKEN` environment variable, or one will be auto-generated on startup.

### Multi-Tenancy

Pass `X-Tenant-Id` header for tenant-scoped operations, or include `tenant_id`
in your JWT payload.
""",
    openapi_tags=API_TAGS,
)

# Initialize auth (set DASHBOARD_TOKEN env var, or auto-generates one)
auth_config = AuthConfig(
    enabled=os.getenv("DASHBOARD_AUTH", "true").lower() == "true",
    api_token=os.getenv("DASHBOARD_TOKEN")
)
auth = init_auth(auth_config)

# Initialize Tenant Manager (Phase 4.1)
from brahmanda.tenancy import TenantManager, get_tenant_manager, validate_tenant_id
tenant_manager = get_tenant_manager(base_data_dir=data_dir)

# Initialize RBAC Manager (Phase 4.2)
from brahmanda.rbac import get_rbac_manager, reset_rbac_manager, Role, Permission
rbac_manager = get_rbac_manager(db_path=os.path.join(data_dir, "rbac.db"))
logger.info("RBAC Manager initialized (Phase 4.2)")

# Initialize RTA engine with verification pipeline (Phase 2.3)
rta_engine = RtaEngine(GuardConfig(log_all=True), verifier=brahmanda_verifier, pipeline=verification_pipeline)

# Initialize Conscience Monitor (Phase 3.1)
try:
    from brahmanda.conscience import ConscienceMonitor
    conscience_monitor = ConscienceMonitor(in_memory=True)  # Dashboard uses in-memory for demo
    # Wire into verifier
    brahmanda_verifier.conscience = conscience_monitor
    logger.info("Conscience Monitor initialized (Phase 3.1)")
except Exception as e:
    conscience_monitor = None
    logger.warning(f"Conscience Monitor init failed: {e}")

# Initialize User Behavior Tracker (Phase 3.5)
try:
    from brahmanda.user_monitor import UserBehaviorTracker
    user_tracker = UserBehaviorTracker()
    logger.info("User Behavior Tracker initialized (Phase 3.5)")
except Exception as e:
    user_tracker = None
    logger.warning(f"User Behavior Tracker init failed: {e}")

# Initialize Escalation Chain (Phase 3.6)
try:
    from brahmanda.escalation import EscalationChain, EscalationConfig
    escalation_chain = EscalationChain()
    logger.info("Escalation Chain initialized (Phase 3.6)")
except Exception as e:
    escalation_chain = None
    logger.warning(f"Escalation Chain init failed: {e}")

# Wire escalation chain into ConscienceMonitor
if conscience_monitor and escalation_chain:
    conscience_monitor.escalation_chain = escalation_chain

# Global guard instance for the dashboard — WITH RTA enabled
guard = DiscusGuard(GuardConfig(log_all=True), rta_engine=rta_engine, user_tracker=user_tracker,
                    escalation_chain=escalation_chain, webhook_manager=webhook_manager,
                    sla_tracker=sla_tracker)

# Connected websocket clients
connected_clients: list[WebSocket] = []

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# --- SLA Monitoring Middleware (Phase 4.8) ---

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse


class SLAMiddleware(BaseHTTPMiddleware):
    """Records request duration and status code for SLA tracking."""

    async def dispatch(self, request: StarletteRequest, call_next):
        if sla_tracker is None:
            return await call_next(request)

        import time as _time
        start = _time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (_time.monotonic() - start) * 1000.0
            try:
                sla_tracker.record_request(
                    endpoint=request.url.path,
                    duration_ms=duration_ms,
                    status_code=status_code,
                )
                # Phase 6.2: Prometheus SLA response time
                if _metrics_enabled:
                    observe_sla_response(request.url.path, duration_ms / 1000.0)
            except Exception:
                pass  # Don't let SLA tracking break requests


if sla_tracker is not None:
    app.add_middleware(SLAMiddleware)
    logger.info("SLA middleware active — all requests tracked")


class EventInput(BaseModel):
    """Manual event input for testing."""
    session_id: str
    input_text: str


@app.get("/", include_in_schema=False)
async def dashboard():
    """Serve the dashboard HTML."""
    html_path = static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>RTA-GUARD Dashboard</h1><p>Dashboard loading...</p>")


@app.get(
    "/api/events",
    response_model=EventsResponse,
    tags=["Guard"],
    summary="Get guard events",
    description="Retrieve all guard events, optionally filtered by session ID. Returns pass/warn/kill decisions with timestamps.",
    responses={401: {"model": ErrorResponse, "description": "Authentication failed"}},
)
async def get_events(session_id: Optional[str] = None, auth: bool = Depends(require_auth)):
    """Get all events, optionally filtered by session."""
    events = guard.get_events(session_id)
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "total": len(events)
    }


@app.get(
    "/api/killed",
    response_model=KilledSessionsResponse,
    tags=["Guard"],
    summary="Get killed sessions",
    description="List all sessions that have been terminated by the guard.",
    responses={401: {"model": ErrorResponse}},
)
async def get_killed_sessions(auth: bool = Depends(require_auth)):
    """Get all killed sessions."""
    killed = guard.get_killed_sessions()
    return {
        "killed_sessions": list(killed),
        "total": len(killed)
    }


@app.get(
    "/api/stats",
    response_model=StatsResponse,
    tags=["Guard"],
    summary="Get guard statistics",
    description="Summary statistics: total events, kills, warnings, passes, and violation type breakdown.",
    responses={401: {"model": ErrorResponse}},
)
async def get_stats(auth: bool = Depends(require_auth)):
    """Get summary statistics."""
    events = guard.get_events()
    kills = [e for e in events if e.decision.value == "kill"]
    warnings = [e for e in events if e.decision.value == "warn"]
    passes = [e for e in events if e.decision.value == "pass"]

    return {
        "total_events": len(events),
        "total_kills": len(kills),
        "total_warnings": len(warnings),
        "total_passes": len(passes),
        "active_killed_sessions": len(guard.get_killed_sessions()),
        "violation_types": {
            vt.value: len([e for e in events if e.violation_type == vt])
            for vt in set(e.violation_type for e in events if e.violation_type)
        }
    }


@app.post(
    "/api/check",
    response_model=CheckResponse,
    tags=["Guard"],
    summary="Check input through guard",
    description="Run input text through all 13 RTA rules. Returns pass/warn/kill decision. Broadcasts result to WebSocket clients.",
    responses={
        401: {"model": ErrorResponse},
    },
)
async def check_input(event_input: EventInput, auth: bool = Depends(require_auth)):
    """Check input text through the guard."""
    try:
        response = guard.check(event_input.input_text, event_input.session_id)
        result = response.model_dump(mode="json")
    except Exception as e:
        # SessionKilledError or other
        if hasattr(e, 'event'):
            result = {
                "allowed": False,
                "session_id": event_input.session_id,
                "event": e.event.model_dump(mode="json"),
                "message": str(e)
            }
        else:
            result = {"error": str(e)}

    # Broadcast to connected websockets
    await broadcast_event(result)

    return result


@app.post(
    "/api/reset/{session_id}",
    response_model=ResetResponse,
    tags=["Guard"],
    summary="Reset a killed session",
    description="Reset (unkill) a previously terminated session, allowing it to resume.",
    responses={401: {"model": ErrorResponse}},
)
async def reset_session(session_id: str, auth: bool = Depends(require_auth)):
    """Reset a killed session."""
    guard.reset_session(session_id)
    return {"status": "ok", "session_id": session_id}


# --- Brahmanda Map endpoints ---

class VerifyInput(BaseModel):
    """Text to verify against ground truth."""
    text: str
    domain: str = "general"


@app.post(
    "/api/brahmanda/verify",
    response_model=VerifyResponse,
    tags=["Brahmanda Map"],
    summary="Verify text against ground truth",
    description="Verify a text claim against the Brahmanda Map ground truth database using semantic search.",
    responses={401: {"model": ErrorResponse}},
)
async def brahmanda_verify(input_data: VerifyInput, auth: bool = Depends(require_auth)):
    """Verify text against the Brahmanda Map (ground truth)."""
    result = brahmanda_verifier.verify(input_data.text, domain=input_data.domain)
    return result.to_dict()


@app.post(
    "/api/brahmanda/pipeline-verify",
    response_model=VerifyResponse,
    tags=["Brahmanda Map"],
    summary="Verify with full pipeline",
    description="Verify text using the full VerificationPipeline (Phase 2.3): multi-stage claim→search→cross-verify→verdict flow with 5 contradiction heuristics.",
    responses={401: {"model": ErrorResponse}},
)
async def brahmanda_pipeline_verify(input_data: VerifyInput, auth: bool = Depends(require_auth)):
    """Verify text using the full VerificationPipeline (Phase 2.3)."""
    if verification_pipeline:
        result = verification_pipeline.verify(input_data.text, domain=input_data.domain)
        return result.to_dict()
    # Fallback to simple verifier
    result = brahmanda_verifier.verify(input_data.text, domain=input_data.domain)
    return result.to_dict()


@app.get("/api/brahmanda/status")
async def brahmanda_status():
    """Get Brahmanda Map backend status."""
    backend_type = "qdrant" if hasattr(brahmanda_verifier.brahmanda, '_client') else "memory"
    return {
        "backend": backend_type,
        "fact_count": brahmanda_verifier.brahmanda.fact_count,
        "qdrant_url": os.getenv("QDRANT_URL") if backend_type == "qdrant" else None,
    }


# --- Auth endpoints ---

# --- Tenant Management endpoints (Phase 4.1) ---

class TenantCreateInput(BaseModel):
    """Input for creating a tenant."""
    tenant_id: str
    name: str = ""
    config: Optional[dict] = None


@app.post("/api/tenants")
async def create_tenant(data: TenantCreateInput, auth: bool = Depends(require_auth)):
    """Create a new tenant with isolated databases."""
    try:
        ctx = tenant_manager.create_tenant(
            tenant_id=data.tenant_id,
            name=data.name or data.tenant_id,
            config=data.config or {},
        )
        return {"status": "created", "tenant": ctx.to_dict()}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/tenants")
async def list_tenants(auth: bool = Depends(require_auth)):
    """List all tenants."""
    return {
        "tenants": tenant_manager.list_tenants(),
        "total": len(tenant_manager.list_tenants()),
    }


@app.get("/api/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, auth: bool = Depends(require_auth)):
    """Get tenant details."""
    try:
        ctx = tenant_manager.get_tenant(tenant_id)
        return ctx.to_dict()
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, auth: bool = Depends(require_auth)):
    """Delete a tenant and all its data."""
    try:
        tenant_manager.delete_tenant(tenant_id)
        return {"status": "deleted", "tenant_id": tenant_id}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/tenants/{tenant_id}/health")
async def tenant_health(tenant_id: str, auth: bool = Depends(require_auth)):
    """Get health status of a tenant's isolated databases."""
    try:
        ctx = tenant_manager.get_tenant(tenant_id)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))

    health = {"tenant_id": tenant_id, "databases": {}}
    for module in ("conscience", "attribution", "user_monitor", "temporal"):
        db_path = ctx.get_db_path(module)
        health["databases"][module] = {
            "path": db_path,
            "exists": os.path.exists(db_path),
            "size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
        }
    return health


# --- RBAC Management endpoints (Phase 4.2) ---

class RoleAssignInput(BaseModel):
    """Input for assigning a role."""
    user_id: str
    tenant_id: str
    role: str  # admin, operator, viewer, auditor
    assigned_by: str = "system"


class RoleRevokeInput(BaseModel):
    """Input for revoking a role."""
    user_id: str
    tenant_id: str


@app.post("/api/rbac/assign")
async def rbac_assign_role(data: RoleAssignInput, auth: bool = Depends(require_auth)):
    """Assign a role to a user in a tenant."""
    try:
        role = Role(data.role)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}. Valid: {[r.value for r in Role]}")
    assignment = rbac_manager.assign_role(
        user_id=data.user_id,
        tenant_id=data.tenant_id,
        role=role,
        assigned_by=data.assigned_by,
    )
    return {"status": "assigned", "assignment": assignment.to_dict()}


@app.post("/api/rbac/revoke")
async def rbac_revoke_role(data: RoleRevokeInput, auth: bool = Depends(require_auth)):
    """Revoke a user's role in a tenant."""
    revoked = rbac_manager.revoke_role(data.user_id, data.tenant_id)
    if revoked:
        return {"status": "revoked", "user_id": data.user_id, "tenant_id": data.tenant_id}
    return {"status": "not_found", "user_id": data.user_id, "tenant_id": data.tenant_id}


@app.get("/api/rbac/user/{user_id}/tenant/{tenant_id}")
async def rbac_get_user_role(user_id: str, tenant_id: str, auth: bool = Depends(require_auth)):
    """Get a user's role and permissions in a tenant."""
    role = rbac_manager.get_user_role(user_id, tenant_id)
    if role is None:
        return {"user_id": user_id, "tenant_id": tenant_id, "role": None, "permissions": []}
    perms = rbac_manager.get_user_permissions(user_id, tenant_id)
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role.value,
        "permissions": [p.value for p in perms],
    }


@app.get("/api/rbac/tenant/{tenant_id}")
async def rbac_list_tenant_roles(tenant_id: str, auth: bool = Depends(require_auth)):
    """List all role assignments for a tenant."""
    assignments = rbac_manager.list_role_assignments(tenant_id)
    return {
        "tenant_id": tenant_id,
        "assignments": [a.to_dict() for a in assignments],
        "total": len(assignments),
    }


@app.get("/api/rbac/roles")
async def rbac_list_roles(auth: bool = Depends(require_auth)):
    """List all available roles and their permissions."""
    from brahmanda.rbac import get_role_permissions, get_all_permissions
    return {
        "roles": {
            role.value: sorted([p.value for p in get_role_permissions(role)])
            for role in Role
        },
        "all_permissions": sorted([p.value for p in get_all_permissions()]),
    }


# --- Conscience Monitor endpoints (Phase 3.1) ---

@app.get("/api/conscience/agents")
async def conscience_agents(auth: bool = Depends(require_auth)):
    """List all registered agents with health scores."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available", "agents": []}
    agents = conscience_monitor.list_agents()
    return {
        "agents": agents,
        "total": len(agents),
    }


@app.get("/api/conscience/health/{agent_id}")
async def conscience_health(agent_id: str, auth: bool = Depends(require_auth)):
    """Get health score for a specific agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_agent_health(agent_id)


@app.get("/api/conscience/anomaly/{agent_id}")
async def conscience_anomaly(agent_id: str, auth: bool = Depends(require_auth)):
    """Detect anomaly for a specific agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    is_anomalous, anomaly_type, detail = conscience_monitor.detect_anomaly(agent_id)
    return {
        "agent_id": agent_id,
        "is_anomalous": is_anomalous,
        "anomaly_type": anomaly_type.value,
        "detail": detail,
    }


@app.get("/api/conscience/session/{agent_id}/{session_id}")
async def conscience_session_drift(
    agent_id: str, session_id: str, auth: bool = Depends(require_auth)
):
    """Get session drift metrics."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_session_drift(agent_id, session_id)


@app.get("/api/conscience/sessions")
async def conscience_sessions(
    agent_id: Optional[str] = None, auth: bool = Depends(require_auth)
):
    """List session profiles, optionally filtered by agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available", "sessions": []}
    sessions = conscience_monitor.list_sessions(agent_id=agent_id)
    return {
        "sessions": sessions,
        "total": len(sessions),
    }


@app.get("/api/conscience/users")
async def conscience_users(auth: bool = Depends(require_auth)):
    """List all user profiles."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available", "users": []}
    users = conscience_monitor.list_users()
    return {
        "users": users,
        "total": len(users),
    }


# --- Live Drift endpoints (Phase 3.2) ---

class DriftComponentsInput(BaseModel):
    """Drift component scores for recording."""
    semantic: float = 0.0
    alignment: float = 0.0
    scope: float = 0.0
    confidence: float = 0.0
    rule_proximity: float = 0.0


class DriftRecordInput(BaseModel):
    """Input for recording a drift measurement."""
    agent_id: str
    session_id: str
    components: DriftComponentsInput


@app.get("/api/conscience/drift/{agent_id}")
async def conscience_drift(agent_id: str, auth: bool = Depends(require_auth)):
    """Get live drift state for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_live_drift(agent_id)


@app.get("/api/conscience/drift/session/{session_id}")
async def conscience_drift_session(session_id: str, auth: bool = Depends(require_auth)):
    """Get live drift state for a session."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_live_drift_session(session_id)


@app.get("/api/conscience/drift/components/{agent_id}")
async def conscience_drift_components(agent_id: str, auth: bool = Depends(require_auth)):
    """Get drift component breakdown for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_drift_components(agent_id)


@app.post("/api/conscience/drift/record")
async def conscience_drift_record(data: DriftRecordInput, auth: bool = Depends(require_auth)):
    """Record a drift measurement."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    result = conscience_monitor.record_drift(
        agent_id=data.agent_id,
        session_id=data.session_id,
        components=data.components.model_dump(),
    )
    # Phase 6.2: Update Prometheus drift gauge
    if _metrics_enabled:
        set_drift_score(data.agent_id, result.get("weighted_score", 0.0))
    return result


# --- Tamas Detection endpoints (Phase 3.3) ---

@app.get("/api/conscience/tamas/{agent_id}")
async def conscience_tamas(agent_id: str, auth: bool = Depends(require_auth)):
    """Get current Tamas state for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    result = conscience_monitor.get_tamas_state(agent_id)
    # Phase 6.2: Update Prometheus Tamas gauge
    if _metrics_enabled:
        _TAMAS_LEVELS = {"sattva": 0, "rajas": 1, "tamas": 2, "critical": 3}
        state = result.get("state", "sattva")
        set_tamas_level(agent_id, _TAMAS_LEVELS.get(state, 0))
    return result


@app.get("/api/conscience/tamas/{agent_id}/history")
async def conscience_tamas_history(agent_id: str, auth: bool = Depends(require_auth)):
    """Get Tamas event history for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return {
        "agent_id": agent_id,
        "events": conscience_monitor.get_tamas_history(agent_id),
    }


@app.get("/api/conscience/tamas/{agent_id}/recovery")
async def conscience_tamas_recovery(agent_id: str, auth: bool = Depends(require_auth)):
    """Get recovery score for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_recovery_score(agent_id)


# --- Temporal Consistency endpoints (Phase 3.4) ---

class TemporalClaimInput(BaseModel):
    """Input for temporal consistency check."""
    claim: str
    confidence: float = 1.0


class TemporalAddInput(BaseModel):
    """Input for adding a temporal statement."""
    claim: str
    confidence: float = 1.0
    source: str = "user"


@app.get("/api/conscience/temporal/{agent_id}")
async def conscience_temporal(agent_id: str, auth: bool = Depends(require_auth)):
    """Get temporal consistency summary for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_temporal_consistency(agent_id)


@app.post("/api/conscience/temporal/{agent_id}/check")
async def conscience_temporal_check(
    agent_id: str, data: TemporalClaimInput, auth: bool = Depends(require_auth)
):
    """Pre-flight check: test a claim against agent's temporal history."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.check_temporal_consistency(
        agent_id, data.claim, data.confidence
    )


@app.post("/api/conscience/temporal/{agent_id}/add")
async def conscience_temporal_add(
    agent_id: str, data: TemporalAddInput, auth: bool = Depends(require_auth)
):
    """Add a statement to an agent's temporal history and get contradictions."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    contradictions = conscience_monitor.temporal_checker.add_statement(
        agent_id, data.claim, data.confidence, data.source
    )
    return {
        "agent_id": agent_id,
        "added": True,
        "contradictions_found": len(contradictions),
        "contradictions": [c.to_dict() for c in contradictions],
        "consistency_score": conscience_monitor.temporal_checker.get_consistency_score(agent_id),
        "consistency_level": conscience_monitor.temporal_checker.get_consistency_level(agent_id).value,
    }


@app.get("/api/conscience/temporal/{agent_id}/contradictions")
async def conscience_temporal_contradictions(
    agent_id: str, auth: bool = Depends(require_auth)
):
    """Get all temporal contradictions for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_contradiction_history(agent_id)


# --- User Behavior Anomaly Detection endpoints (Phase 3.5) ---

@app.get("/api/conscience/users/{user_id}")
async def conscience_user_risk(user_id: str, auth: bool = Depends(require_auth)):
    """Get risk profile for a specific user."""
    if not user_tracker:
        return {"error": "User Behavior Tracker not available"}
    profile = user_tracker.get_user_profile(user_id)
    if not profile:
        return {"error": "User not found", "user_id": user_id}
    risk_score = user_tracker.get_user_risk_score(user_id)
    return {
        **profile.to_dict(),
        "is_adversarial": user_tracker.is_adversarial(user_id),
    }


@app.get("/api/conscience/users/{user_id}/history")
async def conscience_user_risk_history(user_id: str, auth: bool = Depends(require_auth)):
    """Get risk score history and trend for a user."""
    if not user_tracker:
        return {"error": "User Behavior Tracker not available"}
    return user_tracker.get_risk_history(user_id)


@app.get("/api/conscience/users/{user_id}/signals")
async def conscience_user_signals(user_id: str, auth: bool = Depends(require_auth)):
    """Get current anomaly signals for a user."""
    if not user_tracker:
        return {"error": "User Behavior Tracker not available"}
    signals = user_tracker.analyze_behavior(user_id)
    return {
        "user_id": user_id,
        "signals": [s.to_dict() for s in signals],
        "total": len(signals),
        "is_adversarial": user_tracker.is_adversarial(user_id),
        "risk_score": user_tracker.get_user_risk_score(user_id),
    }


@app.get("/api/conscience/user-tracker/list")
async def conscience_user_list(auth: bool = Depends(require_auth)):
    """List all tracked users with risk scores (sorted by risk desc)."""
    if not user_tracker:
        return {"error": "User Behavior Tracker not available", "users": []}
    users = user_tracker.list_users()
    return {
        "users": users,
        "total": len(users),
    }


# --- Escalation Protocol endpoints (Phase 3.6) ---

class EscalationSignalsInput(BaseModel):
    """Input for manual escalation evaluation."""
    drift_score: float = 0.0
    tamas_state: str = "sattva"
    consistency_level: str = "highly_consistent"
    user_risk_score: float = 0.0
    violation_rate: float = 0.0
    session_id: str = ""
    agent_id: str = ""


@app.post("/api/conscience/escalation/evaluate")
async def escalation_evaluate(data: EscalationSignalsInput, auth: bool = Depends(require_auth)):
    """Evaluate escalation from provided signals."""
    if not escalation_chain:
        return {"error": "Escalation Chain not available"}
    from brahmanda.escalation import EscalationChain as EC
    signals = EC.build_signals(
        drift_score=data.drift_score,
        tamas_state=data.tamas_state,
        consistency_level=data.consistency_level,
        user_risk_score=data.user_risk_score,
        violation_rate=data.violation_rate,
    )
    decision = escalation_chain.evaluate(
        signals, session_id=data.session_id, agent_id=data.agent_id
    )
    return decision.to_dict()


@app.get("/api/conscience/escalation/{agent_id}")
async def escalation_agent(agent_id: str, session_id: str = "", auth: bool = Depends(require_auth)):
    """Get escalation decision for an agent using all available signals."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    user_risk = 0.0
    if user_tracker and session_id:
        # Try to find user risk from session events
        pass
    return conscience_monitor.evaluate_escalation(
        agent_id, session_id=session_id, user_risk_score=user_risk
    )


@app.get("/api/conscience/escalation/history")
async def escalation_history(limit: int = 50, auth: bool = Depends(require_auth)):
    """Get recent escalation decisions."""
    if not escalation_chain:
        return {"error": "Escalation Chain not available", "decisions": []}
    return {
        "decisions": escalation_chain.get_decision_history(limit=limit),
        "total": len(escalation_chain.get_decision_history(limit=limit)),
    }


@app.get("/api/conscience/escalation/config")
async def escalation_config(auth: bool = Depends(require_auth)):
    """Get current escalation configuration."""
    if not escalation_chain:
        return {"error": "Escalation Chain not available"}
    return escalation_chain.config.to_dict()


# --- Compliance Reporting endpoints (Phase 4.3) ---

try:
    from brahmanda.compliance import ReportGenerator, ReportType, ReportFormat, generate_report
    _compliance_available = True
except ImportError:
    _compliance_available = False
    logger.warning("Compliance module not available")

# Initialize ReportGenerator
report_generator = None
if _compliance_available:
    try:
        report_generator = ReportGenerator(
            mutation_tracker=None,  # Wired per-request if available
            audit_trail=brahmanda_verifier.brahmanda.attribution.audit if hasattr(brahmanda_verifier.brahmanda, 'attribution') else None,
            conscience_monitor=conscience_monitor,
            user_tracker=user_tracker,
        )
        logger.info("Report Generator initialized (Phase 4.3)")
    except Exception as e:
        logger.warning(f"Report Generator init failed: {e}")


class ReportGenerateInput(BaseModel):
    """Input for generating a compliance report."""
    report_type: str = "eu_ai_act"  # eu_ai_act, soc2, hipaa, custom
    output_format: str = "json"  # json, markdown, pdf
    title: Optional[str] = None
    custom_fields: Optional[dict] = None


@app.post("/api/reports/generate")
async def generate_compliance_report(data: ReportGenerateInput, auth: bool = Depends(require_auth)):
    """Generate a compliance report."""
    if not report_generator:
        return {"error": "Report Generator not available"}

    try:
        rtype = ReportType(data.report_type)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid report_type: {data.report_type}. Valid: {[r.value for r in ReportType]}")

    try:
        fmt = ReportFormat(data.output_format)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid output_format: {data.output_format}. Valid: {[f.value for f in ReportFormat]}")

    report = report_generator.generate(
        report_type=rtype,
        title=data.title,
        custom_fields=data.custom_fields,
    )

    if fmt == ReportFormat.MARKDOWN:
        from fastapi.responses import Response
        return Response(content=report.to_markdown(), media_type="text/markdown")
    elif fmt == ReportFormat.PDF:
        result = report.to_dict()
        result["pdf_placeholder"] = True
        result["pdf_note"] = "PDF generation requires weasyprint or reportlab."
        return result
    else:
        return report.to_dict()


@app.get("/api/reports/types")
async def report_types(auth: bool = Depends(require_auth)):
    """List available report types and formats."""
    return {
        "report_types": [r.value for r in ReportType],
        "output_formats": [f.value for f in ReportFormat],
    }


# --- Webhook Notification endpoints (Phase 4.4) ---

try:
    from brahmanda.webhooks import (
        WebhookManager, WebhookConfig, WebhookEvent, WebhookEventType,
        get_webhook_manager, reset_webhook_manager,
    )
    _webhooks_available = True
except ImportError:
    _webhooks_available = False
    logger.warning("Webhook module not available")

# Initialize WebhookManager
if _webhooks_available:
    try:
        webhook_manager = get_webhook_manager(
            db_path=os.path.join(data_dir, "webhooks.db")
        )
        # Wire into guard
        guard.webhook_manager = webhook_manager
        # Wire into escalation chain
        if escalation_chain:
            escalation_chain.webhook_manager = webhook_manager
        logger.info("Webhook Manager initialized (Phase 4.4)")
    except Exception as e:
        logger.warning(f"Webhook Manager init failed: {e}")


class WebhookCreateInput(BaseModel):
    """Input for creating a webhook."""
    url: str
    secret: str = ""
    events: List[str] = []
    tenant_id: str = ""
    active: bool = True
    description: str = ""


class WebhookUpdateInput(BaseModel):
    """Input for updating a webhook."""
    url: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[List[str]] = None
    active: Optional[bool] = None
    description: Optional[str] = None


@app.post("/api/webhooks")
async def create_webhook(data: WebhookCreateInput, auth: bool = Depends(require_auth)):
    """Register a new webhook endpoint."""
    if not webhook_manager:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Webhook manager not available")
    try:
        events = [WebhookEventType(e) for e in data.events]
    except ValueError as e:
        from fastapi import HTTPException
        valid = [e.value for e in WebhookEventType]
        raise HTTPException(status_code=400, detail=f"Invalid event type. Valid: {valid}")
    config = WebhookConfig(
        url=data.url,
        secret=data.secret,
        events=events,
        tenant_id=data.tenant_id,
        active=data.active,
        description=data.description,
    )
    saved = webhook_manager.register(config)
    return saved.to_dict()


@app.get("/api/webhooks")
async def list_webhooks(tenant_id: Optional[str] = None, auth: bool = Depends(require_auth)):
    """List all registered webhooks."""
    if not webhook_manager:
        return {"error": "Webhook manager not available", "webhooks": []}
    hooks = webhook_manager.list(tenant_id=tenant_id)
    return {
        "webhooks": [h.to_dict() for h in hooks],
        "total": len(hooks),
    }


@app.get("/api/webhooks/{webhook_id}")
async def get_webhook(webhook_id: str, auth: bool = Depends(require_auth)):
    """Get a specific webhook configuration."""
    if not webhook_manager:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Webhook manager not available")
    config = webhook_manager.get(webhook_id)
    if not config:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Webhook not found")
    return config.to_dict()


@app.put("/api/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, data: WebhookUpdateInput, auth: bool = Depends(require_auth)):
    """Update a webhook configuration."""
    if not webhook_manager:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Webhook manager not available")
    kwargs = {}
    if data.url is not None:
        kwargs["url"] = data.url
    if data.secret is not None:
        kwargs["secret"] = data.secret
    if data.events is not None:
        try:
            kwargs["events"] = [WebhookEventType(e) for e in data.events]
        except ValueError:
            from fastapi import HTTPException
            valid = [e.value for e in WebhookEventType]
            raise HTTPException(status_code=400, detail=f"Invalid event type. Valid: {valid}")
    if data.active is not None:
        kwargs["active"] = data.active
    if data.description is not None:
        kwargs["description"] = data.description
    updated = webhook_manager.update(webhook_id, **kwargs)
    if not updated:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Webhook not found")
    return updated.to_dict()


@app.delete("/api/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, auth: bool = Depends(require_auth)):
    """Deregister a webhook endpoint."""
    if not webhook_manager:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Webhook manager not available")
    deleted = webhook_manager.deregister(webhook_id)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "deleted", "webhook_id": webhook_id}


@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str, auth: bool = Depends(require_auth)):
    """Send a test event to a webhook endpoint."""
    if not webhook_manager:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Webhook manager not available")
    config = webhook_manager.get(webhook_id)
    if not config:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Webhook not found")
    test_event = WebhookEvent(
        event_type=WebhookEventType.RULE_VIOLATION,
        payload={"test": True, "message": "This is a test webhook delivery"},
        tenant_id=config.tenant_id,
    )
    webhook_manager.fire(test_event)
    return {"status": "test_sent", "webhook_id": webhook_id, "event_id": test_event.event_id}


@app.post("/api/login")
async def login(req: LoginRequest):
    """Authenticate with a token. Returns a session ID."""
    auth_mgr = get_auth_manager()
    if auth_mgr.verify_token(req.token):
        session_id = auth_mgr.create_session()
        # Try to extract tenant_id from JWT payload
        tenant_id = None
        from dashboard.auth import _decode_jwt_payload, _extract_tenant_from_payload
        payload = _decode_jwt_payload(req.token)
        if payload:
            tenant_id = _extract_tenant_from_payload(payload)
        return LoginResponse(
            session_id=session_id,
            expires_in=auth_mgr.config.session_ttl,
            tenant_id=tenant_id,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/api/auth/status")
async def auth_status():
    """Check if auth is enabled."""
    auth_mgr = get_auth_manager()
    return {
        "enabled": auth_mgr.config.enabled,
        "token_set": auth_mgr._token is not None
    }


# --- SSO endpoints (Phase 4.5) ---

class SSOLoginInput(BaseModel):
    """Input for SSO login redirect."""
    tenant_id: str = ""
    provider_name: str = ""


class SSOCallbackInput(BaseModel):
    """Input for SSO callback processing."""
    code: str
    state: Optional[str] = None
    tenant_id: str = ""
    provider_name: str = ""


class SSOProviderCreateInput(BaseModel):
    """Input for registering an SSO provider."""
    provider_type: str = "oidc"  # oidc or saml
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list = ["openid", "profile", "email"]
    tenant_id: str = ""
    provider_name: str = ""
    saml_entity_id: str = ""
    saml_sso_url: str = ""
    extra: Optional[dict] = None


@app.get("/api/sso/login")
async def sso_login(tenant_id: str = "", provider_name: str = ""):
    """Get SSO login URL for a tenant/provider. Redirects to SSO provider."""
    sso = get_sso_auth()
    url = sso.get_login_url(tenant_id=tenant_id, provider_name=provider_name)
    if url:
        return {"login_url": url, "tenant_id": tenant_id, "provider_name": provider_name}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="No SSO provider configured for this tenant")


@app.post("/api/sso/callback")
async def sso_callback(data: SSOCallbackInput):
    """Process SSO callback — exchange auth code for session."""
    sso = get_sso_auth()
    try:
        result = sso.process_callback(
            code=data.code,
            state=data.state,
            tenant_id=data.tenant_id,
            provider_name=data.provider_name,
        )
        return result
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/sso/providers")
async def sso_list_providers(tenant_id: str = ""):
    """List SSO providers, optionally filtered by tenant."""
    try:
        from brahmanda.sso import get_sso_manager
        manager = get_sso_manager()
        if tenant_id:
            providers = manager.get_providers_for_tenant(tenant_id)
        else:
            providers = manager.get_all_providers()
        return {
            "providers": [p.config.to_dict() for p in providers],
            "total": len(providers),
            "configured": len(providers) > 0,
        }
    except ImportError:
        return {"providers": [], "total": 0, "configured": False}


@app.post("/api/sso/providers")
async def sso_create_provider(data: SSOProviderCreateInput, auth: bool = Depends(require_auth)):
    """Register a new SSO provider."""
    try:
        from brahmanda.sso import (
            get_sso_manager, SSOProviderType, SSOConfig,
            create_oidc_config, create_saml_config,
        )
        manager = get_sso_manager()

        try:
            ptype = SSOProviderType(data.provider_type)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider_type: {data.provider_type}. Valid: {[t.value for t in SSOProviderType]}"
            )

        config = SSOConfig(
            provider_type=ptype,
            issuer_url=data.issuer_url,
            client_id=data.client_id,
            client_secret=data.client_secret,
            redirect_uri=data.redirect_uri,
            scopes=data.scopes,
            tenant_id=data.tenant_id,
            provider_name=data.provider_name,
            saml_entity_id=data.saml_entity_id,
            saml_sso_url=data.saml_sso_url,
            extra=data.extra or {},
        )
        provider = manager.register_provider(config)
        return {"status": "registered", "provider": config.to_dict()}
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="SSO module not available")


@app.delete("/api/sso/providers/{tenant_id}/{provider_name}")
async def sso_delete_provider(tenant_id: str, provider_name: str, auth: bool = Depends(require_auth)):
    """Remove an SSO provider."""
    try:
        from brahmanda.sso import get_sso_manager
        manager = get_sso_manager()
        if manager.remove_provider(tenant_id, provider_name):
            return {"status": "removed", "tenant_id": tenant_id, "provider_name": provider_name}
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Provider not found")
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="SSO module not available")


@app.get("/api/sso/session/{session_id}")
async def sso_verify_session(session_id: str):
    """Verify an SSO session."""
    sso = get_sso_auth()
    session = sso.verify_sso_session(session_id)
    if session:
        return {"valid": True, "user": session}
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="Invalid or expired SSO session")


# --- Rate Limiting endpoints (Phase 4.7) ---


@app.get("/api/rate-limit/status")
async def rate_limit_status(tenant_id: str = "", auth: bool = Depends(require_auth)):
    """Get rate limit and quota status for a tenant."""
    if not rate_limiter:
        return {"enabled": False, "message": "Rate limiting not configured"}
    result = {"enabled": True}
    if tenant_id:
        result["quotas"] = {
            k: v.to_dict() for k, v in rate_limiter.get_quota_status(tenant_id).items()
        }
    return result


@app.post("/api/rate-limit/configure")
async def rate_limit_configure(
    tenant_id: str = "",
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
    burst_size: int = 10,
    max_facts_per_day: int = 10000,
    max_agents: int = 100,
    max_webhooks: int = 50,
    auth: bool = Depends(require_auth),
):
    """Configure per-tenant rate limits and quotas."""
    if not rate_limiter:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Rate limiting not configured")
    if not tenant_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="tenant_id required")
    rl_config = RateLimitConfig(
        requests_per_minute=requests_per_minute,
        requests_per_hour=requests_per_hour,
        burst_size=burst_size,
    )
    q_config = QuotaConfig(
        max_facts_per_day=max_facts_per_day,
        max_agents=max_agents,
        max_webhooks=max_webhooks,
    )
    rate_limiter.configure_tenant(tenant_id, rate_limit=rl_config, quota=q_config)
    return {"status": "configured", "tenant_id": tenant_id, "rate_limit": rl_config.to_dict(), "quota": q_config.to_dict()}


# --- SLA Monitoring endpoints (Phase 4.8) ---

@app.get("/api/sla/status")
async def sla_status(auth: bool = Depends(require_auth)):
    """Get current SLA status for all tracked metrics."""
    if not sla_tracker:
        return {"enabled": False, "metrics": [], "message": "SLA monitoring not configured"}
    metrics = sla_tracker.get_sla_status()
    return {
        "enabled": True,
        "metrics": [m.to_dict() for m in metrics],
        "breached": [m.name for m in metrics if m.status == "breached"],
        "total_breaches": sla_tracker.get_breach_count(),
    }


@app.get("/api/sla/metrics/{metric_name}")
async def sla_metric(metric_name: str, auth: bool = Depends(require_auth)):
    """Get a specific SLA metric by name."""
    if not sla_tracker:
        return {"error": "SLA monitoring not configured"}
    metrics = sla_tracker.get_sla_status()
    for m in metrics:
        if m.name == metric_name:
            return m.to_dict()
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Metric not found: {metric_name}")


@app.get("/api/sla/breaches")
async def sla_breaches(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    auth: bool = Depends(require_auth),
):
    """Get SLA breaches within a date range."""
    if not sla_tracker:
        return {"breaches": [], "total": 0}
    breaches = sla_tracker.get_sla_breaches(from_date=from_date, to_date=to_date)
    return {
        "breaches": [b.to_dict() for b in breaches],
        "total": len(breaches),
    }


@app.get("/api/sla/stats")
async def sla_stats(auth: bool = Depends(require_auth)):
    """Get raw SLA statistics: request count, kill count, uptime, response time."""
    if not sla_tracker:
        return {"enabled": False}
    return {
        "enabled": True,
        "request_count": sla_tracker.get_request_count(),
        "kill_count": sla_tracker.get_kill_count(),
        "breach_count": sla_tracker.get_breach_count(),
        "uptime_percentage": sla_tracker.get_uptime_percentage(),
        "avg_response_time_ms": sla_tracker.get_avg_response_time(),
        "kill_rate": sla_tracker.get_kill_rate(),
        "false_positive_rate": sla_tracker.get_false_positive_rate(),
        "mean_time_to_detect_ms": sla_tracker.get_mean_time_to_detect(),
    }


# --- Prometheus Metrics endpoint (Phase 6.2) ---

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Expose Prometheus metrics. Requires METRICS_ENABLED=true."""
    if not _metrics_enabled:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "# Metrics disabled. Set METRICS_ENABLED=true to enable.\n",
            status_code=404,
        )
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from fastapi.responses import Response
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )
    except ImportError:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "# prometheus_client not installed\n",
            status_code=500,
        )


# --- Drift/Tamas metrics update hooks (Phase 6.2) ---

# Update drift/tamas gauges when those endpoints are queried
_orig_drift_record = None
_orig_tamas_eval = None


# ─── Phase 9: Plugin Marketplace API ───────────────────────────────────

# Initialize plugin manager (lazy)
_plugin_manager = None

def get_plugin_manager():
    global _plugin_manager
    if _plugin_manager is None:
        from discus.plugins import PluginManager
        _plugin_manager = PluginManager()
        _plugin_manager.load_all()
    return _plugin_manager


@app.get("/api/plugins")
async def list_plugins(category: str = "", auth: bool = Depends(require_auth)):
    """List all installed plugins."""
    pm = get_plugin_manager()
    plugins = pm.list_plugins(category=category or None)
    stats = pm.get_stats()
    return {
        "plugins": [p.to_dict() for p in plugins],
        "total": len(plugins),
        "stats": stats,
    }


@app.get("/api/plugins/{plugin_id}")
async def get_plugin(plugin_id: str, auth: bool = Depends(require_auth)):
    """Get plugin details."""
    pm = get_plugin_manager()
    plugin = pm.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_id}")
    return plugin.to_dict()


@app.post("/api/plugins/install")
async def install_plugin(data: dict, auth: bool = Depends(require_auth)):
    """Install a plugin from a source directory."""
    source = data.get("source_dir", "")
    if not source:
        raise HTTPException(status_code=400, detail="source_dir is required")
    try:
        pm = get_plugin_manager()
        plugin = pm.install_plugin(source)
        return {"status": "installed", "plugin": plugin.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/plugins/{plugin_id}")
async def delete_plugin(plugin_id: str, auth: bool = Depends(require_auth)):
    """Uninstall a plugin."""
    pm = get_plugin_manager()
    if pm.uninstall_plugin(plugin_id):
        return {"status": "uninstalled", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_id}")


@app.post("/api/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str, auth: bool = Depends(require_auth)):
    """Enable a plugin."""
    pm = get_plugin_manager()
    if pm.enable_plugin(plugin_id):
        return {"status": "enabled", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_id}")


@app.post("/api/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str, auth: bool = Depends(require_auth)):
    """Disable a plugin."""
    pm = get_plugin_manager()
    if pm.disable_plugin(plugin_id):
        return {"status": "disabled", "plugin_id": plugin_id}
    raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_id}")


@app.post("/api/plugins/{plugin_id}/test")
async def test_plugin(plugin_id: str, auth: bool = Depends(require_auth)):
    """Run tests for a plugin."""
    pm = get_plugin_manager()
    result = pm.test_plugin(plugin_id)
    return result


@app.get("/api/plugins/runs/recent")
async def plugin_runs(plugin_id: str = "", limit: int = 50, auth: bool = Depends(require_auth)):
    """Get recent plugin runs."""
    from discus.plugins import PluginRegistry
    registry = PluginRegistry()
    runs = registry.get_runs(plugin_id=plugin_id or None, limit=limit)
    return {"runs": runs, "total": len(runs)}


@app.get("/api/plugins/stats/summary")
async def plugin_stats(auth: bool = Depends(require_auth)):
    """Get plugin statistics."""
    pm = get_plugin_manager()
    return pm.get_stats()


@app.post("/api/plugins/validate")
async def validate_plugin(data: dict, auth: bool = Depends(require_auth)):
    """Validate a plugin directory without installing."""
    source = data.get("source_dir", "")
    if not source:
        raise HTTPException(status_code=400, detail="source_dir is required")
    try:
        from pathlib import Path
        from discus.plugins import PluginManifest, PluginSandbox
        manifest = PluginManifest.from_yaml(Path(source) / "plugin.yaml")
        sandbox = PluginSandbox()
        entry = Path(source) / manifest.entry_point
        if entry.exists():
            issues = sandbox.validate_ast(entry.read_text(), str(entry))
            return {
                "valid": len(issues) == 0,
                "manifest": manifest.to_dict(),
                "issues": issues,
            }
        return {"valid": False, "manifest": manifest.to_dict(), "issues": [f"Entry point not found: {manifest.entry_point}"]}
    except Exception as e:
        return {"valid": False, "issues": [str(e)]}


# ─── Phase 10: Federation API ─────────────────────────────────────────

_federation_server = None

def get_federation_server():
    global _federation_server
    if _federation_server is None:
        from discus.federation import AggregationServer, PrivacyMode
        privacy_mode = os.getenv("FEDERATION_PRIVACY_MODE", "balanced")
        _federation_server = AggregationServer(
            node_id=os.getenv("FEDERATION_NODE_ID", "default"),
            privacy_mode=PrivacyMode(privacy_mode),
        )
    return _federation_server


@app.get("/api/federation/stats")
async def federation_stats(auth: bool = Depends(require_auth)):
    """Get federation statistics."""
    fs = get_federation_server()
    return fs.get_stats()


@app.get("/api/federation/nodes")
async def federation_nodes(auth: bool = Depends(require_auth)):
    """List federation nodes."""
    fs = get_federation_server()
    return {"nodes": fs.list_nodes()}


@app.post("/api/federation/nodes/register")
async def federation_register_node(data: dict):
    """Register a federation node."""
    from discus.federation import FederationNode
    fs = get_federation_server()
    node = FederationNode(
        node_id=data["node_id"],
        url=data.get("url", ""),
        privacy_mode=data.get("privacy_mode", "balanced"),
    )
    return fs.register_node(node)


@app.post("/api/federation/nodes/heartbeat")
async def federation_heartbeat(data: dict):
    """Process node heartbeat."""
    fs = get_federation_server()
    return fs.heartbeat(data["node_id"])


@app.post("/api/federation/fingerprints/submit")
async def federation_submit_fingerprints(data: dict):
    """Submit anonymized fingerprints."""
    fs = get_federation_server()
    return fs.submit_fingerprints(data["node_id"], data["fingerprints"])


@app.post("/api/federation/aggregate")
async def federation_aggregate(auth: bool = Depends(require_auth)):
    """Run global aggregation."""
    fs = get_federation_server()
    result = fs.run_aggregation()
    return result.to_dict()


@app.post("/api/federation/threats/submit")
async def federation_submit_threat(data: dict):
    """Submit a threat signature."""
    fs = get_federation_server()
    return fs.submit_threat(data["node_id"], data["threat"])


@app.get("/api/federation/threats")
async def federation_get_threats(threat_type: str = "", min_confidence: float = 0.0, auth: bool = Depends(require_auth)):
    """Get shared threat intelligence."""
    fs = get_federation_server()
    threats = fs.get_threat_intel(
        threat_type=threat_type or None,
        min_confidence=min_confidence,
    )
    return {"threats": threats, "total": len(threats)}


@app.get("/api/federation/anomaly/{node_id}")
async def federation_node_anomaly(node_id: str, auth: bool = Depends(require_auth)):
    """Get anomaly assessment for a node."""
    fs = get_federation_server()
    return fs.get_node_anomaly(node_id)


@app.get("/api/federation/baseline")
async def federation_baseline(auth: bool = Depends(require_auth)):
    """Get current global baseline."""
    fs = get_federation_server()
    result = fs.run_aggregation()
    return {"baseline_vector": result.baseline_vector, "participant_count": result.participant_count}


@app.get("/api/federation/privacy/{node_id}")
async def federation_privacy_status(node_id: str, auth: bool = Depends(require_auth)):
    """Get privacy budget status for a node."""
    fs = get_federation_server()
    budget = fs.privacy.budget
    return {
        "node_id": node_id,
        "mode": fs.config.mode.value,
        "epsilon": fs.config.epsilon,
        "max_budget": fs.config.max_budget,
        "budget_remaining": budget.remaining(node_id),
        "budget_used": budget.used(node_id),
        "queries": budget.query_count(node_id),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time event streaming."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            # Keep connection alive, listen for messages
            data = await websocket.receive_text()
            # Could handle commands from frontend here
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def broadcast_event(event_data: dict):
    """Broadcast an event to all connected websocket clients."""
    message = json.dumps(event_data, default=str)
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
