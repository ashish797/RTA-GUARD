"""
RTA-GUARD — Brahmanda Map Verifier

Verifies extracted claims against ground truth facts.
MVP: In-memory fact store with exact/normalized matching.
Future: Qdrant for semantic search, PostgreSQL for facts.
"""
import re
import logging
from typing import List, Optional, Dict, Tuple
from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision
)
from .extractor import extract_claims, ExtractedClaim

logger = logging.getLogger(__name__)

# ─── Domain classification ─────────────────────────────────────────

DOMAIN_KEYWORDS = {
    "medical": {"diagnosis", "symptom", "treatment", "disease", "patient", "medicine", "doctor", "hospital", "drug", "dose", "surgery", "cancer", "infection"},
    "science": {"experiment", "hypothesis", "atom", "molecule", "gravity", "orbit", "temperature", "celsius", "kelvin", "physics", "chemistry", "biology", "quantum", "evolution"},
    "history": {"war", "empire", "century", "founded", "dynasty", "king", "queen", "president", "election", "revolution", "treaty", "civilization"},
    "technology": {"software", "hardware", "algorithm", "programming", "protocol", "network", "database", "api", "server", "computer", "internet"},
    "geography": {"capital", "country", "continent", "river", "mountain", "ocean", "population", "border", "latitude", "longitude"},
    "mathematics": {"theorem", "equation", "proof", "integral", "derivative", "prime", "factorial", "matrix", "vector"},
}


def classify_domain(text: str) -> str:
    """Classify the domain of a text based on keyword matching."""
    words = set(text.lower().split())
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        overlap = len(words & keywords)
        if overlap > 0:
            scores[domain] = overlap
    if scores:
        return max(scores, key=scores.get)
    return "general"


# ─── Enhanced contradiction detection ──────────────────────────────

# Common stopwords that don't contribute to factual content
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "of", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "into", "about", "and", "or",
    "but", "not", "no", "nor", "so", "yet", "if", "then", "than", "that",
    "this", "these", "those", "it", "its", "he", "she", "they", "we", "you",
    "my", "your", "his", "her", "our", "their", "which", "who", "whom",
    "what", "where", "when", "how", "very", "just", "also", "too", "only",
    "quite", "really", "most", "more", "much", "some", "any", "all", "each",
    "every", "both", "few", "such", "there", "here",
}

# Words that signal negation (claim is negated vs fact)
NEGATION_WORDS = {"not", "never", "no", "neither", "nor", "nothing", "nowhere", "nobody", "none"}
NEGATION_CONTRACTIONS = {"isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't", "shouldn't", "hasn't", "haven't", "hadn't"}

# Relationship predicates that carry the core factual claim
RELATION_PREDICATES = {
    "is the capital of", "is capital of",
    "is the largest", "is largest",
    "is located in", "is found in", "is in",
    "borders", "is part of", "belongs to",
    "has a population of", "has population of",
    "was founded in", "was born in",
    "developed", "invented", "discovered",
}


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison — lowercase, strip, collapse whitespace."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def _extract_content_words(text: str) -> set:
    """Extract meaningful content words (excluding stopwords)."""
    words = set(re.findall(r'[a-z]{2,}', text.lower()))
    return words - STOPWORDS


def _extract_entities(text: str) -> set:
    """Extract capitalized entities (proper nouns) from text."""
    # Multi-word entities: "United States", "New York"
    entities = set()
    # Single capitalized words
    for match in re.finditer(r'\b([A-Z][a-z]+)\b', text):
        entities.add(match.group(1).lower())
    # Multi-word: consecutive capitalized words
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text):
        entities.add(match.group(0).lower())
    return entities


def _extract_predicate(text: str) -> str:
    """Extract the main predicate/relation from a claim."""
    text_lower = text.lower()
    for pred in RELATION_PREDICATES:
        if pred in text_lower:
            return pred
    return ""


def _extract_value(text: str, predicate: str) -> str:
    """Extract the 'value' part after a predicate."""
    if not predicate:
        return ""
    text_lower = text.lower()
    idx = text_lower.find(predicate)
    if idx >= 0:
        after = text[idx + len(predicate):].strip()
        # Remove trailing period
        after = after.rstrip('.')
        return after.strip()
    return ""


