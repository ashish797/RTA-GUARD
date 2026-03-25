"""
RTA-GUARD — Brahmanda Map Verifier

Verifies extracted claims against ground truth facts.
MVP: In-memory fact store with exact/normalized matching.
Future: Qdrant for semantic search, PostgreSQL for facts.

Phase 2.4: Source confidence feeds into verification confidence.
Every fact requires source attribution.
"""
import re
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple
from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision, AuditAction,
    confidence_for_authority,
)
from .extractor import extract_claims, ExtractedClaim
from .attribution import AttributionManager
from .confidence import ConfidenceScorer, ConfidenceExplanation, ConfidenceLevel
from .mutation import MutationTracker

logger = logging.getLogger(__name__)

# Phase 3.1: Conscience Monitor (optional import for backward compat)
try:
    from .conscience import ConscienceMonitor
    _CONSCIENCE_AVAILABLE = True
except ImportError:
    _CONSCIENCE_AVAILABLE = False

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

NEGATION_WORDS = {"not", "never", "no", "neither", "nor", "nothing", "nowhere", "nobody", "none"}
NEGATION_CONTRACTIONS = {"isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't", "shouldn't", "hasn't", "haven't", "hadn't"}

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
    return re.sub(r'\s+', ' ', text.lower().strip())


def _extract_content_words(text: str) -> set:
    words = set(re.findall(r'[a-z]{2,}', text.lower()))
    return words - STOPWORDS


def _extract_entities(text: str) -> set:
    entities = set()
    for match in re.finditer(r'\b([A-Z][a-z]+)\b', text):
        entities.add(match.group(1).lower())
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text):
        entities.add(match.group(0).lower())
    return entities


def _extract_predicate(text: str) -> str:
    text_lower = text.lower()
    for pred in RELATION_PREDICATES:
        if pred in text_lower:
            return pred
    return ""


def _extract_value(text: str, predicate: str) -> str:
    if not predicate:
        return ""
    text_lower = text.lower()
    idx = text_lower.find(predicate)
    if idx >= 0:
        after = text[idx + len(predicate):].strip()
        after = after.rstrip('.')
        return after.strip()
    return ""


def _has_negation(text: str) -> bool:
    words = set(text.lower().split())
    if words & NEGATION_WORDS:
        return True
    lower = text.lower()
    for contraction in NEGATION_CONTRACTIONS:
        if contraction in lower:
            return True
    return False


def _numbers_in_text(text: str) -> set:
    return set(re.findall(r'\b\d[\d,]*\.?\d*\b', text))


