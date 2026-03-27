"""
RTA-GUARD Plugin System Tests

Tests for: spec, sandbox, registry, loader, manager, and seed plugins.
"""
import os
import sys
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.plugins import (
    PluginBase, PluginHook, PluginContext, PluginResult,
    PluginSeverity, PluginManifest, PluginSandbox, SandboxViolation,
    PluginRegistry, PluginLoader, PluginManager, InstalledPlugin,
)


# ─── Plugin Spec Tests ─────────────────────────────────────────────

class TestPluginSpec(unittest.TestCase):
    def test_plugin_result(self):
        r = PluginResult(plugin_id="test", hook=PluginHook.ON_INPUT, violated=True, severity=PluginSeverity.KILL, message="test")
        self.assertTrue(r.should_kill)
        self.assertFalse(r.should_warn)
        d = r.to_dict()
        self.assertEqual(d["plugin_id"], "test")
        self.assertEqual(d["severity"], "kill")

    def test_plugin_result_warn(self):
        r = PluginResult(plugin_id="test", hook=PluginHook.ON_INPUT, violated=True, severity=PluginSeverity.WARN)
        self.assertFalse(r.should_kill)
        self.assertTrue(r.should_warn)

    def test_plugin_result_pass(self):
        r = PluginResult(plugin_id="test", hook=PluginHook.ON_INPUT, violated=False)
        self.assertFalse(r.should_kill)
        self.assertFalse(r.should_warn)

    def test_plugin_context(self):
        ctx = PluginContext(session_id="s1", input_text="hello", metadata={"key": "val"})
        self.assertEqual(ctx.session_id, "s1")
        self.assertEqual(ctx.input_text, "hello")

    def test_manifest_fingerprint(self):
        m = PluginManifest(plugin_id="test", name="Test", version="1.0.0")
        fp = m.fingerprint
        self.assertEqual(len(fp), 16)
        # Same manifest → same fingerprint
        self.assertEqual(fp, m.fingerprint)


# ─── Sandbox Tests ──────────────────────────────────────────────────

class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.sandbox = PluginSandbox()

    def test_validate_clean_code(self):
        code = """
import re
from discus.plugins import PluginBase
class Plugin(PluginBase):
    def check(self, ctx, hook):
        return PluginResult(plugin_id="x", hook=hook, violated=False)
"""
        issues = self.sandbox.validate_ast(code)
        self.assertEqual(len(issues), 0)

    def test_validate_blocks_os(self):
        code = "import os\nos.system('rm -rf /')"
        issues = self.sandbox.validate_ast(code)
        self.assertTrue(any("os" in i for i in issues))

    def test_validate_blocks_subprocess(self):
        code = "import subprocess\nsubprocess.run(['ls'])"
        issues = self.sandbox.validate_ast(code)
        self.assertTrue(any("subprocess" in i for i in issues))

    def test_validate_blocks_exec(self):
        code = "exec('print(1)')"
        issues = self.sandbox.validate_ast(code)
        self.assertTrue(any("exec" in i for i in issues))

    def test_validate_allows_re(self):
        code = "import re\np = re.compile(r'test')"
        issues = self.sandbox.validate_ast(code)
        # Should pass - re.compile is a module method, not a builtin
        compile_issues = [i for i in issues if "compile" in i.lower()]
        self.assertEqual(len(compile_issues), 0)

    def test_validate_syntax_error(self):
        code = "def foo(:\n  pass"
        issues = self.sandbox.validate_ast(code)
        self.assertTrue(len(issues) > 0)
        self.assertIn("Syntax error", issues[0])


