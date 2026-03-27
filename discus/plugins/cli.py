#!/usr/bin/env python3
"""
RTA-GUARD Plugin CLI

Manage plugins: install, list, remove, validate, test, enable, disable.

Usage:
    python -m discus.plugins.cli list
    python -m discus.plugins.cli install ./my-plugin/
    python -m discus.plugins.cli remove my-plugin-id
    python -m discus.plugins.cli validate ./my-plugin/
    python -m discus.plugins.cli test my-plugin-id
    python -m discus.plugins.cli enable my-plugin-id
    python -m discus.plugins.cli disable my-plugin-id
    python -m discus.plugins.cli stats
    python -m discus.plugins.cli runs [--plugin ID] [--limit N]
    python -m discus.plugins.cli seed
"""
import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discus.plugins import (
    PluginManager, PluginLoader, PluginRegistry,
    PluginSandbox, PluginManifest, InstalledPlugin,
)
from discus.plugins.loader import PluginLoadError


def cmd_list(args):
    """List installed plugins."""
    registry = PluginRegistry()
    plugins = registry.list_all(category=args.category, enabled_only=args.enabled)

    if not plugins:
        print("No plugins installed.")
        print("Run 'python -m discus.plugins.cli seed' to install example plugins.")
        return

    # Group by category
    by_cat = {}
    for p in plugins:
        by_cat.setdefault(p.category, []).append(p)

    for cat, plist in sorted(by_cat.items()):
        print(f"\n📦 {cat.upper()}")
        print("─" * 60)
        for p in plist:
            status = "✅" if p.enabled else "⏸️"
            test = ""
            if p.test_passed is not None:
                test = " | Tests: " + ("✅" if p.test_passed else "❌")
            print(f"  {status} {p.plugin_id} v{p.version} — {p.name}")
            print(f"     {p.description}")
            print(f"     Hooks: {', '.join(p.hooks)} | Author: {p.author}{test}")
    print()


