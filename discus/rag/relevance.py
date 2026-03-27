"""
RTA-GUARD RAG Intelligence — Relevance Scoring

Scores how relevant retrieved documents are to the query.
Detects irrelevant retrievals that may confuse the LLM.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("discus.rag.relevance")


@dataclass
class DocRelevance:
    """Relevance score for a single document."""
    doc_index: int
    doc_name: str
    relevance_score: float
    keyword_overlap: float
    is_relevant: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_index": self.doc_index,
            "doc_name": self.doc_name,
            "relevance_score": round(self.relevance_score, 3),
            "keyword_overlap": round(self.keyword_overlap, 3),
            "is_relevant": self.is_relevant,
        }


class RelevanceScorer:
    """
    Scores document relevance to a query.

    Uses keyword overlap, question-answer matching,
    and topic detection to determine if retrieved
    documents are actually useful for answering the query.
    """

    # Common stop words to ignore
    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
        "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself",
        "she", "her", "hers", "herself", "it", "its", "itself", "they", "them",
        "their", "theirs", "themselves",
    }

    def extract_keywords(self, text: str) -> Set[str]:
        """Extract meaningful keywords from text."""
        words = set(re.findall(r'\b[a-zA-Z]{3,}\b', text.lower()))
        return words - self.STOP_WORDS

    def compute_keyword_overlap(self, query: str, document: str) -> float:
        """Compute keyword overlap between query and document."""
        query_keywords = self.extract_keywords(query)
        doc_keywords = self.extract_keywords(document)

        if not query_keywords:
            return 0.5  # No keywords = neutral

        overlap = query_keywords & doc_keywords
        return len(overlap) / len(query_keywords)

    def score_document(self, query: str, document: str,
                       doc_index: int = 0, doc_name: str = "",
                       threshold: float = 0.2) -> DocRelevance:
        """Score relevance of a single document to a query."""
        keyword_overlap = self.compute_keyword_overlap(query, document)

        # Boost score if document contains query terms directly
        query_lower = query.lower()
        doc_lower = document.lower()

        direct_match_bonus = 0.0
        query_phrases = re.findall(r'\b\w+\s+\w+\b', query_lower)
        for phrase in query_phrases:
            if phrase in doc_lower:
                direct_match_bonus += 0.15

        relevance_score = min(1.0, keyword_overlap + direct_match_bonus)
        is_relevant = relevance_score >= threshold

        return DocRelevance(
            doc_index=doc_index,
            doc_name=doc_name or f"doc_{doc_index}",
            relevance_score=relevance_score,
            keyword_overlap=keyword_overlap,
            is_relevant=is_relevant,
        )

    def score_documents(self, query: str, documents: List[str],
                        doc_names: Optional[List[str]] = None,
                        threshold: float = 0.2) -> List[DocRelevance]:
        """Score all documents for relevance to query."""
        results = []
        for i, doc in enumerate(documents):
            name = doc_names[i] if doc_names and i < len(doc_names) else ""
            results.append(self.score_document(query, doc, i, name, threshold))
        return results

    def get_context_quality(self, query: str, documents: List[str],
                             doc_names: Optional[List[str]] = None) -> float:
        """
        Get overall context quality score (0-1).
        How useful are the retrieved documents for answering the query?
        """
        if not documents:
            return 0.0

        scores = self.score_documents(query, documents, doc_names)
        if not scores:
            return 0.0

        # Weight by relevance — irrelevant docs bring down the score
        return sum(s.relevance_score for s in scores) / len(scores)

    def get_irrelevant_documents(self, query: str, documents: List[str],
                                  doc_names: Optional[List[str]] = None,
                                  threshold: float = 0.2) -> List[DocRelevance]:
        """Get documents that are irrelevant to the query."""
        scores = self.score_documents(query, documents, doc_names, threshold)
        return [s for s in scores if not s.is_relevant]
