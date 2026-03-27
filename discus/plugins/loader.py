"""
RTA-GUARD — Plugin Loader

Discovers, validates, loads, and manages plugins from disk.
Supports hot-loading: add/remove plugins without restarting the guard.
"""
import importlib
import importlib.util
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .spec import PluginManifest, PluginBase, PluginHook, PluginContext, PluginResult, PluginSeverity
from .sandbox import PluginSandbox, SandboxViolation
from .registry import PluginRegistry, InstalledPlugin

logger = logging.getLogger("discus.plugins.loader")

# Default plugin search paths
DEFAULT_PLUGIN_DIRS = [
    Path.cwd() / "plugins",
    Path.home() / ".rta-guard" / "plugins",
    Path("/usr/local/share/rta-guard/plugins"),
]


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""
    pass


class PluginLoader:
    """
    Discovers and loads RTA-GUARD plugins from disk.

    Plugin directory structure:
        plugins/
          my-plugin/
            plugin.yaml      # Manifest
            plugin.py         # Code (PluginBase subclass)
            tests/
              test_plugin.py  # Optional tests
    """

    def __init__(
        self,
        search_dirs: Optional[List[Path]] = None,
        registry: Optional[PluginRegistry] = None,
        sandbox: Optional[PluginSandbox] = None,
    ):
        self.search_dirs = search_dirs or DEFAULT_PLUGIN_DIRS
        self.registry = registry or PluginRegistry()
        self.sandbox = sandbox or PluginSandbox()

        # Loaded plugin instances (plugin_id -> instance)
        self._loaded: Dict[str, PluginBase] = {}
        # Loaded manifests
        self._manifests: Dict[str, PluginManifest] = {}

    def discover(self) -> List[Tuple[Path, PluginManifest]]:
        """
        Discover plugins in search directories.
        Returns list of (plugin_dir, manifest) tuples.
        """
        discovered = []
        for search_dir in self.search_dirs:
            if not search_dir.exists():
                continue
            for plugin_dir in search_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest_path = plugin_dir / "plugin.yaml"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = PluginManifest.from_yaml(manifest_path)
                    discovered.append((plugin_dir, manifest))
                except Exception as e:
                    logger.warning(f"Invalid manifest in {plugin_dir}: {e}")
        return discovered

    def load_plugin(self, plugin_dir: Path, manifest: PluginManifest) -> PluginBase:
        """
        Load a single plugin from disk.
        Validates, sandbox-checks, imports, and instantiates the plugin.
        """
        entry_file = plugin_dir / manifest.entry_point
        if not entry_file.exists():
            raise PluginLoadError(f"Entry point not found: {entry_file}")

        # Validate via sandbox
        source = entry_file.read_text()
        issues = self.sandbox.validate_ast(source, str(entry_file))
        if issues:
            raise PluginLoadError(f"Sandbox validation failed for {manifest.plugin_id}:\n" + "\n".join(issues))

        # Load the class
        try:
            plugin_class = self.sandbox.load_plugin_module(
                plugin_dir, manifest.entry_point, manifest.class_name
            )
        except SandboxViolation as e:
            raise PluginLoadError(f"Sandbox violation in {manifest.plugin_id}: {e}")
        except Exception as e:
            raise PluginLoadError(f"Failed to load {manifest.plugin_id}: {e}")

        # Instantiate
        try:
            instance = plugin_class()
        except Exception as e:
            raise PluginLoadError(f"Failed to instantiate {manifest.plugin_id}: {e}")

        # Populate metadata from manifest
        instance.plugin_id = manifest.plugin_id
        instance.name = manifest.name
        instance.version = manifest.version
        instance.description = manifest.description
        instance.author = manifest.author
        instance.category = manifest.category
        instance.tags = manifest.tags
        instance.hooks = [PluginHook(h) for h in manifest.hooks if h in [v.value for v in PluginHook]]

        # Call setup
        try:
            instance.setup()
        except Exception as e:
            raise PluginLoadError(f"Plugin setup failed for {manifest.plugin_id}: {e}")

        # Register in registry
        installed = InstalledPlugin(
            plugin_id=manifest.plugin_id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            category=manifest.category,
            tags=manifest.tags,
            hooks=manifest.hooks,
            install_path=str(plugin_dir),
            fingerprint=manifest.fingerprint,
            enabled=True,
            installed_at=time.time(),
            config=manifest.config,
        )
        self.registry.register(installed)

        self._loaded[manifest.plugin_id] = instance
        self._manifests[manifest.plugin_id] = manifest
        logger.info(f"Loaded plugin: {manifest.plugin_id} v{manifest.version} by {manifest.author}")
        return instance

    def unload_plugin(self, plugin_id: str) -> bool:
        """Unload a plugin, calling teardown."""
        if plugin_id not in self._loaded:
            return False
        try:
            self._loaded[plugin_id].teardown()
        except Exception as e:
            logger.warning(f"Plugin teardown error for {plugin_id}: {e}")
        del self._loaded[plugin_id]
        del self._manifests[plugin_id]
        self.registry.set_enabled(plugin_id, False)
        logger.info(f"Unloaded plugin: {plugin_id}")
        return True

    def reload_plugin(self, plugin_id: str) -> Optional[PluginBase]:
        """Reload a plugin (teardown + load)."""
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            return None
        plugin_dir = Path(self._loaded[plugin_id].__class__.__module__.replace(".", "/")).parent
        self.unload_plugin(plugin_id)
        # Re-discover to find the directory
        for dir_path, m in self.discover():
            if m.plugin_id == plugin_id:
                return self.load_plugin(dir_path, m)
        return None

    def load_all(self) -> Dict[str, PluginBase]:
        """Discover and load all plugins."""
        discovered = self.discover()
        loaded = {}
        for plugin_dir, manifest in discovered:
            try:
                instance = self.load_plugin(plugin_dir, manifest)
                loaded[manifest.plugin_id] = instance
            except PluginLoadError as e:
                logger.error(f"Failed to load {manifest.plugin_id}: {e}")
        return loaded

    def get_loaded(self, plugin_id: str) -> Optional[PluginBase]:
        """Get a loaded plugin instance by ID."""
        return self._loaded.get(plugin_id)

    def get_all_loaded(self) -> Dict[str, PluginBase]:
        """Get all loaded plugin instances."""
        return dict(self._loaded)

    def get_hooks_map(self) -> Dict[PluginHook, List[PluginBase]]:
        """Get plugins grouped by hook for fast lookup."""
        hooks: Dict[PluginHook, List[PluginBase]] = {}
        for plugin in self._loaded.values():
            if not self.registry.get(plugin.plugin_id):
                continue
            reg = self.registry.get(plugin.plugin_id)
            if reg and not reg.enabled:
                continue
            for hook in plugin.hooks:
                hooks.setdefault(hook, []).append(plugin)
        return hooks

    def install_from_path(self, source_dir: Path, target_dir: Optional[Path] = None) -> PluginManifest:
        """
        Install a plugin from a source directory to the target plugins directory.
        Validates manifest and code before copying.
        """
        manifest_path = source_dir / "plugin.yaml"
        if not manifest_path.exists():
            raise PluginLoadError(f"No plugin.yaml found in {source_dir}")

        manifest = PluginManifest.from_yaml(manifest_path)

        # Validate entry point exists
        entry = source_dir / manifest.entry_point
        if not entry.exists():
            raise PluginLoadError(f"Entry point {manifest.entry_point} not found")

        # Validate sandbox
        source = entry.read_text()
        issues = self.sandbox.validate_ast(source, str(entry))
        if issues:
            raise PluginLoadError(f"Sandbox validation failed:\n" + "\n".join(issues))

        # Copy to target
        target = target_dir or self.search_dirs[0]
        target.mkdir(parents=True, exist_ok=True)
        dest = target / manifest.plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_dir, dest)

        logger.info(f"Installed plugin {manifest.plugin_id} to {dest}")
        return manifest

    def uninstall(self, plugin_id: str) -> bool:
        """Uninstall a plugin: unload + remove from disk + registry."""
        self.unload_plugin(plugin_id)

        reg = self.registry.get(plugin_id)
        if reg and reg.install_path:
            path = Path(reg.install_path)
            if path.exists():
                shutil.rmtree(path)
                logger.info(f"Removed plugin directory: {path}")

        return self.registry.unregister(plugin_id)