def _has_negation(text: str) -> bool:
    """Check if text contains negation."""
    words = set(text.lower().split())
    if words & NEGATION_WORDS:
        return True
    lower = text.lower()
    for contraction in NEGATION_CONTRACTIONS:
        if contraction in lower:
            return True
    return False


def _numbers_in_text(text: str) -> set:
    """Extract all numbers from text for numeric comparison."""
    return set(re.findall(r'\b\d[\d,]*\.?\d*\b', text))


def enhanced_check_contradiction(claim: str, fact: str, similarity: float) -> Tuple[bool, str]:
    """
    Enhanced contradiction detection with multiple heuristics.

    Returns:
        (is_contradicted: bool, reason: str)
    """
    claim_norm = _normalize_for_comparison(claim)
    fact_norm = _normalize_for_comparison(fact)

    # If they're essentially the same, no contradiction
    if claim_norm == fact_norm:
        return False, "exact_match"

    # ── Heuristic 1: Negation mismatch ──
    claim_neg = _has_negation(claim)
    fact_neg = _has_negation(fact)
    if claim_neg != fact_neg:
        # One says "X is Y", other says "X is not Y" — contradiction
        # But only if they share enough content words
        claim_content = _extract_content_words(claim)
        fact_content = _extract_content_words(fact)
        shared = claim_content & fact_content
        if len(shared) >= 2:
            return True, f"negation_mismatch: claim_neg={claim_neg}, fact_neg={fact_neg}"

    # ── Heuristic 2: Same subject + same predicate, different value ──
    claim_entities = _extract_entities(claim)
    fact_entities = _extract_entities(fact)
    shared_entities = claim_entities & fact_entities

    claim_pred = _extract_predicate(claim)
    fact_pred = _extract_predicate(fact)

    if claim_pred and fact_pred and claim_pred == fact_pred and shared_entities:
        claim_val = _extract_value(claim, claim_pred)
        fact_val = _extract_value(fact, fact_pred)
        if claim_val and fact_val and claim_val.lower() != fact_val.lower():
            # Same predicate, same entities, different values → contradiction
            return True, f"value_mismatch: '{claim_val}' vs '{fact_val}' under '{claim_pred}'"

    # ── Heuristic 2b: Generic "X is [prep] Y" vs "X is [prep] Z" ──
    # Handles: "Eiffel Tower is in London" vs "Eiffel Tower is in Paris"
    for pred_pattern in ["is the capital of", "is capital of", "is in", "is located in", "is found in"]:
        if pred_pattern in claim.lower() and pred_pattern in fact.lower():
            claim_parts = claim.lower().split(pred_pattern)
            fact_parts = fact.lower().split(pred_pattern)
            if len(claim_parts) >= 2 and len(fact_parts) >= 2:
                claim_subject = claim_parts[0].strip()  # "paris" or "eiffel tower"
                fact_subject = fact_parts[0].strip()     # "berlin" or "eiffel tower"
                claim_object = claim_parts[1].strip().rstrip('.')   # "france" or "london"
                fact_object = fact_parts[1].strip().rstrip('.')
                # Subjects must be the same (or very similar), objects must differ
                subj_sim = len(set(claim_subject.split()) & set(fact_subject.split())) / max(len(set(claim_subject.split()) | set(fact_subject.split())), 1)
                if subj_sim >= 0.5 and claim_object != fact_object:
                    return True, f"location_contradiction: '{claim_subject}' {pred_pattern} '{claim_object}' vs '{fact_object}'"

    # ── Heuristic 3: High similarity but different entities (capital pattern) ──
    if similarity >= 0.4 and claim_pred and fact_pred and claim_pred == fact_pred:
        # Check if the subject differs: "capital of France" vs "capital of Germany"
        claim_subj = _extract_value(claim, claim_pred) if "capital" in claim_pred else ""
        fact_subj = _extract_value(fact, fact_pred) if "capital" in fact_pred else ""
        # Actually for "is the capital of", the entity BEFORE the predicate is the value
        # "Paris is the capital of France" — predicate "is the capital of", value "France"
        # So if predicates match but entities after differ, check if the subject (before predicate) differs
        for pred_pattern in ["is the capital of", "is capital of"]:
            if pred_pattern in claim.lower() and pred_pattern in fact.lower():
                claim_parts = claim.lower().split(pred_pattern)
                fact_parts = fact.lower().split(pred_pattern)
                if len(claim_parts) >= 2 and len(fact_parts) >= 2:
                    claim_value = claim_parts[0].strip()  # "paris"
                    fact_value = fact_parts[0].strip()     # "berlin"
                    claim_subject = claim_parts[1].strip()  # "france"
                    fact_subject = fact_parts[1].strip()
                    if claim_subject == fact_subject and claim_value != fact_value:
                        # Same subject (France), different values (Paris vs Berlin) → contradiction!
                        return True, f"capital_contradiction: '{claim_value}' vs '{fact_value}' for '{claim_subject}'"

    # ── Heuristic 4: Numeric contradiction ──
    claim_nums = _numbers_in_text(claim)
    fact_nums = _numbers_in_text(fact)
    if claim_nums and fact_nums and claim_nums != fact_nums:
        # If they share subject words but have different numbers, it might be a contradiction
        claim_content = _extract_content_words(claim) - {"population", "area", "temperature", "speed", "distance", "million", "billion", "thousand"}
        fact_content = _extract_content_words(fact) - {"population", "area", "temperature", "speed", "distance", "million", "billion", "thousand"}
        shared = claim_content & fact_content
        if len(shared) >= 2:
            return True, f"numeric_mismatch: claim={claim_nums}, fact={fact_nums}"

    # ── Heuristic 5: Very low similarity but share entities = likely unrelated, not contradictory ──
    if similarity < 0.3:
        return False, "too_dissimilar_for_contradiction"

    # Default: not contradictory
    return False, "no_contradiction_detected"