def enhanced_check_contradiction(claim: str, fact: str, similarity: float) -> Tuple[bool, str]:
    claim_norm = _normalize_for_comparison(claim)
    fact_norm = _normalize_for_comparison(fact)
    if claim_norm == fact_norm:
        return False, "exact_match"

    claim_neg = _has_negation(claim)
    fact_neg = _has_negation(fact)
    if claim_neg != fact_neg:
        claim_content = _extract_content_words(claim)
        fact_content = _extract_content_words(fact)
        shared = claim_content & fact_content
        if len(shared) >= 2:
            return True, f"negation_mismatch: claim_neg={claim_neg}, fact_neg={fact_neg}"

    claim_entities = _extract_entities(claim)
    fact_entities = _extract_entities(fact)
    shared_entities = claim_entities & fact_entities
    claim_pred = _extract_predicate(claim)
    fact_pred = _extract_predicate(fact)

    if claim_pred and fact_pred and claim_pred == fact_pred and shared_entities:
        claim_val = _extract_value(claim, claim_pred)
        fact_val = _extract_value(fact, fact_pred)
        if claim_val and fact_val and claim_val.lower() != fact_val.lower():
            return True, f"value_mismatch: '{claim_val}' vs '{fact_val}' under '{claim_pred}'"

    for pred_pattern in ["is the capital of", "is capital of", "is in", "is located in", "is found in"]:
        if pred_pattern in claim.lower() and pred_pattern in fact.lower():
            claim_parts = claim.lower().split(pred_pattern)
            fact_parts = fact.lower().split(pred_pattern)
            if len(claim_parts) >= 2 and len(fact_parts) >= 2:
                claim_subject = claim_parts[0].strip()
                fact_subject = fact_parts[0].strip()
                claim_object = claim_parts[1].strip().rstrip('.')
                fact_object = fact_parts[1].strip().rstrip('.')
                subj_sim = len(set(claim_subject.split()) & set(fact_subject.split())) / max(len(set(claim_subject.split()) | set(fact_subject.split())), 1)
                if subj_sim >= 0.5 and claim_object != fact_object:
                    return True, f"location_contradiction: '{claim_subject}' {pred_pattern} '{claim_object}' vs '{fact_object}'"

    for pred in ["the capital of", "capital of"]:
        if pred in claim.lower() and pred in fact.lower():
            claim_lc = claim.lower().rstrip('.')
            fact_lc = fact.lower().rstrip('.')
            pat_a = r'(?:the\s+)?capital\s+of\s+(.+?)\s+is\s+(.+)'
            pat_b = r'(.+?)\s+is\s+(?:the\s+)?capital\s+of\s+(.+)'

            def _parse_capital(text):
                m = re.match(pat_a, text)
                if m:
                    return (m.group(1).strip(), m.group(2).strip())
                m = re.match(pat_b, text)
                if m:
                    return (m.group(2).strip(), m.group(1).strip())
                return None

            claim_cap = _parse_capital(claim_lc)
            fact_cap = _parse_capital(fact_lc)
            if claim_cap and fact_cap:
                claim_country, claim_city = claim_cap
                fact_country, fact_city = fact_cap
                if claim_country == fact_country and claim_city != fact_city:
                    return True, f"capital_contradiction: '{claim_city}' vs '{fact_city}' for '{claim_country}'"

    if similarity >= 0.4 and claim_pred and fact_pred and claim_pred == fact_pred:
        for pred_pattern in ["is the capital of", "is capital of"]:
            if pred_pattern in claim.lower() and pred_pattern in fact.lower():
                claim_parts = claim.lower().split(pred_pattern)
                fact_parts = fact.lower().split(pred_pattern)
                if len(claim_parts) >= 2 and len(fact_parts) >= 2:
                    claim_value = claim_parts[0].strip()
                    fact_value = fact_parts[0].strip()
                    claim_subject = claim_parts[1].strip()
                    fact_subject = fact_parts[1].strip()
                    if claim_subject == fact_subject and claim_value != fact_value:
                        return True, f"capital_contradiction: '{claim_value}' vs '{fact_value}' for '{claim_subject}'"

    claim_nums = _numbers_in_text(claim)
    fact_nums = _numbers_in_text(fact)
    if claim_nums and fact_nums and claim_nums != fact_nums:
        claim_content = _extract_content_words(claim) - {"population", "area", "temperature", "speed", "distance", "million", "billion", "thousand"}
        fact_content = _extract_content_words(fact) - {"population", "area", "temperature", "speed", "distance", "million", "billion", "thousand"}
        shared = claim_content & fact_content
        if len(shared) >= 2:
            return True, f"numeric_mismatch: claim={claim_nums}, fact={fact_nums}"

    if similarity < 0.3:
        return False, "too_dissimilar_for_contradiction"

    return False, "no_contradiction_detected"


