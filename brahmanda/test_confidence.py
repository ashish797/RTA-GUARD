"""
RTA-GUARD — Confidence Scoring System Tests

Tests for brahmanda/confidence.py covering source-based scoring,
corroboration, contradiction, recency decay, domain weighting,
explanation structure, threshold boundaries, edge cases, pipeline
integration, and determinism.

Run: ``python3 -m pytest brahmanda/test_confidence.py -v``
"""

from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone

# ─── Guard import ───────────────────────────────────────────────────

try:
    from brahmanda.confidence import (
        ConfidenceScorer,
        ConfidenceExplanation,
        ConfidenceLevel,
        HIGH_CONFIDENCE_THRESHOLD,
        MEDIUM_CONFIDENCE_THRESHOLD,
        DEFAULT_WEIGHTS,
        RECENCY_HALF_LIFE_YEARS,
    )
    _IMPORTABLE = True
except ImportError:
    _IMPORTABLE = False


@pytest.fixture(autouse=True)
def _skip_if_missing():
    """Skip all tests in this module if confidence.py is not importable."""
    if not _IMPORTABLE:
        pytest.skip("brahmanda.confidence not importable")


@pytest.fixture
def scorer():
    return ConfidenceScorer()


# ═══════════════════════════════════════════════════════════════════
# 1. Source-based scoring (primary / secondary / tertiary / uncertain)
# ═══════════════════════════════════════════════════════════════════

class TestSourceBasedScoring:
    """Source authority tiers translate into correct score ranges."""

    def test_primary_source_high_authority(self, scorer: ConfidenceScorer):
        """Primary source (0.95 authority) → high confidence."""
        score, exp = scorer.score(source_scores=[0.95], sources_agree=True)
        assert score >= MEDIUM_CONFIDENCE_THRESHOLD
        assert exp.source_score == pytest.approx(0.95, abs=1e-3)

    def test_secondary_source_moderate_authority(self, scorer: ConfidenceScorer):
        """Secondary source (0.70 authority) → MEDIUM tier."""
        score, exp = scorer.score(
            source_scores=[0.70], sources_agree=True, domain="general"
        )
        # Single source capped at 0.84 unless ≥0.95
        assert score <= 0.84
        assert exp.confidence_level == ConfidenceLevel.MEDIUM

    def test_tertiary_source_low_authority(self, scorer: ConfidenceScorer):
        """Tertiary source (0.40) → lower score than primary source."""
        score_tertiary, _ = scorer.score(source_scores=[0.40])
        score_primary, _ = scorer.score(source_scores=[0.95])
        assert score_tertiary < score_primary

    def test_uncertain_source_lowest_score(self, scorer: ConfidenceScorer):
        """Uncertain source (0.10) → lowest source score among tiers."""
        score_uncertain, exp = scorer.score(source_scores=[0.10])
        score_tertiary, _ = scorer.score(source_scores=[0.40])
        assert exp.source_score < score_tertiary / 1.0  # just verify raw source is low
        assert exp.source_score == pytest.approx(0.10, abs=1e-3)

    def test_average_of_multiple_source_scores(self, scorer: ConfidenceScorer):
        """Source score is the average of all source authority scores."""
        scores = [0.90, 0.80, 0.70]
        score, exp = scorer.score(source_scores=scores, sources_agree=True)
        assert exp.source_score == pytest.approx(0.80, abs=1e-3)


# ═══════════════════════════════════════════════════════════════════
# 2. Corroboration bonus (multiple sources agree)
# ═══════════════════════════════════════════════════════════════════

