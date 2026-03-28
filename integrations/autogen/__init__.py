"""
RTA-GUARD — Microsoft AutoGen Integration

Drop-in protection for AutoGen conversable agents, group chats, user proxies,
and code execution. Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.autogen import RtaGuardAgent, RtaGuardGroupChat

    # Option 1: Wrap individual agents
    agent = ConversableAgent(name="assistant", llm_config=llm_config)
    protected = RtaGuardAgent(agent)

    # Option 2: Wrap group chat for multi-agent monitoring
    groupchat = GroupChat(agents=[agent1, agent2], messages=[])
    protected_gc = RtaGuardGroupChat(groupchat)
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("rta_guard.autogen")

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
# Agent Wrapper — wraps ConversableAgent
# ═══════════════════════════════════════════════════════════════════

class RtaGuardAgent:
    """
    Wraps an AutoGen ConversableAgent with RTA-GUARD protection.
    Checks every message in agent-to-agent conversations.

    Usage:
        agent = ConversableAgent(name="assistant", llm_config=llm_config)
        protected = RtaGuardAgent(agent)
        # Use protected.generate_reply() instead of agent.generate_reply()
    """

    def __init__(self, inner_agent: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_agent: The AutoGen ConversableAgent to wrap
            session_id: Session identifier (auto-generated if None)
            on_violation: What to do on violation: "raise", "warn", "block"
            check_input: Check incoming messages
            check_output: Check agent responses
            guard: Custom DiscusGuard instance (uses shared if None)
        """
        self.inner = inner_agent
        self.session_id = session_id or f"ag-agent-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
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
            logger.warning(f"RTA-GUARD autogen agent violation: {e}")
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

    def _extract_message_text(self, message: Any) -> str:
        """Extract text from various message formats."""
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            return message.get("content", message.get("text", ""))
        if hasattr(message, "content"):
            return str(message.content or "")
        return str(message)[:500]

    def generate_reply(
        self, messages: Optional[List[Any]] = None,
        sender: Optional[Any] = None, **kwargs
    ) -> Any:
        """Generate reply with input/output protection.

        Args:
            messages: Conversation messages
            sender: The sending agent
        Returns:
            Agent reply (safe) or blocked message
        """
        # Check input messages
        if self.check_input and messages:
            for msg in messages:
                text = self._extract_message_text(msg)
                if text:
                    self._last_input = text
                    violation = self._check(text, is_output=False)
                    if violation and self.on_violation == "raise":
                        self._handle_violation(violation)

        # Generate reply
        reply = self.inner.generate_reply(messages=messages, sender=sender, **kwargs)

        # Check output
        if self.check_output and reply:
            output_text = self._extract_message_text(reply)
            if output_text:
                self._last_output = output_text
                violation = self._check(output_text, is_output=True)
                if violation:
                    handled = self._handle_violation(violation)
                    if isinstance(reply, str):
                        return handled
                    if isinstance(reply, dict):
                        reply["content"] = handled
                        return reply
                    return handled

        return reply

    async def a_generate_reply(
        self, messages: Optional[List[Any]] = None,
        sender: Optional[Any] = None, **kwargs
    ) -> Any:
        """Async generate reply with protection."""
        if self.check_input and messages:
            for msg in messages:
                text = self._extract_message_text(msg)
                if text:
                    violation = self._check(text, is_output=False)
                    if violation and self.on_violation == "raise":
                        self._handle_violation(violation)

        if hasattr(self.inner, "a_generate_reply"):
            reply = await self.inner.a_generate_reply(
                messages=messages, sender=sender, **kwargs
            )
        else:
            reply = self.inner.generate_reply(messages=messages, sender=sender, **kwargs)

        if self.check_output and reply:
            output_text = self._extract_message_text(reply)
            if output_text:
                violation = self._check(output_text, is_output=True)
                if violation:
                    handled = self._handle_violation(violation)
                    if isinstance(reply, str):
                        return handled
                    if isinstance(reply, dict):
                        reply["content"] = handled
                        return handled

        return reply

    def receive(self, message: Any, sender: Any, **kwargs) -> None:
        """Receive a message with input protection."""
        if self.check_input:
            text = self._extract_message_text(message)
            if text:
                violation = self._check(text, is_output=False)
                if violation and self.on_violation == "raise":
                    self._handle_violation(violation)

        if hasattr(self.inner, "receive"):
            self.inner.receive(message, sender=sender, **kwargs)

    def send(self, message: Any, recipient: Any, **kwargs) -> None:
        """Send a message with output protection."""
        if self.check_output:
            text = self._extract_message_text(message)
            if text:
                violation = self._check(text, is_output=True)
                if violation:
                    handled = self._handle_violation(violation)
                    if isinstance(message, str):
                        message = handled
                    elif isinstance(message, dict):
                        message["content"] = handled

        if hasattr(self.inner, "send"):
            self.inner.send(message, recipient=recipient, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        name = getattr(self.inner, "name", "unknown")
        return f"RtaGuardAgent(session={self.session_id}, name={name!r})"


# ═══════════════════════════════════════════════════════════════════
# Group Chat Wrapper — wraps GroupChat and GroupChatManager
# ═══════════════════════════════════════════════════════════════════

class RtaGuardGroupChat:
    """
    Wraps AutoGen GroupChat with RTA-GUARD protection.
    Monitors the entire conversation tree. Catches cross-agent manipulation.

    Usage:
        groupchat = GroupChat(agents=[agent1, agent2], messages=[],
                              max_round=10)
        protected = RtaGuardGroupChat(groupchat)
        manager = GroupChatManager(groupchat=protected, llm_config=llm_config)
    """

    def __init__(self, inner_groupchat: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_messages: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_groupchat: The AutoGen GroupChat to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_messages: Check each message added to the group chat
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_groupchat
        self.session_id = session_id or f"ag-gc-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_messages = check_messages
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        return self._violations

    def _check(self, text: str, is_output: bool = False,
               session_id: Optional[str] = None) -> Optional[str]:
        sid = session_id or self.session_id
        if not text:
            return None
        try:
            self.guard.check(text, session_id=sid)
            return None
        except Exception as e:
            violation = {
                "text": text[:200],
                "is_output": is_output,
                "error": str(e),
                "session_id": sid,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD group chat violation: {e}")
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

    def _extract_message_text(self, message: Any) -> str:
        """Extract text from various message formats."""
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            return message.get("content", message.get("text", ""))
        if hasattr(message, "content"):
            return str(message.content or "")
        return str(message)[:500]

    def append(self, message: Any, speaker: Optional[Any] = None) -> None:
        """Add a message to the group chat with protection.

        Args:
            message: The message to add
            speaker: The agent that sent the message
        """
        if self.check_messages:
            text = self._extract_message_text(message)
            if text:
                # Use per-speaker session for tracking
                speaker_name = getattr(speaker, "name", "unknown") if speaker else "unknown"
                sid = f"{self.session_id}:{speaker_name}"
                error = self._check(text, is_output=True, session_id=sid)
                if error and self.on_violation == "raise":
                    raise RuntimeError(f"RTA-GUARD group chat blocked: {error}")

        if hasattr(self.inner, "append"):
            self.inner.append(message, speaker=speaker)
        elif hasattr(self.inner, "messages") and isinstance(self.inner.messages, list):
            self.inner.messages.append(message)

    def select_speaker(self, last_speaker: Any, **kwargs) -> Any:
        """Select next speaker with input protection.

        Args:
            last_speaker: The agent that spoke last
        Returns:
            The next speaker agent
        """
        # Check the selection context
        if self.check_messages and hasattr(self.inner, "messages"):
            recent = self.inner.messages[-5:] if self.inner.messages else []
            for msg in recent:
                text = self._extract_message_text(msg)
                if text:
                    error = self._check(text, is_output=False)
                    if error and self.on_violation == "raise":
                        raise RuntimeError(f"RTA-GUARD speaker selection blocked: {error}")

        if hasattr(self.inner, "select_speaker"):
            return self.inner.select_speaker(last_speaker, **kwargs)
        return last_speaker

    def run_chat(self, **kwargs) -> Any:
        """Run the group chat with full protection."""
        result = self.inner.run_chat(**kwargs)

        # Check final messages
        if self.check_messages and hasattr(self.inner, "messages"):
            for msg in self.inner.messages[-10:]:
                text = self._extract_message_text(msg)
                if text:
                    self._check(text, is_output=True)

        return result

    @property
    def messages(self) -> List[Any]:
        """Access the messages list."""
        return getattr(self.inner, "messages", [])

    @messages.setter
    def messages(self, value: List[Any]):
        """Set the messages list."""
        if hasattr(self.inner, "messages"):
            self.inner.messages = value

    @property
    def agents(self) -> List[Any]:
        """Access the agents list."""
        return getattr(self.inner, "agents", [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        n_agents = len(getattr(self.inner, "agents", []))
        n_msgs = len(getattr(self.inner, "messages", []))
        return (f"RtaGuardGroupChat(session={self.session_id}, "
                f"agents={n_agents}, messages={n_msgs})")


# ═══════════════════════════════════════════════════════════════════
# User Proxy Wrapper — wraps UserProxyAgent
# ═══════════════════════════════════════════════════════════════════

class RtaGuardUserProxy:
    """
    Wraps an AutoGen UserProxyAgent with RTA-GUARD protection.
    Input protection on human→agent messages, output on agent→human.

    Usage:
        user_proxy = UserProxyAgent(name="user", human_input_mode="ALWAYS")
        protected = RtaGuardUserProxy(user_proxy)
    """

    def __init__(self, inner_proxy: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_proxy: The AutoGen UserProxyAgent to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_input: Check user inputs before sending
            check_output: Check agent responses before displaying
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_proxy
        self.session_id = session_id or f"ag-proxy-{uuid.uuid4().hex[:8]}"
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
            logger.warning(f"RTA-GUARD user proxy violation: {e}")
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

    def _extract_message_text(self, message: Any) -> str:
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            return message.get("content", message.get("text", ""))
        if hasattr(message, "content"):
            return str(message.content or "")
        return str(message)[:500]

    def get_human_input(self, prompt: str, **kwargs) -> str:
        """Get human input with output protection (prompt check).

        Args:
            prompt: The prompt shown to the human
        Returns:
            Human input (safe)
        """
        if self.check_output:
            self._handle(prompt, is_output=True)

        if hasattr(self.inner, "get_human_input"):
            return self.inner.get_human_input(prompt, **kwargs)
        return ""

    def generate_reply(
        self, messages: Optional[List[Any]] = None,
        sender: Optional[Any] = None, **kwargs
    ) -> Any:
        """Generate reply with input/output protection."""
        # Check input messages
        if self.check_input and messages:
            for msg in messages:
                text = self._extract_message_text(msg)
                if text:
                    violation = self._check(text, is_output=False)
                    if violation and self.on_violation == "raise":
                        raise RuntimeError(f"RTA-GUARD input blocked: {violation}")

        # Generate reply
        reply = self.inner.generate_reply(messages=messages, sender=sender, **kwargs)

        # Check output
        if self.check_output and reply:
            output_text = self._extract_message_text(reply)
            if output_text:
                violation = self._check(output_text, is_output=True)
                if violation:
                    handled = self._handle(output_text, is_output=True)
                    if isinstance(reply, str):
                        return handled
                    if isinstance(reply, dict):
                        reply["content"] = handled
                        return handled

        return reply

    async def a_generate_reply(
        self, messages: Optional[List[Any]] = None,
        sender: Optional[Any] = None, **kwargs
    ) -> Any:
        """Async generate reply with protection."""
        if self.check_input and messages:
            for msg in messages:
                text = self._extract_message_text(msg)
                if text:
                    violation = self._check(text, is_output=False)
                    if violation and self.on_violation == "raise":
                        raise RuntimeError(f"RTA-GUARD input blocked: {violation}")

        if hasattr(self.inner, "a_generate_reply"):
            reply = await self.inner.a_generate_reply(
                messages=messages, sender=sender, **kwargs
            )
        else:
            reply = self.inner.generate_reply(messages=messages, sender=sender, **kwargs)

        if self.check_output and reply:
            output_text = self._extract_message_text(reply)
            if output_text:
                violation = self._check(output_text, is_output=True)
                if violation:
                    handled = self._handle(output_text, is_output=True)
                    if isinstance(reply, str):
                        return handled

        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        name = getattr(self.inner, "name", "unknown")
        return f"RtaGuardUserProxy(session={self.session_id}, name={name!r})"


# ═══════════════════════════════════════════════════════════════════
# Code Executor Wrapper — wraps code execution with safety checks
# ═══════════════════════════════════════════════════════════════════

class RtaGuardCodeExecutor:
    """
    Wraps AutoGen code execution with RTA-GUARD protection.
    Checks code before execution. Catches prompt-to-code attacks.

    Usage:
        executor = LocalCommandLineCodeExecutor()
        protected = RtaGuardCodeExecutor(executor)
        result = protected.execute_code("print('hello')")
    """

    def __init__(self, inner_executor: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_code: bool = True, check_output: bool = True,
                 block_dangerous: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_executor: The AutoGen code executor to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_code: Check code before execution
            check_output: Check execution output
            block_dangerous: Block dangerous code patterns (os.system, subprocess, etc.)
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_executor
        self.session_id = session_id or f"ag-exec-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_code = check_code
        self.check_output = check_output
        self.block_dangerous = block_dangerous
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

        # Dangerous code patterns
        self._dangerous_patterns = [
            "os.system",
            "subprocess.call",
            "subprocess.run",
            "subprocess.Popen",
            "os.exec",
            "os.remove",
            "os.unlink",
            "shutil.rmtree",
            "eval(",
            "exec(",
            "__import__",
            "importlib",
            "ctypes",
            "socket.connect",
            "requests.post",
            "urllib.request",
        ]

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
            logger.warning(f"RTA-GUARD code executor violation: {e}")
            return str(e)

    def _check_dangerous_code(self, code: str) -> Optional[str]:
        """Check for dangerous code patterns."""
        if not self.block_dangerous:
            return None
        for pattern in self._dangerous_patterns:
            if pattern in code:
                return f"Dangerous code pattern detected: {pattern}"
        return None

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

    def execute_code(self, code: str, language: str = "python",
                     **kwargs) -> Any:
        """Execute code with input/output protection.

        Args:
            code: The code to execute
            language: Programming language
        Returns:
            Execution result (safe) or blocked message
        """
        # Check for dangerous patterns
        danger = self._check_dangerous_code(code)
        if danger:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD code blocked: {danger}")
            logger.warning(f"RTA-GUARD dangerous code: {danger}")

        # Check code content via guard
        if self.check_code:
            self._handle(code, is_output=False)

        # Execute
        if hasattr(self.inner, "execute_code"):
            result = self.inner.execute_code(code, language=language, **kwargs)
        elif hasattr(self.inner, "execute"):
            result = self.inner.execute(code, **kwargs)
        elif callable(self.inner):
            result = self.inner(code, **kwargs)
        else:
            raise AttributeError(f"Executor {type(self.inner)} has no execute method")

        # Check output
        if self.check_output and result:
            output_text = str(result)
            handled = self._handle(output_text, is_output=True)
            if handled == "[BLOCKED BY RTA-GUARD]":
                return handled

        return result

    async def execute_code_async(self, code: str, language: str = "python",
                                 **kwargs) -> Any:
        """Async execute code with protection."""
        danger = self._check_dangerous_code(code)
        if danger:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD code blocked: {danger}")

        if self.check_code:
            self._handle(code, is_output=False)

        if hasattr(self.inner, "execute_code_async"):
            result = await self.inner.execute_code_async(code, language=language, **kwargs)
        elif hasattr(self.inner, "execute_code"):
            result = self.inner.execute_code(code, language=language, **kwargs)
        else:
            result = self.inner(code, **kwargs)

        if self.check_output and result:
            self._handle(str(result), is_output=True)

        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardCodeExecutor(session={self.session_id})"
