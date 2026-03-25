"""
RTA-GUARD Dashboard — FastAPI Server

Real-time dashboard showing blocked sessions, violations, and events.
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
import logging
logger = logging.getLogger(__name__)
sys.path.insert(0, str(Path(__file__).parent.parent))
from discus import DiscusGuard, GuardConfig, RtaEngine

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

from dashboard.auth import init_auth, require_auth, require_auth_with_tenant, require_permission, AuthConfig, LoginRequest, LoginResponse, get_auth_manager

app = FastAPI(title="RTA-GUARD Dashboard", version="0.1.0")

# Initialize auth (set DASHBOARD_TOKEN env var, or auto-generates one)
auth_config = AuthConfig(
    enabled=os.getenv("DASHBOARD_AUTH", "true").lower() == "true",
    api_token=os.getenv("DASHBOARD_TOKEN")
)
auth = init_auth(auth_config)

# Initialize Tenant Manager (Phase 4.1)
from brahmanda.tenancy import TenantManager, get_tenant_manager, validate_tenant_id
data_dir = os.getenv("RTA_DATA_DIR", "data")
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
                    escalation_chain=escalation_chain)

# Connected websocket clients
connected_clients: list[WebSocket] = []

# Mount static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class EventInput(BaseModel):
    """Manual event input for testing."""
    session_id: str
    input_text: str


@app.get("/")
async def dashboard():
    """Serve the dashboard HTML."""
    html_path = static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>RTA-GUARD Dashboard</h1><p>Dashboard loading...</p>")


@app.get("/api/events")
async def get_events(session_id: Optional[str] = None, auth: bool = Depends(require_auth)):
    """Get all events, optionally filtered by session."""
    events = guard.get_events(session_id)
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "total": len(events)
    }


@app.get("/api/killed")
async def get_killed_sessions(auth: bool = Depends(require_auth)):
    """Get all killed sessions."""
    killed = guard.get_killed_sessions()
    return {
        "killed_sessions": list(killed),
        "total": len(killed)
    }


@app.get("/api/stats")
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


@app.post("/api/check")
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


@app.post("/api/reset/{session_id}")
async def reset_session(session_id: str, auth: bool = Depends(require_auth)):
    """Reset a killed session."""
    guard.reset_session(session_id)
    return {"status": "ok", "session_id": session_id}


# --- Brahmanda Map endpoints ---

class VerifyInput(BaseModel):
    """Text to verify against ground truth."""
    text: str
    domain: str = "general"


@app.post("/api/brahmanda/verify")
async def brahmanda_verify(input_data: VerifyInput, auth: bool = Depends(require_auth)):
    """Verify text against the Brahmanda Map (ground truth)."""
    result = brahmanda_verifier.verify(input_data.text, domain=input_data.domain)
    return result.to_dict()


@app.post("/api/brahmanda/pipeline-verify")
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
    return conscience_monitor.record_drift(
        agent_id=data.agent_id,
        session_id=data.session_id,
        components=data.components.model_dump(),
    )


# --- Tamas Detection endpoints (Phase 3.3) ---

@app.get("/api/conscience/tamas/{agent_id}")
async def conscience_tamas(agent_id: str, auth: bool = Depends(require_auth)):
    """Get current Tamas state for an agent."""
    if not conscience_monitor:
        return {"error": "Conscience Monitor not available"}
    return conscience_monitor.get_tamas_state(agent_id)


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
