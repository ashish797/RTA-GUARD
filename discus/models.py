"""
RTA-GUARD Discus — Core Models
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ViolationType(str, Enum):
    PII_DETECTED = "pii_detected"
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_CONTENT = "sensitive_content"
    CUSTOM = "custom"
    DESTRUCTIVE_ACTION = "destructive_action"
    UNAUTHORIZED_ACTION = "unauthorized_action"
    SCOPE_VIOLATION = "scope_violation"
    UNVERIFIED_CLAIM = "unverified_claim"
    HALLUCINATION = "hallucination"
    INCONSISTENCY = "inconsistency"
    HARMFUL_CONTENT = "harmful_content"


class KillDecision(str, Enum):
    KILL = "kill"
    WARN = "warn"
    PASS = "pass"


class SessionEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    input_text: str
    violation_type: Optional[ViolationType] = None
    severity: Optional[Severity] = None
    decision: KillDecision
    details: str = ""
    metadata: dict = Field(default_factory=dict)


class GuardConfig(BaseModel):
    """Configuration for DiscusGuard behavior."""
    # Severity threshold for auto-kill
    kill_threshold: Severity = Severity.HIGH
    # Whether to log all events (including passes)
    log_all: bool = True
    # Max events in memory (oldest dropped when exceeded; 0 = unlimited)
    max_events: int = 10000
    # Custom PII patterns (regex)
    pii_patterns: list[str] = Field(default_factory=list)
    # Path to dynamic PII patterns YAML file (auto-detected if not set)
    pii_patterns_yaml: Optional[str] = None
    # Custom blocked keywords
    blocked_keywords: list[str] = Field(default_factory=list)
    # Enable NeMo Guardrails (if False, uses built-in rules only)
    use_nemo: bool = True
    # Dashboard websocket URL for real-time notifications
    dashboard_ws_url: Optional[str] = None


class GuardResponse(BaseModel):
    """Response from the guard after checking input."""
    allowed: bool
    session_id: str
    event: SessionEvent
    message: Optional[str] = None  # User-facing message if killed
