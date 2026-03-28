"""
RTA-GUARD — Framework Auto-Detection

Detects installed AI frameworks and provides the appropriate
RTA-GUARD wrapper via a unified interface.

Usage:
    from integrations.detect import detect_frameworks, guard_for

    # Check what's installed
    frameworks = detect_frameworks()
    # → ['langchain', 'llamaindex', 'haystack']

    # Get the right wrapper automatically
    guard = guard_for("langchain")
    # → RtaGuardChain (or appropriate wrapper)
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rta_guard.detect")

# ═══════════════════════════════════════════════════════════════════
# Framework Detection
# ═══════════════════════════════════════════════════════════════════

_FRAMEWORK_MODULES = {
    "langchain": ["langchain", "langchain_core", "langchain_community"],
    "llamaindex": ["llama_index", "llama_index.core"],
    "haystack": ["haystack", "haystack.core"],
    "semantic_kernel": ["semantic_kernel"],
    "crewai": ["crewai"],
    "autogen": ["autogen", "pyautogen"],
}


def _check_module(module_name: str) -> bool:
    """Check if a Python module is installed."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def detect_frameworks() -> List[str]:
    """Detect which AI frameworks are installed.

    Returns:
        List of installed framework names (lowercase).

    Usage:
        frameworks = detect_frameworks()
        if "langchain" in frameworks:
            print("LangChain is available")
    """
    installed = []
    for framework, modules in _FRAMEWORK_MODULES.items():
        if any(_check_module(mod) for mod in modules):
            installed.append(framework)
    return installed


def is_framework_installed(framework: str) -> bool:
    """Check if a specific framework is installed.

    Args:
        framework: Framework name (e.g., "langchain", "crewai")
    Returns:
        True if installed, False otherwise
    """
    modules = _FRAMEWORK_MODULES.get(framework.lower(), [])
    return any(_check_module(mod) for mod in modules)


# ═══════════════════════════════════════════════════════════════════
# Unified Guard Factory
# ═══════════════════════════════════════════════════════════════════

def guard_for(framework: str, inner: Optional[Any] = None,
              **kwargs) -> Any:
    """Get the appropriate RTA-GUARD wrapper for a framework.

    Args:
        framework: Framework name ("langchain", "llamaindex", "haystack",
                   "semantic_kernel", "crewai", "autogen")
        inner: The framework object to wrap (chain, agent, pipeline, etc.)
        **kwargs: Additional arguments passed to the wrapper constructor
    Returns:
        The appropriate RtaGuard wrapper instance

    Raises:
        ImportError: If the framework is not installed
        ValueError: If the framework is not supported

    Usage:
        from integrations import guard_for

        # Wrap a LangChain chain
        protected = guard_for("langchain", chain, session_id="user-1")

        # Wrap a CrewAI crew
        protected = guard_for("crewai", crew)

        # Wrap a Haystack pipeline
        protected = guard_for("haystack", pipeline)
    """
    fw = framework.lower().replace("-", "_").replace(" ", "_")

    if fw in ("langchain", "lc"):
        return _wrap_langchain(inner, **kwargs)
    elif fw in ("llamaindex", "llama_index", "li"):
        return _wrap_llamaindex(inner, **kwargs)
    elif fw in ("haystack", "hs", "deepset"):
        return _wrap_haystack(inner, **kwargs)
    elif fw in ("semantic_kernel", "semantickernel", "sk"):
        return _wrap_semantic_kernel(inner, **kwargs)
    elif fw in ("crewai", "cr", "crew"):
        return _wrap_crewai(inner, **kwargs)
    elif fw in ("autogen", "ag", "auto_gen"):
        return _wrap_autogen(inner, **kwargs)
    else:
        supported = ", ".join(sorted(_FRAMEWORK_MODULES.keys()))
        raise ValueError(
            f"Unsupported framework: {framework}. "
            f"Supported: {supported}"
        )


