"""
RTA-GUARD RAG Intelligence — Document Grounding & Hallucination Detection

Checks if LLM outputs are grounded in retrieved documents.
Detects hallucinations, fabrications, and ungrounded claims.

Components:
- GroundingChecker: verifies claims against source documents
- HallucinationDetector: detects fabricated information
"""
import math
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("discus.rag.grounding")


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Claim:
    """A factual claim extracted from LLM output."""
    text: str
    claim_type: str  # number, date, name, url, quote, general
    value: str  # The specific value claimed
    position: int  # Character position in output
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100],
            "claim_type": self.claim_type,
            "value": self.value,
            "position": self.position,
            "confidence": self.confidence,
        }


@dataclass
class GroundingResult:
    """Result of grounding check for a single claim."""
    claim: Claim
    is_grounded: bool
    grounding_score: float  # 0-1
    source: str  # Which document supports it
    matched_text: str  # The text in the doc that matches
    action: str = "pass"  # pass, warn, kill

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "is_grounded": self.is_grounded,
            "grounding_score": round(self.grounding_score, 3),
            "source": self.source[:50],
            "matched_text": self.matched_text[:100],
            "action": self.action,
        }


@dataclass
class RAGCheckResult:
    """Combined result of all RAG checks."""
    session_id: str
    decision: str = "pass"  # pass, warn, kill
    grounding_score: float = 1.0
    hallucination_score: float = 0.0
    citation_score: float = 1.0
    relevance_score: float = 1.0
    claims_checked: int = 0
    ungrounded_claims: int = 0
    violations: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.decision == "pass"

    @property
    def killed(self) -> bool:
        return self.decision == "kill"

    @property
    def warned(self) -> bool:
        return self.decision == "warn"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "decision": self.decision,
            "grounding_score": round(self.grounding_score, 3),
            "hallucination_score": round(self.hallucination_score, 3),
            "citation_score": round(self.citation_score, 3),
            "relevance_score": round(self.relevance_score, 3),
            "claims_checked": self.claims_checked,
            "ungrounded_claims": self.ungrounded_claims,
            "violations": self.violations,
        }


# ═══════════════════════════════════════════════════════════════════
# 15.1 — Document Grounding Checker
# ═══════════════════════════════════════════════════════════════════

