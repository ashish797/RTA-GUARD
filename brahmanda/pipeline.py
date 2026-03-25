"""
RTA-GUARD — Truth Verification Pipeline

Full verification pipeline: extract claims → search facts → cross-verify → verdict.
Wraps BrahmandaVerifier with structured claim-level verification and confidence weighting.

Usage:
    pipeline = VerificationPipeline(verifier)
    result = pipeline.verify("The capital of France is Paris")
    print(result.decision)  # VerifyDecision.PASS
"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision
)
from .extractor import extract_claims, ExtractedClaim
from .verifier import BrahmandaMap, BrahmandaVerifier, classify_domain
from .confidence import ConfidenceScorer, ConfidenceExplanation, ConfidenceLevel

logger = logging.getLogger(__name__)


@dataclass
class ClaimVerification:
    """Detailed verification result for a single claim."""
    claim: str
    claim_type: str
    domain: str
    top_matches: List[ClaimMatch]  # top-k matches with similarity scores
    best_match: Optional[ClaimMatch]
    decision: VerifyDecision
    confidence: float  # 0.0-1.0
    contradicted: bool
    verified: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    confidence_explanation: Optional[dict] = None  # Phase 2.5: detailed breakdown

    def to_dict(self) -> dict:
        d = {
            "claim": self.claim,
            "claim_type": self.claim_type,
            "domain": self.domain,
            "best_match": self.best_match.to_dict() if self.best_match else None,
            "top_matches_count": len(self.top_matches),
            "decision": self.decision.value,
            "confidence": round(self.confidence, 4),
            "confidence_level": ConfidenceLevel.from_score(self.confidence).value,
            "contradicted": self.contradicted,
            "verified": self.verified,
            "reason": self.reason,
            "details": self.details,
        }
        if self.confidence_explanation:
            d["confidence_explanation"] = self.confidence_explanation
        return d


@dataclass
class PipelineResult:
    """Result of the full verification pipeline."""
    text: str
    overall_decision: VerifyDecision
    overall_confidence: float
    claims: List[ClaimVerification]
    claim_count: int
    passed_count: int
    blocked_count: int
    warned_count: int
    details: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text[:200] + ("..." if len(self.text) > 200 else ""),
            "overall_decision": self.overall_decision.value,
            "overall_confidence": round(self.overall_confidence, 4),
            "confidence_level": ConfidenceLevel.from_score(self.overall_confidence).value,
            "claim_count": self.claim_count,
            "passed": self.passed_count,
            "blocked": self.blocked_count,
            "warned": self.warned_count,
            "claims": [c.to_dict() for c in self.claims],
            "details": self.details,
            "metadata": self.metadata,
        }

    # Backward compat: some callers check result.verified
    @property
    def verified(self) -> bool:
        return self.overall_decision == VerifyDecision.PASS


class VerificationPipeline:
    """
    Full verification pipeline for AI output.

    Pipeline:
        1. Extract verifiable claims from raw text
        2. For each claim:
           a. Classify domain
           b. Search in-memory fact store (all domains)
           c. (Optionally) search Qdrant vector store
           d. Find top-k matches with similarity scores
           e. Check for contradictions across ALL matches
           f. Calculate confidence-weighted verification
        3. Aggregate into overall verdict
    """

    def __init__(
        self,
        verifier: Optional[BrahmandaVerifier] = None,
        top_k: int = 5,
        contradiction_threshold: float = 0.5,  # min fact confidence to trust contradiction
        pass_similarity: float = 0.5,  # min similarity for PASS
        warn_similarity: float = 0.2,  # min similarity for WARN (below = unverifiable)
        scorer: Optional[ConfidenceScorer] = None,
    ):
        self.verifier = verifier or BrahmandaVerifier()
        self.top_k = top_k
        self.contradiction_threshold = contradiction_threshold
        self.pass_similarity = pass_similarity
        self.warn_similarity = warn_similarity
        self.scorer = scorer or ConfidenceScorer()

    def verify(self, text: str, domain: Optional[str] = None) -> PipelineResult:
        """
        Run the full verification pipeline on AI output text.

        Args:
            text: Raw AI output text
            domain: Force a specific domain (auto-detected if None)

        Returns:
            PipelineResult with overall verdict and per-claim details
        """
        # Step 1: Extract claims
        claims = extract_claims(text)

        if not claims:
            return PipelineResult(
                text=text,
                overall_decision=VerifyDecision.WARN,
                overall_confidence=0.5,
                claims=[],
                claim_count=0,
                passed_count=0,
                blocked_count=0,
                warned_count=1,
                details="No verifiable claims extracted from text",
                metadata={"extraction_method": "pattern_matching"},
            )

        # Step 2: Verify each claim
        claim_results: List[ClaimVerification] = []
        for claim in claims:
            claim_domain = domain or classify_domain(claim.text)
            cv = self._verify_single_claim(claim, claim_domain)
            claim_results.append(cv)

        # Step 3: Aggregate results
        return self._aggregate_results(text, claim_results)

    def _verify_single_claim(self, claim: ExtractedClaim, domain: str) -> ClaimVerification:
        """Verify a single claim with full multi-fact cross-verification."""

        # Search fact store — try both specific domain and general
        facts_specific = self.verifier.brahmanda.search(claim.text, domain=domain, limit=self.top_k)
        facts_general = []
        if domain != "general":
            facts_general = self.verifier.brahmanda.search(claim.text, domain="general", limit=self.top_k)

        # Also search without domain filter as fallback
        facts_all = self.verifier.brahmanda.search(claim.text, domain=None, limit=self.top_k)

        # Merge and deduplicate
        seen_ids = set()
        all_facts = []
        for f in facts_specific + facts_general + facts_all:
            fid = getattr(f, 'id', None) or id(f)
            if fid not in seen_ids:
                seen_ids.add(fid)
                all_facts.append(f)

        if not all_facts:
            return ClaimVerification(
                claim=claim.text,
                claim_type=claim.claim_type,
                domain=domain,
                top_matches=[],
                best_match=None,
                decision=VerifyDecision.WARN,
                confidence=0.3,
                contradicted=False,
                verified=False,
                reason="No matching facts in ground truth store",
                details={"facts_searched": 0},
            )

        # Calculate similarities and check contradictions for ALL matches
        matches: List[ClaimMatch] = []
        contradiction_detected = False
        contradiction_match = None

        for fact in all_facts:
            sim = self.verifier._calculate_similarity(claim.text, fact.claim)
            contradicted, contra_reason = self.verifier._check_contradiction(claim.text, fact.claim, sim)
            fact_conf = fact.calculate_effective_confidence()

            match = ClaimMatch(
                claim=claim.text,
                matched_fact=fact,
                similarity=sim,
                contradicted=contradicted,
                reason=contra_reason if contradicted else f"sim={sim:.2f}",
            )
            matches.append(match)

            # Check if this is a trustworthy contradiction
            if contradicted and fact_conf >= self.contradiction_threshold:
                if not contradiction_detected:
                    contradiction_detected = True
                    contradiction_match = match

        # Sort matches by similarity * confidence (best first)
        matches.sort(
            key=lambda m: (m.similarity * (m.matched_fact.calculate_effective_confidence() if m.matched_fact else 0)),
            reverse=True,
        )

        best_match = matches[0] if matches else None

        # Determine decision for this claim
        if contradiction_detected and contradiction_match:
            # BLOCK — authoritative contradiction
            fact_conf = contradiction_match.matched_fact.calculate_effective_confidence()
            return ClaimVerification(
                claim=claim.text,
                claim_type=claim.claim_type,
                domain=domain,
                top_matches=matches[:self.top_k],
                best_match=contradiction_match,
                decision=VerifyDecision.BLOCK,
                confidence=0.0,
                contradicted=True,
                verified=False,
                reason=f"CONTRADICTION: Claim contradicts verified fact (conf={fact_conf:.2f}): '{contradiction_match.matched_fact.claim}'",
                details={
                    "contradiction_reason": contradiction_match.reason,
                    "fact_confidence": fact_conf,
                    "facts_checked": len(all_facts),
                },
            )

        if best_match and best_match.matched_fact:
            sim = best_match.similarity
            fact = best_match.matched_fact
            fact_conf = fact.calculate_effective_confidence()

            # Phase 2.5: Use ConfidenceScorer for verification confidence
            try:
                verified_dt = datetime.fromisoformat(fact.verified_at.replace("Z", "+00:00"))
                age_days = max(0.0, (datetime.now(timezone.utc) - verified_dt).total_seconds() / 86400)
            except (ValueError, TypeError):
                age_days = 0.0

            verification_confidence, conf_explanation = self.scorer.score_verification(
                similarity=sim,
                fact_confidence=fact.confidence,
                source_authority_score=fact.source.authority_score,
                fact_age_days=age_days,
                domain=domain,
                is_expired=fact.is_expired(),
            )

            if sim >= self.pass_similarity:
                decision = VerifyDecision.PASS
                reason = f"Verified (sim={sim:.2f}, fact_conf={fact_conf:.2f})"
            elif sim >= self.warn_similarity:
                decision = VerifyDecision.WARN
                reason = f"Partial match only (sim={sim:.2f})"
            else:
                decision = VerifyDecision.WARN
                reason = f"Low similarity match (sim={sim:.2f})"

            return ClaimVerification(
                claim=claim.text,
                claim_type=claim.claim_type,
                domain=domain,
                top_matches=matches[:self.top_k],
                best_match=best_match,
                decision=decision,
                confidence=round(verification_confidence, 4),
                contradicted=False,
                verified=(decision == VerifyDecision.PASS),
                reason=reason,
                confidence_explanation=conf_explanation.to_dict(),
                details={
                    "similarity": sim,
                    "fact_confidence": fact_conf,
                    "facts_checked": len(all_facts),
                },
            )

        # No matches at all
        return ClaimVerification(
            claim=claim.text,
            claim_type=claim.claim_type,
            domain=domain,
            top_matches=[],
            best_match=None,
            decision=VerifyDecision.WARN,
            confidence=0.3,
            contradicted=False,
            verified=False,
            reason="No usable matches found",
            details={"facts_checked": len(all_facts)},
        )

    def _aggregate_results(self, text: str, results: List[ClaimVerification]) -> PipelineResult:
        """Aggregate per-claim results into an overall verdict."""
        total = len(results)
        blocked = sum(1 for r in results if r.decision == VerifyDecision.BLOCK)
        warned = sum(1 for r in results if r.decision == VerifyDecision.WARN)
        passed = sum(1 for r in results if r.decision == VerifyDecision.PASS)

        # Overall confidence: weighted average of claim confidences
        if total > 0:
            overall_conf = sum(r.confidence for r in results) / total
        else:
            overall_conf = 0.5

        # Decision logic
        if blocked > 0:
            # Any BLOCK → overall BLOCK
            decision = VerifyDecision.BLOCK
            contradicted_claims = [r for r in results if r.contradicted]
            details = f"{blocked}/{total} claims blocked — contradictions detected"
            if contradicted_claims:
                details += f": {contradicted_claims[0].reason}"
        elif warned > total / 2:
            # Majority unverifiable → WARN
            decision = VerifyDecision.WARN
            details = f"{warned}/{total} claims could not be fully verified"
        elif warned > 0:
            # Some unverifiable but majority passed → PASS with notes
            decision = VerifyDecision.PASS
            details = f"{passed}/{total} verified, {warned} unverifiable"
        else:
            decision = VerifyDecision.PASS
            details = f"All {total} claims verified against ground truth"

        return PipelineResult(
            text=text,
            overall_decision=decision,
            overall_confidence=round(overall_conf, 4),
            claims=results,
            claim_count=total,
            passed_count=passed,
            blocked_count=blocked,
            warned_count=warned,
            details=details,
            metadata={
                "pipeline_version": "1.0",
                "top_k": self.top_k,
                "contradiction_threshold": self.contradiction_threshold,
            },
        )


# ─── Factory functions ─────────────────────────────────────────────

def get_seed_pipeline() -> VerificationPipeline:
    """Get a pipeline with pre-populated common facts."""
    from .verifier import get_seed_verifier
    return VerificationPipeline(get_seed_verifier())


def create_pipeline(brahmanda: Optional[BrahmandaMap] = None, **kwargs) -> VerificationPipeline:
    """Create a pipeline with a specific Brahmanda Map."""
    verifier = BrahmandaVerifier(brahmanda) if brahmanda else BrahmandaVerifier()
    return VerificationPipeline(verifier, **kwargs)
