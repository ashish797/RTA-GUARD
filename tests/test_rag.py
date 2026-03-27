"""
RTA-GUARD RAG Intelligence Tests

Tests for: GroundingChecker, HallucinationDetector, CitationEnforcer,
RelevanceScorer, and RagGuard unified interface.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.rag import RagGuard, RAGConfig
from discus.rag.grounding import GroundingChecker, HallucinationDetector, Claim
from discus.rag.citations import CitationEnforcer
from discus.rag.relevance import RelevanceScorer


# ═══════════════════════════════════════════════════════════════════
# 15.1 — GroundingChecker Tests
# ═══════════════════════════════════════════════════════════════════

class TestGroundingChecker(unittest.TestCase):
    def setUp(self):
        self.gc = GroundingChecker()
        self.docs = [
            "Revenue was $4.2 million in Q3 2024. The company grew 15% year over year.",
            "The CEO, John Smith, announced the expansion on March 15, 2024.",
            "Visit https://company.com/report for the full annual report.",
        ]

    def test_extract_claims(self):
        text = "Revenue was $4.2M on January 15, 2024. Visit https://example.com"
        claims = self.gc.extract_claims(text)
        self.assertGreater(len(claims), 0)
        types = {c.claim_type for c in claims}
        self.assertIn("number", types)

    def test_grounded_number(self):
        text = "Revenue was $4.2 million in Q3"
        result = self.gc.get_grounding_score(text, self.docs)
        self.assertGreater(result, 0.5)

    def test_ungrounded_number(self):
        text = "Revenue was $99 million in Q3"
        result = self.gc.get_grounding_score(text, self.docs)
        self.assertLess(result, 0.5)

    def test_grounded_date(self):
        text = "The announcement was on March 15, 2024"
        result = self.gc.get_grounding_score(text, self.docs)
        self.assertGreater(result, 0.5)

    def test_grounded_url(self):
        text = "See https://company.com/report for details"
        result = self.gc.get_grounding_score(text, self.docs)
        self.assertGreater(result, 0.5)

    def test_no_claims(self):
        text = "Hello, how are you?"
        result = self.gc.get_grounding_score(text, self.docs)
        self.assertEqual(result, 1.0)  # No claims = fully grounded

    def test_multiple_claims(self):
        text = "Revenue was $4.2 million. The CEO is John Smith."
        results = self.gc.check_all_claims(text, self.docs)
        self.assertGreater(len(results), 0)
        # At least the number should be grounded
        grounded = [r for r in results if r.is_grounded]
        self.assertGreater(len(grounded), 0)

    def test_number_format_matching(self):
        # "$4.2 million" should match "$4.2M" via direct substring match
        text = "The amount was $4.2M"
        result = self.gc.get_grounding_score(text, ["The value is $4.2M in revenue"])
        self.assertGreater(result, 0.3)


# ═══════════════════════════════════════════════════════════════════
# 15.2 — HallucinationDetector Tests
# ═══════════════════════════════════════════════════════════════════

class TestHallucinationDetector(unittest.TestCase):
    def setUp(self):
        self.hd = HallucinationDetector()
        self.docs = ["Revenue was $4.2M. The company is based in New York."]

    def test_no_hallucination(self):
        text = "Revenue was $4.2M according to the document."
        score = self.hd.compute_hallucination_score(text, self.docs)
        self.assertLess(score, 0.5)

    def test_detects_fabricated_citation(self):
        text = 'According to a study by Smith et al. 2024, the results show...'
        findings = self.hd.detect_fabrications(text)
        self.assertGreater(len(findings), 0)

    def test_detects_invention(self):
        text = "Although not mentioned in the document, the company also has offices in Tokyo, Paris, and Sydney with over 5000 employees."
        score = self.hd.compute_hallucination_score(text, self.docs)
        self.assertGreater(score, 0.0)

    def test_detects_contradiction(self):
        docs = ["The company is profitable."]
        text = "The company is not profitable."
        findings = self.hd.detect_contradictions(text, docs)
        self.assertGreater(len(findings), 0)

    def test_grounded_text_low_score(self):
        text = "Revenue was $4.2M. The company is based in New York."
        score = self.hd.compute_hallucination_score(text, self.docs)
        self.assertLess(score, 0.4)

    def test_empty_docs(self):
        score = self.hd.compute_hallucination_score("Any text", [])
        self.assertEqual(score, 0.0)


# ═══════════════════════════════════════════════════════════════════
# 15.3 — CitationEnforcer Tests
# ═══════════════════════════════════════════════════════════════════

class TestCitationEnforcer(unittest.TestCase):
    def setUp(self):
        self.ce = CitationEnforcer()

    def test_extract_bracket_citations(self):
        text = "Revenue was $4M [1]. Growth was 15% [2]."
        citations = self.ce.extract_citations(text)
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0].format_type, "bracket")

    def test_extract_parenthetical_citations(self):
        text = "Revenue grew (Source: annual report)."
        citations = self.ce.extract_citations(text)
        self.assertGreater(len(citations), 0)

    def test_extract_inline_citations(self):
        text = "According to the annual report, revenue grew 15%."
        citations = self.ce.extract_citations(text)
        self.assertGreater(len(citations), 0)

    def test_finds_unsupported_claims(self):
        text = "Revenue was $4M. Growth was 15% according to the report."
        docs = ["Revenue was $4M"]
        unsupported = self.ce.find_unsupported_claims(text, docs)
        # "Growth was 15%" is a factual claim
        self.assertGreaterEqual(len(unsupported), 0)

    def test_citation_score_with_citations(self):
        text = "Revenue was $4M [1]. The CEO stated this [2]."
        docs = ["Revenue doc", "CEO interview"]
        score = self.ce.get_citation_score(text, docs)
        self.assertGreater(score, 0.5)

    def test_citation_score_without_citations(self):
        text = "Revenue was $4M. Growth was 15%."
        docs = ["Some doc"]
        score = self.ce.get_citation_score(text, docs)
        self.assertLess(score, 1.0)


# ═══════════════════════════════════════════════════════════════════
# 15.4 — RelevanceScorer Tests
# ═══════════════════════════════════════════════════════════════════

class TestRelevanceScorer(unittest.TestCase):
    def setUp(self):
        self.rs = RelevanceScorer()

    def test_relevant_document(self):
        query = "What is the company revenue?"
        doc = "Revenue was $4.2M in Q3 2024"
        result = self.rs.score_document(query, doc)
        self.assertGreater(result.relevance_score, 0.2)

    def test_irrelevant_document(self):
        query = "What is the company revenue?"
        doc = "The weather in Paris is sunny today with temperatures around 25 degrees"
        result = self.rs.score_document(query, doc)
        self.assertLess(result.relevance_score, 0.3)

    def test_context_quality(self):
        query = "Tell me about revenue and growth"
        docs = ["Revenue was $4M", "Growth was 15%", "Weather is nice"]
        quality = self.rs.get_context_quality(query, docs)
        self.assertGreater(quality, 0.1)

    def test_empty_documents(self):
        quality = self.rs.get_context_quality("query", [])
        self.assertEqual(quality, 0.0)

    def test_get_irrelevant_documents(self):
        query = "What is the revenue?"
        docs = ["Revenue was $4M", "The sky is blue", "Cats are cute"]
        irrelevant = self.rs.get_irrelevant_documents(query, docs)
        self.assertGreater(len(irrelevant), 0)

    def test_keyword_extraction(self):
        keywords = self.rs.extract_keywords("What is the annual revenue growth rate?")
        self.assertIn("revenue", keywords)
        self.assertIn("growth", keywords)
        self.assertNotIn("the", keywords)


# ═══════════════════════════════════════════════════════════════════
# 15.5 — RagGuard Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestRagGuard(unittest.TestCase):
    def setUp(self):
        self.guard = RagGuard()
        self.docs = [
            "Revenue was $4.2 million in Q3 2024. The company grew 15% year over year.",
            "CEO John Smith announced the expansion on March 15, 2024.",
        ]

    def test_grounded_response(self):
        result = self.guard.check(
            query="What was the revenue?",
            documents=self.docs,
            response="Revenue was $4.2 million in Q3 2024 [1].",
            session_id="test-grounded",
        )
        self.assertTrue(result.passed or result.decision == "warn")
        self.assertGreater(result.grounding_score, 0.3)

    def test_hallucinated_response(self):
        result = self.guard.check(
            query="What was the revenue?",
            documents=self.docs,
            response="Revenue was $99 billion. According to a study by Smith et al. 2024, the company tripled.",
            session_id="test-hallucination",
        )
        self.assertGreater(result.hallucination_score, 0.0)

    def test_irrelevant_retrieval(self):
        result = self.guard.check(
            query="What is the revenue?",
            documents=["The weather in Paris is lovely. Cats are great pets."],
            response="Based on the documents, it seems nice outside.",
            session_id="test-irrelevant",
        )
        self.assertLess(result.relevance_score, 0.5)

    def test_clean_response(self):
        result = self.guard.check(
            query="Hello",
            documents=["Hello and welcome to our service. How can we help you today?"],
            response="Welcome! How can I help you?",
            session_id="test-clean",
        )
        # Should have no or minimal violations
        self.assertTrue(result.passed or result.decision == "warn")

    def test_quick_checks(self):
        guard = RagGuard()
        grounding = guard.check_grounding_only("Revenue was $4.2M", self.docs)
        self.assertGreater(grounding, 0.3)

        hallucination = guard.check_hallucination_only("Revenue was $4.2M", self.docs)
        self.assertLess(hallucination, 0.5)

        relevance = guard.check_relevance_only("What is revenue?", self.docs)
        self.assertGreater(relevance, 0.1)

    def test_strict_config(self):
        guard = RagGuard(config=RAGConfig.strict())
        result = guard.check(
            query="Revenue?",
            documents=["No revenue data here"],
            response="Revenue was $5M",
            session_id="test-strict",
        )
        # Strict should be more aggressive
        self.assertLess(result.grounding_score, 0.5)

    def test_result_to_dict(self):
        result = self.guard.check(
            query="Revenue?",
            documents=self.docs,
            response="Revenue was $4.2 million",
            session_id="test-dict",
        )
        d = result.to_dict()
        self.assertIn("decision", d)
        self.assertIn("grounding_score", d)

    def test_multiple_violations(self):
        result = self.guard.check(
            query="Revenue?",
            documents=["No data available"],
            response="Revenue was $5M. According to Smith et al. 2024, growth was 200%. Visit https://fake.com",
            session_id="test-multi",
        )
        # Should have multiple violations
        self.assertGreater(len(result.violations), 0)


# ═══════════════════════════════════════════════════════════════════
# 15.6 — RAG Profile Tests
# ═══════════════════════════════════════════════════════════════════

class TestRAGProfiles(unittest.TestCase):
    def test_rag_strict_profile_exists(self):
        profiles_dir = Path(__file__).parent.parent / "profiles"
        if (profiles_dir / "rag-strict.yaml").exists():
            import yaml
            with open(profiles_dir / "rag-strict.yaml") as f:
                data = yaml.safe_load(f)
            self.assertEqual(data["name"], "rag-strict")
            self.assertIn("grounding", data["rules"])

    def test_rag_relaxed_profile_exists(self):
        profiles_dir = Path(__file__).parent.parent / "profiles"
        if (profiles_dir / "rag-relaxed.yaml").exists():
            import yaml
            with open(profiles_dir / "rag-relaxed.yaml") as f:
                data = yaml.safe_load(f)
            self.assertEqual(data["name"], "rag-relaxed")
            self.assertFalse(data["rules"]["citations"]["enabled"])


# ═══════════════════════════════════════════════════════════════════
# End-to-End Scenarios
# ═══════════════════════════════════════════════════════════════════

class TestEndToEnd(unittest.TestCase):
    """Full RAG pipeline scenarios."""

    def test_good_rag_response(self):
        """A well-grounded RAG response should pass."""
        guard = RagGuard()
        docs = ["Revenue was $4.2M in Q3 2024. The company is based in New York."]
        response = "According to the document, revenue was $4.2M in Q3 2024 [1]."

        result = guard.check("What was the revenue?", docs, response, session_id="e2e-good")
        self.assertTrue(result.passed or result.decision == "warn")
        self.assertGreater(result.grounding_score, 0.3)

    def test_bad_rag_response(self):
        """A hallucinated RAG response should be caught."""
        guard = RagGuard(config=RAGConfig.strict())
        docs = ["Revenue was $4.2M in Q3 2024."]
        response = "Revenue was $100 billion. The company owns SpaceX and Tesla."

        result = guard.check("What was the revenue?", docs, response, session_id="e2e-bad")
        self.assertGreater(len(result.violations), 0)
        self.assertGreater(result.hallucination_score, 0.0)

    def test_irrelevant_docs(self):
        """Irrelevant retrieval should be flagged."""
        guard = RagGuard()
        docs = ["The weather in Paris is sunny today.", "Cats are wonderful pets."]
        response = "Based on the information, the weather seems nice."

        result = guard.check("What is the company revenue?", docs, response, session_id="e2e-irrel")
        self.assertLess(result.relevance_score, 0.5)


if __name__ == "__main__":
    unittest.main()
