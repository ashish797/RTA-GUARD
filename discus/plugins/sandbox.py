"""
RTA-GUARD — Plugin Sandbox

Executes plugins in a restricted environment to prevent malicious code execution.
Restricts: file I/O, network, imports, subprocess, eval/exec of external code.
"""
import ast
import importlib
import importlib.util
import sys
import types
import logging
from pathlib import Path
from typing import Any, Dict, Set, Optional

logger = logging.getLogger("discus.plugins.sandbox")

# ─── Dangerous imports/operations blocked by sandbox ──────────────

BLOCKED_MODULES: Set[str] = {
    "os", "subprocess", "shutil", "socket", "http",
    "urllib", "requests", "httpx", "aiohttp",
    "ctypes", "multiprocessing", "threading",
    "__builtin__", "builtins",
    "signal", "faulthandler", "gc",
    "pickle", "shelve", "dbm",
    "tempfile",
}

BLOCKED_BUILTINS: Set[str] = {
    "exec", "eval", "__import__",
    "open", "input", "breakpoint",
    "exit", "quit",
    "globals", "locals", "vars",
    "setattr", "delattr",
}

ALLOWED_MODULES: Set[str] = {
    "re", "math", "json", "datetime", "collections",
    "itertools", "functools", "string", "typing",
    "hashlib", "base64", "unicodedata",
    "dataclasses", "enum", "abc",
    "copy", "operator", "statistics",
    "discus",  # Allow discus.plugins imports for plugin base class
}


class SandboxViolation(Exception):
    """Raised when a plugin tries to do something forbidden."""
    pass


class RestrictedImporter:
    """Custom import hook that blocks dangerous modules."""

    def __init__(self, allowed: Set[str], blocked: Set[str]):
        self.allowed = allowed
        self.blocked = blocked
        self._original_import = None

    def install(self):
        self._original_import = builtins_ref.__import__
        builtins_ref.__import__ = self._restricted_import

    def uninstall(self):
        if self._original_import:
            builtins_ref.__import__ = self._original_import

    def _restricted_import(self, name: str, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level in self.blocked:
            raise SandboxViolation(f"Plugin attempted to import blocked module: {name}")
        if self.allowed and top_level not in self.allowed:
            raise SandboxViolation(f"Plugin attempted to import non-allowed module: {name}")
        return self._original_import(name, *args, **kwargs)


# Will be set when sandbox is initialized
builtins_ref = None


class PluginSandbox:
    """
    Executes plugin code in a restricted sandbox.

    Features:
    - AST validation: scans for dangerous calls before execution
    - Restricted builtins: blocks exec, eval, open, __import__, etc.
    - Module allowlist: only safe standard library modules
    - No file I/O, no network, no subprocess
    - Timeout protection (via caller)
    """

    def __init__(self):
        self._importer: Optional[RestrictedImporter] = None

    def validate_ast(self, source_code: str, filename: str = "<plugin>") -> list[str]:
        """
        Validate Python source code via AST analysis.
        Returns list of warnings/errors found.
        """
        issues = []
        try:
            tree = ast.parse(source_code, filename)
        except SyntaxError as e:
            return [f"Syntax error: {e}"]

        for node in ast.walk(tree):
            # Check for dangerous function calls
            if isinstance(node, ast.Call):
                func = node.func
                func_name = None
                is_module_method = False
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr
                    is_module_method = True  # e.g., re.compile() — safe

                # Only flag builtin calls (not module methods like re.compile)
                if func_name in BLOCKED_BUILTINS and not is_module_method:
                    issues.append(f"Blocked builtin call: {func_name}() at line {node.lineno}")

            # Check for import statements
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in BLOCKED_MODULES:
                        issues.append(f"Blocked import: {alias.name} at line {node.lineno}")
                    elif top not in ALLOWED_MODULES:
                        issues.append(f"Unknown import (not in allowlist): {alias.name} at line {node.lineno}")

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in BLOCKED_MODULES:
                        issues.append(f"Blocked import from: {node.module} at line {node.lineno}")
                    elif top not in ALLOWED_MODULES:
                        issues.append(f"Unknown import from (not in allowlist): {node.module} at line {node.lineno}")

            # Check for attribute access on dangerous modules
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in BLOCKED_MODULES:
                    issues.append(f"Access to blocked module attribute: {node.value.id}.{node.attr} at line {node.lineno}")

        return issues

    def load_plugin_module(self, plugin_dir: Path, entry_point: str, class_name: str) -> type:
        """
        Load a plugin class from a directory in the sandbox.

        Args:
            plugin_dir: Path to plugin directory
            entry_point: Python filename (e.g., "plugin.py")
            class_name: Class name to instantiate

        Returns:
            The plugin class
        """
        plugin_file = plugin_dir / entry_point
        if not plugin_file.exists():
            raise FileNotFoundError(f"Plugin entry point not found: {plugin_file}")

        source_code = plugin_file.read_text()

        # Step 1: AST validation
        issues = self.validate_ast(source_code, str(plugin_file))
        if issues:
            raise SandboxViolation(f"Plugin failed sandbox validation:\n" + "\n".join(issues))

        # Step 2: Load in restricted environment
        global builtins_ref
        builtins_ref = __builtins__ if isinstance(__builtins__, types.ModuleType) else types.ModuleType("builtins")
        for attr in dir(builtins_ref):
            pass

        # Create restricted builtins
        restricted_builtins = {}
        builtin_source = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
        for name, val in builtin_source.items():
            if name not in BLOCKED_BUILTINS:
                restricted_builtins[name] = val

        # Add restricted __import__ that allows safe modules
        _orig_import = builtin_source.get("__import__", __import__)

        def _restricted_import(name, *args, **kwargs):
            top = name.split(".")[0]
            if top in BLOCKED_MODULES:
                raise SandboxViolation(f"Import blocked: {name}")
            if ALLOWED_MODULES and top not in ALLOWED_MODULES:
                raise SandboxViolation(f"Import not allowed: {name}")
            return _orig_import(name, *args, **kwargs)

        restricted_builtins["__import__"] = _restricted_import
        restricted_builtins["SandboxViolation"] = SandboxViolation

        # Create module with restricted globals
        module_globals = {
            "__builtins__": restricted_builtins,
            "__name__": f"rta_guard_plugin.{plugin_dir.name}",
            "__file__": str(plugin_file),
        }

        # Execute the module
        module = types.ModuleType(f"rta_guard_plugin.{plugin_dir.name}")
        module.__dict__.update(module_globals)

        try:
            exec(compile(source_code, str(plugin_file), "exec"), module.__dict__)
        except SandboxViolation:
            raise
        except Exception as e:
            raise RuntimeError(f"Plugin execution failed: {e}")

        # Step 3: Extract the plugin class
        if not hasattr(module, class_name):
            raise AttributeError(f"Plugin class '{class_name}' not found in {entry_point}")

        plugin_class = getattr(module, class_name)
        if not isinstance(plugin_class, type):
            raise TypeError(f"'{class_name}' is not a class")

        return plugin_class

    def run_with_timeout(self, func, *args, timeout_ms: int = 500, **kwargs):
        """
        Run a function with a timeout. Note: Python doesn't have true
        thread-level timeout for arbitrary code. This uses a simple
        signal-based approach on Unix, or falls back to no-timeout on Windows.

        For production, use subprocess-based isolation.
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError(f"Plugin execution exceeded {timeout_ms}ms timeout")

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000.0)
        try:
            return func(*args, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
