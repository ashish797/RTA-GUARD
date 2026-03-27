"""
RTA-GUARD — Plugin System Core

Defines the plugin spec, hooks, and base class for community rules.
Plugins extend RTA-GUARD with custom validation logic without modifying core code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path
import yaml
import hashlib
import time


class PluginHook(Enum):
    """Available plugin hooks — when a plugin gets called."""
    ON_INPUT = "on_input"           # Before guard checks input
    ON_OUTPUT = "on_output"         # After LLM generates output
    ON_VIOLATION = "on_violation"   # When any violation is detected
    ON_SESSION_START = "on_session_start"  # When a new session starts
    ON_SESSION_END = "on_session_end"      # When a session ends (killed or closed)


class PluginSeverity(Enum):
    """Plugin violation severity — maps to guard decisions."""
    PASS = "pass"
    WARN = "warn"
    KILL = "kill"


@dataclass
class PluginResult:
    """Result returned by a plugin check."""
    plugin_id: str
    hook: PluginHook
    violated: bool
    severity: PluginSeverity = PluginSeverity.PASS
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # 0.0 = clean, 1.0 = certain violation

    @property
    def should_kill(self) -> bool:
        return self.violated and self.severity == PluginSeverity.KILL

    @property
    def should_warn(self) -> bool:
        return self.violated and self.severity == PluginSeverity.WARN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "hook": self.hook.value,
            "violated": self.violated,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "score": self.score,
        }


@dataclass
class PluginContext:
    """Context passed to plugins during execution."""
    session_id: str
    input_text: str = ""
    output_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    # Available on violation hook
    violation_type: Optional[str] = None
    violation_severity: Optional[str] = None


class PluginBase(ABC):
    """
    Base class for RTA-GUARD plugins.

    Subclass this and implement check() to create a plugin.
    The plugin.yaml file defines metadata; this class defines behavior.
    """

    # Populated from plugin.yaml by the loader
    plugin_id: str = "unknown"
    name: str = "Unknown Plugin"
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    hooks: List[PluginHook] = []
    category: str = "general"
    tags: List[str] = []

    @abstractmethod
    def check(self, context: PluginContext, hook: PluginHook) -> PluginResult:
        """
        Execute the plugin check.

        Args:
            context: The current session context
            hook: Which hook triggered this check

        Returns:
            PluginResult with violation status and details
        """
        pass

    def setup(self) -> None:
        """Called once when the plugin is loaded. Override for initialization."""
        pass

    def teardown(self) -> None:
        """Called when the plugin is unloaded. Override for cleanup."""
        pass


@dataclass
class PluginManifest:
    """
    Parsed plugin.yaml manifest — defines plugin metadata and configuration.
    """
    plugin_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    entry_point: str = "plugin.py"  # Python file containing the PluginBase subclass
    class_name: str = "Plugin"      # Name of the class to instantiate
    config: Dict[str, Any] = field(default_factory=dict)  # Plugin-specific config
    rta_guard_version: str = ">=2.0.0"
    python_version: str = ">=3.11"
    dependencies: List[str] = field(default_factory=list)  # pip packages needed

    @classmethod
    def from_yaml(cls, path: Path) -> "PluginManifest":
        """Load manifest from plugin.yaml."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            category=data.get("category", "general"),
            tags=data.get("tags", []),
            hooks=data.get("hooks", ["on_input"]),
            entry_point=data.get("entry_point", "plugin.py"),
            class_name=data.get("class_name", "Plugin"),
            config=data.get("config", {}),
            rta_guard_version=data.get("rta_guard_version", ">=2.0.0"),
            python_version=data.get("python_version", ">=3.11"),
            dependencies=data.get("dependencies", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "hooks": self.hooks,
            "entry_point": self.entry_point,
            "class_name": self.class_name,
            "config": self.config,
            "rta_guard_version": self.rta_guard_version,
            "python_version": self.python_version,
            "dependencies": self.dependencies,
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 fingerprint of the manifest for integrity checking."""
        content = yaml.dump(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