class TestCorroborationBonus:
    """More agreeing sources → higher corroboration score."""

    def test_single_source_corroboration_is_0_5(self, scorer: ConfidenceScorer):
        """1 source → corroboration baseline of 0.5."""
        _, exp = scorer.score(source_scores=[0.8])
        assert exp.corroboration_score == pytest.approx(0.5, abs=1e-3)

    def test_two_sources_corroboration(self, scorer: ConfidenceScorer):
        """2 agreeing sources → corroboration 0.75."""
        _, exp = scorer.score(source_scores=[0.8, 0.8], sources_agree=True)
        assert exp.corroboration_score == pytest.approx(0.75, abs=1e-2)

    def test_five_sources_high_corroboration(self, scorer: ConfidenceScorer):
        """5 agreeing sources → corroboration ~0.88."""
        _, exp = scorer.score(
            source_scores=[0.9] * 5, sources_agree=True
        )
        assert exp.corroboration_score > 0.85

    def test_many_sources_diminishing_returns(self, scorer: ConfidenceScorer):
        """Corroboration uses diminishing returns curve, caps at 1.0."""
        _, exp10 = scorer.score(source_scores=[0.9] * 10, sources_agree=True)
        _, exp100 = scorer.score(source_scores=[0.9] * 100, sources_agree=True)
        # Should be capped at 1.0
        assert exp100.corroboration_score <= 1.0
        # 100 sources barely more than 10
        assert abs(exp100.corroboration_score - exp10.corroboration_score) < 0.05


# ═══════════════════════════════════════════════════════════════════
# 3. Contradiction penalty (sources disagree)
# ═══════════════════════════════════════════════════════════════════

class TestContradictionPenalty:
    """Disagreement reduces confidence."""

    def test_no_contradiction_penalty_is_neutral(self, scorer: ConfidenceScorer):
        """Agreeing sources → contradiction_score = 1.0 (no penalty)."""
        _, exp = scorer.score(source_scores=[0.8, 0.8], sources_agree=True)
        assert exp.contradiction_penalty == pytest.approx(1.0)

    def test_disagreement_reduces_score(self, scorer: ConfidenceScorer):
        """Disagreeing sources → lower final score than agreeing."""
        score_agree, _ = scorer.score(
            source_scores=[0.9, 0.9], sources_agree=True, fact_age_days=0
        )
        score_disagree, _ = scorer.score(
            source_scores=[0.9, 0.9], sources_agree=False, fact_age_days=0
        )
        assert score_disagree < score_agree

    def test_high_authority_disagreement_penalized_more(self, scorer: ConfidenceScorer):
        """Higher-authority disagreement → worse penalty."""
        _, exp_high = scorer.score(
            source_scores=[0.95, 0.95], sources_agree=False
        )
        _, exp_low = scorer.score(
            source_scores=[0.50, 0.50], sources_agree=False
        )
        # Higher authority disagreement should have lower penalty
        assert exp_high.contradiction_penalty < exp_low.contradiction_penalty

    def test_single_source_no_contradiction(self, scorer: ConfidenceScorer):
        """Single source with sources_agree=False → no penalty (need 2+ to disagree)."""
        _, exp = scorer.score(source_scores=[0.8], sources_agree=False)
        assert exp.contradiction_penalty == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════
# 4. Recency decay (older → lower)
# ═══════════════════════════════════════════════════════════════════

class TestRecencyDecay:
    """Fact age reduces confidence via exponential decay."""

    def test_fresh_fact_recency_is_1(self, scorer: ConfidenceScorer):
        """Age 0 → recency = 1.0."""
        _, exp = scorer.score(fact_age_days=0)
        assert exp.recency_score == pytest.approx(1.0)

    def test_one_year_recency(self, scorer: ConfidenceScorer):
        """1 year old → recency = 0.5^(1/5) ≈ 0.87."""
        _, exp = scorer.score(fact_age_days=365.25)
        expected = 0.5 ** (1.0 / RECENCY_HALF_LIFE_YEARS)
        assert exp.recency_score == pytest.approx(expected, abs=1e-2)

    def test_five_years_recency_is_half(self, scorer: ConfidenceScorer):
        """5 years (half-life) → recency ≈ 0.5."""
        _, exp = scorer.score(fact_age_days=365.25 * 5)
        assert exp.recency_score == pytest.approx(0.5, abs=1e-2)

    def test_very_old_fact_low_recency(self, scorer: ConfidenceScorer):
        """100 years old → recency very low but never 0."""
        _, exp = scorer.score(fact_age_days=365.25 * 100)
        assert exp.recency_score < 0.05
        assert exp.recency_score > 0.0  # floor at 0.01

    def test_newer_fact_higher_than_older(self, scorer: ConfidenceScorer):
        """Newer facts always score higher recency than older ones."""
        _, exp_new = scorer.score(fact_age_days=10)
        _, exp_old = scorer.score(fact_age_days=3650)
        assert exp_new.recency_score > exp_old.recency_score