def _wrap_langchain(inner: Any, **kwargs) -> Any:
    """Wrap a LangChain object."""
    from integrations.langchain import RtaGuardChain, RtaGuardLLM, RtaGuardRunnable
    if inner is None:
        return RtaGuardChain  # Return the class for manual use
    # Auto-detect what type of object it is
    cls_name = type(inner).__name__.lower()
    if "llm" in cls_name or "chat" in cls_name:
        return RtaGuardLLM(inner, **kwargs)
    if "runnable" in cls_name or hasattr(inner, "invoke"):
        return RtaGuardRunnable(inner, **kwargs)
    return RtaGuardChain(inner, **kwargs)


def _wrap_llamaindex(inner: Any, **kwargs) -> Any:
    """Wrap a LlamaIndex object."""
    from integrations.llamaindex import RtaGuardQueryEngine, RtaGuardChatEngine
    if inner is None:
        return RtaGuardQueryEngine
    cls_name = type(inner).__name__.lower()
    if "chat" in cls_name:
        return RtaGuardChatEngine(inner, **kwargs)
    return RtaGuardQueryEngine(inner, **kwargs)


def _wrap_haystack(inner: Any, **kwargs) -> Any:
    """Wrap a Haystack object."""
    from integrations.haystack import RtaGuardPipeline, RtaGuardGenerator, RtaGuardComponent
    if inner is None:
        return RtaGuardPipeline
    cls_name = type(inner).__name__.lower()
    if "generator" in cls_name or "transformer" in cls_name:
        return RtaGuardGenerator(inner, **kwargs)
    if "pipeline" in cls_name:
        return RtaGuardPipeline(inner, **kwargs)
    return RtaGuardComponent(inner, **kwargs)


def _wrap_semantic_kernel(inner: Any, **kwargs) -> Any:
    """Wrap a Semantic Kernel object."""
    from integrations.semantic_kernel import (
        RtaGuardPlugin, RtaGuardFilter, RtaGuardPlanner, RtaGuardChatService
    )
    if inner is None:
        return RtaGuardPlugin
    cls_name = type(inner).__name__.lower()
    if "chat" in cls_name or "completion" in cls_name:
        return RtaGuardChatService(inner, **kwargs)
    if "planner" in cls_name:
        return RtaGuardPlanner(inner, **kwargs)
    if "kernel" in cls_name:
        return RtaGuardFilter(**kwargs)
    return RtaGuardPlugin(**kwargs)


def _wrap_crewai(inner: Any, **kwargs) -> Any:
    """Wrap a CrewAI object."""
    from integrations.crewai import RtaGuardAgent, RtaGuardCrew, RtaGuardTask, RtaGuardTool
    if inner is None:
        return RtaGuardCrew
    cls_name = type(inner).__name__.lower()
    if "crew" in cls_name:
        return RtaGuardCrew(inner, **kwargs)
    if "task" in cls_name:
        return RtaGuardTask(inner, **kwargs)
    if "tool" in cls_name:
        return RtaGuardTool(inner, **kwargs)
    return RtaGuardAgent(inner, **kwargs)


def _wrap_autogen(inner: Any, **kwargs) -> Any:
    """Wrap an AutoGen object."""
    from integrations.autogen import (
        RtaGuardAgent, RtaGuardGroupChat, RtaGuardUserProxy, RtaGuardCodeExecutor
    )
    if inner is None:
        return RtaGuardAgent
    cls_name = type(inner).__name__.lower()
    if "groupchat" in cls_name or "group_chat" in cls_name:
        return RtaGuardGroupChat(inner, **kwargs)
    if "user" in cls_name or "proxy" in cls_name:
        return RtaGuardUserProxy(inner, **kwargs)
    if "code" in cls_name or "executor" in cls_name:
        return RtaGuardCodeExecutor(inner, **kwargs)
    return RtaGuardAgent(inner, **kwargs)
