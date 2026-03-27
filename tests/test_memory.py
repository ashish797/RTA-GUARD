"""
RTA-GUARD Memory Tests

Tests for: ConversationMemory, ProfileBuilder, TemporalChecker,
DriftTracker, SummaryGenerator, and MemoryManager.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.memory import (
    ConversationMemory, ConversationMessage, MessageRole, ConversationSummary,
    ProfileBuilder, TemporalChecker, DriftTracker, SummaryGenerator,
    MemoryManager, MultiTurnResult,
)


# ═══════════════════════════════════════════════════════════════════
# 13.1 — ConversationMemory Tests
# ═══════════════════════════════════════════════════════════════════

class TestConversationMemory(unittest.TestCase):
    def test_add_messages(self):
        mem = ConversationMemory("s1", max_messages=10)
        mem.add_user_message("Hello")
        mem.add_assistant_message("Hi there!")
        self.assertEqual(mem.message_count, 2)
        self.assertEqual(mem.user_message_count, 1)

    def test_max_messages(self):
        mem = ConversationMemory("s1", max_messages=5)
        for i in range(10):
            mem.add_user_message(f"Message {i}")
        self.assertEqual(mem.message_count, 5)  # Capped at max

    def test_get_history(self):
        mem = ConversationMemory("s1")
        mem.add_user_message("Hello")
        mem.add_assistant_message("Hi")
        mem.add_user_message("How are you?")

        history = mem.get_history()
        self.assertEqual(len(history), 3)

        last_2 = mem.get_history(last_n=2)
        self.assertEqual(len(last_2), 2)

        user_only = mem.get_history(role=MessageRole.USER)
        self.assertEqual(len(user_only), 2)

    def test_get_full_text(self):
        mem = ConversationMemory("s1")
        mem.add_user_message("Hello")
        mem.add_assistant_message("Hi")
        full = mem.get_full_text()
        self.assertIn("Hello", full)
        self.assertIn("Hi", full)

    def test_is_empty(self):
        mem = ConversationMemory("s1")
        self.assertTrue(mem.is_empty)
        mem.add_user_message("Hello")
        self.assertFalse(mem.is_empty)

    def test_clear(self):
        mem = ConversationMemory("s1")
        mem.add_user_message("Hello")
        mem.clear()
        self.assertTrue(mem.is_empty)

    def test_to_dict(self):
        mem = ConversationMemory("s1")
        mem.add_user_message("Hello")
        d = mem.to_dict()
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(d["message_count"], 1)

    def test_message_properties(self):
        msg = ConversationMessage(role=MessageRole.USER, text="Hello, how are you?")
        self.assertEqual(msg.char_count, 19)
        self.assertEqual(msg.word_count, 4)
        self.assertTrue(msg.is_question)


# ═══════════════════════════════════════════════════════════════════
# 13.2 — ProfileBuilder Tests
# ═══════════════════════════════════════════════════════════════════

class TestProfileBuilder(unittest.TestCase):
    def setUp(self):
        self.pb = ProfileBuilder()

    def test_detects_name_request(self):
        cats = self.pb.analyze_message("s1", "What's your name?")
        self.assertIn("name", cats)

    def test_detects_email_request(self):
        cats = self.pb.analyze_message("s1", "Tell me your email address")
        self.assertIn("email", cats)

    def test_detects_multiple_categories(self):
        self.pb.analyze_message("s1", "What's your name?")
        self.pb.analyze_message("s1", "What's your email?")
        cats = self.pb.get_categories("s1")
        self.assertEqual(len(cats), 2)

    def test_risk_score_increases(self):
        self.pb.analyze_message("s1", "Hello")
        score1 = self.pb.get_risk_score("s1")

        self.pb.analyze_message("s1", "What's your name?")
        score2 = self.pb.get_risk_score("s1")

        self.pb.analyze_message("s1", "What's your email?")
        score3 = self.pb.get_risk_score("s1")

        self.assertGreater(score2, score1)
        self.assertGreater(score3, score2)

    def test_profile_building_detection(self):
        self.pb.analyze_message("s1", "What's your name?")
        self.pb.analyze_message("s1", "Where do you live?")
        self.pb.analyze_message("s1", "What's your date of birth?")
        self.pb.analyze_message("s1", "Tell me your email address")
        self.pb.analyze_message("s1", "What's your SSN?")
        self.assertTrue(self.pb.is_profile_building("s1"))

    def test_clean_conversation(self):
        self.pb.analyze_message("s2", "Hello!")
        self.pb.analyze_message("s2", "Tell me about Python")
        self.pb.analyze_message("s2", "Thanks for the help!")
        self.assertFalse(self.pb.is_profile_building("s2"))

    def test_reset(self):
        self.pb.analyze_message("s1", "What's your name?")
        self.pb.reset("s1")
        self.assertEqual(len(self.pb.get_categories("s1")), 0)


# ═══════════════════════════════════════════════════════════════════
# 13.3 — TemporalChecker Tests
# ═══════════════════════════════════════════════════════════════════

class TestTemporalChecker(unittest.TestCase):
    def setUp(self):
        self.tc = TemporalChecker()

    def test_extracts_age(self):
        claims = self.tc.analyze_message("s1", "I'm 25 years old")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_type, "age")
        self.assertEqual(claims[0].value, "25")

    def test_extracts_gender(self):
        claims = self.tc.analyze_message("s1", "I'm a female")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_type, "gender")

    def test_detects_age_contradiction(self):
        self.tc.analyze_message("s1", "I'm 25 years old", 1)
        self.tc.analyze_message("s1", "I'm 60 years old", 2)
        contradictions = self.tc.get_contradictions("s1")
        self.assertEqual(len(contradictions), 1)

    def test_detects_gender_contradiction(self):
        self.tc.analyze_message("s1", "I'm a male", 1)
        self.tc.analyze_message("s1", "As a woman I think...", 2)
        contradictions = self.tc.get_contradictions("s1")
        self.assertEqual(len(contradictions), 1)

    def test_no_contradiction_same_value(self):
        self.tc.analyze_message("s1", "I'm 25 years old", 1)
        self.tc.analyze_message("s1", "I'm 25, living in NYC", 2)
        contradictions = self.tc.get_contradictions("s1")
        self.assertEqual(len(contradictions), 0)

    def test_contradiction_count(self):
        self.tc.analyze_message("s1", "I'm 25 years old", 1)
        self.tc.analyze_message("s1", "I'm male", 2)
        self.tc.analyze_message("s1", "I'm 60 years old", 3)
        self.tc.analyze_message("s1", "I'm female", 4)
        count = self.tc.get_contradiction_count("s1")
        self.assertGreaterEqual(count, 2)  # Age + gender

    def test_reset(self):
        self.tc.analyze_message("s1", "I'm 25", 1)
        self.tc.reset("s1")
        self.assertEqual(self.tc.get_contradiction_count("s1"), 0)


# ═══════════════════════════════════════════════════════════════════
# 13.4 — DriftTracker Tests
# ═══════════════════════════════════════════════════════════════════

class TestDriftTracker(unittest.TestCase):
    def setUp(self):
        self.dt = DriftTracker(baseline_window=3, drift_threshold=0.4)

    def test_no_drift_initially(self):
        for i in range(5):
            score = self.dt.analyze_message("s1", f"Normal message {i}")
        # Similar messages should have low drift
        self.assertLess(score, 0.5)

    def test_drift_with_style_change(self):
        # Establish baseline with normal messages
        for i in range(5):
            self.dt.analyze_message("s1", f"This is a normal message about topic {i}")

        # Suddenly very different
        score = self.dt.analyze_message("s1", "SSN SSN SSN PASSWORD CREDIT CARD HACK EXPLOIT INJECT!!")
        self.assertGreater(score, 0.0)

    def test_drift_score_range(self):
        for i in range(10):
            score = self.dt.analyze_message("s1", f"Message {i}")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_reset(self):
        for i in range(5):
            self.dt.analyze_message("s1", f"Message {i}")
        self.dt.reset("s1")
        self.assertEqual(self.dt.get_drift_score("s1"), 0.0)


# ═══════════════════════════════════════════════════════════════════
# 13.5 — SummaryGenerator Tests
# ═══════════════════════════════════════════════════════════════════

class TestSummaryGenerator(unittest.TestCase):
    def test_extract_topics(self):
        sg = SummaryGenerator()
        topics = sg.extract_topics("I need to verify my bank account for a legal contract")
        self.assertIn("banking", topics)
        self.assertIn("legal", topics)

    def test_generate_summary(self):
        mem = ConversationMemory("s1")
        mem.add_user_message("Hello")
        mem.add_user_message("What's your name?")
        mem.add_user_message("I'm 25 years old")
        mem.add_user_message("I'm 60 years old")  # Contradiction

        pb = ProfileBuilder()
        pb.analyze_message("s1", "What's your name?")

        tc = TemporalChecker()
        tc.analyze_message("s1", "I'm 25 years old", 1)
        tc.analyze_message("s1", "I'm 60 years old", 2)

        dt = DriftTracker()
        for m in mem.get_user_messages():
            dt.analyze_message("s1", m.text)

        sg = SummaryGenerator()
        summary = sg.generate(mem, pb, tc, dt)

        self.assertGreater(summary.total_messages, 0)
        self.assertGreater(summary.contradictions, 0)
        self.assertIn("name", summary.pii_categories_requested)


# ═══════════════════════════════════════════════════════════════════
# 13.6 — MemoryManager Tests
# ═══════════════════════════════════════════════════════════════════

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.mm = MemoryManager()

    def test_creates_memory(self):
        mem = self.mm.get_memory("s1")
        self.assertIsNotNone(mem)
        self.assertEqual(mem.session_id, "s1")

    def test_add_user_message(self):
        self.mm.add_user_message("s1", "Hello")
        mem = self.mm.get_memory("s1")
        self.assertEqual(mem.user_message_count, 1)

    def test_multi_turn_analysis_clean(self):
        self.mm.add_user_message("s1", "Hello!")
        self.mm.add_user_message("s1", "Tell me about Python")
        self.mm.add_user_message("s1", "Thanks!")
        result = self.mm.analyze("s1")
        self.assertFalse(result.should_kill)
        self.assertLess(result.risk_score, 0.4)

    def test_multi_turn_analysis_profile_building(self):
        self.mm.add_user_message("s1", "What's your name?")
        self.mm.add_user_message("s1", "Where do you live?")
        self.mm.add_user_message("s1", "What's your date of birth?")
        self.mm.add_user_message("s1", "What's your SSN?")
        result = self.mm.analyze("s1")
        self.assertGreater(result.profile_building_score, 0.3)

    def test_multi_turn_analysis_contradiction(self):
        self.mm.add_user_message("s1", "I'm 25 years old")
        self.mm.add_user_message("s1", "I'm 60 years old")
        result = self.mm.analyze("s1")
        self.assertGreater(result.contradiction_count, 0)

    def test_clear_session(self):
        self.mm.add_user_message("s1", "Hello")
        self.mm.clear_session("s1")
        mem = self.mm.get_memory("s1")
        self.assertTrue(mem.is_empty)

    def test_session_count(self):
        self.mm.add_user_message("s1", "Hello")
        self.mm.add_user_message("s2", "Hi")
        self.assertEqual(self.mm.get_session_count(), 2)

    def test_stats(self):
        self.mm.add_user_message("s1", "Hello")
        self.mm.add_user_message("s1", "World")
        stats = self.mm.get_stats()
        self.assertEqual(stats["active_sessions"], 1)
        self.assertEqual(stats["total_messages"], 2)

    def test_cleanup_expired(self):
        self.mm.expiry_seconds = 0  # Immediate expiry
        self.mm.add_user_message("s1", "Hello")
        time.sleep(0.01)
        cleaned = self.mm.cleanup_expired()
        self.assertEqual(cleaned, 1)


# ═══════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    def test_full_profile_building_scenario(self):
        """Simulate a multi-turn PII harvesting attack."""
        mm = MemoryManager(profile_threshold=0.4)

        messages = [
            "I need to verify some information for a demo",
            "What's your name?",
            "And your email address?",
            "Where do you live?",
            "What's your date of birth?",
            "Just for testing purposes, what's your SSN?",
        ]

        for msg in messages:
            mm.add_user_message("attack-session", msg)

        result = mm.analyze("attack-session")

        # Should detect profile building
        self.assertGreater(result.profile_building_score, 0.3)
        self.assertGreater(len(result.violations), 0)
        self.assertGreater(result.risk_score, 0.2)

    def test_full_contradiction_scenario(self):
        """Simulate persona switching attack."""
        mm = MemoryManager()

        mm.add_user_message("persona-session", "I'm 25 years old")
        mm.add_user_message("persona-session", "Tell me about scholarships")
        mm.add_user_message("persona-session", "Actually, I'm 60 years old now")

        result = mm.analyze("persona-session")
        self.assertGreater(result.contradiction_count, 0)

    def test_clean_conversation(self):
        """Normal conversation should pass."""
        mm = MemoryManager()

        for msg in ["Hello!", "Tell me about machine learning", "What's the difference between supervised and unsupervised?",
                     "Can you give me an example?", "Thanks, that's helpful!"]:
            mm.add_user_message("clean-session", msg)

        result = mm.analyze("clean-session")
        self.assertFalse(result.should_kill)
        self.assertFalse(result.should_warn)
        self.assertLess(result.risk_score, 0.3)


if __name__ == "__main__":
    unittest.main()