# ═══════════════════════════════════════════════════════════════════
# 5. Domain-specific weighting
# ═══════════════════════════════════════════════════════════════════

class TestDomainWeighting:
    """Different domains apply different weight profiles."""

    def test_medical_is_source_heavy(self, scorer: ConfidenceScorer):
        """Medical domain has higher source weight than general."""
        w_med = scorer.get_domain_weights("medical")
        w_gen = scorer.get_domain_weights("general")
        assert w_med[0] > w_gen[0]  # source weight higher

    def test_news_is_recency_heavy(self, scorer: ConfidenceScorer):
        """News domain has higher recency weight than general."""
        w_news = scorer.get_domain_weights("news")
        w_gen = scorer.get_domain_weights("general")
        assert w_news[2] > w_gen[2]  # recency weight higher

    def test_history_is_contradiction_heavy(self, scorer: ConfidenceScorer):
        """History domain weights contradiction higher."""
        w_hist = scorer.get_domain_weights("history")
        w_gen = scorer.get_domain_weights("general")
        assert w_hist[3] > w_gen[3]

    def test_unknown_domain_falls_back_to_general(self, scorer: ConfidenceScorer):
        """Unknown domain → general weights."""
        w = scorer.get_domain_weights("nonexistent_domain_xyz")
        assert w == scorer.get_domain_weights("general")

    def test_custom_domain_weights(self, scorer: ConfidenceScorer):
        """Can set and retrieve custom domain weights."""
        scorer.set_domain_weights("custom", 0.5, 0.2, 0.2, 0.1)
        w = scorer.get_domain_weights("custom")
        assert w == (0.5, 0.2, 0.2, 0.1)

    def test_weights_must_sum_to_one(self, scorer: ConfidenceScorer):
        """Weights that don't sum to ~1.0 raise ValueError."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            scorer.set_domain_weights("bad", 0.5, 0.5, 0.5, 0.5)


# ═══════════════════════════════════════════════════════════════════
# 6. Confidence explanation structure
# ═══════════════════════════════════════════════════════════════════

class TestConfidenceExplanation:
    """Explanation object has correct structure and content."""

    def test_explanation_is_dataclass(self, scorer: ConfidenceScorer):
        """Return is a ConfidenceExplanation dataclass."""
        _, exp = scorer.score()
        assert isinstance(exp, ConfidenceExplanation)

    def test_explanation_to_dict_keys(self, scorer: ConfidenceScorer):
        """to_dict() contains all expected top-level keys."""
        _, exp = scorer.score()
        d = exp.to_dict()
        assert "final_score" in d
        assert "confidence_level" in d
        assert "domain" in d
        assert "breakdown" in d
        assert "weights" in d
        assert "metadata" in d
        assert "notes" in d

    def test_explanation_str_readable(self, scorer: ConfidenceScorer):
        """__str__ produces a human-readable multi-line string."""
        _, exp = scorer.score(source_scores=[0.9, 0.85])
        text = str(exp)
        assert "Confidence:" in text
        assert "Domain:" in text
        assert "Source authority:" in text

    def test_explanation_breakdown_values(self, scorer: ConfidenceScorer):
        """Breakdown dict has source/corroboration/recency/contradiction."""
        _, exp = scorer.score()
        bd = exp.to_dict()["breakdown"]
        assert "source" in bd
        assert "corroboration" in bd
        assert "recency" in bd
        assert "contradiction_penalty" in bd

    def test_notes_populated(self, scorer: ConfidenceScorer):
        """Single source gets a capping note."""
        _, exp = scorer.score(source_scores=[0.5])
        assert any("Single source" in n for n in exp.notes)

    def test_expired_note(self, scorer: ConfidenceScorer):
        """Expired fact gets an expiry note."""
        _, exp = scorer.score(is_expired=True)
        assert any("expired" in n.lower() for n in exp.notes)


# ═══════════════════════════════════════════════════════════════════
# 7. HIGH / MEDIUM / LOW threshold boundaries
# ═══════════════════════════════════════════════════════════════════

class TestConfidenceLevels:
    """Threshold boundaries are correctly enforced."""

    def test_high_threshold_exact(self):
        """Score exactly at HIGH threshold → HIGH."""
        assert ConfidenceLevel.from_score(HIGH_CONFIDENCE_THRESHOLD) == ConfidenceLevel.HIGH

    def test_high_threshold_just_below(self):
        """Score just below HIGH → MEDIUM."""
        assert ConfidenceLevel.from_score(HIGH_CONFIDENCE_THRESHOLD - 0.001) == ConfidenceLevel.MEDIUM

    def test_medium_threshold_exact(self):
        """Score exactly at MEDIUM threshold → MEDIUM."""
        assert ConfidenceLevel.from_score(MEDIUM_CONFIDENCE_THRESHOLD) == ConfidenceLevel.MEDIUM

    def test_medium_threshold_just_below(self):
        """Score just below MEDIUM → LOW."""
        assert ConfidenceLevel.from_score(MEDIUM_CONFIDENCE_THRESHOLD - 0.001) == ConfidenceLevel.LOW

    def test_score_clamped_to_0_1(self, scorer: ConfidenceScorer):
        """Final score is always clamped to [0, 1]."""
        score, _ = scorer.score(source_scores=[0.0], sources_agree=False, is_expired=True)
        assert 0.0 <= score <= 1.0

    def test_score_rounded_to_4_decimals(self, scorer: ConfidenceScorer):
        """Final score is rounded to 4 decimal places."""
        score, _ = scorer.score(source_scores=[0.123456789])
        assert score == round(score, 4)


# ═══════════════════════════════════════════════════════════════════
# 8. Edge cases (no source, expired, empty)
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary and degenerate inputs."""

    def test_no_source_scores_defaults_to_0_5(self, scorer: ConfidenceScorer):
        """Empty source_scores → default [0.5]."""
        _, exp = scorer.score(source_scores=[])
        assert exp.source_count == 1
        assert exp.source_score == pytest.approx(0.5)

    def test_none_source_scores(self, scorer: ConfidenceScorer):
        """None source_scores → default [0.5]."""
        _, exp = scorer.score(source_scores=None)
        assert exp.source_count == 1

    def test_expired_fact_aggressive_decay(self, scorer: ConfidenceScorer):
        """Expired fact → score multiplied by 0.2."""
        score_normal, _ = scorer.score(
            source_scores=[0.9, 0.9], sources_agree=True, is_expired=False
        )
        score_expired, _ = scorer.score(
            source_scores=[0.9, 0.9], sources_agree=True, is_expired=True
        )
        # Expired should be ~20% of normal (same inputs otherwise)
        assert score_expired < score_normal * 0.25

    def test_negative_source_clamped_to_0(self, scorer: ConfidenceScorer):
        """Negative source score clamped to 0."""
        _, exp = scorer.score(source_scores=[-0.5])
        assert exp.source_score == pytest.approx(0.0)

    def test_source_above_1_clamped(self, scorer: ConfidenceScorer):
        """Source score > 1.0 clamped to 1.0."""
        _, exp = scorer.score(source_scores=[1.5])
        assert exp.source_score == pytest.approx(1.0)

    def test_zero_fact_age_is_fresh(self, scorer: ConfidenceScorer):
        """0-day-old fact is completely fresh."""
        _, exp = scorer.score(fact_age_days=0)
        assert exp.recency_score == pytest.approx(1.0)
        assert exp.fact_age_days == 0.0


