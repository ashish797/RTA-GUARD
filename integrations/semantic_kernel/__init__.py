"""
RTA-GUARD — Microsoft Semantic Kernel Integration

Drop-in protection for Semantic Kernel functions, planners, and chat services.
Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.semantic_kernel import RtaGuardPlugin, RtaGuardFilter

    # Option 1: Add as a plugin to the kernel
    kernel = Kernel()
    kernel.add_plugin(RtaGuardPlugin(), plugin_name="rta_guard")

    # Option 2: Use as a function invocation filter
    kernel.add_filter(RtaGuardFilter())

    # Option 3: Wrap the chat completion service
    protected_service = RtaGuardChatService(chat_service)
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("rta_guard.semantic_kernel")

# ─── Guard Engine Import ───────────────────────────────────────────

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discus import DiscusGuard, GuardConfig
from discus.plugins import PluginManager

# Shared guard instance (lazy initialized)
_guard: Optional[DiscusGuard] = None
_plugins: Optional[PluginManager] = None


def get_guard(**kwargs) -> DiscusGuard:
    """Get or create the shared guard instance.

    Usage:
        guard = get_guard()
        guard = get_guard(config=GuardConfig())
    """
    global _guard, _plugins
    if _guard is None:
        _plugins = PluginManager()
        try:
            _plugins.load_all()
        except Exception:
            pass
        _guard = DiscusGuard(
            config=kwargs.get("config", GuardConfig()),
            plugin_manager=_plugins,
        )
    return _guard


def set_guard(guard: DiscusGuard):
    """Set a custom guard instance.

    Usage:
        custom_guard = DiscusGuard(config=my_config)
        set_guard(custom_guard)
    """
    global _guard
    _guard = guard


# ═══════════════════════════════════════════════════════════════════
# Plugin — exposes RTA-GUARD as a Semantic Kernel native plugin
# ═══════════════════════════════════════════════════════════════════

class RtaGuardPlugin:
    """
    Semantic Kernel plugin that exposes RTA-GUARD functions.
    Can be added to any kernel for inline text validation.

    Usage:
        kernel = Kernel()
        plugin = RtaGuardPlugin()
        kernel.add_plugin(plugin, plugin_name="rta_guard")

        # Call via kernel
        result = await kernel.invoke("rta_guard", "check_text",
                                      input_text="Hello world")
    """

    def __init__(self, guard: Optional[DiscusGuard] = None,
                 on_violation: str = "raise"):
        """
        Args:
            guard: Custom DiscusGuard instance (uses shared if None)
            on_violation: What to do on violation: "raise", "warn", "block"
        """
        self.guard = guard or get_guard()
        self.on_violation = on_violation
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _check(self, text: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Run guard check on text. Returns violation dict or None."""
        sid = session_id or f"sk-plugin-{uuid.uuid4().hex[:8]}"
        try:
            self.guard.check(text, session_id=sid)
            return None
        except Exception as e:
            violation = {
                "text": str(text)[:200],
                "error": str(e),
                "session_id": sid,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD plugin violation: {e}")
            return violation

    def check_text(self, input_text: str) -> str:
        """Check text for violations. Returns safe text or blocked message.

        Args:
            input_text: The text to check
        Returns:
            Original text if safe, or "[BLOCKED BY RTA-GUARD]" if violation
        """
        violation = self._check(input_text)
        if violation:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD blocked: {violation['error']}")
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
            else:
                logger.warning(f"RTA-GUARD warning: {violation['error']}")
        return input_text

    def check_input(self, input_text: str) -> str:
        """Alias for check_text — validates user/agent input."""
        return self.check_text(input_text)

    def check_output(self, output_text: str) -> str:
        """Validate LLM output text.

        Args:
            output_text: The LLM response to check
        Returns:
            Original text if safe, or "[BLOCKED BY RTA-GUARD]" if violation
        """
        violation = self._check(output_text)
        if violation:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD output blocked: {violation['error']}")
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
        return output_text

    def get_violations(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all violations, optionally filtered by session.

        Args:
            session_id: Filter by session (None = all)
        Returns:
            List of violation dicts
        """
        if session_id is None:
            return self._violations
        return [v for v in self._violations if v.get("session_id") == session_id]

    def clear_violations(self):
        """Clear the violation history."""
        self._violations.clear()


# ═══════════════════════════════════════════════════════════════════
# Filter — FunctionInvocationFilter for kernel-wide protection
# ═══════════════════════════════════════════════════════════════════

class RtaGuardFilter:
    """
    Semantic Kernel function invocation filter.
    Intercepts every kernel function call for input/output protection.

    Usage:
        kernel = Kernel()
        kernel.add_filter(RtaGuardFilter())

        # All function invocations are now checked
        result = await kernel.invoke("my_plugin", "my_function",
                                      input_data="...")
    """

    def __init__(self, session_id: Optional[str] = None,
                 check_input: bool = True, check_output: bool = True,
                 on_violation: str = "raise",
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            session_id: Session identifier (auto-generated if None)
            check_input: Check function inputs before execution
            check_output: Check function outputs after execution
            on_violation: What to do on violation: "raise", "warn", "block"
            guard: Custom DiscusGuard instance (uses shared if None)
        """
        self.session_id = session_id or f"sk-filter-{uuid.uuid4().hex[:8]}"
        self.check_input = check_input
        self.check_output = check_output
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []
        self._last_input: str = ""
        self._last_output: str = ""

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _check(self, text: str, is_output: bool = False) -> Optional[Dict[str, Any]]:
        """Run guard check on text. Returns violation dict or None."""
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
            logger.warning(f"RTA-GUARD filter violation: {e}")
            return violation

    def _handle_violation(self, violation: Dict[str, Any]) -> str:
        """Handle a violation based on on_violation setting."""
        if self.on_violation == "raise":
            raise RuntimeError(
                f"RTA-GUARD blocked this {'output' if violation['is_output'] else 'input'}: "
                f"{violation['error']}"
            )
        elif self.on_violation == "block":
            return "[BLOCKED BY RTA-GUARD]"
        else:  # warn
            logger.warning(f"RTA-GUARD warning: {violation['error']}")
            return violation["text"]

    def _extract_text(self, data: Any) -> str:
        """Extract text from various input formats."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("input", "query", "text", "message", "prompt"):
                if key in data:
                    val = data[key]
                    return val if isinstance(val, str) else str(val)
            return str(data)[:500]
        return str(data)[:500]

    async def on_function_invocation(self, context: Any, next: Any) -> Any:
        """Pre/post function invocation hook.

        This is the Semantic Kernel filter signature. Called for every
        kernel function invocation.
        """
        # Pre-invocation: check inputs
        if self.check_input:
            try:
                arguments = getattr(context, "arguments", None)
                if arguments:
                    for key in ("input", "query", "text", "message", "prompt", "value"):
                        if hasattr(arguments, key):
                            text = self._extract_text(getattr(arguments, key))
                        elif isinstance(arguments, dict) and key in arguments:
                            text = self._extract_text(arguments[key])
                        else:
                            continue
                        if text:
                            self._last_input = text
                            violation = self._check(text, is_output=False)
                            if violation and self.on_violation == "raise":
                                self._handle_violation(violation)
                            break
            except Exception:
                pass

        # Execute the function
        await next(context)

        # Post-invocation: check outputs
        if self.check_output:
            try:
                result = getattr(context, "result", None)
                if result is not None:
                    text = self._extract_text(result)
                    if text:
                        self._last_output = text
                        violation = self._check(text, is_output=True)
                        if violation and self.on_violation == "raise":
                            self._handle_violation(violation)
            except Exception:
                pass

    def check_before(self, input_data: Any) -> Optional[str]:
        """Manually check input before a function call.

        Args:
            input_data: The input to check
        Returns:
            None if safe, error message if violation (when not raising)
        """
        text = self._extract_text(input_data)
        if not text:
            return None
        violation = self._check(text, is_output=False)
        if violation:
            return self._handle_violation(violation)
        return None

    def check_after(self, output_data: Any) -> Optional[str]:
        """Manually check output after a function call.

        Args:
            output_data: The output to check
        Returns:
            None if safe, error message if violation (when not raising)
        """
        text = self._extract_text(output_data)
        if not text:
            return None
        violation = self._check(text, is_output=True)
        if violation:
            return self._handle_violation(violation)
        return None


# ═══════════════════════════════════════════════════════════════════
# Planner — wraps planner execution for step-by-step protection
# ═══════════════════════════════════════════════════════════════════

class RtaGuardPlanner:
    """
    Wraps Semantic Kernel planner execution with step-by-step protection.
    Checks each plan step before execution and the final result.

    Usage:
        planner = StepwisePlanner(kernel)
        protected = RtaGuardPlanner(planner)
        result = protected.execute("Summarize the latest news")
    """

    def __init__(self, inner_planner: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_steps: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_planner: The Semantic Kernel planner to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_steps: Check each plan step before execution
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_planner
        self.session_id = session_id or f"sk-planner-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_steps = check_steps
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        return self._violations

    def _check(self, text: str, is_output: bool = False) -> Optional[str]:
        """Check text. Returns error message or None."""
        if not text:
            return None
        try:
            self.guard.check(text, session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "text": text[:200],
                "is_output": is_output,
                "error": str(e),
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD planner violation: {e}")
            return str(e)

    def _handle(self, text: str, is_output: bool = False) -> str:
        """Check and handle. Returns text or blocked message."""
        error = self._check(text, is_output)
        if error:
            if self.on_violation == "raise":
                raise RuntimeError(
                    f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
                )
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
        return text

    def execute(self, goal: str, **kwargs) -> Any:
        """Execute a plan with input/output protection.

        Args:
            goal: The planning goal
        Returns:
            Plan result (safe) or blocked message
        """
        # Check the goal
        self._handle(goal, is_output=False)

        # Execute the plan
        result = self.inner.execute(goal, **kwargs)

        # Check the result
        result_text = str(result) if result else ""
        if result_text:
            error = self._check(result_text, is_output=True)
            if error:
                handled = self._handle(result_text, is_output=True)
                if self.on_violation == "block":
                    return handled

        return result

    async def execute_async(self, goal: str, **kwargs) -> Any:
        """Async execute a plan with protection."""
        self._handle(goal, is_output=False)

        if hasattr(self.inner, "execute_async"):
            result = await self.inner.execute_async(goal, **kwargs)
        elif hasattr(self.inner, "execute"):
            result = self.inner.execute(goal, **kwargs)
        else:
            raise AttributeError(f"Planner {type(self.inner)} has no execute method")

        result_text = str(result) if result else ""
        if result_text:
            self._handle(result_text, is_output=True)

        return result

    def create_plan(self, goal: str, **kwargs) -> Any:
        """Create a plan with input protection (no output check for plan objects).

        Args:
            goal: The planning goal
        Returns:
            Plan object
        """
        self._handle(goal, is_output=False)

        if hasattr(self.inner, "create_plan"):
            return self.inner.create_plan(goal, **kwargs)
        elif hasattr(self.inner, "execute"):
            return self.inner.execute(goal, **kwargs)
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


# ═══════════════════════════════════════════════════════════════════
# Chat Service — wraps ChatCompletionService
# ═══════════════════════════════════════════════════════════════════

class RtaGuardChatService:
    """
    Wraps a Semantic Kernel ChatCompletionService with RTA-GUARD protection.
    Checks prompts before sending and completions before returning.

    Usage:
        service = OpenAIChatCompletion()
        protected = RtaGuardChatService(service)
        kernel.add_service(protected)
    """

    def __init__(self, inner_service: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_service: The ChatCompletionService to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_input: Check prompts before sending
            check_output: Check completions before returning
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_service
        self.session_id = session_id or f"sk-chat-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        return self._violations

    def _check(self, text: str, is_output: bool = False) -> Optional[str]:
        if not text:
            return None
        try:
            self.guard.check(text, session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "text": text[:200],
                "is_output": is_output,
                "error": str(e),
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD chat service violation: {e}")
            return str(e)

    def _handle(self, text: str, is_output: bool = False) -> str:
        error = self._check(text, is_output)
        if error:
            if self.on_violation == "raise":
                raise RuntimeError(
                    f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
                )
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
        return text

    def _extract_messages_text(self, messages: Any) -> str:
        """Extract text from chat messages for checking."""
        if isinstance(messages, str):
            return messages
        if isinstance(messages, list):
            texts = []
            for msg in messages:
                if hasattr(msg, "content"):
                    texts.append(str(msg.content or ""))
                elif isinstance(msg, dict):
                    texts.append(str(msg.get("content", "")))
                elif isinstance(msg, str):
                    texts.append(msg)
            return " ".join(texts)
        return str(messages)[:500]

    async def get_chat_message_contents(
        self, chat_history: Any, settings: Any = None, **kwargs
    ) -> Any:
        """Get chat completions with input/output protection.

        Args:
            chat_history: The chat history / messages
            settings: Chat completion settings
        Returns:
            Chat completion responses
        """
        # Check input messages
        if self.check_input:
            input_text = self._extract_messages_text(chat_history)
            if input_text:
                self._handle(input_text, is_output=False)

        # Call inner service
        result = await self.inner.get_chat_message_contents(
            chat_history, settings=settings, **kwargs
        )

        # Check output
        if self.check_output and result:
            for msg in result:
                content = getattr(msg, "content", None) or ""
                if content:
                    self._handle(content, is_output=True)

        return result

    async def get_streaming_chat_message_contents(
        self, chat_history: Any, settings: Any = None, **kwargs
    ) -> Any:
        """Stream chat completions with per-chunk protection.

        Args:
            chat_history: The chat history / messages
            settings: Chat completion settings
        Yields:
            Streaming chat completion chunks
        """
        # Check input
        if self.check_input:
            input_text = self._extract_messages_text(chat_history)
            if input_text:
                self._handle(input_text, is_output=False)

        buffer = ""
        async for chunk in self.inner.get_streaming_chat_message_contents(
            chat_history, settings=settings, **kwargs
        ):
            if self.check_output:
                for msg in chunk if isinstance(chunk, list) else [chunk]:
                    content = getattr(msg, "content", None) or ""
                    if content:
                        buffer += content
                        # Check every 200 chars to catch violations early
                        if len(buffer) >= 200:
                            error = self._check(buffer, is_output=True)
                            if error and self.on_violation == "raise":
                                raise RuntimeError(f"RTA-GUARD streaming blocked: {error}")
                            buffer = ""

            yield chunk

        # Final check on remaining buffer
        if self.check_output and buffer:
            self._handle(buffer, is_output=True)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
