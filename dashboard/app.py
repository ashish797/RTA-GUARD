"""
RTA-GUARD Dashboard — FastAPI Server

Real-time dashboard showing blocked sessions, violations, and events.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from discus import DiscusGuard, GuardConfig

app = FastAPI(title="RTA-GUARD Dashboard", version="0.1.0")

# Global guard instance for the dashboard
guard = DiscusGuard(GuardConfig(log_all=True))

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
async def get_events(session_id: Optional[str] = None):
    """Get all events, optionally filtered by session."""
    events = guard.get_events(session_id)
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "total": len(events)
    }


@app.get("/api/killed")
async def get_killed_sessions():
    """Get all killed sessions."""
    killed = guard.get_killed_sessions()
    return {
        "killed_sessions": list(killed),
        "total": len(killed)
    }


@app.get("/api/stats")
async def get_stats():
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
async def check_input(event_input: EventInput):
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
async def reset_session(session_id: str):
    """Reset a killed session."""
    guard.reset_session(session_id)
    return {"status": "ok", "session_id": session_id}


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