class BrahmandaMap:
    """
    The Brahmanda Map — ground truth database.

    Phase 2.4: Every fact requires a source. Source confidence feeds into
    fact confidence. Facts can expire. Optional AttributionManager integration.
    """

    def __init__(self, attribution: Optional[AttributionManager] = None):
        self._facts: Dict[str, GroundTruthFact] = {}
        self._normalized_index: Dict[str, str] = {}
        self._fact_count = 0
        self.attribution = attribution or AttributionManager()
        self.mutation_tracker = MutationTracker(attribution_manager=self.attribution)

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
        expires_at: Optional[str] = None,
    ) -> GroundTruthFact:
        """Add a verified fact to the Brahmanda Map. Source is required."""
        if source is None:
            # Phase 2.4: Create a default source via attribution system
            source = self.attribution.register_source(
                name="RTA-GUARD Default",
                authority=SourceAuthority.SECONDARY,
                authority_score=0.7,
            )

        # Apply source confidence to fact confidence
        source_conf = source.effective_confidence()
        adjusted_confidence = round(confidence * source_conf, 4)

        fact = GroundTruthFact(
            claim=claim,
            domain=domain,
            fact_type=fact_type,
            confidence=adjusted_confidence,
            source=source,
            source_url=source_url,
            tags=tags or [],
            metadata=metadata or {},
            expires_at=expires_at,
        )

        self._facts[fact.id] = fact
        self._normalized_index[fact.normalized] = fact.id
        self._fact_count += 1

        # Audit trail: log creation
        self.attribution.log_fact_create(fact)

        # Link fact to source via provenance tracker
        self.attribution.link_fact(fact.id, source.id)

        # Mutation tracking: record creation
        self.mutation_tracker.track_creation(
            fact=fact,
            source_name=source.name,
            reason="Fact created",
        )

        return fact

    def get_fact(self, fact_id: str) -> Optional[GroundTruthFact]:
        return self._facts.get(fact_id)

    def find_by_normalized(self, normalized: str) -> Optional[GroundTruthFact]:
        fact_id = self._normalized_index.get(normalized)
        if fact_id:
            return self._facts.get(fact_id)
        return None

    def search(self, query: str, domain: Optional[str] = None, limit: int = 5) -> List[GroundTruthFact]:
        query_lower = query.lower().strip()
        results = []

        for fact in self._facts.values():
            if domain and fact.domain != domain:
                continue

            claim_lower = fact.claim.lower()

            if query_lower == claim_lower:
                results.insert(0, fact)
                continue

            if query_lower in claim_lower or claim_lower in query_lower:
                results.append(fact)
                continue

            query_words = set(query_lower.split())
            claim_words = set(claim_lower.split())
            overlap = len(query_words & claim_words)
            if overlap >= 2 and overlap / len(query_words) >= 0.5:
                results.append(fact)

        # Phase 2.4: Sort by effective confidence (includes source weight + expiration)
        results.sort(key=lambda f: f.calculate_effective_confidence(), reverse=True)
        return results[:limit]

    def update_fact(self, fact_id: str, **kwargs) -> Optional[GroundTruthFact]:
        old_fact = self._facts.get(fact_id)
        if not old_fact:
            return None

        before = old_fact.to_dict()

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
            expires_at=kwargs.get("expires_at", old_fact.expires_at),
            version=old_fact.version + 1,
        )

        old_fact.superseded_by = new_fact.id

        if old_fact.normalized in self._normalized_index:
            del self._normalized_index[old_fact.normalized]
        self._normalized_index[new_fact.normalized] = new_fact.id

        self._facts[new_fact.id] = new_fact

        # Audit trail
        self.attribution.log_fact_update(new_fact, before=before)

        # Mutation tracking: record update with diff
        self.mutation_tracker.track_update(
            fact_id=fact_id,
            old_value=before,
            new_value=new_fact.to_dict(),
            reason=kwargs.get("reason", "Fact updated"),
        )

        return new_fact

    def retract_fact(self, fact_id: str, reason: str = "") -> bool:
        fact = self._facts.get(fact_id)
        if not fact:
            return False

        # Capture snapshot before retraction
        before_snapshot = fact.to_dict()

        fact.confidence = 0.0
        fact.metadata["retracted"] = True
        fact.metadata["retraction_reason"] = reason

        # Audit trail
        self.attribution.log_fact_retract(fact_id, reason)

        # Mutation tracking: record retraction
        self.mutation_tracker.track_retraction(
            fact_id=fact_id,
            reason=reason,
            fact_snapshot=before_snapshot,
        )

        return True

    def check_expired_facts(self) -> List[GroundTruthFact]:
        """Find and audit expired facts."""
        expired = []
        for fact in self._facts.values():
            if fact.is_expired() and not fact.metadata.get("expiration_logged"):
                fact.metadata["expiration_logged"] = True
                self.attribution.log_expiration(fact)

                # Mutation tracking: record expiration
                self.mutation_tracker.track_expiration(
                    fact_id=fact.id,
                    fact_snapshot=fact.to_dict(),
                )

                expired.append(fact)
        return expired

    @property
    def fact_count(self) -> int:
        return self._fact_count


