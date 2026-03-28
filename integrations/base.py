"""
RTA-GUARD — Base Integration Class

Abstract base class for all RTA-GUARD framework integrations.
Provides shared violation handling, text extraction, and session management.
"""
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rta_guard.integrations.base")


class RtaGuardIntegration(ABC):
    """
    Abstract base class for all RTA-GUARD framework integrations.
    Provides shared logic for checking, violation handling, and text extraction.

    Subclasses must implement:
        - _setup_inner(inner, **kwargs): Configure the wrapped object

    Usage:
        class MyIntegration(RtaGuardIntegration):
            def __init__(self, inner, **kwargs):
                super().__init__(session_prefix="my", **kwargs)
                self._setup_inner(inner)

            def _setup_inner(self, inner, **kwargs):
                self.inner = inner
    """

    def __init__(self, session_id: Optional[str] = None,
                 session_prefix: str = "rta",
                 on_violation: str = "raise",
                 check_input: bool = True,
                 check_output: bool = True,
                 guard: Optional[Any] = None):
        """
        Args:
            session_id: Session identifier (auto-generated if None)
            session_prefix: Prefix for auto-generated session IDs
            on_violation: What to do on violation: "raise", "warn", "block"
            check_input: Check inputs before processing
            check_output: Check outputs after processing
            guard: Custom DiscusGuard instance
        """
        self.session_id = session_id or f"{session_prefix}-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self._violations: List[Dict[str, Any]] = []

        # Lazy guard initialization
        self._guard_instance = guard

    @property
    def guard(self) -> Any:
        """Get the guard instance, lazy-initializing if needed."""
        if self._guard_instance is None:
            from discus import DiscusGuard, GuardConfig
            self._guard_instance = DiscusGuard(config=GuardConfig())
        return self._guard_instance

    @guard.setter
    def guard(self, value: Any):
        """Set the guard instance."""
        self._guard_instance = value

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def check(self, text: str, is_output: bool = False) -> Optional[Dict[str, Any]]:
        """Run guard check on text. Returns violation dict or None.

        Args:
            text: The text to check
            is_output: Whether this is an output (True) or input (False)
        Returns:
            Violation dict if violation detected, None if safe
        """
        if not text:
            return None
        try:
            self.guard.check(text, session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "text": str(text)[:200],
                "is_output": is_output,
                "error": str(e),
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation in {self.__class__.__name__}: {e}")
            return violation

    def handle_violation(self, violation: Dict[str, Any]) -> str:
        """Handle a violation based on on_violation setting.

        Args:
            violation: The violation dict from check()
        Returns:
            Text to return (original, warning, or blocked message)
        """
        if self.on_violation == "raise":
            label = "output" if violation.get("is_output") else "input"
            raise RuntimeError(
                f"RTA-GUARD blocked this {label}: {violation['error']}"
            )
        elif self.on_violation == "block":
            return "[BLOCKED BY RTA-GUARD]"
        else:  # warn
            logger.warning(f"RTA-GUARD warning: {violation['error']}")
            return violation.get("text", "")

    def extract_text(self, data: Any) -> str:
        """Extract text from various input/output formats.

        Args:
            data: The data to extract text from
        Returns:
            Extracted text string
        """
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("text", "content", "input", "query", "output", "result", "message"):
                if key in data:
                    val = data[key]
                    return val if isinstance(val, str) else str(val)
            return str(data)[:500]
        if hasattr(data, "content"):
            return str(data.content or "")
        if hasattr(data, "text"):
            return str(data.text or "")
        return str(data)[:500]

    def check_and_handle(self, text: str, is_output: bool = False) -> str:
        """Check text and handle any violation. Returns safe text.

        Args:
            text: The text to check
            is_output: Whether this is output
        Returns:
            Original text if safe, or blocked/warning message
        """
        violation = self.check(text, is_output)
        if violation:
            return self.handle_violation(violation)
        return text

    def clear_violations(self):
        """Clear the violation history."""
        self._violations.clear()

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"session={self.session_id}, "
                f"violations={len(self._violations)})")
