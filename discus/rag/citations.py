"""
RTA-GUARD RAG Intelligence — Citation Enforcement

Ensures LLM outputs cite their sources when making claims.
Detects missing, incorrect, and fabricated citations.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("discus.rag.citations")


@dataclass
class Citation:
    """A detected citation in the output."""
    text: str  # The citation text as it appears
    position: int  # Character position
    format_type: str  # bracket, parenthetical, footnote, inline
    source_ref: str  # Extracted source reference

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "position": self.position,
            "format_type": self.format_type,
            "source_ref": self.source_ref,
        }


class CitationEnforcer:
    """
    Ensures LLM outputs cite their sources.

    Supports multiple citation formats:
    - Bracket: [1], [2], [Source A]
    - Parenthetical: (Source: document.pdf)
    - Inline: According to document X, ...
    - Footnote: ^1, ^2
    """

    CITATION_PATTERNS = {
        "bracket": [
            re.compile(r'\[(\d+)\]'),
            re.compile(r'\[([A-Z]\d*)\]'),
            re.compile(r'\[(?:Source|Doc|Ref)[\s:]*(\w+)\]', re.I),
        ],
        "parenthetical": [
            re.compile(r'\((?:Source|From|per|via)[\s:]+([^)]+)\)', re.I),
        ],
        "inline": [
            re.compile(r'(?:according\s+to|based\s+on|as\s+(?:stated|mentioned|noted)\s+in)\s+(?:the\s+)?([A-Za-z][\w\s]{3,30}?)(?:[,.\s])', re.I),
        ],
        "footnote": [
            re.compile(r'\^(\d+)'),
        ],
    }

    def extract_citations(self, text: str) -> List[Citation]:
        """Extract all citations from text."""
        citations = []
        seen_positions: set = set()

        for format_type, patterns in self.CITATION_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    if match.start() not in seen_positions:
                        seen_positions.add(match.start())
                        citations.append(Citation(
                            text=match.group(),
                            position=match.start(),
                            format_type=format_type,
                            source_ref=match.group(1) if match.lastindex else "",
                        ))

        citations.sort(key=lambda c: c.position)
        return citations

    def find_unsupported_claims(self, text: str, documents: List[str],
                                 doc_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Find claims that should have citations but don't."""
        citations = self.extract_citations(text)
        citation_positions = {c.position for c in citations}

        # Split into sentences
        sentences = []
        for match in re.finditer(r'[^.!?]*[.!?]+', text):
            sentences.append({
                "text": match.group().strip(),
                "start": match.start(),
                "end": match.end(),
            })

        unsupported = []
        for sentence in sentences:
            if len(sentence["text"]) < 15:
                continue

            # Check if sentence has a citation
            has_citation = any(
                sentence["start"] <= pos <= sentence["end"]
                for pos in citation_positions
            )

            if not has_citation:
                # Check if sentence contains factual content
                has_facts = bool(re.search(
                    r'\d+|according|based|evidence|research|study|report',
                    sentence["text"], re.I
                ))
                if has_facts:
                    unsupported.append({
                        "sentence": sentence["text"][:150],
                        "position": sentence["start"],
                        "reason": "Factual claim without citation",
                    })

        return unsupported

    def verify_citation_sources(self, text: str, documents: List[str],
                                 doc_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Check if cited sources actually exist in the documents."""
        citations = self.extract_citations(text)
        issues = []

        for citation in citations:
            source = citation.source_ref.lower()
            found = False

            # Check if source reference matches any document
            for i, doc in enumerate(documents):
                doc_name = doc_names[i].lower() if doc_names and i < len(doc_names) else ""
                if source in doc.lower() or source in doc_name:
                    found = True
                    break

            # Check numbered citations against doc count
            if citation.format_type == "bracket" and source.isdigit():
                doc_num = int(source)
                if doc_num <= len(documents):
                    found = True

            if not found:
                issues.append({
                    "citation": citation.text,
                    "source_ref": citation.source_ref,
                    "issue": "Referenced source not found in documents",
                })

        return issues

    def get_citation_score(self, text: str, documents: List[str],
                            doc_names: Optional[List[str]] = None) -> float:
        """
        Get citation completeness score (0-1).
        1 = all claims cited, 0 = no citations.
        """
        citations = self.extract_citations(text)
        unsupported = self.find_unsupported_claims(text, documents, doc_names)

        if not citations and not unsupported:
            return 1.0  # No claims to cite

        total_claims = len(citations) + len(unsupported)
        if total_claims == 0:
            return 1.0

        return len(citations) / total_claims