def cmd_install(args):
    """Install a plugin from directory."""
    manager = PluginManager()
    try:
        plugin = manager.install_plugin(args.path)
        print(f"✅ Installed: {plugin.plugin_id} v{plugin.version}")
        print(f"   {plugin.name} — {plugin.description}")
        print(f"   Hooks: {', '.join(plugin.hooks)}")
    except PluginLoadError as e:
        print(f"❌ Installation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_remove(args):
    """Remove a plugin."""
    manager = PluginManager()
    if manager.uninstall_plugin(args.plugin_id):
        print(f"✅ Removed: {args.plugin_id}")
    else:
        print(f"❌ Plugin not found: {args.plugin_id}", file=sys.stderr)
        sys.exit(1)


def cmd_validate(args):
    """Validate a plugin without installing."""
    manifest_path = Path(args.path) / "plugin.yaml"
    if not manifest_path.exists():
        print(f"❌ No plugin.yaml found in {args.path}", file=sys.stderr)
        sys.exit(1)

    try:
        manifest = PluginManifest.from_yaml(manifest_path)
        print(f"✅ Valid manifest: {manifest.plugin_id} v{manifest.version}")
    except Exception as e:
        print(f"❌ Invalid manifest: {e}", file=sys.stderr)
        sys.exit(1)

    entry = Path(args.path) / manifest.entry_point
    if not entry.exists():
        print(f"❌ Entry point not found: {manifest.entry_point}", file=sys.stderr)
        sys.exit(1)

    sandbox = PluginSandbox()
    source = entry.read_text()
    issues = sandbox.validate_ast(source, str(entry))
    if issues:
        print(f"❌ Sandbox validation failed:")
        for issue in issues:
            print(f"   • {issue}")
        sys.exit(1)
    else:
        print(f"✅ Sandbox validation passed")

    # Try loading
    try:
        plugin_class = sandbox.load_plugin_module(Path(args.path), manifest.entry_point, manifest.class_name)
        instance = plugin_class()
        print(f"✅ Plugin loads successfully: {manifest.class_name}")
    except Exception as e:
        print(f"❌ Load failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_test(args):
    """Run test cases for a plugin."""
    manager = PluginManager()
    manager.loader.load_all()
    result = manager.test_plugin(args.plugin_id)

    print(f"\n{'✅' if result['passed'] else '❌'} Test results for {args.plugin_id}:")
    print("─" * 50)
    for line in result.get("results", []):
        print(f"  {line}")
    print()


def cmd_enable(args):
    """Enable a plugin."""
    registry = PluginRegistry()
    if registry.set_enabled(args.plugin_id, True):
        print(f"✅ Enabled: {args.plugin_id}")
    else:
        print(f"❌ Plugin not found: {args.plugin_id}", file=sys.stderr)


def cmd_disable(args):
    """Disable a plugin."""
    registry = PluginRegistry()
    if registry.set_enabled(args.plugin_id, False):
        print(f"⏸️ Disabled: {args.plugin_id}")
    else:
        print(f"❌ Plugin not found: {args.plugin_id}", file=sys.stderr)


def cmd_stats(args):
    """Show plugin statistics."""
    registry = PluginRegistry()
    stats = registry.get_stats()
    print("\n📊 Plugin Statistics")
    print("─" * 40)
    print(f"  Total plugins:   {stats['total_plugins']}")
    print(f"  Enabled:         {stats['enabled_plugins']}")
    print(f"  Total runs:      {stats['total_runs']}")
    print(f"  Violations:      {stats['total_violations']}")
    print(f"  Avg duration:    {stats['avg_duration_ms']}ms")
    print()


def cmd_runs(args):
    """Show recent plugin runs."""
    registry = PluginRegistry()
    runs = registry.get_runs(plugin_id=args.plugin, limit=args.limit)

    if not runs:
        print("No plugin runs recorded.")
        return

    print(f"\n📝 Recent Runs (last {args.limit})")
    print("─" * 70)
    for run in runs:
        status = "🛑" if run["violated"] else "✅"
        print(f"  {status} [{run['hook']}] {run['plugin_id']} — {run['message'] or 'pass'} "
              f"({run['duration_ms']:.1f}ms)")
    print()


def cmd_seed(args):
    """Install seed/example plugins."""
    seed_dir = Path(__file__).parent.parent.parent / "plugins"
    if not seed_dir.exists():
        print(f"❌ Seed plugins directory not found: {seed_dir}", file=sys.stderr)
        sys.exit(1)

    manager = PluginManager()
    installed = 0
    for plugin_dir in sorted(seed_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / "plugin.yaml"
        if not manifest_path.exists():
            continue
        try:
            plugin = manager.install_plugin(plugin_dir)
            print(f"  ✅ {plugin.plugin_id} — {plugin.name}")
            installed += 1
        except PluginLoadError as e:
            print(f"  ❌ {plugin_dir.name}: {e}")

    print(f"\n{'✅' if installed else '⚠️'} Installed {installed} seed plugins.")
    if installed:
        print("Run 'python -m discus.plugins.cli list' to see them.")


def main():
    parser = argparse.ArgumentParser(
        prog="rta-guard plugin",
        description="RTA-GUARD Plugin Manager",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # list
    p = sub.add_parser("list", help="List installed plugins")
    p.add_argument("--category", help="Filter by category")
    p.add_argument("--enabled", action="store_true", help="Show only enabled")

    # install
    p = sub.add_parser("install", help="Install a plugin from directory")
    p.add_argument("path", help="Path to plugin directory")

    # remove
    p = sub.add_parser("remove", help="Remove a plugin")
    p.add_argument("plugin_id", help="Plugin ID to remove")

    # validate
    p = sub.add_parser("validate", help="Validate a plugin without installing")
    p.add_argument("path", help="Path to plugin directory")

    # test
    p = sub.add_parser("test", help="Run test cases for a plugin")
    p.add_argument("plugin_id", help="Plugin ID to test")

    # enable/disable
    p = sub.add_parser("enable", help="Enable a plugin")
    p.add_argument("plugin_id", help="Plugin ID")
    p = sub.add_parser("disable", help="Disable a plugin")
    p.add_argument("plugin_id", help="Plugin ID")

    # stats
    sub.add_parser("stats", help="Show plugin statistics")

    # runs
    p = sub.add_parser("runs", help="Show recent plugin runs")
    p.add_argument("--plugin", help="Filter by plugin ID")
    p.add_argument("--limit", type=int, default=50, help="Max runs to show")

    # seed
    sub.add_parser("seed", help="Install example/seed plugins")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "list": cmd_list, "install": cmd_install, "remove": cmd_remove,
        "validate": cmd_validate, "test": cmd_test, "enable": cmd_enable,
        "disable": cmd_disable, "stats": cmd_stats, "runs": cmd_runs,
        "seed": cmd_seed,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