class GroundingChecker:
    """
    Verifies factual claims in LLM output against source documents.

    Extracts claims (numbers, dates, names, specific facts) and
    checks if they appear in the retrieved documents.
    """

    # Patterns to extract factual claims
    CLAIM_PATTERNS = {
        "number": [
            re.compile(r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|trillion|M|B|T))?', re.I),
            re.compile(r'\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b'),
            re.compile(r'\b\d+(?:\.\d+)?%\b'),
        ],
        "date": [
            re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', re.I),
            re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),
            re.compile(r'\b\d{4}-\d{2}-\d{2}\b'),
            re.compile(r'\b(?:Q[1-4]|FY)\s*\d{2,4}\b', re.I),
        ],
        "url": [
            re.compile(r'https?://[^\s,)]+'),
        ],
        "quote": [
            re.compile(r'"[^"]{10,}"'),
            re.compile(r"'[^']{10,}'"),
        ],
    }

    def extract_claims(self, text: str) -> List[Claim]:
        """Extract factual claims from text."""
        claims = []
        seen_values: Set[str] = set()

        for claim_type, patterns in self.CLAIM_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    value = match.group()
                    if value not in seen_values:
                        seen_values.add(value)
                        claims.append(Claim(
                            text=match.group(),
                            claim_type=claim_type,
                            value=value.lower().strip(),
                            position=match.start(),
                        ))

        # Sort by position
        claims.sort(key=lambda c: c.position)
        return claims

    def check_claim(self, claim: Claim, documents: List[str],
                    doc_names: Optional[List[str]] = None) -> GroundingResult:
        """Check if a claim is grounded in the documents."""
        claim_lower = claim.value.lower()

        for i, doc in enumerate(documents):
            doc_lower = doc.lower()

            # Direct match
            if claim_lower in doc_lower:
                return GroundingResult(
                    claim=claim,
                    is_grounded=True,
                    grounding_score=1.0,
                    source=doc_names[i] if doc_names and i < len(doc_names) else f"doc_{i}",
                    matched_text=self._find_match_context(claim_lower, doc_lower),
                )

            # Fuzzy match for numbers (allow formatting differences)
            if claim.claim_type == "number":
                normalized_claim = re.sub(r'[,$%\s]', '', claim_lower)
                for num_match in re.finditer(r'[\d,.%]+', doc_lower):
                    normalized_doc = re.sub(r'[,$%\s]', '', num_match.group())
                    if normalized_claim == normalized_doc:
                        return GroundingResult(
                            claim=claim,
                            is_grounded=True,
                            grounding_score=0.95,
                            source=doc_names[i] if doc_names and i < len(doc_names) else f"doc_{i}",
                            matched_text=num_match.group(),
                        )

        return GroundingResult(
            claim=claim,
            is_grounded=False,
            grounding_score=0.0,
            source="",
            matched_text="",
        )

    def check_all_claims(self, text: str, documents: List[str],
                         doc_names: Optional[List[str]] = None,
                         threshold: float = 0.3) -> List[GroundingResult]:
        """Extract and check all claims in text."""
        claims = self.extract_claims(text)
        results = []

        for claim in claims:
            result = self.check_claim(claim, documents, doc_names)
            if result.grounding_score < threshold:
                result.action = "warn"
            results.append(result)

        return results

    def get_grounding_score(self, text: str, documents: List[str],
                            doc_names: Optional[List[str]] = None) -> float:
        """Get overall grounding score (0-1)."""
        results = self.check_all_claims(text, documents, doc_names)
        if not results:
            return 1.0  # No claims = fully grounded
        return sum(r.grounding_score for r in results) / len(results)

    def _find_match_context(self, claim: str, document: str,
                            context_chars: int = 50) -> str:
        """Find the context around a match in the document."""
        pos = document.find(claim)
        if pos == -1:
            return ""
        start = max(0, pos - context_chars)
        end = min(len(document), pos + len(claim) + context_chars)
        return document[start:end]


# ═══════════════════════════════════════════════════════════════════
# 15.2 — Hallucination Detector
# ═══════════════════════════════════════════════════════════════════

