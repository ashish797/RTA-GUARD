"""
RTA-GUARD — Brahmanda Map Verifier

Verifies extracted claims against ground truth facts.
MVP: In-memory fact store with exact/normalized matching.
Future: Qdrant for semantic search, PostgreSQL for facts.
"""
import re
from typing import List, Optional, Dict
from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision
)
from .extractor import extract_claims, ExtractedClaim


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
        """Verify a single claim against ground truth."""
        # Search for matching facts
        facts = self.brahmanda.search(claim.text, domain=domain)

        if not facts:
            return ClaimMatch(
                claim=claim.text,
                matched_fact=None,
                similarity=0.0,
                contradicted=False,
                reason="No matching fact found in ground truth",
            )

        best_match = facts[0]
        similarity = self._calculate_similarity(claim.text, best_match.claim)

        # Check for contradiction
        contradicted = self._check_contradiction(claim.text, best_match.claim, similarity)

        reason = ""
        if contradicted:
            reason = f"Claim contradicts verified fact: '{best_match.claim}'"
        elif similarity >= 0.8:
            reason = "High confidence match with ground truth"
        elif similarity >= 0.5:
            reason = "Partial match with ground truth"
        else:
            reason = "Low confidence match"

        return ClaimMatch(
            claim=claim.text,
            matched_fact=best_match,
            similarity=similarity,
            contradicted=contradicted,
            reason=reason,
        )

    def _calculate_similarity(self, claim: str, fact: str) -> float:
        """
        Calculate similarity between claim and fact.
        MVP: Word overlap ratio.
        Future: Embedding cosine similarity (via Qdrant).
        """
        claim_words = set(claim.lower().split())
        fact_words = set(fact.lower().split())

        if not claim_words or not fact_words:
            return 0.0

        intersection = claim_words & fact_words
        union = claim_words | fact_words

        # Jaccard similarity
        jaccard = len(intersection) / len(union) if union else 0.0

        # Also check containment
        claim_lower = claim.lower()
        fact_lower = fact.lower()
        if claim_lower in fact_lower or fact_lower in claim_lower:
            jaccard = max(jaccard, 0.7)

        return round(jaccard, 4)

    def _check_contradiction(self, claim: str, fact: str, similarity: float) -> bool:
        """
        Check if the claim contradicts the fact.
        Simple heuristic: if subjects match but predicates differ significantly.
        """
        if similarity < 0.3:
            return False  # Too different to be a contradiction

        claim_lower = claim.lower()
        fact_lower = fact.lower()

        # Check for negation
        negation_patterns = [
            (r"not\s+", True),
            (r"isn't\s+", True),
            (r"wasn't\s+", True),
            (r"don't\s+", True),
            (r"never\s+", True),
            (r"is\s+the\s+", False),
            (r"are\s+the\s+", False),
        ]

        claim_has_negation = any(re.search(p, claim_lower) for p, neg in negation_patterns if neg)
        fact_has_negation = any(re.search(p, fact_lower) for p, neg in negation_patterns if neg)

        # If one has negation and the other doesn't (and they share words), it's a contradiction
        if claim_has_negation != fact_has_negation:
            return True

        # Check for different values in similar subjects
        # e.g., "Paris is the capital" vs "Berlin is the capital"
        # Extract the subject-verb-object pattern
        subjects_match = self._extract_subject(claim) == self._extract_subject(fact)
        values_differ = not self._values_overlap(claim, fact)

        return subjects_match and values_differ

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
