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
from dashboard.auth import init_auth, require_auth, AuthConfig, LoginRequest, LoginResponse, get_auth_manager

app = FastAPI(title="RTA-GUARD Dashboard", version="0.1.0")

# Initialize auth (set DASHBOARD_TOKEN env var, or auto-generates one)
auth_config = AuthConfig(
    enabled=os.getenv("DASHBOARD_AUTH", "true").lower() == "true",
    api_token=os.getenv("DASHBOARD_TOKEN")
)
auth = init_auth(auth_config)

# Initialize RTA engine (draft rules)
rta_engine = RtaEngine(GuardConfig(log_all=True))

# Global guard instance for the dashboard — WITH RTA enabled
guard = DiscusGuard(GuardConfig(log_all=True), rta_engine=rta_engine)

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

@app.post("/api/login")
async def login(req: LoginRequest):
    """Authenticate with a token. Returns a session ID."""
    auth_mgr = get_auth_manager()
    if auth_mgr.verify_token(req.token):
        session_id = auth_mgr.create_session()
        return LoginResponse(
            session_id=session_id,
            expires_in=auth_mgr.config.session_ttl
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
