"""
RTA-GUARD — Plugin System

Import this package to access plugin infrastructure.
"""
from .spec import (
    PluginBase, PluginHook, PluginContext, PluginResult,
    PluginSeverity, PluginManifest,
)
from .sandbox import PluginSandbox, SandboxViolation
from .registry import PluginRegistry, InstalledPlugin
from .loader import PluginLoader, PluginLoadError
from .manager import PluginManager

__all__ = [
    "PluginBase", "PluginHook", "PluginContext", "PluginResult",
    "PluginSeverity", "PluginManifest",
    "PluginSandbox", "SandboxViolation",
    "PluginRegistry", "InstalledPlugin",
    "PluginLoader", "PluginLoadError",
    "PluginManager",
]