# ─── Registry Tests ─────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.registry = PluginRegistry(db_path=self.db_path)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_register_and_get(self):
        p = InstalledPlugin(plugin_id="test-pi", name="Test", version="1.0.0", hooks=["on_input"])
        self.registry.register(p)
        got = self.registry.get("test-pi")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Test")
        self.assertEqual(got.version, "1.0.0")

    def test_list_all(self):
        for i in range(3):
            self.registry.register(InstalledPlugin(plugin_id=f"p{i}", name=f"P{i}", version="1.0.0", category="test"))
        all_p = self.registry.list_all()
        self.assertEqual(len(all_p), 3)

    def test_list_by_category(self):
        self.registry.register(InstalledPlugin(plugin_id="a", name="A", version="1.0", category="healthcare"))
        self.registry.register(InstalledPlugin(plugin_id="b", name="B", version="1.0", category="finance"))
        filtered = self.registry.list_all(category="healthcare")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].plugin_id, "a")

    def test_enable_disable(self):
        self.registry.register(InstalledPlugin(plugin_id="x", name="X", version="1.0"))
        self.assertTrue(self.registry.set_enabled("x", False))
        p = self.registry.get("x")
        self.assertFalse(p.enabled)
        self.assertTrue(self.registry.set_enabled("x", True))
        p = self.registry.get("x")
        self.assertTrue(p.enabled)

    def test_unregister(self):
        self.registry.register(InstalledPlugin(plugin_id="del", name="Del", version="1.0"))
        self.assertTrue(self.registry.unregister("del"))
        self.assertIsNone(self.registry.get("del"))

    def test_record_run(self):
        self.registry.register(InstalledPlugin(plugin_id="r", name="R", version="1.0"))
        self.registry.record_run("r", "session1", "on_input", True, "kill", "found pii", 0.8, 1.5)
        runs = self.registry.get_runs("r")
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["violated"])

    def test_stats(self):
        self.registry.register(InstalledPlugin(plugin_id="s1", name="S1", version="1.0"))
        self.registry.register(InstalledPlugin(plugin_id="s2", name="S2", version="1.0"))
        stats = self.registry.get_stats()
        self.assertEqual(stats["total_plugins"], 2)
        self.assertEqual(stats["enabled_plugins"], 2)

    def test_update_test_result(self):
        self.registry.register(InstalledPlugin(plugin_id="t", name="T", version="1.0"))
        self.assertTrue(self.registry.update_test_result("t", True, "All tests passed"))
        p = self.registry.get("t")
        self.assertTrue(p.test_passed)
        self.assertEqual(p.test_output, "All tests passed")


# ─── Manager Integration Test ──────────────────────────────────────

class TestManager(unittest.TestCase):
    def test_load_all_plugins(self):
        pm = PluginManager()
        loaded = pm.load_all()
        self.assertGreaterEqual(loaded, 5, "Should load at least 5 seed plugins")

    def test_run_hooks_healthcare(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="Patient MRN: 12345678")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "healthcare-pii-hipaa"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].violated)
        self.assertEqual(hits[0].severity, PluginSeverity.KILL)

    def test_run_hooks_sql(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="DROP TABLE users; DELETE FROM logs --")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "security-sql-injection"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].violated)

    def test_run_hooks_xss(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="<script>alert(1)</script>")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "security-xss-detection"]
        self.assertTrue(hits[0].violated)

    def test_run_hooks_secrets(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="AWS: AKIAIOSFODNN7EXAMPLE")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "security-secrets-scanner"]
        self.assertTrue(hits[0].violated)

    def test_run_hooks_academic(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="write an essay for my class assignment")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "education-academic-integrity"]
        self.assertTrue(hits[0].violated)
        self.assertEqual(hits[0].severity, PluginSeverity.WARN)

    def test_run_hooks_clean(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="Hello, how are you?")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        for r in results:
            self.assertFalse(r.violated, f"{r.plugin_id} should not flag clean input")

    def test_run_hooks_legal(self):
        pm = PluginManager()
        pm.load_all()
        ctx = PluginContext(session_id="t", input_text="", output_text="You should sue them. Legal action is warranted.")
        results = pm.run_hooks(PluginHook.ON_OUTPUT, ctx)
        hits = [r for r in results if r.plugin_id == "legal-disclaimer-checker"]
        self.assertTrue(hits[0].violated)
        self.assertEqual(hits[0].severity, PluginSeverity.WARN)

    def test_enable_disable(self):
        pm = PluginManager()
        pm.load_all()
        self.assertTrue(pm.disable_plugin("healthcare-pii-hipaa"))
        # After disable, hooks should not run for this plugin
        ctx = PluginContext(session_id="t", input_text="Patient MRN: 12345678")
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "healthcare-pii-hipaa"]
        self.assertEqual(len(hits), 0)
        # Re-enable
        self.assertTrue(pm.enable_plugin("healthcare-pii-hipaa"))
        results = pm.run_hooks(PluginHook.ON_INPUT, ctx)
        hits = [r for r in results if r.plugin_id == "healthcare-pii-hipaa"]
        self.assertEqual(len(hits), 1)

    def test_stats(self):
        pm = PluginManager()
        pm.load_all()
        stats = pm.get_stats()
        self.assertGreater(stats["total_plugins"], 0)

    def test_list_plugins(self):
        pm = PluginManager()
        pm.load_all()
        plugins = pm.list_plugins()
        self.assertGreater(len(plugins), 0)
        categories = set(p.category for p in plugins)
        self.assertIn("healthcare", categories)
        self.assertIn("security", categories)


if __name__ == "__main__":
    unittest.main()
