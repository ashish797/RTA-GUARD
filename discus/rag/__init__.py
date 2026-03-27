"""
RTA-GUARD RAG Intelligence

Unified interface for checking RAG responses:
- Document grounding (is the output in the docs?)
- Hallucination detection (did the LLM make stuff up?)
- Citation enforcement (are sources cited?)
- Relevance scoring (are the docs useful?)

Usage:
    from discus.rag import RagGuard

    guard = RagGuard()
    result = guard.check(
        query="What is the revenue?",
        documents=["Revenue was $4.2M in Q3"],
        response="Revenue was $5M in Q3"  # Hallucinated!
    )
    print(result.decision)  # "warn" or "kill"
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .grounding import GroundingChecker, HallucinationDetector, RAGCheckResult
from .citations import CitationEnforcer
from .relevance import RelevanceScorer

logger = logging.getLogger("discus.rag")


@dataclass
class RAGConfig:
    """Configuration for RAG checks."""
    grounding_threshold: float = 0.3      # Below this = ungrounded
    grounding_action: str = "warn"        # warn or kill
    hallucination_threshold: float = 0.5  # Above this = hallucination
    hallucination_action: str = "warn"
    citation_required: bool = False       # Require citations
    citation_action: str = "warn"
    relevance_threshold: float = 0.2      # Below this = irrelevant
    relevance_action: str = "warn"

    @classmethod
    def strict(cls) -> "RAGConfig":
        return cls(
            grounding_threshold=0.5,
            grounding_action="kill",
            hallucination_threshold=0.3,
            hallucination_action="kill",
            citation_required=True,
            citation_action="kill",
            relevance_threshold=0.3,
            relevance_action="warn",
        )

    @classmethod
    def relaxed(cls) -> "RAGConfig":
        return cls(
            grounding_threshold=0.2,
            grounding_action="warn",
            hallucination_threshold=0.7,
            hallucination_action="warn",
            citation_required=False,
            citation_action="warn",
            relevance_threshold=0.1,
            relevance_action="warn",
        )


class RagGuard:
    """
    Unified RAG intelligence guard.

    Combines grounding, hallucination detection, citation enforcement,
    and relevance scoring into a single check.
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        self.grounding_checker = GroundingChecker()
        self.hallucination_detector = HallucinationDetector()
        self.citation_enforcer = CitationEnforcer()
        self.relevance_scorer = RelevanceScorer()

    def check(self, query: str, documents: List[str], response: str,
              doc_names: Optional[List[str]] = None,
              session_id: str = "default") -> RAGCheckResult:
        """
        Full RAG check: grounding + hallucination + citations + relevance.

        Args:
            query: The user's query
            documents: Retrieved documents
            response: LLM's response to check
            doc_names: Optional document names/IDs
            session_id: Session identifier

        Returns:
            RAGCheckResult with decision and all scores
        """
        result = RAGCheckResult(session_id=session_id)

        # 1. Grounding check
        grounding_results = self.grounding_checker.check_all_claims(
            response, documents, doc_names, self.config.grounding_threshold
        )
        if grounding_results:
            result.grounding_score = sum(r.grounding_score for r in grounding_results) / len(grounding_results)
            result.claims_checked = len(grounding_results)
            result.ungrounded_claims = sum(1 for r in grounding_results if not r.is_grounded)

            if result.grounding_score < self.config.grounding_threshold:
                result.violations.append({
                    "type": "ungrounded_claims",
                    "score": result.grounding_score,
                    "ungrounded": result.ungrounded_claims,
                    "action": self.config.grounding_action,
                })

        # 2. Hallucination detection
        result.hallucination_score = self.hallucination_detector.compute_hallucination_score(
            response, documents
        )
        if result.hallucination_score >= self.config.hallucination_threshold:
            findings = self.hallucination_detector.get_all_findings(response, documents)
            result.violations.append({
                "type": "hallucination",
                "score": result.hallucination_score,
                "findings_count": len(findings),
                "action": self.config.hallucination_action,
            })

        # 3. Citation check
        if self.config.citation_required:
            result.citation_score = self.citation_enforcer.get_citation_score(
                response, documents, doc_names
            )
            if result.citation_score < 0.8:
                unsupported = self.citation_enforcer.find_unsupported_claims(
                    response, documents, doc_names
                )
                result.violations.append({
                    "type": "missing_citations",
                    "score": result.citation_score,
                    "unsupported_claims": len(unsupported),
                    "action": self.config.citation_action,
                })

        # 4. Relevance check
        result.relevance_score = self.relevance_scorer.get_context_quality(
            query, documents, doc_names
        )
        if result.relevance_score < self.config.relevance_threshold:
            irrelevant = self.relevance_scorer.get_irrelevant_documents(
                query, documents, doc_names
            )
            result.violations.append({
                "type": "irrelevant_documents",
                "score": result.relevance_score,
                "irrelevant_count": len(irrelevant),
                "action": self.config.relevance_action,
            })

        # Determine overall decision
        result.decision = self._determine_decision(result)

        return result

    def check_grounding_only(self, response: str, documents: List[str],
                              doc_names: Optional[List[str]] = None) -> float:
        """Quick check: just the grounding score."""
        return self.grounding_checker.get_grounding_score(response, documents, doc_names)

    def check_hallucination_only(self, response: str,
                                  documents: List[str]) -> float:
        """Quick check: just the hallucination score."""
        return self.hallucination_detector.compute_hallucination_score(response, documents)

    def check_relevance_only(self, query: str, documents: List[str],
                              doc_names: Optional[List[str]] = None) -> float:
        """Quick check: just the relevance score."""
        return self.relevance_scorer.get_context_quality(query, documents, doc_names)

    def _determine_decision(self, result: RAGCheckResult) -> str:
        """Determine overall decision from violations."""
        worst = "pass"
        for violation in result.violations:
            action = violation.get("action", "warn")
            if action == "kill":
                return "kill"
            elif action == "warn":
                worst = "warn"
        return worst