# ═══════════════════════════════════════════════════════════════════
# 9. Integration with pipeline (score_fact, score_verification)
# ═══════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """score_fact and score_verification convenience methods."""

    def test_score_fact_basic(self, scorer: ConfidenceScorer):
        """score_fact produces a valid score and explanation."""
        score, exp = scorer.score_fact(
            fact_confidence=0.9,
            source_authority_score=0.85,
            corroboration_sources=3,
        )
        assert 0.0 <= score <= 1.0
        assert exp.source_count == 3

    def test_score_fact_note(self, scorer: ConfidenceScorer):
        """score_fact includes base fact confidence in notes."""
        _, exp = scorer.score_fact(fact_confidence=0.75, source_authority_score=0.8)
        assert any("Base fact confidence" in n for n in exp.notes)

    def test_score_verification_combines_similarity(self, scorer: ConfidenceScorer):
        """score_verification blends similarity with fact confidence."""
        score, exp = scorer.score_verification(
            similarity=0.95,
            fact_confidence=0.9,
            source_authority_score=0.85,
            corroboration_sources=2,
        )
        assert 0.0 <= score <= 1.0
        # High similarity + good source → should be HIGH
        assert exp.confidence_level == ConfidenceLevel.HIGH

    def test_score_verification_low_similarity(self, scorer: ConfidenceScorer):
        """Low similarity drags down verification score."""
        score_high_sim, _ = scorer.score_verification(
            similarity=0.95, fact_confidence=0.9, source_authority_score=0.85
        )
        score_low_sim, _ = scorer.score_verification(
            similarity=0.30, fact_confidence=0.9, source_authority_score=0.85
        )
        assert score_low_sim < score_high_sim


