"""
RTA-GUARD — CrewAI Integration

Drop-in protection for CrewAI agents, tasks, crews, and tools.
Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.crewai import RtaGuardAgent, RtaGuardCrew

    # Option 1: Wrap individual agents
    agent = Agent(role="Researcher", goal="...", backstory="...")
    protected_agent = RtaGuardAgent(agent)

    # Option 2: Wrap the entire crew
    crew = Crew(agents=[agent1, agent2], tasks=[task1, task2])
    protected_crew = RtaGuardCrew(crew)
    result = protected_crew.kickoff()
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("rta_guard.crewai")

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
# Agent Wrapper — wraps CrewAI Agent with input/output protection
# ═══════════════════════════════════════════════════════════════════

class RtaGuardAgent:
    """
    Wraps a CrewAI Agent with RTA-GUARD protection.
    Checks agent inputs, outputs, and execution context.

    Usage:
        agent = Agent(role="Researcher", goal="Find information",
                      backstory="Expert researcher", llm=llm)
        protected = RtaGuardAgent(agent)
        result = protected.execute("Research quantum computing")
    """

    def __init__(self, inner_agent: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_agent: The CrewAI Agent to wrap
            session_id: Session identifier (auto-generated if None)
            on_violation: What to do on violation: "raise", "warn", "block"
            check_input: Check agent inputs before execution
            check_output: Check agent outputs after execution
            guard: Custom DiscusGuard instance (uses shared if None)
        """
        self.inner = inner_agent
        self.session_id = session_id or f"cr-agent-{uuid.uuid4().hex[:8]}"
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
            logger.warning(f"RTA-GUARD agent violation: {e}")
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
            return data.get("input", data.get("query", data.get("text", "")))
        return str(data)[:500]

    def execute(self, input_data: Any, **kwargs) -> Any:
        """Execute agent with input/output protection.

        Args:
            input_data: The input for the agent
        Returns:
            Agent output (safe) or blocked message
        """
        # Check input
        text = self._extract_text(input_data)
        if self.check_input and text:
            self._last_input = text
            violation = self._check(text, is_output=False)
            if violation and self.on_violation == "raise":
                self._handle_violation(violation)

        # Execute
        if hasattr(self.inner, "execute"):
            result = self.inner.execute(input_data, **kwargs)
        elif hasattr(self.inner, "run"):
            result = self.inner.run(input_data, **kwargs)
        else:
            result = self.inner(input_data, **kwargs)

        # Check output
        if self.check_output:
            output_text = self._extract_text(result)
            if output_text:
                self._last_output = output_text
                violation = self._check(output_text, is_output=True)
                if violation:
                    return self._handle_violation(violation)

        return result

    async def execute_async(self, input_data: Any, **kwargs) -> Any:
        """Async execute agent with protection."""
        text = self._extract_text(input_data)
        if self.check_input and text:
            violation = self._check(text, is_output=False)
            if violation and self.on_violation == "raise":
                self._handle_violation(violation)

        if hasattr(self.inner, "execute_async"):
            result = await self.inner.execute_async(input_data, **kwargs)
        elif hasattr(self.inner, "execute"):
            result = self.inner.execute(input_data, **kwargs)
        else:
            result = self.inner(input_data, **kwargs)

        if self.check_output:
            output_text = self._extract_text(result)
            if output_text:
                violation = self._check(output_text, is_output=True)
                if violation:
                    return self._handle_violation(violation)

        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        role = getattr(self.inner, "role", "unknown")
        return f"RtaGuardAgent(session={self.session_id}, role={role!r})"


# ═══════════════════════════════════════════════════════════════════
# Task Wrapper — wraps CrewAI Task with validation
# ═══════════════════════════════════════════════════════════════════

