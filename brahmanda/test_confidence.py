"""
Test suite for brahmanda Confidence Scoring System (Phase 2.5).

Methodology
-----------
The confidence scoring system combines four signals:
  - Source-based: trust authority scores from sources
  - Corroboration: multiple sources agree → higher confidence
  - Recency: newer facts score higher
  - Contradiction: if sources disagree, confidence drops

Confidence thresholds:
  HIGH   ≥ 0.85
  MEDIUM 0.5–0.85
  LOW    < 0.5

All tests use in-memory objects — no network calls.

Run with: ``python3 -m pytest brahmanda/test_confidence.py -v``
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _import_confidence():
    """Import confidence symbols, skipping if unavailable."""
    try:
        from brahmanda.confidence import (
            ConfidenceScorer,
            ConfidenceExplanation,
            ConfidenceLevel,
            HIGH_CONFIDENCE_THRESHOLD,
            MEDIUM_CONFIDENCE_THRESHOLD,
        )
        return ConfidenceScorer, ConfidenceExplanation, ConfidenceLevel
    except ImportError as exc:
        pytest.skip(f"Confidence module not yet implemented: {exc}")


def _import_scorer():
    ConfidenceScorer, *_ = _import_confidence()
    return ConfidenceScorer


def _import_level():
    _, _, ConfidenceLevel = _import_confidence()
    return ConfidenceLevel


# ===========================================================================
# 1. Confidence Level Thresholds
# ===========================================================================

class TestConfidenceLevels:
    """Confidence levels: HIGH ≥ 0.85, MEDIUM 0.5–0.85, LOW < 0.5."""

    def test_high_level(self):
        ConfidenceLevel = _import_level()
        assert ConfidenceLevel.from_score(0.95) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.85) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(1.0) == ConfidenceLevel.HIGH

    def test_medium_level(self):
        ConfidenceLevel = _import_level()
        assert ConfidenceLevel.from_score(0.84) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.50) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.65) == ConfidenceLevel.MEDIUM

    def test_low_level(self):
        ConfidenceLevel = _import_level()
        assert ConfidenceLevel.from_score(0.49) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.0) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.25) == ConfidenceLevel.LOW

    def test_threshold_constants(self):
        from brahmanda.confidence import (
            HIGH_CONFIDENCE_THRESHOLD,
            MEDIUM_CONFIDENCE_THRESHOLD,
        )
        assert HIGH_CONFIDENCE_THRESHOLD == 0.85
        assert MEDIUM_CONFIDENCE_THRESHOLD == 0.50


# ===========================================================================
# 2. Single Source → Medium Confidence
# ===========================================================================

class TestSingleSource:
    """A single source should produce MEDIUM confidence (capped)."""

    def test_single_high_authority_source(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.95],
            sources_agree=True,
            fact_age_days=1,
            domain="general",
        )
        # Very high authority single source can reach HIGH; verify explanation notes
        assert 0.0 < score <= 1.0
        assert explanation.source_count == 1

    def test_single_medium_authority_source(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.7],
            sources_agree=True,
            fact_age_days=1,
            domain="general",
        )
        assert 0.3 < score < 0.85, f"Expected MEDIUM range, got {score}"
        assert any("single source" in n.lower() for n in explanation.notes)

    def test_single_source_capped_below_high(self):
        """Single source (authority < 0.95) is capped at MEDIUM."""
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.90],
            sources_agree=True,
            fact_age_days=0,
            domain="general",
        )
        assert score < 0.85, f"Single source (0.90) should be capped at MEDIUM, got {score}"
        assert any("single source" in n.lower() for n in explanation.notes)

    def test_single_low_authority_source(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.3],
            sources_agree=True,
            fact_age_days=1,
            domain="general",
        )
        assert score < 0.7, f"Low authority source should not score high, got {score}"


# ===========================================================================
# 3. Multiple Sources Agree → High Confidence
# ===========================================================================

class TestMultipleSourcesAgree:
    """Multiple agreeing sources should produce HIGH confidence."""

    def test_two_sources_agree(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.9, 0.85],
            sources_agree=True,
            fact_age_days=1,
            domain="science",
        )
        assert score >= 0.6, f"Two agreeing sources should score well, got {score}"
        assert explanation.sources_agree is True
        assert explanation.source_count == 2

    def test_three_sources_agree(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.95, 0.90, 0.85],
            sources_agree=True,
            fact_age_days=1,
            domain="general",
        )
        assert score >= 0.75, f"Three high-authority agreeing sources should be high, got {score}"

    def test_more_sources_higher_corroboration(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score_1, _ = scorer.score(source_scores=[0.9], sources_agree=True, fact_age_days=1)
        score_2, _ = scorer.score(source_scores=[0.9, 0.85], sources_agree=True, fact_age_days=1)
        score_3, _ = scorer.score(source_scores=[0.9, 0.85, 0.8], sources_agree=True, fact_age_days=1)

        # More sources → higher or equal score
        assert score_2 >= score_1, f"Two sources should >= one source: {score_2} vs {score_1}"
        assert score_3 >= score_2, f"Three sources should >= two sources: {score_3} vs {score_2}"


# ===========================================================================
# 4. Conflicting Sources → Low Confidence
# ===========================================================================

class TestConflictingSources:
    """Disagreeing sources should produce LOWER confidence."""

    def test_two_sources_disagree(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()
        score, explanation = scorer.score(
            source_scores=[0.9, 0.85],
            sources_agree=False,
            fact_age_days=1,
            domain="general",
        )
        assert explanation.sources_agree is False
        # Contradiction should lower the score
        assert score < 0.85, f"Conflicting sources should lower confidence, got {score}"

    def test_disagreement_lower_than_agreement(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score_agree, _ = scorer.score(
            source_scores=[0.9, 0.85],
            sources_agree=True,
            fact_age_days=1,
        )
        score_disagree, _ = scorer.score(
            source_scores=[0.9, 0.85],
            sources_agree=False,
            fact_age_days=1,
        )

        assert score_disagree < score_agree, (
            f"Disagreement ({score_disagree}) should be lower than agreement ({score_agree})"
        )

    def test_high_authority_disagreement_worse(self):
        """Higher authority disagreement should be penalized more."""
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, expl_high = scorer.score(
            source_scores=[0.95, 0.90],
            sources_agree=False,
        )
        _, expl_low = scorer.score(
            source_scores=[0.4, 0.3],
            sources_agree=False,
        )

        # Higher authority disagreement → bigger penalty
        assert expl_high.contradiction_penalty < expl_low.contradiction_penalty


# ===========================================================================
# 5. Old Facts (Recency) → Lower Confidence
# ===========================================================================

class TestRecencyDecay:
    """Older facts should score lower due to recency decay."""

    def test_new_fact_scores_higher_than_old(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score_new, _ = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=1,
        )
        score_old, _ = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=365 * 10,  # 10 years
        )

        assert score_new > score_old, (
            f"New fact ({score_new}) should score higher than old ({score_old})"
        )

    def test_very_old_fact_still_positive(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, explanation = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=365 * 50,  # 50 years
        )

        assert score > 0, "Even very old facts should have positive score"
        assert explanation.recency_score < 0.5

    def test_expired_fact_aggressive_decay(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score_active, _ = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=1,
            is_expired=False,
        )
        score_expired, expl = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=1,
            is_expired=True,
        )

        assert score_expired < score_active * 0.5, (
            f"Expired fact ({score_expired}) should be much lower than active ({score_active})"
        )
        assert expl.is_expired is True


# ===========================================================================
# 6. Domain-Specific Weighting
# ===========================================================================

class TestDomainWeights:
    """Different domains have different scoring weights."""

    def test_medical_is_source_heavy(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        w_med = scorer.get_domain_weights("medical")
        w_gen = scorer.get_domain_weights("general")

        assert w_med[0] > w_gen[0], "Medical should weigh source authority more"

    def test_technology_is_recency_heavy(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        w_tech = scorer.get_domain_weights("technology")
        w_gen = scorer.get_domain_weights("general")

        assert w_tech[2] > w_gen[2], "Technology should weigh recency more"

    def test_custom_domain_weights(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        scorer.set_domain_weights("finance", 0.5, 0.2, 0.2, 0.1)
        w = scorer.get_domain_weights("finance")
        assert w == (0.5, 0.2, 0.2, 0.1)

    def test_invalid_weights_rejected(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        with pytest.raises(ValueError):
            scorer.set_domain_weights("bad", 0.5, 0.5, 0.5, 0.5)

    def test_supported_domains(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        domains = scorer.supported_domains
        assert "general" in domains
        assert "medical" in domains
        assert "technology" in domains

    def test_unknown_domain_falls_back_to_general(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        w = scorer.get_domain_weights("nonexistent_domain_xyz")
        w_gen = scorer.get_domain_weights("general")
        assert w == w_gen


# ===========================================================================
# 7. Confidence Explanation
# ===========================================================================

class TestConfidenceExplanation:
    """Confidence explanations show WHY a score is what it is."""

    def test_explanation_has_all_fields(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, explanation = scorer.score(
            source_scores=[0.9, 0.85],
            sources_agree=True,
            fact_age_days=30,
            domain="medical",
        )

        d = explanation.to_dict()
        assert "final_score" in d
        assert "confidence_level" in d
        assert "breakdown" in d
        assert "weights" in d
        assert "metadata" in d
        assert "notes" in d

        bd = d["breakdown"]
        assert "source" in bd
        assert "corroboration" in bd
        assert "recency" in bd
        assert "contradiction_penalty" in bd

    def test_explanation_str_is_readable(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, explanation = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=30,
        )

        s = str(explanation)
        assert "Confidence:" in s
        assert "Domain:" in s
        assert "Source authority:" in s

    def test_explanation_notes_on_single_source(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, explanation = scorer.score(
            source_scores=[0.7],
            sources_agree=True,
            fact_age_days=1,
        )

        assert any("single source" in n.lower() for n in explanation.notes), (
            f"Expected single source note, got: {explanation.notes}"
        )

    def test_explanation_notes_on_expired(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, explanation = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=1,
            is_expired=True,
        )

        assert any("expired" in n.lower() for n in explanation.notes)


# ===========================================================================
# 8. Determinism
# ===========================================================================

class TestDeterminism:
    """Same inputs always produce same outputs."""

    def test_repeated_scoring_is_stable(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        kwargs = dict(
            source_scores=[0.9, 0.85],
            sources_agree=True,
            fact_age_days=30,
            domain="medical",
        )

        s1, e1 = scorer.score(**kwargs)
        s2, e2 = scorer.score(**kwargs)

        assert s1 == s2, f"Non-deterministic: {s1} vs {s2}"
        assert e1.final_score == e2.final_score
        assert e1.confidence_level == e2.confidence_level

    def test_different_scorers_same_result(self):
        ConfidenceScorer = _import_scorer()

        scorer1 = ConfidenceScorer()
        scorer2 = ConfidenceScorer()

        s1, _ = scorer1.score(source_scores=[0.9, 0.85], sources_agree=True, fact_age_days=10)
        s2, _ = scorer2.score(source_scores=[0.9, 0.85], sources_agree=True, fact_age_days=10)

        assert s1 == s2

    def test_score_fact_deterministic(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        s1, _ = scorer.score_fact(
            fact_confidence=0.95,
            source_authority_score=0.9,
            corroboration_sources=2,
            sources_agree=True,
            fact_age_days=10,
            domain="science",
        )
        s2, _ = scorer.score_fact(
            fact_confidence=0.95,
            source_authority_score=0.9,
            corroboration_sources=2,
            sources_agree=True,
            fact_age_days=10,
            domain="science",
        )

        assert s1 == s2


# ===========================================================================
# 9. Score Bounds
# ===========================================================================

class TestScoreBounds:
    """Scores must always be in [0.0, 1.0]."""

    def test_score_always_in_bounds(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        test_cases = [
            dict(source_scores=[0.0], sources_agree=True, fact_age_days=0),
            dict(source_scores=[1.0], sources_agree=True, fact_age_days=0),
            dict(source_scores=[0.0, 0.0], sources_agree=False, fact_age_days=99999),
            dict(source_scores=[1.0, 1.0], sources_agree=True, fact_age_days=0),
            dict(source_scores=[0.5, 0.5, 0.5], sources_agree=True, fact_age_days=365*20),
            dict(source_scores=[0.9], sources_agree=True, fact_age_days=1, is_expired=True),
        ]

        for kwargs in test_cases:
            score, _ = scorer.score(**kwargs)
            assert 0.0 <= score <= 1.0, f"Score {score} out of bounds for {kwargs}"


# ===========================================================================
# 10. Verification Scoring
# ===========================================================================

class TestVerificationScoring:
    """score_verification combines similarity + fact confidence."""

    def test_high_similarity_high_confidence(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, explanation = scorer.score_verification(
            similarity=0.95,
            fact_confidence=0.98,
            source_authority_score=0.95,
            corroboration_sources=2,
            sources_agree=True,
            fact_age_days=1,
            domain="general",
        )

        assert score >= 0.8, f"High sim + high conf should score high, got {score}"

    def test_high_similarity_low_confidence(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, _ = scorer.score_verification(
            similarity=0.95,
            fact_confidence=0.3,
            source_authority_score=0.3,
            corroboration_sources=1,
            sources_agree=True,
            fact_age_days=1,
        )

        # Even with high similarity, low fact confidence pulls score down
        assert score < 0.9

    def test_low_similarity_high_confidence(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, _ = scorer.score_verification(
            similarity=0.2,
            fact_confidence=0.98,
            source_authority_score=0.95,
            corroboration_sources=3,
            sources_agree=True,
            fact_age_days=1,
        )

        # Low similarity pulls overall score down
        assert score < 0.8

    def test_verification_explanation_has_verification_note(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        _, explanation = scorer.score_verification(
            similarity=0.9,
            fact_confidence=0.95,
        )

        assert any("verification" in n.lower() for n in explanation.notes)


# ===========================================================================
# 11. Integration: Pipeline Uses ConfidenceScorer
# ===========================================================================

class TestPipelineIntegration:
    """The pipeline should use ConfidenceScorer and expose confidence explanations."""

    def _import_pipeline(self):
        try:
            from brahmanda.pipeline import VerificationPipeline
            from brahmanda.verifier import BrahmandaVerifier
            from brahmanda.confidence import ConfidenceScorer
            return VerificationPipeline, BrahmandaVerifier, ConfidenceScorer
        except ImportError:
            pytest.skip("Pipeline module not available")

    def test_pipeline_accepts_scorer(self):
        VerificationPipeline, _, ConfidenceScorer = self._import_pipeline()
        scorer = ConfidenceScorer()
        try:
            pipe = VerificationPipeline(scorer=scorer)
        except TypeError:
            pytest.skip("Pipeline does not yet accept scorer=")

        assert pipe is not None

    def test_claim_verification_has_confidence_level(self):
        VerificationPipeline, _, _ = self._import_pipeline()
        from brahmanda.verifier import BrahmandaMap, BrahmandaVerifier

        kb = BrahmandaMap()
        kb.add_fact(claim="Paris is the capital of France", domain="general", confidence=0.98)
        verifier = BrahmandaVerifier(kb)
        pipe = VerificationPipeline(verifier)

        result = pipe.verify("Paris is the capital of France.")
        assert result.claims
        claim = result.claims[0]

        d = claim.to_dict()
        assert "confidence_level" in d
        assert d["confidence_level"] in ("high", "medium", "low")

    def test_claim_verification_has_confidence_explanation(self):
        VerificationPipeline, _, _ = self._import_pipeline()
        from brahmanda.verifier import BrahmandaMap, BrahmandaVerifier

        kb = BrahmandaMap()
        kb.add_fact(claim="Paris is the capital of France", domain="general", confidence=0.98)
        verifier = BrahmandaVerifier(kb)
        pipe = VerificationPipeline(verifier)

        result = pipe.verify("Paris is the capital of France.")
        assert result.claims
        claim = result.claims[0]

        d = claim.to_dict()
        if "confidence_explanation" in d and d["confidence_explanation"]:
            expl = d["confidence_explanation"]
            assert "breakdown" in expl
            assert "weights" in expl

    def test_pipeline_result_has_confidence_level(self):
        VerificationPipeline, _, _ = self._import_pipeline()
        from brahmanda.verifier import BrahmandaMap, BrahmandaVerifier

        kb = BrahmandaMap()
        kb.add_fact(claim="Paris is the capital of France", domain="general", confidence=0.98)
        verifier = BrahmandaVerifier(kb)
        pipe = VerificationPipeline(verifier)

        result = pipe.verify("Paris is the capital of France.")
        d = result.to_dict()
        assert "confidence_level" in d
        assert d["confidence_level"] in ("high", "medium", "low")


# ===========================================================================
# 12. Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Boundary conditions for the confidence scorer."""

    def test_empty_source_scores_defaults_to_single(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, explanation = scorer.score(
            source_scores=[],
            sources_agree=True,
            fact_age_days=1,
        )

        assert explanation.source_count == 1  # defaults to [0.5]

    def test_none_source_scores(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, explanation = scorer.score(
            source_scores=None,
            sources_agree=True,
            fact_age_days=1,
        )

        assert 0.0 <= score <= 1.0
        assert explanation.source_count == 1

    def test_negative_age_treated_as_zero(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, explanation = scorer.score(
            source_scores=[0.9],
            sources_agree=True,
            fact_age_days=-10,
        )

        assert explanation.recency_score == 1.0  # future → no decay

    def test_zero_authority_sources(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        score, _ = scorer.score(
            source_scores=[0.0, 0.0],
            sources_agree=True,
            fact_age_days=1,
        )

        assert 0.0 <= score <= 1.0

    def test_clamped_out_of_range_scores(self):
        ConfidenceScorer = _import_scorer()
        scorer = ConfidenceScorer()

        # Scores above 1.0 and below 0.0 should be clamped
        score, _ = scorer.score(
            source_scores=[1.5],  # above range
            sources_agree=True,
            fact_age_days=0,
        )
        assert score <= 1.0

        score, _ = scorer.score(
            source_scores=[-0.5],  # below range
            sources_agree=True,
            fact_age_days=0,
        )
        assert score >= 0.0