# ═══════════════════════════════════════════════════════════════════
# 10. Determinism (same input → same output)
# ═══════════════════════════════════════════════════════════════════

class TestDeterminism:
    """Same inputs always produce identical outputs."""

    def test_score_determinism(self, scorer: ConfidenceScorer):
        """Calling score() twice with identical args → identical result."""
        kwargs = dict(
            source_scores=[0.85, 0.90],
            sources_agree=True,
            fact_age_days=42,
            domain="medical",
            is_expired=False,
        )
        s1, e1 = scorer.score(**kwargs)
        s2, e2 = scorer.score(**kwargs)
        assert s1 == s2
        assert e1.to_dict() == e2.to_dict()

    def test_score_fact_determinism(self, scorer: ConfidenceScorer):
        """score_fact is deterministic."""
        kwargs = dict(
            fact_confidence=0.88,
            source_authority_score=0.75,
            corroboration_sources=3,
            sources_agree=True,
            fact_age_days=100,
            domain="science",
        )
        s1, e1 = scorer.score_fact(**kwargs)
        s2, e2 = scorer.score_fact(**kwargs)
        assert s1 == s2
        assert e1.final_score == e2.final_score

    def test_scorer_state_independence(self):
        """Two separate scorers produce same results with default config."""
        s1 = ConfidenceScorer()
        s2 = ConfidenceScorer()
        kwargs = dict(source_scores=[0.7, 0.8], sources_agree=True, domain="general")
        score1, _ = s1.score(**kwargs)
        score2, _ = s2.score(**kwargs)
        assert score1 == score2


# ═══════════════════════════════════════════════════════════════════
# Bonus: additional coverage
# ═══════════════════════════════════════════════════════════════════

class TestBonusCoverage:

    def test_all_default_domains_have_valid_weights(self, scorer: ConfidenceScorer):
        """Every default domain has weights that sum to 1.0."""
        for domain in DEFAULT_WEIGHTS:
            w = scorer.get_domain_weights(domain)
            assert abs(sum(w) - 1.0) < 0.01, f"{domain} weights sum to {sum(w)}"

    def test_supported_domains_property(self, scorer: ConfidenceScorer):
        """supported_domains returns a non-empty list."""
        domains = scorer.supported_domains
        assert isinstance(domains, list)
        assert "general" in domains

    def test_additional_notes_in_explanation(self, scorer: ConfidenceScorer):
        """Additional notes are included in the explanation."""
        _, exp = scorer.score(additional_notes=["Custom note"])
        assert "Custom note" in exp.notes

    def test_score_verification_note_format(self, scorer: ConfidenceScorer):
        """score_verification includes verification formula in notes."""
        _, exp = scorer.score_verification(similarity=0.9, fact_confidence=0.8)
        assert any("Verification:" in n for n in exp.notes)

    def test_corroboration_disagree_drops_to_0_2(self, scorer: ConfidenceScorer):
        """Multiple disagreeing sources → corroboration = 0.2."""
        _, exp = scorer.score(
            source_scores=[0.8, 0.7, 0.9], sources_agree=False
        )
        assert exp.corroboration_score == pytest.approx(0.2)
