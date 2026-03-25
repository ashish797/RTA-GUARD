"""
RTA-GUARD — Truth Verification Pipeline Tests (Phase 2.3)

Test cases:
1. Correct fact: Paris is capital of France → PASS
2. Incorrect fact: Berlin is capital of France → BLOCK (contradiction)
3. Partially correct: Paris is large city in France → PASS (no contradiction)
4. Unverifiable: Mars population is 5 billion → WARN
5. Multiple facts in one output: each verified independently
6. Enhanced contradiction detection
7. Domain-aware verification
8. Confidence-weighted decisions
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brahmanda.models import VerifyDecision
from brahmanda.verifier import BrahmandaMap, BrahmandaVerifier, get_seed_verifier, create_seed_map
from brahmanda.extractor import extract_claims
from brahmanda.pipeline import VerificationPipeline, PipelineResult, get_seed_pipeline


def get_test_pipeline():
    """Create a pipeline with seed facts for testing."""
    return get_seed_pipeline()


# ═══════════════════════════════════════════════════════════════════
# Test 1: Correct fact → PASS
# ═══════════════════════════════════════════════════════════════════
def test_correct_fact_pass():
    """Paris is capital of France → should PASS."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("Paris is the capital of France")

    assert result.overall_decision == VerifyDecision.PASS, \
        f"Expected PASS, got {result.overall_decision.value}. Details: {result.details}"
    assert result.claim_count >= 1, "Should extract at least 1 claim"
    assert result.passed_count >= 1, "At least 1 claim should pass"

    best = result.claims[0].best_match
    assert best is not None, "Should find a matching fact"
    assert best.similarity >= 0.5, f"Similarity too low: {best.similarity}"
    print(f"✅ test_correct_fact_pass — sim={best.similarity}, conf={result.overall_confidence}")


# ═══════════════════════════════════════════════════════════════════
# Test 2: Incorrect fact → BLOCK (contradiction)
# ═══════════════════════════════════════════════════════════════════
def test_incorrect_fact_block():
    """Berlin is capital of France → should BLOCK (Paris is capital of France is in store)."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("Berlin is the capital of France")

    assert result.overall_decision == VerifyDecision.BLOCK, \
        f"Expected BLOCK, got {result.overall_decision.value}. Details: {result.details}"
    assert result.blocked_count >= 1, "At least 1 claim should be blocked"
    blocked_claims = [c for c in result.claims if c.contradicted]
    assert len(blocked_claims) >= 1, "Should have at least 1 contradicted claim"
    print(f"✅ test_incorrect_fact_block — {blocked_claims[0].reason}")


# ═══════════════════════════════════════════════════════════════════
# Test 3: Partially correct → PASS (no contradiction)
# ═══════════════════════════════════════════════════════════════════
def test_partially_correct_pass():
    """Paris is large city in France → PASS (no contradiction with known facts)."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("Paris is a large city in France")

    # Should not be BLOCK — no contradiction with "Paris is the capital of France"
    assert result.overall_decision != VerifyDecision.BLOCK, \
        f"Should not BLOCK, got {result.overall_decision.value}. Details: {result.details}"
    # It may PASS or WARN depending on match quality — both are acceptable
    print(f"✅ test_partially_correct_pass — decision={result.overall_decision.value}, details={result.details}")


# ═══════════════════════════════════════════════════════════════════
# Test 4: Unverifiable → WARN
# ═══════════════════════════════════════════════════════════════════
def test_unverifiable_warn():
    """Mars population is 5 billion → WARN (no matching facts)."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("The population of Mars is 5 billion")

    assert result.overall_decision == VerifyDecision.WARN, \
        f"Expected WARN, got {result.overall_decision.value}. Details: {result.details}"
    assert result.warned_count >= 1, "At least 1 claim should be warned"
    print(f"✅ test_unverifiable_warn — {result.details}")


# ═══════════════════════════════════════════════════════════════════
# Test 5: Multiple facts in one output
# ═══════════════════════════════════════════════════════════════════
def test_multiple_claims():
    """Multiple verifiable claims, each verified independently."""
    pipeline = get_test_pipeline()
    text = "Paris is the capital of France. Berlin is the capital of Germany. The Earth orbits the Sun."
    result = pipeline.verify(text)

    assert result.claim_count >= 2, f"Should extract multiple claims, got {result.claim_count}"
    # All 3 claims should PASS since they're all in the seed facts
    assert result.passed_count >= 2, f"Most claims should pass, got {result.passed_count}"
    assert result.overall_decision == VerifyDecision.PASS, \
        f"Expected PASS, got {result.overall_decision.value}"
    print(f"✅ test_multiple_claims — {result.claim_count} claims, {result.passed_count} passed")


# ═══════════════════════════════════════════════════════════════════
# Test 6: Enhanced contradiction detection — negation
# ═══════════════════════════════════════════════════════════════════
def test_negation_contradiction():
    """'Paris is not the capital of France' contradicts known fact."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("Paris is not the capital of France")

    # The negation should be detected as contradiction
    contradicted = [c for c in result.claims if c.contradicted]
    assert len(contradicted) >= 1, \
        f"Expected contradiction from negation, got decision={result.overall_decision.value}"
    print(f"✅ test_negation_contradiction — {contradicted[0].reason}")


