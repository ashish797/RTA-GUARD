"""
RTA-GUARD WebSocket Event Protocol — 36-Channel Real-Time Streaming.

Provides structured event channels for the RTA-GUARD dashboard WebSocket
connection, supporting 36 distinct event types across security, behavioral,
and governance categories.

Channel Map:
    0x01-0x0C: Security & Rule Events (12 channels)
    0x0D-0x12: Behavioral Analysis (6 channels)  
    0x13-0x18: Drift & Governance (6 channels)
    0x19-0x1E: Infrastructure (6 channels)
    0x1F-0x24: System & Meta (6 channels)

Usage:
    from dashboard.ws_protocol import WSEventProtocol, EventChannel

    protocol = WSEventProtocol()
    await protocol.broadcast(EventChannel.PII_DETECTED, {
        "session_id": "abc123",
        "field": "email",
        "confidence": 0.98,
    })
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Set, Union

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("rta.ws_protocol")


class EventChannel(IntEnum):
    """36-channel event types for RTA-GUARD WebSocket protocol."""

    # ── Security & Rule Events (0x01-0x0C) ─────────────────────────────
    PII_DETECTED = 0x01           # PII leak detected (email, SSN, CC, phone)
    INJECTION_ATTEMPT = 0x02      # Prompt injection / jailbreak attempt
    HALLUCINATION_DETECTED = 0x03 # Hallucination / fabricated facts
    POLICY_VIOLATION = 0x04       # Custom policy rule violation
    SESSION_KILLED = 0x05         # Session terminated by guard
    SESSION_WARNED = 0x06         # Warning issued (not killed)
    SESSION_PASSED = 0x07         # Input passed all checks
    RULE_TRIGGERED = 0x08         # Specific rule fired
    RULE_UPDATED = 0x09           # Rule configuration changed
    CHECK_COMPLETED = 0x0A        # Full check pipeline completed
    THRESHOLD_EXCEEDED = 0x0B     # Rate/count threshold breached
    ANOMALY_SCORED = 0x0C         # Anomaly score calculated

    # ── Behavioral Analysis (0x0D-0x12) ────────────────────────────────
    USER_BEHAVIOR_ANOMALY = 0x0D  # User behavior deviation detected
    SESSION_PATTERN = 0x0E        # Session pattern analysis result
    ESCALATION_TRIGGERED = 0x0F   # Escalation chain activated
    ESCALATION_RESOLVED = 0x10    # Escalation resolved
    TAMAS_EVALUATED = 0x11        # Tamas (inertia) score evaluated
    TEMPORAL_ANOMALY = 0x12       # Temporal consistency check result

    # ── Drift & Governance (0x13-0x18) ────────────────────────────────
    DRIFT_RECORDED = 0x13         # Model drift score recorded
    DRIFT_ALERT = 0x14            # Drift threshold alert
    CONSCIENCE_CHECK = 0x15       # Conscience monitor check result
    RTA_VERDICT = 0x16            # RTA constitutional verdict
    COMPLIANCE_CHECK = 0x17       # Compliance template check
    AUDIT_LOG = 0x18              # Audit trail entry

    # ── Infrastructure (0x19-0x1E) ────────────────────────────────────
    WEBHOOK_FIRED = 0x19          # Webhook dispatched
    WEBHOOK_FAILED = 0x1A         # Webhook delivery failed
    RATE_LIMIT_HIT = 0x1B         # Rate limit triggered
    SLA_BREACH = 0x1C             # SLA breach detected
    METRIC_RECORDED = 0x1D        # Metric data point
    HEALTH_CHECK = 0x1E           # Health check result

    # ── System & Meta (0x1F-0x24) ────────────────────────────────────
    TENANT_EVENT = 0x1F           # Tenant-specific event
    AUTH_EVENT = 0x20             # Authentication event
    CONFIG_CHANGED = 0x21         # Configuration change
    SYSTEM_ERROR = 0x22           # System error event
    HEARTBEAT = 0x23              # Keepalive heartbeat
    CHANNEL_SUBSCRIBE = 0x24      # Client subscription change


# Channel name map for human-readable logging
CHANNEL_NAMES: Dict[EventChannel, str] = {ch: ch.name for ch in EventChannel}

# Severity levels for channels
CHANNEL_SEVERITY: Dict[EventChannel, str] = {
    EventChannel.PII_DETECTED: "critical",
    EventChannel.INJECTION_ATTEMPT: "critical",
    EventChannel.HALLUCINATION_DETECTED: "high",
    EventChannel.SESSION_KILLED: "critical",
    EventChannel.SESSION_WARNED: "warning",
    EventChannel.SESSION_PASSED: "info",
    EventChannel.DRIFT_ALERT: "high",
    EventChannel.SLA_BREACH: "high",
    EventChannel.RATE_LIMIT_HIT: "warning",
    EventChannel.ESCALATION_TRIGGERED: "high",
    EventChannel.SYSTEM_ERROR: "critical",
}


@dataclass
class WSEvent:
    """Structured WebSocket event."""
    channel: int
    channel_name: str
    timestamp: float
    data: Dict[str, Any]
    severity: str = "info"
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ClientSubscription:
    """Tracks what channels a WebSocket client is subscribed to."""

    def __init__(self, websocket: WebSocket, channels: Optional[Set[EventChannel]] = None):
        self.websocket = websocket
        self.channels = channels or set(EventChannel)  # Default: all channels
        self.connected_at = time.time()

    def is_subscribed(self, channel: EventChannel) -> bool:
        return channel in self.channels

    def subscribe(self, channel: EventChannel) -> None:
        self.channels.add(channel)

    def unsubscribe(self, channel: EventChannel) -> None:
        self.channels.discard(channel)


class WSEventProtocol:
    """
    36-channel WebSocket event protocol for RTA-GUARD.

    Manages client connections, channel subscriptions, and event broadcasting.
    Supports filtering by channel, tenant, and session.
    """

    def __init__(self) -> None:
        self._clients: Dict[WebSocket, ClientSubscription] = {}
        self._event_log: List[WSEvent] = []
        self._max_log_size: int = 10000
        self._handlers: Dict[EventChannel, List[Callable]] = {}

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket, channels: Optional[Set[EventChannel]] = None) -> None:
        """Accept a WebSocket connection and register the client."""
        await websocket.accept()
        sub = ClientSubscription(websocket, channels)
        self._clients[websocket] = sub
        logger.info(
            "WebSocket client connected (total: %d, channels: %d)",
            len(self._clients),
            len(sub.channels),
        )
        # Send subscription confirmation
        await self._send_to_client(websocket, WSEvent(
            channel=EventChannel.CHANNEL_SUBSCRIBE,
            channel_name="CHANNEL_SUBSCRIBE",
            timestamp=time.time(),
            data={
                "action": "connected",
                "subscribed_channels": [ch.name for ch in sub.channels],
                "total_channels": len(EventChannel),
            },
        ))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket client."""
        self._clients.pop(websocket, None)
        logger.info("WebSocket client disconnected (total: %d)", len(self._clients))

    async def handle_message(self, websocket: WebSocket, raw: str) -> None:
        """
        Handle an incoming message from a client.

        Supported commands:
            {"action": "subscribe", "channels": ["PII_DETECTED", ...]}
            {"action": "unsubscribe", "channels": ["PII_DETECTED", ...]}
            {"action": "ping"}
            {"action": "get_log", "limit": 100}
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        action = msg.get("action")
        sub = self._clients.get(websocket)
        if sub is None:
            return

        if action == "subscribe":
            channel_names = msg.get("channels", [])
            for name in channel_names:
                try:
                    ch = EventChannel[name]
                    sub.subscribe(ch)
                except KeyError:
                    pass
            await self._send_to_client(websocket, WSEvent(
                channel=EventChannel.CHANNEL_SUBSCRIBE,
                channel_name="CHANNEL_SUBSCRIBE",
                timestamp=time.time(),
                data={
                    "action": "subscribed",
                    "channels": [ch.name for ch in sub.channels],
                },
            ))

        elif action == "unsubscribe":
            channel_names = msg.get("channels", [])
            for name in channel_names:
                try:
                    ch = EventChannel[name]
                    sub.unsubscribe(ch)
                except KeyError:
                    pass
            await self._send_to_client(websocket, WSEvent(
                channel=EventChannel.CHANNEL_SUBSCRIBE,
                channel_name="CHANNEL_SUBSCRIBE",
                timestamp=time.time(),
                data={
                    "action": "unsubscribed",
                    "channels": [ch.name for ch in sub.channels],
                },
            ))

        elif action == "ping":
            await self._send_to_client(websocket, WSEvent(
                channel=EventChannel.HEARTBEAT,
                channel_name="HEARTBEAT",
                timestamp=time.time(),
                data={"pong": True},
            ))

        elif action == "get_log":
            limit = min(msg.get("limit", 100), 1000)
            events = self._event_log[-limit:]
            await self._send_to_client(websocket, WSEvent(
                channel=EventChannel.AUDIT_LOG,
                channel_name="AUDIT_LOG",
                timestamp=time.time(),
                data={
                    "events": [e.to_dict() for e in events],
                    "total": len(self._event_log),
                },
            ))

    def register_handler(self, channel: EventChannel, handler: Callable) -> None:
        """Register a local handler for a channel (for server-side processing)."""
        self._handlers.setdefault(channel, []).append(handler)

    async def broadcast(
        self,
        channel: EventChannel,
        data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Broadcast an event to all subscribed clients.

        Args:
            channel: The event channel to broadcast on.
            data: Event payload.
            tenant_id: Optional tenant filter.
            session_id: Optional session reference.
        """
        event = WSEvent(
            channel=int(channel),
            channel_name=channel.name,
            timestamp=time.time(),
            data=data,
            severity=CHANNEL_SEVERITY.get(channel, "info"),
            tenant_id=tenant_id,
            session_id=session_id,
        )

        # Log the event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

        # Run local handlers
        for handler in self._handlers.get(channel, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                logger.exception("Error in event handler for %s", channel.name)

        # Broadcast to subscribed clients
        disconnected: List[WebSocket] = []
        for websocket, sub in self._clients.items():
            if not sub.is_subscribed(channel):
                continue
            # Optional tenant filtering
            if tenant_id and hasattr(sub, 'tenant_filter') and sub.tenant_filter != tenant_id:
                continue
            try:
                await self._send_to_client(websocket, event)
            except Exception:
                disconnected.append(websocket)

        for ws in disconnected:
            await self.disconnect(ws)

    async def _send_to_client(self, websocket: WebSocket, event: WSEvent) -> None:
        """Send an event to a single client."""
        await websocket.send_text(event.to_json())

    async def broadcast_raw(self, data: Dict[str, Any]) -> None:
        """
        Broadcast raw dict to all clients (backward compatibility).

        Maps to CHECK_COMPLETED channel for legacy event format.
        """
        # Detect channel from data
        decision = data.get("decision", "")
        if decision == "kill":
            channel = EventChannel.SESSION_KILLED
        elif decision == "warn":
            channel = EventChannel.SESSION_WARNED
        elif decision == "pass":
            channel = EventChannel.SESSION_PASSED
        else:
            channel = EventChannel.CHECK_COMPLETED

        await self.broadcast(channel, data, session_id=data.get("session_id"))


# ---------------------------------------------------------------------------
# Singleton instance for dashboard
# ---------------------------------------------------------------------------

_protocol_instance: Optional[WSEventProtocol] = None


def get_protocol() -> WSEventProtocol:
    """Get or create the global WSEventProtocol instance."""
    global _protocol_instance
    if _protocol_instance is None:
        _protocol_instance = WSEventProtocol()
    return _protocol_instance
