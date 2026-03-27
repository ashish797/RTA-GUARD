"""
RTA-GUARD — LangChain Integration

Drop-in protection for any LangChain chain, LLM, or runnable.
Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.langchain import RtaGuardCallbackHandler, RtaGuardChain

    # Option 1: Callback handler (works with ANY chain)
    handler = RtaGuardCallbackHandler()
    chain = LLMChain(llm=llm, prompt=prompt, callbacks=[handler])

    # Option 2: Chain wrapper (explicit wrapping)
    protected = RtaGuardChain(inner_chain=chain)
    result = protected.invoke({"input": "user message"})

    # Option 3: Runnable wrapper (LangChain Expression Language)
    protected = RtaGuardRunnable(llm | parser)
    result = protected.invoke("user message")
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("rta_guard.langchain")

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
    """Get or create the shared guard instance."""
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
    """Set a custom guard instance."""
    global _guard
    _guard = guard


# ═══════════════════════════════════════════════════════════════════
# Callback Handler — works with ANY LangChain chain
# ═══════════════════════════════════════════════════════════════════

class RtaGuardCallbackHandler:
    """
    LangChain callback handler that checks inputs and outputs.

    Usage:
        handler = RtaGuardCallbackHandler(session_id="user-123")
        chain = LLMChain(llm=llm, prompt=prompt)
        result = chain.invoke({"input": "hello"}, config={"callbacks": [handler]})
    """

    name = "rta_guard_callback"

    def __init__(self, session_id: Optional[str] = None,
                 check_input: bool = True, check_output: bool = True,
                 on_violation: Optional[str] = "raise",
                 guard: Optional[DiscusGuard] = None,
                 memory_manager: Optional[Any] = None):
        """
        Args:
            session_id: Session identifier (auto-generated if None)
            check_input: Check user inputs before LLM
            check_output: Check LLM outputs before returning
            on_violation: What to do on violation: "raise", "warn", "block"
            guard: Custom DiscusGuard instance (uses shared if None)
            memory_manager: Optional MemoryManager for conversation tracking
        """
        self.session_id = session_id or f"lc-{uuid.uuid4().hex[:8]}"
        self.check_input = check_input
        self.check_output = check_output
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self.memory_manager = memory_manager
        self._violations: List[Dict[str, Any]] = []
        self._last_input: str = ""
        self._last_output: str = ""

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _check(self, text: str, is_output: bool = False) -> Optional[Dict[str, Any]]:
        """Run guard check on text. Returns violation dict or None."""
        try:
            result = self.guard.check(text, session_id=self.session_id)
            return None  # Passed
        except Exception as e:
            violation = {
                "text": str(text)[:200],
                "is_output": is_output,
                "error": str(e),
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation: {e}")
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

    # ─── LangChain Callback Methods ────────────────────────────────

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                       *, run_id: str, parent_run_id: Optional[str] = None,
                       tags: Optional[List[str]] = None,
                       metadata: Optional[Dict[str, Any]] = None,
                       **kwargs: Any) -> None:
        """Called when a chain starts — check inputs."""
        if not self.check_input:
            return

        # Extract text from various input formats
        text = ""
        if isinstance(inputs, dict):
            text = inputs.get("input", inputs.get("query", inputs.get("text", "")))
        elif isinstance(inputs, str):
            text = inputs

        if text:
            self._last_input = text
            violation = self._check(text, is_output=False)
            if violation and self.on_violation == "raise":
                self._handle_violation(violation)

    def on_chain_end(self, outputs: Dict[str, Any], *, run_id: str,
                     parent_run_id: Optional[str] = None, **kwargs: Any) -> None:
        """Called when a chain ends — check outputs."""
        if not self.check_output:
            return

        text = ""
        if isinstance(outputs, dict):
            text = outputs.get("text", outputs.get("output", outputs.get("result", "")))
        elif isinstance(outputs, str):
            text = outputs

        if text:
            self._last_output = text
            # Add to conversation memory
            if self.memory_manager:
                try:
                    self.memory_manager.add_assistant_message(self.session_id, text)
                except Exception:
                    pass
            violation = self._check(text, is_output=True)
            if violation and self.on_violation == "raise":
                self._handle_violation(violation)

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str],
                     *, run_id: str, **kwargs: Any) -> None:
        """Called when LLM starts — check prompts."""
        if not self.check_input:
            return
        for prompt in prompts:
            violation = self._check(prompt, is_output=False)
            if violation and self.on_violation == "raise":
                self._handle_violation(violation)

    def on_llm_end(self, response: Any, *, run_id: str, **kwargs: Any) -> None:
        """Called when LLM ends — check response."""
        if not self.check_output:
            return
        try:
            if hasattr(response, "generations"):
                for gens in response.generations:
                    for gen in gens:
                        if hasattr(gen, "text"):
                            violation = self._check(gen.text, is_output=True)
                            if violation and self.on_violation == "raise":
                                self._handle_violation(violation)
        except Exception as e:
            logger.debug(f"LLM output check error: {e}")

    # No-op callbacks for other events
    def on_llm_error(self, error: BaseException, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_chain_error(self, error: BaseException, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                      *, run_id: str, **kwargs: Any) -> None:
        if self.check_input:
            self._check(input_str, is_output=False)

    def on_tool_end(self, output: str, *, run_id: str, **kwargs: Any) -> None:
        if self.check_output:
            self._check(output, is_output=True)

    def on_tool_error(self, error: BaseException, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_text(self, text: str, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_agent_action(self, action: Any, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_agent_finish(self, finish: Any, *, run_id: str, **kwargs: Any) -> None:
        pass

    def on_retriever_start(self, serialized: Dict[str, Any], query: str,
                           *, run_id: str, **kwargs: Any) -> None:
        if self.check_input:
            self._check(query, is_output=False)

    def on_retriever_end(self, documents: Any, *, run_id: str, **kwargs: Any) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════
# Chain Wrapper — wraps any LangChain chain
# ═══════════════════════════════════════════════════════════════════

class RtaGuardChain:
    """
    Wraps any LangChain chain with RTA-GUARD protection.

    Usage:
        from langchain.chains import LLMChain
        chain = LLMChain(llm=llm, prompt=prompt)
        protected = RtaGuardChain(chain, session_id="user-123")
        result = protected.invoke({"input": "hello"})
    """

    def __init__(self, inner_chain: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 guard: Optional[DiscusGuard] = None):
        self.inner_chain = inner_chain
        self.session_id = session_id or f"lc-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self._callback = RtaGuardCallbackHandler(
            session_id=self.session_id,
            on_violation=on_violation,
            guard=self.guard,
        )

    def invoke(self, input_data: Union[str, Dict[str, Any]], **kwargs) -> Any:
        """Invoke the chain with input/output protection."""
        # Check input
        text = ""
        if isinstance(input_data, str):
            text = input_data
        elif isinstance(input_data, dict):
            text = input_data.get("input", input_data.get("query", ""))

        if text:
            try:
                self.guard.check(text, session_id=self.session_id)
            except Exception as e:
                if self.on_violation == "raise":
                    raise RuntimeError(f"RTA-GUARD input blocked: {e}")
                elif self.on_violation == "block":
                    return {"output": "[BLOCKED BY RTA-GUARD]"}

        # Run chain with callback
        config = kwargs.pop("config", {})
        callbacks = config.get("callbacks", []) if isinstance(config, dict) else []
        if not isinstance(callbacks, list):
            callbacks = [callbacks]
        callbacks.append(self._callback)

        if isinstance(config, dict):
            config["callbacks"] = callbacks
        else:
            config = {"callbacks": callbacks}
        kwargs["config"] = config

        result = self.inner_chain.invoke(input_data, **kwargs)

        # Check output
        output_text = ""
        if isinstance(result, str):
            output_text = result
        elif isinstance(result, dict):
            output_text = result.get("text", result.get("output", result.get("result", "")))

        if output_text:
            try:
                self.guard.check(output_text, session_id=self.session_id)
            except Exception as e:
                if self.on_violation == "raise":
                    raise RuntimeError(f"RTA-GUARD output blocked: {e}")
                elif self.on_violation == "block":
                    if isinstance(result, dict):
                        result["output"] = "[BLOCKED BY RTA-GUARD]"
                        return result
                    return "[BLOCKED BY RTA-GUARD]"

        return result

    async def ainvoke(self, input_data: Union[str, Dict[str, Any]], **kwargs) -> Any:
        """Async invoke with protection."""
        # Same input check
        text = ""
        if isinstance(input_data, str):
            text = input_data
        elif isinstance(input_data, dict):
            text = input_data.get("input", input_data.get("query", ""))

        if text:
            try:
                self.guard.check(text, session_id=self.session_id)
            except Exception as e:
                if self.on_violation == "raise":
                    raise RuntimeError(f"RTA-GUARD input blocked: {e}")

        result = await self.inner_chain.ainvoke(input_data, **kwargs)

        # Check output
        output_text = ""
        if isinstance(result, str):
            output_text = result
        elif isinstance(result, dict):
            output_text = result.get("text", result.get("output", ""))

        if output_text:
            try:
                self.guard.check(output_text, session_id=self.session_id)
            except Exception as e:
                if self.on_violation == "raise":
                    raise RuntimeError(f"RTA-GUARD output blocked: {e}")

        return result

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to inner chain."""
        return getattr(self.inner_chain, name)

    def __repr__(self) -> str:
        return f"RtaGuardChain(session={self.session_id}, inner={self.inner_chain!r})"


