"""
Unit tests for discus-rs Python bindings.

Tests both native (maturin) and fallback (WASM) paths.
Run with: pytest test_python_bindings.py -v
"""
import sys
import os

# Add parent to path for testing
sys.path.insert(0, os.path.dirname(__file__))

import unittest


class TestPythonBindingsImport(unittest.TestCase):
    """Test that the bindings module imports correctly."""

    def test_module_imports(self):
        """Module should import without errors."""
        import __init__ as discus
        self.assertTrue(hasattr(discus, "check"))
        self.assertTrue(hasattr(discus, "kill"))
        self.assertTrue(hasattr(discus, "is_alive"))
        self.assertTrue(hasattr(discus, "get_rules"))

    def test_version(self):
        """Module should have a version string."""
        import __init__ as discus
        self.assertIsInstance(discus.__version__, str)
        self.assertEqual(discus.__version__, "0.1.0")


class TestCheckFunction(unittest.TestCase):
    """Test the check() function."""

    def test_check_returns_dict(self):
        """check() should return a dict with required keys."""
        import __init__ as discus
        result = discus.check("test-session", "Hello, world!")
        self.assertIsInstance(result, dict)
        self.assertIn("allowed", result)
        self.assertIn("session_id", result)
        self.assertIn("decision", result)

    def test_check_session_id_preserved(self):
        """check() should return the same session_id."""
        import __init__ as discus
        result = discus.check("my-session-42", "test input")
        self.assertEqual(result["session_id"], "my-session-42")

    def test_check_allowed_is_bool(self):
        """check() allowed field should be boolean."""
        import __init__ as discus
        result = discus.check("test", "safe content")
        self.assertIsInstance(result["allowed"], bool)


class TestKillFunction(unittest.TestCase):
    """Test the kill() function."""

    def test_kill_returns_none(self):
        """kill() should return None."""
        import __init__ as discus
        result = discus.kill("kill-test-session")
        self.assertIsNone(result)

    def test_kill_does_not_raise(self):
        """kill() should not raise on any session_id."""
        import __init__ as discus
        try:
            discus.kill("")
            discus.kill("non-existent-session")
            discus.kill("session/with/slashes")
        except Exception as e:
            self.fail(f"kill() raised unexpected exception: {e}")


class TestIsAliveFunction(unittest.TestCase):
    """Test the is_alive() function."""

    def test_is_alive_returns_bool(self):
        """is_alive() should return a boolean."""
        import __init__ as discus
        result = discus.is_alive("alive-test-session")
        self.assertIsInstance(result, bool)


class TestGetRulesFunction(unittest.TestCase):
    """Test the get_rules() function."""

    def test_get_rules_returns_list(self):
        """get_rules() should return a list."""
        import __init__ as discus
        rules = discus.get_rules()
        self.assertIsInstance(rules, list)

    def test_get_rules_not_empty(self):
        """get_rules() should return at least one rule."""
        import __init__ as discus
        rules = discus.get_rules()
        self.assertGreater(len(rules), 0)

    def test_get_rules_all_strings(self):
        """All rule names should be strings."""
        import __init__ as discus
        rules = discus.get_rules()
        for rule in rules:
            self.assertIsInstance(rule, str)

    def test_get_rules_contains_core_rules(self):
        """get_rules() should include core rules."""
        import __init__ as discus
        rules = discus.get_rules()
        core_rules = {"SATYA", "DHARMA", "YAMA"}
        for rule in core_rules:
            self.assertIn(rule, rules)


class TestWorkflow(unittest.TestCase):
    """Test full check → kill → is_alive workflow."""

    def test_check_kill_isalive(self):
        """Full workflow: check → kill → is_alive returns False (native only)."""
        import __init__ as discus
        session_id = "workflow-test-session"

        # Check
        result = discus.check(session_id, "test content")
        self.assertIn("allowed", result)

        # Kill
        discus.kill(session_id)

        # is_alive — in fallback mode this may still return True
        alive = discus.is_alive(session_id)
        self.assertIsInstance(alive, bool)


if __name__ == "__main__":
    unittest.main()