class BrahmandaVerifier:
    """
    Verifies text against the Brahmanda Map.

    Phase 2.4: Source confidence is weighted into verification confidence.
    Phase 2.5: ConfidenceScorer provides multi-dimensional scoring.
    Higher-authority sources produce higher-confidence verifications.
    """

    def __init__(
        self,
        brahmanda: Optional[BrahmandaMap] = None,
        use_pipeline: bool = True,
        scorer: Optional[ConfidenceScorer] = None,
        conscience_monitor: Optional["ConscienceMonitor"] = None,
    ):
        self.brahmanda = brahmanda or BrahmandaMap()
        self.use_pipeline = use_pipeline
        self.scorer = scorer or ConfidenceScorer()
        self.conscience = conscience_monitor  # Phase 3.1
        self._pipeline = None
        if self.use_pipeline:
            try:
                from .pipeline import VerificationPipeline
                self._pipeline = VerificationPipeline(self)
            except ImportError:
                logger.debug("VerificationPipeline not available, falling back to legacy verify")

    def verify(self, text: str, domain: str = "general") -> VerifyResult:
        if self._pipeline:
            return self._verify_via_pipeline(text, domain)
        return self._verify_legacy(text, domain)

    def verify_and_record(
        self,
        text: str,
        domain: str = "general",
        agent_id: str = "",
        session_id: str = "",
        user_id: str = "",
    ) -> VerifyResult:
        """
        Verify text and optionally record to Conscience Monitor.

        If agent_id is provided and a conscience monitor is configured,
        the verification result is recorded for behavioral profiling.
        """
        result = self.verify(text, domain=domain)

        if self.conscience and agent_id and session_id:
            contradicted = any(m.contradicted for m in result.claims) if result.claims else False
            self.conscience.record_interaction(
                agent_id=agent_id,
                session_id=session_id,
                verification_result=result,
                user_id=user_id,
                violation=contradicted,
                violation_type="hallucination" if contradicted else "",
                domain=domain,
            )

        return result

    def _verify_via_pipeline(self, text: str, domain: str) -> VerifyResult:
        pipeline_result = self._pipeline.verify(text, domain=domain)

        claim_matches = []
        for cv in pipeline_result.claims:
            match = ClaimMatch(
                claim=cv.claim,
                matched_fact=cv.best_match.matched_fact if cv.best_match else None,
                similarity=cv.best_match.similarity if cv.best_match else 0.0,
                contradicted=cv.contradicted,
                reason=cv.reason,
            )
            claim_matches.append(match)

            # Audit verification events
            if match.matched_fact:
                self.brahmanda.attribution.log_verification(
                    fact_id=match.matched_fact.id,
                    claim=cv.claim,
                    decision=cv.decision.value,
                    confidence=cv.confidence,
                    source_id=match.matched_fact.source.id,
                )

        return VerifyResult(
            verified=(pipeline_result.overall_decision == VerifyDecision.PASS),
            overall_confidence=pipeline_result.overall_confidence,
            claims=claim_matches,
            decision=pipeline_result.overall_decision,
            details=pipeline_result.details,
        )

    def _verify_legacy(self, text: str, domain: str) -> VerifyResult:
        claims = extract_claims(text)

        if not claims:
            return VerifyResult(
                verified=True,
                overall_confidence=0.5,
                decision=VerifyDecision.WARN,
                details="No verifiable claims extracted from text",
            )

        claim_matches = []
        total_confidence = 0.0

        for claim in claims:
            match = self._verify_claim(claim, domain)
            claim_matches.append(match)
            total_confidence += self._match_confidence(match)

            # Audit each verification
            if match.matched_fact:
                self.brahmanda.attribution.log_verification(
                    fact_id=match.matched_fact.id,
                    claim=claim.text,
                    decision="pass" if not match.contradicted else "block",
                    confidence=self._match_confidence(match),
                    source_id=match.matched_fact.source.id,
                )

        overall_confidence = total_confidence / len(claims) if claims else 0.5

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
        facts_specific = self.brahmanda.search(claim.text, domain=domain, limit=5)
        facts_general = []
        if domain != "general":
            facts_general = self.brahmanda.search(claim.text, domain="general", limit=5)

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
                fact_conf = fact.calculate_effective_confidence()
                if fact_conf >= 0.5:
                    contradiction_found = True
                    contradiction_fact = fact
                    best_contradicted = True
                    best_match = fact
                    best_similarity = similarity
                    best_reason = f"Claim contradicts verified fact (conf={fact_conf:.2f}): '{fact.claim}' [{contra_reason}]"
                    break

            if similarity > best_similarity and not contradicted:
                best_similarity = similarity
                best_match = fact
                best_contradicted = False

        if not contradiction_found and best_match:
            fact_conf = best_match.calculate_effective_confidence()
            if best_similarity >= 0.8:
                best_reason = f"High confidence match (sim={best_similarity:.2f}, conf={fact_conf:.2f})"
            elif best_similarity >= 0.5:
                best_reason = f"Partial match (sim={best_similarity:.2f}, conf={fact_conf:.2f})"
            else:
                best_reason = f"Low confidence match (sim={best_similarity:.2f})"

        if contradiction_found and contradiction_fact and domain != "general":
            if contradiction_fact.domain == "general" and domain in DOMAIN_KEYWORDS:
                logger.debug(f"Domain mismatch: general fact contradicting {domain} claim")

        return ClaimMatch(
            claim=claim.text,
            matched_fact=best_match,
            similarity=best_similarity,
            contradicted=best_contradicted,
            reason=best_reason or "No clear match found",
        )

    def _calculate_similarity(self, claim: str, fact: str) -> float:
        claim_content = _extract_content_words(claim)
        fact_content = _extract_content_words(fact)

        if not claim_content or not fact_content:
            return 0.0

        intersection = claim_content & fact_content
        union = claim_content | fact_content
        jaccard = len(intersection) / len(union) if union else 0.0

        claim_entities = _extract_entities(claim)
        fact_entities = _extract_entities(fact)
        if claim_entities and fact_entities:
            entity_overlap = len(claim_entities & fact_entities) / len(claim_entities | fact_entities)
            jaccard = max(jaccard, entity_overlap)

        claim_lower = claim.lower()
        fact_lower = fact.lower()
        if claim_lower in fact_lower or fact_lower in claim_lower:
            jaccard = max(jaccard, 0.7)

        claim_pred = _extract_predicate(claim)
        fact_pred = _extract_predicate(fact)
        if claim_pred and fact_pred and claim_pred == fact_pred:
            jaccard = max(jaccard, 0.4)

        return round(min(jaccard, 1.0), 4)

    def _check_contradiction(self, claim: str, fact: str, similarity: float) -> Tuple[bool, str]:
        return enhanced_check_contradiction(claim, fact, similarity)

    def _match_confidence(self, match: ClaimMatch) -> float:
        if match.matched_fact is None:
            return 0.3
        if match.contradicted:
            return 0.0
        fact = match.matched_fact
        score, _ = self.scorer.score_verification(
            similarity=match.similarity,
            fact_confidence=fact.confidence,
            source_authority_score=fact.source.authority_score,
            fact_age_days=self._fact_age_days(fact),
            domain=fact.domain,
            is_expired=fact.is_expired(),
        )
        return round(score, 4)

    def _fact_age_days(self, fact) -> float:
        """Calculate age of a fact in days."""
        try:
            verified = datetime.fromisoformat(fact.verified_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - verified).total_seconds() / 86400
            return max(0.0, age)
        except (ValueError, TypeError):
            return 0.0

    def get_confidence_explanation(
        self, match: ClaimMatch, domain: str = "general"
    ) -> Optional[ConfidenceExplanation]:
        """Get a detailed explanation of a claim match's confidence score."""
        if match.matched_fact is None:
            return None
        fact = match.matched_fact
        _, explanation = self.scorer.score_verification(
            similarity=match.similarity,
            fact_confidence=fact.confidence,
            source_authority_score=fact.source.authority_score,
            fact_age_days=self._fact_age_days(fact),
            domain=domain,
            is_expired=fact.is_expired(),
        )
        return explanation

    def _get_contradiction_details(self, matches: List[ClaimMatch]) -> str:
        contradicted = [m for m in matches if m.contradicted]
        if not contradicted:
            return ""
        details = []
        for m in contradicted:
            if m.matched_fact:
                details.append(f"'{m.claim}' contradicts verified: '{m.matched_fact.claim}'")
        return "; ".join(details)

    def add_verified_fact(
        self,
        claim: str,
        source_name: str = "Manual Entry",
        source_authority: SourceAuthority = SourceAuthority.SECONDARY,
        source_url: Optional[str] = None,
        domain: str = "general",
        confidence: float = 0.9,
    ) -> GroundTruthFact:
        source = self.brahmanda.attribution.register_source(
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
        mapping = {
            SourceAuthority.PRIMARY: 0.95,
            SourceAuthority.SECONDARY: 0.75,
            SourceAuthority.TERTIARY: 0.45,
            SourceAuthority.UNCERTAIN: 0.2,
        }
        return mapping.get(authority, 0.5)


def create_seed_map() -> BrahmandaMap:
    brahmanda = BrahmandaMap()

    seed_src = brahmanda.attribution.register_source(
        name="Seed Dataset",
        authority=SourceAuthority.SECONDARY,
        authority_score=0.8,
    )

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
            source=seed_src,
        )

    return brahmanda


def get_seed_verifier() -> BrahmandaVerifier:
    return BrahmandaVerifier(create_seed_map())
