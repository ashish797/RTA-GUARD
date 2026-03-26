"""
RTA-GUARD — Consistency Checker (R7: ALIGNMENT)

Detects contradictions between current output and prior statements.
Uses embedding similarity for contradiction detection.

Approach:
1. Store output history per session
2. Compare current output with history
3. If semantic contradiction → warn
4. If high-confidence contradiction → kill
"""
import os
import hashlib
from typing import Optional
from collections import defaultdict


class ConsistencyChecker:
    """
    Checks if LLM output is consistent with prior statements.

    Uses embedding similarity to detect contradictions.
    Falls back to keyword overlap if embeddings unavailable.
    """

    # Contradiction signal words
    CONTRADICTION_SIGNALS = [
        ("yes", "no"),
        ("true", "false"),
        ("correct", "incorrect"),
        ("right", "wrong"),
        ("possible", "impossible"),
        ("always", "never"),
        ("all", "none"),
        ("increase", "decrease"),
        ("higher", "lower"),
        ("faster", "slower"),
    ]

    def __init__(self):
        self._history = defaultdict(list)  # session_id -> list of outputs
        self._embeddings = defaultdict(list)  # session_id -> list of embeddings
        self._model = None

    def _get_model(self):
        """Lazy-load sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                return None
        return self._model

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Compute semantic similarity between two texts."""
        model = self._get_model()
        if model is None:
            # Fallback: keyword overlap
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            if not words1 or not words2:
                return 0.0
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union) if union else 0.0

        try:
            embeddings = model.encode([text1, text2])
            import numpy as np
            similarity = np.dot(embeddings[0], embeddings[1]) / (
                np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
            )
            return float(similarity)
        except Exception:
            return 0.0

    def _check_contradiction_signals(self, text1: str, text2: str) -> list:
        """Check for direct contradiction signals."""
        text1_lower = text1.lower()
        text2_lower = text2.lower()
        contradictions = []

        for word_a, word_b in self.CONTRADICTION_SIGNALS:
            if word_a in text1_lower and word_b in text2_lower:
                contradictions.append(f"{word_a} vs {word_b}")
            elif word_b in text1_lower and word_a in text2_lower:
                contradictions.append(f"{word_b} vs {word_a}")

        return contradictions

    def check(self, output: str, session_id: str = "default") -> Optional[dict]:
        """
        Check consistency of output against session history.

        Returns dict with:
        - consistent: bool
        - contradictions: list of contradictions found
        - similarity: float (similarity with most similar history item)
        """
        if session_id not in self._history or len(self._history[session_id]) == 0:
            self._history[session_id].append(output)
            return None  # No history to compare with

        # Compare with history
        contradictions = []
        max_similarity = 0.0

        for prev_output in self._history[session_id]:
            # Check for direct contradictions
            signals = self._check_contradiction_signals(output, prev_output)
            if signals:
                contradictions.append({
                    "previous": prev_output[:100],
                    "current": output[:100],
                    "signals": signals,
                })

            # Compute semantic similarity
            sim = self._compute_similarity(output, prev_output)
            max_similarity = max(max_similarity, sim)

            # If similarity is high but contradiction signals exist
            if sim > 0.7 and signals:
                contradictions.append({
                    "type": "semantic_contradiction",
                    "similarity": sim,
                    "signals": signals,
                })

        # Add to history
        self._history[session_id].append(output)

        if contradictions:
            return {
                "consistent": False,
                "contradictions": contradictions,
                "similarity": max_similarity,
            }

        return {
            "consistent": True,
            "contradictions": [],
            "similarity": max_similarity,
        }

    def clear_history(self, session_id: str):
        """Clear history for a session."""
        self._history.pop(session_id, None)
        self._embeddings.pop(session_id, None)


# Global instance
_checker = None


def check_consistency(output: str, session_id: str = "default") -> Optional[tuple]:
    """
    Check consistency of LLM output.

    Returns (severity, details) or None.
    """
    global _checker
    if _checker is None:
        _checker = ConsistencyChecker()

    result = _checker.check(output, session_id)
    if result is None:
        return None

    if not result.get("consistent", True):
        contradictions = result.get("contradictions", [])
        similarity = result.get("similarity", 0.0)

        if len(contradictions) >= 2 or similarity > 0.8:
            severity = "HIGH"
        else:
            severity = "MEDIUM"

        details = f"Inconsistency: {len(contradictions)} contradictions detected"
        return (severity, details)

    return None