class RtaGuardTask:
    """
    Wraps a CrewAI Task with RTA-GUARD protection.
    Validates task descriptions and results. Catches task poisoning.

    Usage:
        task = Task(description="Research AI safety",
                    agent=researcher, expected_output="Report")
        protected = RtaGuardTask(task)
        result = protected.execute()
    """

    def __init__(self, inner_task: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_description: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_task: The CrewAI Task to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_description: Check task description for injection
            check_output: Check task result for violations
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_task
        self.session_id = session_id or f"cr-task-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_description = check_description
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
            logger.warning(f"RTA-GUARD task violation: {e}")
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

    def execute(self, **kwargs) -> Any:
        """Execute task with input/output protection.

        Returns:
            Task result (safe) or blocked message
        """
        # Check task description
        if self.check_description:
            desc = getattr(self.inner, "description", "")
            if desc:
                self._handle(desc, is_output=False)

        # Execute task
        if hasattr(self.inner, "execute"):
            result = self.inner.execute(**kwargs)
        elif hasattr(self.inner, "run"):
            result = self.inner.run(**kwargs)
        else:
            result = self.inner(**kwargs)

        # Check result
        if self.check_output and result:
            result_text = str(result)
            handled = self._handle(result_text, is_output=True)
            if handled == "[BLOCKED BY RTA-GUARD]":
                return handled

        return result

    async def execute_async(self, **kwargs) -> Any:
        """Async execute task with protection."""
        if self.check_description:
            desc = getattr(self.inner, "description", "")
            if desc:
                self._handle(desc, is_output=False)

        if hasattr(self.inner, "execute_async"):
            result = await self.inner.execute_async(**kwargs)
        elif hasattr(self.inner, "execute"):
            result = self.inner.execute(**kwargs)
        else:
            result = self.inner(**kwargs)

        if self.check_output and result:
            self._handle(str(result), is_output=True)

        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        desc = getattr(self.inner, "description", "")[:50]
        return f"RtaGuardTask(session={self.session_id}, desc={desc!r})"


# ═══════════════════════════════════════════════════════════════════
# Crew Wrapper — wraps CrewAI Crew for full orchestration protection
# ═══════════════════════════════════════════════════════════════════

class RtaGuardCrew:
    """
    Wraps a CrewAI Crew with RTA-GUARD protection.
    Monitors inter-agent communication and catches agent-to-agent manipulation.

    Usage:
        crew = Crew(agents=[researcher, writer], tasks=[task1, task2])
        protected = RtaGuardCrew(crew)
        result = protected.kickoff()
    """

    def __init__(self, inner_crew: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_inter_agent: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_crew: The CrewAI Crew to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_inter_agent: Monitor agent-to-agent communication
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_crew
        self.session_id = session_id or f"cr-crew-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_inter_agent = check_inter_agent
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []
        self._agent_sessions: Dict[str, str] = {}

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
            logger.warning(f"RTA-GUARD crew violation: {e}")
            return str(e)

    def _handle(self, text: str, is_output: bool = False,
                session_id: Optional[str] = None) -> str:
        error = self._check(text, is_output, session_id)
        if error:
            if self.on_violation == "raise":
                raise RuntimeError(
                    f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
                )
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
        return text

    def _wrap_agents(self, crew: Any) -> Any:
        """Wrap all agents in the crew with individual guard sessions."""
        agents = getattr(crew, "agents", [])
        for i, agent in enumerate(agents):
            agent_role = getattr(agent, "role", f"agent-{i}")
            agent_sid = f"{self.session_id}:{agent_role}"
            self._agent_sessions[agent_role] = agent_sid
            if not isinstance(agent, RtaGuardAgent):
                crew.agents[i] = RtaGuardAgent(
                    agent, session_id=agent_sid,
                    on_violation=self.on_violation,
                    guard=self.guard,
                )
        return crew

    def _wrap_tasks(self, crew: Any) -> Any:
        """Wrap all tasks in the crew with guard sessions."""
        tasks = getattr(crew, "tasks", [])
        for i, task in enumerate(tasks):
            task_sid = f"{self.session_id}:task-{i}"
            if not isinstance(task, RtaGuardTask):
                crew.tasks[i] = RtaGuardTask(
                    task, session_id=task_sid,
                    on_violation=self.on_violation,
                    guard=self.guard,
                )
        return crew

    def kickoff(self, **kwargs) -> Any:
        """Execute crew with full protection.

        Returns:
            Crew result (safe) or blocked message
        """
        # Wrap agents and tasks
        self._wrap_agents(self.inner)
        self._wrap_tasks(self.inner)

        # Execute crew
        result = self.inner.kickoff(**kwargs)

        # Check final output
        if result:
            result_text = str(result)
            handled = self._handle(result_text, is_output=True)
            if handled == "[BLOCKED BY RTA-GUARD]":
                return handled

        return result

    async def kickoff_async(self, **kwargs) -> Any:
        """Async execute crew with protection."""
        self._wrap_agents(self.inner)
        self._wrap_tasks(self.inner)

        if hasattr(self.inner, "kickoff_async"):
            result = await self.inner.kickoff_async(**kwargs)
        elif hasattr(self.inner, "kickoff"):
            result = self.inner.kickoff(**kwargs)
        else:
            result = self.inner(**kwargs)

        if result:
            self._handle(str(result), is_output=True)

        return result

    def get_all_violations(self) -> List[Dict[str, Any]]:
        """Get violations from all agents and the crew itself."""
        all_violations = list(self._violations)
        agents = getattr(self.inner, "agents", [])
        for agent in agents:
            if isinstance(agent, RtaGuardAgent):
                all_violations.extend(agent.violations)
        tasks = getattr(self.inner, "tasks", [])
        for task in tasks:
            if isinstance(task, RtaGuardTask):
                all_violations.extend(task.violations)
        return all_violations

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardCrew(session={self.session_id}, inner={self.inner!r})"


# ═══════════════════════════════════════════════════════════════════
# Tool Wrapper — wraps CrewAI Tool execution
# ═══════════════════════════════════════════════════════════════════

class RtaGuardTool:
    """
    Wraps a CrewAI Tool with RTA-GUARD protection.
    Checks tool inputs and outputs for violations.

    Usage:
        tool = Tool(name="search", func=search_fn, description="Search the web")
        protected = RtaGuardTool(tool)
        result = protected.run("What is quantum computing?")
    """

    def __init__(self, inner_tool: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_tool: The CrewAI Tool to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_input: Check tool inputs
            check_output: Check tool outputs
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_tool
        self.session_id = session_id or f"cr-tool-{uuid.uuid4().hex[:8]}"
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
            logger.warning(f"RTA-GUARD tool violation: {e}")
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

    def run(self, input_data: Any, **kwargs) -> Any:
        """Run tool with input/output protection.

        Args:
            input_data: Tool input
        Returns:
            Tool output (safe) or blocked message
        """
        text = str(input_data) if not isinstance(input_data, str) else input_data

        # Check input
        if self.check_input:
            self._handle(text, is_output=False)

        # Run tool
        if hasattr(self.inner, "run"):
            result = self.inner.run(input_data, **kwargs)
        elif hasattr(self.inner, "func") and callable(self.inner.func):
            result = self.inner.func(input_data, **kwargs)
        elif callable(self.inner):
            result = self.inner(input_data, **kwargs)
        else:
            raise AttributeError(f"Tool {type(self.inner)} has no run method or func")

        # Check output
        if self.check_output and result:
            result_text = str(result)
            handled = self._handle(result_text, is_output=True)
            if handled == "[BLOCKED BY RTA-GUARD]":
                return handled

        return result

    async def run_async(self, input_data: Any, **kwargs) -> Any:
        """Async run tool with protection."""
        text = str(input_data) if not isinstance(input_data, str) else input_data

        if self.check_input:
            self._handle(text, is_output=False)

        if hasattr(self.inner, "run_async"):
            result = await self.inner.run_async(input_data, **kwargs)
        elif hasattr(self.inner, "run"):
            result = self.inner.run(input_data, **kwargs)
        elif hasattr(self.inner, "func") and callable(self.inner.func):
            result = self.inner.func(input_data, **kwargs)
        else:
            result = self.inner(input_data, **kwargs)

        if self.check_output and result:
            self._handle(str(result), is_output=True)

        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        name = getattr(self.inner, "name", "unknown")
        return f"RtaGuardTool(session={self.session_id}, name={name!r})"