# ═══════════════════════════════════════════════════════════════════
# Runnable Wrapper — for LangChain Expression Language (LCEL)
# ═══════════════════════════════════════════════════════════════════

class RtaGuardRunnable:
    """
    Wraps any LangChain Runnable with RTA-GUARD protection.
    Works with LCEL chains (prompt | llm | parser).

    Usage:
        from langchain_core.runnables import RunnableLambda
        chain = prompt | llm | parser
        protected = RtaGuardRunnable(chain)
        result = protected.invoke({"input": "hello"})
    """

    def __init__(self, inner_runnable: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 guard: Optional[DiscusGuard] = None,
                 buffer_size: int = 200,
                 check_every_n_chars: int = 10):
        self.inner = inner_runnable
        self.session_id = session_id or f"lc-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self.buffer_size = buffer_size
        self.check_every_n_chars = check_every_n_chars
        self._streaming_guard = None

    def _extract_text(self, data: Any) -> str:
        """Extract text from various input/output formats."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("input", data.get("query", data.get("text", "")))
        return str(data)[:500]

    def _check_text(self, text: str, is_output: bool = False) -> None:
        """Check text, raise/block if violation."""
        if not text:
            return
        try:
            self.guard.check(text, session_id=self.session_id)
        except Exception as e:
            if self.on_violation == "raise":
                raise RuntimeError(
                    f"RTA-GUARD {'output' if is_output else 'input'} blocked: {e}"
                )

    def invoke(self, input_data: Any, config: Optional[Any] = None, **kwargs) -> Any:
        """Invoke with protection."""
        self._check_text(self._extract_text(input_data), is_output=False)
        result = self.inner.invoke(input_data, config=config, **kwargs)
        self._check_text(self._extract_text(result), is_output=True)
        return result

    async def ainvoke(self, input_data: Any, config: Optional[Any] = None, **kwargs) -> Any:
        """Async invoke with protection."""
        self._check_text(self._extract_text(input_data), is_output=False)
        result = await self.inner.ainvoke(input_data, config=config, **kwargs)
        self._check_text(self._extract_text(result), is_output=True)
        return result

    def _get_streaming_guard(self):
        """Get or create a StreamingGuard instance."""
        if self._streaming_guard is None or self._streaming_guard.is_killed:
            from discus.streaming import StreamingGuard
            self._streaming_guard = StreamingGuard(
                guard=self.guard,
                session_id=self.session_id,
                on_violation=self.on_violation,
                buffer_size=self.buffer_size,
                check_every_n_chars=self.check_every_n_chars,
            )
        return self._streaming_guard

    @property
    def streaming_metrics(self):
        """Get streaming metrics from last stream operation."""
        if self._streaming_guard:
            return self._streaming_guard.metrics
        return None

    def stream(self, input_data: Any, config: Optional[Any] = None, **kwargs):
        """Stream with per-chunk protection and early termination."""
        self._check_text(self._extract_text(input_data), is_output=False)

        sguard = self._get_streaming_guard()
        sguard.reset()

        for chunk in self.inner.stream(input_data, config=config, **kwargs):
            chunk_text = self._extract_text(chunk)
            if chunk_text:
                result = sguard.process_chunk(chunk_text)
                if result.should_stop:
                    if result.raise_error:
                        sguard.complete()
                        raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
                    if result.replacement_text:
                        yield result.replacement_text
                    sguard.complete()
                    return
            yield chunk

        sguard.complete()

    async def astream(self, input_data: Any, config: Optional[Any] = None, **kwargs):
        """Async stream with per-chunk protection and early termination."""
        self._check_text(self._extract_text(input_data), is_output=False)

        sguard = self._get_streaming_guard()
        sguard.reset()

        async for chunk in self.inner.astream(input_data, config=config, **kwargs):
            chunk_text = self._extract_text(chunk)
            if chunk_text:
                result = await sguard.process_chunk_async(chunk_text)
                if result.should_stop:
                    if result.raise_error:
                        sguard.complete()
                        raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
                    if result.replacement_text:
                        yield result.replacement_text
                    sguard.complete()
                    return
            yield chunk

        sguard.complete()

    def batch(self, inputs: List[Any], config: Optional[Any] = None, **kwargs) -> List[Any]:
        """Batch invoke with per-item protection."""
        results = []
        for inp in inputs:
            results.append(self.invoke(inp, config=config, **kwargs))
        return results

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __or__(self, other: Any) -> "RtaGuardRunnable":
        """Support LCEL pipe operator."""
        try:
            composed = self.inner | other
            return RtaGuardRunnable(composed, session_id=self.session_id,
                                    on_violation=self.on_violation, guard=self.guard)
        except Exception:
            raise TypeError(f"Cannot compose RtaGuardRunnable with {type(other)}")

    def __ror__(self, other: Any) -> "RtaGuardRunnable":
        """Support reverse pipe."""
        try:
            composed = other | self.inner
            return RtaGuardRunnable(composed, session_id=self.session_id,
                                    on_violation=self.on_violation, guard=self.guard)
        except Exception:
            raise TypeError(f"Cannot compose {type(other)} with RtaGuardRunnable")

    def __repr__(self) -> str:
        return f"RtaGuardRunnable(session={self.session_id}, inner={self.inner!r})"


# ═══════════════════════════════════════════════════════════════════
# LLM Wrapper — wraps any LangChain LLM
# ═══════════════════════════════════════════════════════════════════

class RtaGuardLLM:
    """
    Wraps any LangChain LLM with RTA-GUARD protection.

    Usage:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI()
        protected_llm = RtaGuardLLM(llm)
        result = protected_llm.invoke("Tell me something")
    """

    def __init__(self, inner_llm: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 guard: Optional[DiscusGuard] = None):
        self.inner = inner_llm
        self.session_id = session_id or f"lc-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.guard = guard or get_guard()

    def _check(self, text: str, is_output: bool = False):
        if not text:
            return
        try:
            self.guard.check(text, session_id=self.session_id)
        except Exception as e:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD {'output' if is_output else 'input'} blocked: {e}")

    def invoke(self, input: Any, **kwargs) -> Any:
        text = str(input) if not isinstance(input, str) else input
        self._check(text, is_output=False)
        result = self.inner.invoke(input, **kwargs)
        result_text = str(result.content) if hasattr(result, "content") else str(result)
        self._check(result_text, is_output=True)
        return result

    async def ainvoke(self, input: Any, **kwargs) -> Any:
        text = str(input) if not isinstance(input, str) else input
        self._check(text, is_output=False)
        result = await self.inner.ainvoke(input, **kwargs)
        result_text = str(result.content) if hasattr(result, "content") else str(result)
        self._check(result_text, is_output=True)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