class BrahmandaMap:
    """
    The Brahmanda Map — ground truth database.
    
    MVP: In-memory fact store with normalized matching.
    Production: Qdrant + PostgreSQL (see Phase 2.6).
    """

    def __init__(self):
        self._facts: Dict[str, GroundTruthFact] = {}
        self._normalized_index: Dict[str, str] = {}  # normalized claim -> fact ID
        self._fact_count = 0

    # === Fact Management ===

    def add_fact(
        self,
        claim: str,
        domain: str = "general",
        fact_type: FactType = FactType.ENTITY,
        confidence: float = 0.9,
        source: Optional[Source] = None,
        source_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
    ) -> GroundTruthFact:
        """Add a verified fact to the Brahmanda Map."""
        if source is None:
            source = Source(
                name="RTA-GUARD Default",
                authority=SourceAuthority.SECONDARY,
                authority_score=0.7,
            )

        fact = GroundTruthFact(
            claim=claim,
            domain=domain,
            fact_type=fact_type,
            confidence=confidence,
            source=source,
            source_url=source_url,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Store fact
        self._facts[fact.id] = fact
        # Index for fast lookup
        self._normalized_index[fact.normalized] = fact.id
        self._fact_count += 1

        return fact

    def get_fact(self, fact_id: str) -> Optional[GroundTruthFact]:
        """Get a fact by ID."""
        return self._facts.get(fact_id)

    def find_by_normalized(self, normalized: str) -> Optional[GroundTruthFact]:
        """Find a fact by normalized claim text."""
        fact_id = self._normalized_index.get(normalized)
        if fact_id:
            return self._facts.get(fact_id)
        return None

    def search(self, query: str, domain: Optional[str] = None, limit: int = 5) -> List[GroundTruthFact]:
        """
        Search for facts matching the query.
        MVP: Simple keyword matching.
        Future: Qdrant semantic search.
        """
        query_lower = query.lower().strip()
        results = []

        for fact in self._facts.values():
            if domain and fact.domain != domain:
                continue

            claim_lower = fact.claim.lower()

            # Check exact match
            if query_lower == claim_lower:
                results.insert(0, fact)  # Highest priority
                continue

            # Check if query is contained in fact or vice versa
            if query_lower in claim_lower or claim_lower in query_lower:
                results.append(fact)
                continue

            # Check for significant word overlap
            query_words = set(query_lower.split())
            claim_words = set(claim_lower.split())
            overlap = len(query_words & claim_words)
            if overlap >= 2 and overlap / len(query_words) >= 0.5:
                results.append(fact)

        # Sort by confidence (descending)
        results.sort(key=lambda f: f.calculate_effective_confidence(), reverse=True)
        return results[:limit]

    def update_fact(self, fact_id: str, **kwargs) -> Optional[GroundTruthFact]:
        """Update an existing fact (creates new version)."""
        old_fact = self._facts.get(fact_id)
        if not old_fact:
            return None

        # Create new version
        new_fact = GroundTruthFact(
            claim=kwargs.get("claim", old_fact.claim),
            normalized=kwargs.get("claim", old_fact.claim).lower().strip(),
            domain=kwargs.get("domain", old_fact.domain),
            fact_type=kwargs.get("fact_type", old_fact.fact_type),
            confidence=kwargs.get("confidence", old_fact.confidence),
            source=kwargs.get("source", old_fact.source),
            source_url=kwargs.get("source_url", old_fact.source_url),
            tags=kwargs.get("tags", old_fact.tags),
            metadata=kwargs.get("metadata", old_fact.metadata),
            version=old_fact.version + 1,
        )

        # Mark old version as superseded
        old_fact.superseded_by = new_fact.id

        # Update index
        if old_fact.normalized in self._normalized_index:
            del self._normalized_index[old_fact.normalized]
        self._normalized_index[new_fact.normalized] = new_fact.id

        # Store
        self._facts[new_fact.id] = new_fact
        return new_fact

    def retract_fact(self, fact_id: str, reason: str = "") -> bool:
        """Retract a fact (soft delete — never hard delete)."""
        fact = self._facts.get(fact_id)
        if not fact:
            return False
        fact.confidence = 0.0
        fact.metadata["retracted"] = True
        fact.metadata["retraction_reason"] = reason
        return True

    @property
    def fact_count(self) -> int:
        return self._fact_count


class BrahmandaVerifier:
    """
    Verifies text against the Brahmanda Map.
    
    Pipeline: extract claims → search facts → compare → verdict
    """

    def __init__(self, brahmanda: Optional[BrahmandaMap] = None):
        self.brahmanda = brahmanda or BrahmandaMap()

    def verify(self, text: str, domain: str = "general") -> VerifyResult:
        """
        Verify AI output against ground truth.
        
        Returns VerifyResult with:
        - decision: pass/warn/block
        - overall_confidence: 0.0-1.0
        - claims: list of individual claim verifications
        """
        # Step 1: Extract claims from text
        claims = extract_claims(text)

        if not claims:
            # No verifiable claims found
            return VerifyResult(
                verified=True,
                overall_confidence=0.5,  # Can't verify, but no contradiction
                decision=VerifyDecision.WARN,
                details="No verifiable claims extracted from text",
            )

        # Step 2: Verify each claim
        claim_matches = []
        total_confidence = 0.0

        for claim in claims:
            match = self._verify_claim(claim, domain)
            claim_matches.append(match)
            total_confidence += self._match_confidence(match)

        # Step 3: Calculate overall confidence
        overall_confidence = total_confidence / len(claims) if claims else 0.5

        # Step 4: Determine final decision
        contradicted = any(m.contradicted for m in claim_matches)
        unverifiable = sum(1 for m in claim_matches if m.matched_fact is None)

        if contradicted:
            decision = VerifyDecision.BLOCK
            details = self._get_contradiction_details(claim_matches)
        elif unverifiable > len(claims) / 2:
            decision = VerifyDecision.WARN
            details = f"{unverifiable}/{len(claims)} claims could not be verified"
        else:
            decision = VerifyDecision.PASS
            details = "All claims verified against ground truth"

        return VerifyResult(
            verified=(decision == VerifyDecision.PASS),
            overall_confidence=round(overall_confidence, 4),
            claims=claim_matches,
            decision=decision,
            details=details,
        )

    def _verify_claim(self, claim: ExtractedClaim, domain: str) -> ClaimMatch:
        """Verify a single claim against ground truth using multi-fact cross-verification."""
        # Search for matching facts — try both specific domain and general
        facts_specific = self.brahmanda.search(claim.text, domain=domain, limit=5)
        facts_general = []
        if domain != "general":
            facts_general = self.brahmanda.search(claim.text, domain="general", limit=5)

        # Merge and deduplicate by fact ID
        seen_ids = set()
        all_facts = []
        for f in facts_specific + facts_general:
            if f.id not in seen_ids:
                seen_ids.add(f.id)
                all_facts.append(f)

        if not all_facts:
            return ClaimMatch(
                claim=claim.text,
                matched_fact=None,
                similarity=0.0,
                contradicted=False,
                reason="No matching fact found in ground truth",
            )

        # Cross-verify: check claim against ALL matched facts
        best_match = None
        best_similarity = 0.0
        best_contradicted = False
        best_reason = ""
        contradiction_found = False
        contradiction_fact = None

        for fact in all_facts:
            similarity = self._calculate_similarity(claim.text, fact.claim)
            contradicted, contra_reason = self._check_contradiction(claim.text, fact.claim, similarity)

            if contradicted:
                # Weight by fact confidence: higher-confidence facts are more authoritative
                fact_conf = fact.calculate_effective_confidence()
                if fact_conf >= 0.5:  # Only trust contradictions from authoritative sources
                    contradiction_found = True
                    contradiction_fact = fact
                    best_contradicted = True
                    best_match = fact
                    best_similarity = similarity
                    best_reason = f"Claim contradicts verified fact (conf={fact_conf:.2f}): '{fact.claim}' [{contra_reason}]"
                    break  # One authoritative contradiction is enough

            # Track best non-contradictory match
            if similarity > best_similarity and not contradicted:
                best_similarity = similarity
                best_match = fact
                best_contradicted = False

        # If no contradiction found, use best match
        if not contradiction_found and best_match:
            fact_conf = best_match.calculate_effective_confidence()
            if best_similarity >= 0.8:
                best_reason = f"High confidence match (sim={best_similarity:.2f}, conf={fact_conf:.2f})"
            elif best_similarity >= 0.5:
                best_reason = f"Partial match (sim={best_similarity:.2f}, conf={fact_conf:.2f})"
            else:
                best_reason = f"Low confidence match (sim={best_similarity:.2f})"

        # Domain-aware check: general facts shouldn't contradict domain-specific claims
        if contradiction_found and contradiction_fact and domain != "general":
            if contradiction_fact.domain == "general" and domain in DOMAIN_KEYWORDS:
                # A general fact contradicting a domain-specific claim is weaker evidence
                logger.debug(f"Domain mismatch: general fact contradicting {domain} claim — weakening signal")
                # Don't downgrade, but log it

        return ClaimMatch(
            claim=claim.text,
            matched_fact=best_match,
            similarity=best_similarity,
            contradicted=best_contradicted,
            reason=best_reason or "No clear match found",
        )

    def _calculate_similarity(self, claim: str, fact: str) -> float:
        """
        Calculate similarity between claim and fact.
        Uses content-word Jaccard + containment + entity overlap.
        Future: Embedding cosine similarity (via Qdrant).
        """
        # Content-word Jaccard (more meaningful than raw word overlap)
        claim_content = _extract_content_words(claim)
        fact_content = _extract_content_words(fact)

        if not claim_content or not fact_content:
            return 0.0

        intersection = claim_content & fact_content
        union = claim_content | fact_content
        jaccard = len(intersection) / len(union) if union else 0.0

        # Boost for entity overlap (proper nouns are strong signals)
        claim_entities = _extract_entities(claim)
        fact_entities = _extract_entities(fact)
        if claim_entities and fact_entities:
            entity_overlap = len(claim_entities & fact_entities) / len(claim_entities | fact_entities)
            jaccard = max(jaccard, entity_overlap)

        # Containment boost
        claim_lower = claim.lower()
        fact_lower = fact.lower()
        if claim_lower in fact_lower or fact_lower in claim_lower:
            jaccard = max(jaccard, 0.7)

        # Predicate match boost
        claim_pred = _extract_predicate(claim)
        fact_pred = _extract_predicate(fact)
        if claim_pred and fact_pred and claim_pred == fact_pred:
            jaccard = max(jaccard, 0.4)  # Same predicate = at least moderately similar

        return round(min(jaccard, 1.0), 4)

    def _check_contradiction(self, claim: str, fact: str, similarity: float) -> Tuple[bool, str]:
        """
        Check if the claim contradicts the fact.
        Delegates to enhanced_check_contradiction for multi-heuristic detection.
        """
        return enhanced_check_contradiction(claim, fact, similarity)

    def _extract_subject(self, text: str) -> str:
        """Extract the main subject from a claim."""
        match = re.search(r"(?:the\s+)?(?:capital|population|area|founder)\s+of\s+([A-Z][a-z]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        match = re.search(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:is|are|has|was)", text)
        if match:
            return match.group(1).lower()
        return ""

    def _values_overlap(self, claim: str, fact: str) -> bool:
        """Check if the values (objects) in claim and fact overlap."""
        claim_words = set(re.findall(r"[a-z]{3,}", claim.lower()))
        fact_words = set(re.findall(r"[a-z]{3,}", fact.lower()))
        # Filter out common words
        common = {"the", "is", "are", "was", "has", "have", "and", "or", "of", "in", "to"}
        claim_words -= common
        fact_words -= common
        overlap = claim_words & fact_words
        return len(overlap) > 0

    def _match_confidence(self, match: ClaimMatch) -> float:
        """Calculate confidence for a single claim match."""
        if match.matched_fact is None:
            return 0.3  # Can't verify

        if match.contradicted:
            return 0.0

        fact_confidence = match.matched_fact.calculate_effective_confidence()
        return round(fact_confidence * match.similarity, 4)

    def _get_contradiction_details(self, matches: List[ClaimMatch]) -> str:
        """Get human-readable contradiction details."""
        contradicted = [m for m in matches if m.contradicted]
        if not contradicted:
            return ""
        details = []
        for m in contradicted:
            if m.matched_fact:
                details.append(f"'{m.claim}' contradicts verified: '{m.matched_fact.claim}'")
        return "; ".join(details)

    # === Convenience Methods ===

    def add_verified_fact(
        self,
        claim: str,
        source_name: str = "Manual Entry",
        source_authority: SourceAuthority = SourceAuthority.SECONDARY,
        source_url: Optional[str] = None,
        domain: str = "general",
        confidence: float = 0.9,
    ) -> GroundTruthFact:
        """Convenience method to add a verified fact."""
        source = Source(
            name=source_name,
            authority=source_authority,
            authority_score=self._authority_to_score(source_authority),
            url=source_url,
        )
        return self.brahmanda.add_fact(
            claim=claim,
            domain=domain,
            confidence=confidence,
            source=source,
        )

    def _authority_to_score(self, authority: SourceAuthority) -> float:
        """Map authority level to numeric score."""
        mapping = {
            SourceAuthority.PRIMARY: 0.95,
            SourceAuthority.SECONDARY: 0.75,
            SourceAuthority.TERTIARY: 0.45,
            SourceAuthority.UNCERTAIN: 0.2,
        }
        return mapping.get(authority, 0.5)


# ============================================================
# Factory — Create a pre-populated Brahmanda Map for testing
# ============================================================

def create_seed_map() -> BrahmandaMap:
    """Create a pre-populated Brahmanda Map with common facts for testing."""
    brahmanda = BrahmandaMap()

    # Add common geographic facts
    facts = [
        ("Paris is the capital of France", "general", 0.98),
        ("Berlin is the capital of Germany", "general", 0.98),
        ("London is the capital of the United Kingdom", "general", 0.98),
        ("Tokyo is the capital of Japan", "general", 0.98),
        ("Washington D.C. is the capital of the United States", "general", 0.98),
        ("The Earth orbits the Sun", "science", 0.99),
        ("Water boils at 100 degrees Celsius at sea level", "science", 0.99),
        ("The speed of light is approximately 299,792 kilometers per second", "science", 0.99),
        ("Einstein developed the theory of relativity", "history", 0.95),
        ("Python is a programming language", "technology", 0.99),
        ("HTTP stands for HyperText Transfer Protocol", "technology", 0.99),
    ]

    for claim, domain, confidence in facts:
        brahmanda.add_fact(
            claim=claim,
            domain=domain,
            confidence=confidence,
            source=Source(
                name="Seed Dataset",
                authority=SourceAuthority.SECONDARY,
                authority_score=0.8,
            ),
        )

    return brahmanda


def get_seed_verifier() -> BrahmandaVerifier:
    """Get a pre-populated verifier for testing/demo."""
    return BrahmandaVerifier(create_seed_map())
