"""
RTA-GUARD — Webhook Notifications (Phase 4.4)

Push notifications to external systems when RTA-GUARD detects violations,
escalations, Tamas state changes, or other anomalies.

Features:
  - HMAC-SHA256 signature verification for payload integrity
  - Fire-and-forget async HTTP POST with exponential backoff retry
  - SQLite persistence for webhook configurations
  - Event type filtering (only receive events you care about)
  - Tenant-scoped webhooks

Event Types:
  - RULE_VIOLATION: DiscusGuard killed or warned a session
  - DRIFT_ALERT: Live drift score exceeded threshold
  - TAMAS_DETECTED: Agent entered degraded (Tamas) state
  - USER_ANOMALY: User behavior anomaly detected
  - ESCALATION: Escalation chain triggered an action
  - SESSION_KILL: Session was terminated
  - AUDIT_ANOMALY: Audit trail integrity issue
"""
import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)

# ─── Event Types ──────────────────────────────────────────────────


class WebhookEventType(str, Enum):
    """Types of events that can trigger webhook notifications."""
    RULE_VIOLATION = "rule_violation"
    DRIFT_ALERT = "drift_alert"
    TAMAS_DETECTED = "tamas_detected"
    USER_ANOMALY = "user_anomaly"
    ESCALATION = "escalation"
    SESSION_KILL = "session_kill"
    AUDIT_ANOMALY = "audit_anomaly"


# ─── Data Models ──────────────────────────────────────────────────


@dataclass
class WebhookConfig:
    """Configuration for a registered webhook endpoint."""
    id: str = field(default_factory=lambda: f"wh-{uuid.uuid4().hex[:12]}")
    url: str = ""
    secret: str = ""
    events: List[WebhookEventType] = field(default_factory=lambda: list(WebhookEventType))
    tenant_id: str = ""
    active: bool = True
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "events": [e.value for e in self.events],
            "tenant_id": self.tenant_id,
            "active": self.active,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "has_secret": bool(self.secret),
        }


@dataclass
class WebhookEvent:
    """An event to be dispatched to webhook endpoints."""
    event_type: WebhookEventType = WebhookEventType.RULE_VIOLATION
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "tenant_id": self.tenant_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ─── Signature Utilities ──────────────────────────────────────────