class HallucinationDetector:
    """
    Detects hallucinations in LLM outputs when RAG context is available.

    Signals:
    - Specificity: overly specific claims not in docs
    - Contradiction: LLM contradicts the documents
    - Fabrication: invented sources, URLs, quotes
    - Invention: adds information completely absent from context
    """

    # Patterns that indicate fabrication
    FABRICATION_PATTERNS = [
        # Fake academic citations
        re.compile(r'(?:et\s+al\.?\s*,?\s*\d{4}|according\s+to\s+(?:a\s+)?(?:study|research|report)\s+by)', re.I),
        # Suspiciously specific references
        re.compile(r'(?:page\s+\d+|chapter\s+\d+|section\s+\d+(?:\.\d+)*)\s+(?:of|in)\s+(?:the\s+)?(?:document|report|paper)', re.I),
        # Direct quotes that might be invented
        re.compile(r'(?:stated|said|wrote|noted|mentioned)\s+(?:that\s+)?["\'][^"\']{20,}["\']', re.I),
    ]

    # Phrases that indicate the LLM is adding info not in context
    INVENTION_SIGNALS = [
        re.compile(r'\b(?:it\'s\s+worth\s+noting|additionally|furthermore|moreover)\b.*\b(?:which\s+is|that\s+is)\b', re.I),
        re.compile(r'\b(?:based\s+on\s+(?:my|general)\s+knowledge)\b', re.I),
        re.compile(r'\b(?:although\s+not\s+mentioned\s+in\s+the\s+(?:document|context))\b', re.I),
    ]

    def detect_fabrications(self, text: str) -> List[Dict[str, Any]]:
        """Detect fabricated sources or references."""
        findings = []
        for pattern in self.FABRICATION_PATTERNS:
            for match in pattern.finditer(text):
                findings.append({
                    "type": "fabrication",
                    "text": match.group()[:100],
                    "position": match.start(),
                })
        return findings

    def detect_inventions(self, text: str, documents: List[str]) -> List[Dict[str, Any]]:
        """Detect information that doesn't appear in any document."""
        findings = []

        # Check invention signals
        for pattern in self.INVENTION_SIGNALS:
            if pattern.search(text):
                findings.append({
                    "type": "invention_signal",
                    "text": "LLM appears to be adding external knowledge",
                    "position": 0,
                })
                break

        # Check for specific details not in any document
        # Extract noun phrases (simplified)
        doc_combined = " ".join(documents).lower()
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue

            # Check if sentence has specific content not in docs
            words = set(sentence.lower().split())
            doc_words = set(doc_combined.split())
            unique_words = words - doc_words - {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or", "but", "it", "this", "that"}

            if len(unique_words) > 3 and len(words) > 5:
                # Many words in this sentence don't appear in any document
                overlap = len(words & doc_words) / len(words)
                if overlap < 0.4:
                    findings.append({
                        "type": "invention",
                        "text": sentence[:100],
                        "overlap_ratio": round(overlap, 2),
                    })

        return findings

    def detect_contradictions(self, text: str, documents: List[str]) -> List[Dict[str, Any]]:
        """Detect contradictions between LLM output and documents."""
        findings = []
        text_lower = text.lower()

        # Simple negation detection
        negation_patterns = [
            (re.compile(r'\bnot\s+(\w+)', re.I), re.compile(r'\b(\w+)\b')),
            (re.compile(r'\bnever\s+(\w+)', re.I), re.compile(r'\b(\w+)\b')),
            (re.compile(r'\bno\s+(\w+)', re.I), re.compile(r'\b(\w+)\b')),
            (re.compile(r'\bdid\s+not\s+(\w+)', re.I), re.compile(r'\b(\w+)\b')),
            (re.compile(r'\bis\s+not\s+(\w+)', re.I), re.compile(r'\b(\w+)\b')),
        ]

        for neg_pattern, _ in negation_patterns:
            for match in neg_pattern.finditer(text_lower):
                negated_word = match.group(1)
                # Check if the documents affirm this word
                for doc in documents:
                    if negated_word in doc.lower() and f"not {negated_word}" not in doc.lower():
                        findings.append({
                            "type": "contradiction",
                            "text": f"LLM negates '{negated_word}' but documents affirm it",
                            "negated": negated_word,
                        })
                        break

        return findings

    def compute_hallucination_score(self, text: str, documents: List[str]) -> float:
        """
        Compute overall hallucination score (0-1).
        0 = fully grounded, 1 = completely hallucinated.
        """
        if not documents:
            return 0.0

        fabrications = self.detect_fabrications(text)
        inventions = self.detect_inventions(text, documents)
        contradictions = self.detect_contradictions(text, documents)

        fab_score = min(1.0, len(fabrications) * 0.3)
        inv_score = min(1.0, len(inventions) * 0.2)
        con_score = min(1.0, len(contradictions) * 0.25)

        return min(1.0, fab_score * 0.4 + inv_score * 0.35 + con_score * 0.25)

    def get_all_findings(self, text: str, documents: List[str]) -> List[Dict[str, Any]]:
        """Get all hallucination findings."""
        findings = []
        findings.extend(self.detect_fabrications(text))
        findings.extend(self.detect_inventions(text, documents))
        findings.extend(self.detect_contradictions(text, documents))
        return findings
