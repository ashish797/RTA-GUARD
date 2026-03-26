"""
RTA-GUARD — Structured Logging Configuration (Phase 6.3)

JSON-formatted structured logging with correlation IDs, log rotation,
and ELK stack integration. Opt-in via LOG_LEVEL env var (default: WARNING).

Fields emitted in every log record:
    - timestamp: ISO 8601 timestamp
    - level: DEBUG | INFO | WARNING | ERROR | CRITICAL
    - message: Human-readable log message
    - module: Python module name
    - function: Function name where log was emitted
    - line: Line number in source file
    - request_id: Correlation ID for HTTP request tracing
    - session_id: RTA-GUARD session ID (if in session context)
    - agent_id: Agent ID (if in agent context)
    - correlation_id: Cross-module trace ID for kill decisions
    - hostname: Container/host identifier
    - service: Always "rta-guard"
"""
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# ─── Context management (thread-local) ────────────────────────────

_context = threading.local()


def set_request_context(
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
):
    """Set logging context for the current thread/request.

    Args:
        request_id: Unique HTTP request identifier
        session_id: RTA-GUARD session being evaluated
        agent_id: AI agent identifier
        correlation_id: Cross-module trace ID for kill decision tracing
    """
    if not hasattr(_context, "data"):
        _context.data = {}
    if request_id:
        _context.data["request_id"] = request_id
    if session_id:
        _context.data["session_id"] = session_id
    if agent_id:
        _context.data["agent_id"] = agent_id
    if correlation_id:
        _context.data["correlation_id"] = correlation_id


def clear_request_context():
    """Clear all logging context for the current thread."""
    if hasattr(_context, "data"):
        _context.data.clear()


def get_context() -> Dict[str, str]:
    """Get current logging context."""
    if hasattr(_context, "data"):
        return dict(_context.data)
    return {}


def new_correlation_id() -> str:
    """Generate a new correlation ID for tracing kill decisions."""
    cid = uuid.uuid4().hex[:12]
    set_request_context(correlation_id=cid)
    return cid


# ─── JSON Formatter ───────────────────────────────────────────────

class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as JSON for ELK ingestion.

    Every record includes: timestamp, level, message, module, function,
    line, service, hostname, plus any thread-local context fields.
    """

    def __init__(self, service_name: str = "rta-guard"):
        super().__init__()
        self.service_name = service_name
        self.hostname = socket.gethostname()

    def format(self, record: logging.LogRecord) -> str:
        # Build base fields
        entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "service": self.service_name,
            "hostname": self.hostname,
            "logger": record.name,
        }

        # Add thread-local context
        ctx = get_context()
        for key in ("request_id", "session_id", "agent_id", "correlation_id"):
            val = ctx.get(key)
            if val:
                entry[key] = val

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
            entry["exception_type"] = record.exc_info[0].__name__

        # Add any extra fields passed via logger.info("msg", extra={"key": "val"})
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs", "message",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName", "exc_info", "exc_text",
            ):
                if key not in entry:
                    try:
                        json.dumps(value)  # Ensure serializable
                        entry[key] = value
                    except (TypeError, ValueError):
                        entry[key] = str(value)

        return json.dumps(entry, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable formatter for console output."""

    FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d — %(message)s"

    def __init__(self):
        super().__init__(fmt=self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


# ─── Log level mapping ────────────────────────────────────────────

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_log_level() -> int:
    """Get log level from LOG_LEVEL env var. Default: WARNING."""
    level_str = os.getenv("LOG_LEVEL", "WARNING").upper()
    return LOG_LEVEL_MAP.get(level_str, logging.WARNING)


# ─── Configuration ────────────────────────────────────────────────

# Defaults (overridable via env vars)
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.getenv("LOG_FILE", os.path.join(LOG_DIR, "rta-guard.log"))
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()  # "json" or "plain"
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"


def configure_logging(
    level: Optional[int] = None,
    json_format: Optional[bool] = None,
    log_file: Optional[str] = None,
    console: Optional[bool] = None,
    service_name: str = "rta-guard",
) -> logging.Logger:
    """Configure structured logging for RTA-GUARD.

    Call once at application startup. Idempotent (clears existing handlers).

    Args:
        level: Log level (default: from LOG_LEVEL env var)
        json_format: Use JSON format (default: from LOG_FORMAT env var)
        log_file: Log file path (default: from LOG_FILE env var)
        console: Log to console (default: from LOG_TO_CONSOLE env var)
        service_name: Service name in log records

    Returns:
        Root logger for RTA-GUARD
    """
    if level is None:
        level = get_log_level()
    if json_format is None:
        json_format = LOG_FORMAT == "json"
    if log_file is None:
        log_file = LOG_FILE
    if console is None:
        console = LOG_TO_CONSOLE

    # Get root logger
    root = logging.getLogger()

    # Clear existing handlers (idempotent)
    root.handlers.clear()
    root.setLevel(level)

    # Choose formatter
    if json_format:
        formatter = StructuredJsonFormatter(service_name=service_name)
    else:
        formatter = PlainFormatter()

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # File handler with rotation
    if LOG_TO_FILE and log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("qdrant_client").setLevel(logging.WARNING)

    root.info(
        "Logging configured: level=%s, format=%s, file=%s, console=%s",
        logging.getLevelName(level),
        "json" if json_format else "plain",
        log_file if LOG_TO_FILE else "disabled",
        console,
    )

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Configure logging first with configure_logging()."""
    return logging.getLogger(name)


# ─── Convenience log functions with context ────────────────────────

def log_kill_decision(
    logger: logging.Logger,
    session_id: str,
    agent_id: str,
    reason: str,
    rule_id: Optional[str] = None,
    severity: str = "critical",
    **extra: Any,
):
    """Log a kill decision with full correlation context."""
    logger.warning(
        "KILL DECISION: session=%s agent=%s reason=%s rule=%s",
        session_id, agent_id, reason, rule_id,
        extra={
            "event_type": "kill_decision",
            "session_id": session_id,
            "agent_id": agent_id,
            "rule_id": rule_id,
            "severity": severity,
            "reason": reason,
            **extra,
        },
    )


def log_violation(
    logger: logging.Logger,
    session_id: str,
    rule_id: str,
    severity: str = "medium",
    message: str = "",
    **extra: Any,
):
    """Log a rule violation with context."""
    level = logging.ERROR if severity in ("high", "critical") else logging.WARNING
    logger.log(
        level,
        "VIOLATION: rule=%s severity=%s session=%s — %s",
        rule_id, severity, session_id, message,
        extra={
            "event_type": "rule_violation",
            "session_id": session_id,
            "rule_id": rule_id,
            "severity": severity,
            **extra,
        },
    )


def log_check(
    logger: logging.Logger,
    session_id: str,
    result: str,
    duration_ms: float,
    **extra: Any,
):
    """Log a guard check result."""
    logger.info(
        "CHECK: session=%s result=%s duration=%.2fms",
        session_id, result, duration_ms,
        extra={
            "event_type": "guard_check",
            "session_id": session_id,
            "result": result,
            "duration_ms": duration_ms,
            **extra,
        },
    )


# ─── Module-level init guard ──────────────────────────────────────

_initialized = False


def init_logging():
    """Initialize logging if not already done. Safe to call multiple times."""
    global _initialized
    if not _initialized:
        configure_logging()
        _initialized = True