def compute_signature(payload_json: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload_json: str, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature of a webhook payload."""
    expected = compute_signature(payload_json, secret)
    return hmac.compare_digest(expected, signature)


# ─── SQLite Persistence ───────────────────────────────────────────

WEBHOOK_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS webhook_configs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    events TEXT NOT NULL DEFAULT '[]',
    tenant_id TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_tenant ON webhook_configs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhook_active ON webhook_configs(active);
"""


class WebhookStore:
    """SQLite persistence for webhook configurations."""

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(WEBHOOK_SCHEMA_SQL)

    def save(self, config: WebhookConfig) -> WebhookConfig:
        """Save or update a webhook config."""
        self._conn.execute(
            """INSERT OR REPLACE INTO webhook_configs
               (id, url, secret, events, tenant_id, active, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config.id,
                config.url,
                config.secret,
                json.dumps([e.value for e in config.events]),
                config.tenant_id,
                1 if config.active else 0,
                config.description,
                config.created_at,
                config.updated_at,
            ),
        )
        self._conn.commit()
        return config

    def get(self, webhook_id: str) -> Optional[WebhookConfig]:
        """Get a webhook config by ID."""
        row = self._conn.execute(
            "SELECT * FROM webhook_configs WHERE id = ?", (webhook_id,)
        ).fetchone()
        if row:
            return self._row_to_config(row)
        return None

    def list(self, tenant_id: Optional[str] = None) -> List[WebhookConfig]:
        """List webhooks, optionally filtered by tenant."""
        if tenant_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM webhook_configs WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM webhook_configs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_config(r) for r in rows]

    def list_active(self, tenant_id: Optional[str] = None) -> List[WebhookConfig]:
        """List active webhooks, optionally filtered by tenant."""
        if tenant_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM webhook_configs WHERE active = 1 AND tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM webhook_configs WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_config(r) for r in rows]

    def delete(self, webhook_id: str) -> bool:
        """Delete a webhook config. Returns True if found."""
        cursor = self._conn.execute(
            "DELETE FROM webhook_configs WHERE id = ?", (webhook_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _row_to_config(self, row: sqlite3.Row) -> WebhookConfig:
        """Convert a SQLite row to a WebhookConfig."""
        events_raw = json.loads(row["events"])
        events = []
        for e in events_raw:
            try:
                events.append(WebhookEventType(e))
            except ValueError:
                pass
        return WebhookConfig(
            id=row["id"],
            url=row["url"],
            secret=row["secret"],
            events=events,
            tenant_id=row["tenant_id"],
            active=bool(row["active"]),
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ─── Webhook Manager ──────────────────────────────────────────────

# HTTP client — use httpx if available, fallback to urllib
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

import urllib.request
import urllib.error


def _sync_post(url: str, headers: Dict[str, str], body: str, timeout: float = 10.0) -> int:
    """Synchronous HTTP POST. Returns status code. Raises on network errors."""
    if _HAS_HTTPX:
        resp = httpx.post(url, headers=headers, content=body, timeout=timeout)
        return resp.status_code
    else:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status
        except urllib.error.HTTPError as e:
            return e.code


class WebhookManager:
    """
    Manages webhook registrations and event dispatching.

    Usage:
        manager = WebhookManager(db_path="data/webhooks.db")

        # Register a webhook
        config = WebhookConfig(
            url="https://example.com/hook",
            secret="my-secret",
            events=[WebhookEventType.RULE_VIOLATION, WebhookEventType.SESSION_KILL],
            tenant_id="acme",
        )
        manager.register(config)

        # Fire an event
        event = WebhookEvent(
            event_type=WebhookEventType.RULE_VIOLATION,
            payload={"session_id": "abc", "details": "PII detected"},
            tenant_id="acme",
        )
        manager.fire(event)  # fire-and-forget async dispatch
    """

    def __init__(self, db_path: str = ":memory:"):
        self._store = WebhookStore(db_path)
        self._retry_attempts = 3
        self._retry_base_delay = 1.0  # seconds
        self._timeout = 10.0

    # ── Registration ────────────────────────────────────────────

    def register(self, config: WebhookConfig) -> WebhookConfig:
        """Register a new webhook endpoint."""
        config.updated_at = datetime.now(timezone.utc).isoformat()
        saved = self._store.save(config)
        logger.info(f"Webhook registered: {saved.id} → {saved.url} "
                     f"(events={[e.value for e in saved.events]})")
        return saved

    def deregister(self, webhook_id: str) -> bool:
        """Deregister (delete) a webhook endpoint."""
        deleted = self._store.delete(webhook_id)
        if deleted:
            logger.info(f"Webhook deregistered: {webhook_id}")
        return deleted

    def get(self, webhook_id: str) -> Optional[WebhookConfig]:
        """Get a webhook config by ID."""
        return self._store.get(webhook_id)

    def list(self, tenant_id: Optional[str] = None) -> List[WebhookConfig]:
        """List all webhook configs, optionally filtered by tenant."""
        return self._store.list(tenant_id)

    def update(self, webhook_id: str, **kwargs) -> Optional[WebhookConfig]:
        """Update a webhook config's fields."""
        config = self._store.get(webhook_id)
        if not config:
            return None
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.now(timezone.utc).isoformat()
        return self._store.save(config)

    # ── Event Dispatch ──────────────────────────────────────────

    def fire(self, event: WebhookEvent) -> None:
        """
        Fire an event to all matching active webhooks.

        Fire-and-forget: dispatches async HTTP POST with retry.
        """
        # Find matching webhooks
        webhooks = self._get_matching_webhooks(event)
        if not webhooks:
            return

        # Dispatch async
        try:
            loop = asyncio.get_running_loop()
            for wh in webhooks:
                loop.create_task(self._dispatch_with_retry(wh, event))
        except RuntimeError:
            # No running event loop — use thread-based fallback
            import threading
            for wh in webhooks:
                t = threading.Thread(
                    target=self._sync_dispatch_with_retry,
                    args=(wh, event),
                    daemon=True,
                )
                t.start()

    async def _dispatch_with_retry(
        self, config: WebhookConfig, event: WebhookEvent
    ) -> None:
        """Dispatch event with exponential backoff retry."""
        payload_json = event.to_json()
        signature = compute_signature(payload_json, config.secret)

        for attempt in range(self._retry_attempts):
            try:
                status = await self._async_post(config.url, signature, payload_json)
                if 200 <= status < 300:
                    logger.debug(f"Webhook delivered: {config.id} → {config.url} (attempt {attempt + 1})")
                    return
                else:
                    logger.warning(
                        f"Webhook delivery failed (status={status}): {config.id} → {config.url} "
                        f"(attempt {attempt + 1}/{self._retry_attempts})"
                    )
            except Exception as e:
                logger.warning(
                    f"Webhook delivery error: {config.id} → {config.url} "
                    f"(attempt {attempt + 1}/{self._retry_attempts}): {e}"
                )

            # Exponential backoff
            if attempt < self._retry_attempts - 1:
                delay = self._retry_base_delay * (2 ** attempt)
                await asyncio.sleep(delay)

        logger.error(
            f"Webhook delivery FAILED after {self._retry_attempts} attempts: "
            f"{config.id} → {config.url}"
        )

    def _sync_dispatch_with_retry(
        self, config: WebhookConfig, event: WebhookEvent
    ) -> None:
        """Synchronous dispatch with retry (fallback when no event loop)."""
        payload_json = event.to_json()
        signature = compute_signature(payload_json, config.secret)

        for attempt in range(self._retry_attempts):
            try:
                status = _sync_post(
                    config.url,
                    {
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                    },
                    payload_json,
                    timeout=self._timeout,
                )
                if 200 <= status < 300:
                    logger.debug(f"Webhook delivered (sync): {config.id} → {config.url}")
                    return
            except Exception as e:
                logger.warning(
                    f"Webhook delivery error (sync): {config.id} → {config.url} "
                    f"(attempt {attempt + 1}): {e}"
                )

            import time
            if attempt < self._retry_attempts - 1:
                delay = self._retry_base_delay * (2 ** attempt)
                time.sleep(delay)

    async def _async_post(self, url: str, signature: str, body: str) -> int:
        """Async HTTP POST."""
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
        }
        if _HAS_HTTPX:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, content=body)
                return resp.status_code
        else:
            # Fallback: use sync in thread executor
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, lambda: _sync_post(url, headers, body, self._timeout)
            )

    # ── Helpers ─────────────────────────────────────────────────

    def _get_matching_webhooks(self, event: WebhookEvent) -> List[WebhookConfig]:
        """Get webhooks that match the event type and tenant."""
        if event.tenant_id:
            # Tenant-specific event: match tenant webhooks + global webhooks
            webhooks = self._store.list_active(tenant_id=event.tenant_id)
            global_hooks = self._store.list_active(tenant_id="")
            # Dedup by id
            seen_ids = {w.id for w in webhooks}
            webhooks.extend(w for w in global_hooks if w.id not in seen_ids)
        else:
            # Global event: only match global webhooks (empty tenant_id)
            webhooks = self._store.list_active(tenant_id="")

        # Filter by event type
        return [w for w in webhooks if event.event_type in w.events]

    @staticmethod
    def verify_signature(payload_json: str, signature: str, secret: str) -> bool:
        """Verify HMAC-SHA256 signature of a webhook payload."""
        return verify_signature(payload_json, signature, secret)


# ─── Global Instance ──────────────────────────────────────────────

_global_manager: Optional[WebhookManager] = None


def get_webhook_manager(db_path: str = ":memory:") -> WebhookManager:
    """Get or create the global WebhookManager instance."""
    global _global_manager
    if _global_manager is None:
        _global_manager = WebhookManager(db_path=db_path)
    return _global_manager


def reset_webhook_manager():
    """Reset the global manager (for testing)."""
    global _global_manager
    _global_manager = None
