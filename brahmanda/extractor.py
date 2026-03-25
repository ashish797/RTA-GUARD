"""
RTA-GUARD — Brahmanda Map Claim Extractor

Extracts verifiable claims from AI output for ground truth verification.
MVP: Rule-based extraction. Future: NLP-based with spaCy/NLTK.
"""
import re
from dataclasses import dataclass
from typing import List


@dataclass
class ExtractedClaim:
    """A claim extracted from text, ready for verification."""
    text: str
    claim_type: str = "general"
    confidence: float = 0.8
    subject: str = ""
    predicate: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "type": self.claim_type,
            "confidence": self.confidence,
            "subject": self.subject,
        }


# Patterns that indicate verifiable claims
CLAIM_PATTERNS = [
    # Definitional claims: "X is Y", "X are Y"
    (r"(?:The\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|are)\s+(.+?)\.?", "entity"),
    # Capital/governance: "The capital of X is Y"
    (r"(?:The\s+)?capital\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|are)\s+(.+?)\.?", "entity"),
    # Population/stats: "X has a population of Y"
    (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+has\s+(?:a\s+)?population\s+of\s+(.+?)\.?", "metric"),
    # Historical: "X was founded in Y", "X occurred in Y"
    (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+was\s+(?:founded|born|created|established)\s+in\s+(.+?)\.?", "historical"),
    # Relationship: "X borders Y", "X is located in Y"
    (r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:borders?|is\s+located\s+in|belongs?\s+to)\s+(.+?)\.?", "relationship"),
    # Year-based: "In YYYY, X happened"
    (r"In\s+(\d{4}),?\s+(.+?)\.?", "historical"),
    # Number-based claims with units
    (r"(?:The\s+)?(?:population|area|altitude|temperature|price|cost|speed|distance)\s+(?:of\s+)?(.+?)\s+(?:is|was|are)\s+(.+?)\.?", "metric"),
]


def extract_claims(text: str) -> List[ExtractedClaim]:
    """
    Extract verifiable claims from text.
    
    MVP: Simple pattern matching.
    Future: spaCy dependency parsing + named entity recognition.
    """
    claims = []
    seen = set()

    # Split into sentences
    sentences = _split_sentences(text)

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 10:
            continue

        for pattern, claim_type in CLAIM_PATTERNS:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if match:
                claim_text = sentence
                # Deduplicate
                normalized = claim_text.lower().strip()
                if normalized in seen:
                    continue
                seen.add(normalized)

                # Extract subject
                subject = ""
                if match.lastindex >= 1:
                    subject = match.group(1)

                claims.append(ExtractedClaim(
                    text=claim_text,
                    claim_type=claim_type,
                    confidence=0.8,
                    subject=subject,
                ))
                break

    # If no specific patterns matched but text has factual-looking content,
    # add the sentence as a general claim if it contains numbers or proper nouns
    if not claims:
        for sentence in sentences:
            if len(sentence) >= 15:
                # Has numbers or capitalized words
                if re.search(r"\d+", sentence) or re.search(r"[A-Z][a-z]{2,}", sentence):
                    normalized = sentence.lower().strip()
                    if normalized not in seen:
                        seen.add(normalized)
                        claims.append(ExtractedClaim(
                            text=sentence,
                            claim_type="general",
                            confidence=0.6,  # Lower confidence for generic extraction
                        ))

    return claims


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    # Simple split on period, exclamation, question mark
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if s.strip()]