# ═══════════════════════════════════════════════════════════════════
# Test 7: Domain-aware verification
# ═══════════════════════════════════════════════════════════════════
def test_domain_aware():
    """Science domain fact verified correctly."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("The Earth orbits the Sun", domain="science")

    assert result.overall_decision == VerifyDecision.PASS, \
        f"Expected PASS for science fact, got {result.overall_decision.value}"
    print(f"✅ test_domain_aware — science domain verified")


# ═══════════════════════════════════════════════════════════════════
# Test 8: Pipeline with custom BrahmandaMap
# ═══════════════════════════════════════════════════════════════════
def test_custom_map():
    """Pipeline with a custom fact store."""
    from brahmanda.pipeline import create_pipeline
    from brahmanda.verifier import BrahmandaMap

    bm = BrahmandaMap()
    bm.add_fact("The Eiffel Tower is in Paris", domain="geography", confidence=0.99)
    bm.add_fact("Tokyo is the capital of Japan", domain="general", confidence=0.98)

    pipeline = create_pipeline(bm)

    result1 = pipeline.verify("The Eiffel Tower is in Paris")
    assert result1.overall_decision == VerifyDecision.PASS, \
        f"Expected PASS, got {result1.overall_decision.value}"

    result2 = pipeline.verify("The Eiffel Tower is in London")
    assert result2.overall_decision == VerifyDecision.BLOCK, \
        f"Expected BLOCK, got {result2.overall_decision.value}"

    print(f"✅ test_custom_map — custom facts work correctly")


# ═══════════════════════════════════════════════════════════════════
# Test 9: Empty text handling
# ═══════════════════════════════════════════════════════════════════
def test_empty_text():
    """Empty text → WARN with no claims."""
    pipeline = get_test_pipeline()
    result = pipeline.verify("")

    assert result.overall_decision == VerifyDecision.WARN
    assert result.claim_count == 0
    print(f"✅ test_empty_text — handled gracefully")


# ═══════════════════════════════════════════════════════════════════
# Test 10: PipelineResult backward compat
# ═══════════════════════════════════════════════════════════════════
def test_result_compat():
    """PipelineResult.verified property works for backward compat."""
    pipeline = get_test_pipeline()

    result_pass = pipeline.verify("Paris is the capital of France")
    assert result_pass.verified is True, "PASS should have verified=True"

    result_block = pipeline.verify("Berlin is the capital of France")
    assert result_block.verified is False, "BLOCK should have verified=False"

    print(f"✅ test_result_compat — backward compat verified")


# ═══════════════════════════════════════════════════════════════════
# Test 11: Enhanced verifier backward compat
# ═══════════════════════════════════════════════════════════════════
def test_verifier_backward_compat():
    """BrahmandaVerifier.verify() still works as before."""
    verifier = get_seed_verifier()

    result1 = verifier.verify("Paris is the capital of France")
    assert result1.decision == VerifyDecision.PASS, f"Expected PASS, got {result1.decision.value}"

    result2 = verifier.verify("Berlin is the capital of France")
    assert result2.decision == VerifyDecision.BLOCK, f"Expected BLOCK, got {result2.decision.value}"

    print(f"✅ test_verifier_backward_compat — legacy verify() still works")


# ═══════════════════════════════════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Running Truth Verification Pipeline tests...\n")

    tests = [
        test_correct_fact_pass,
        test_incorrect_fact_block,
        test_partially_correct_pass,
        test_unverifiable_warn,
        test_multiple_claims,
        test_negation_contradiction,
        test_domain_aware,
        test_custom_map,
        test_empty_text,
        test_result_compat,
        test_verifier_backward_compat,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Pipeline Tests: {passed} passed, {failed} failed")
    print(f"{'='*50}")

    if failed > 0:
        sys.exit(1)
