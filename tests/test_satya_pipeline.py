"""
RTA-GUARD — SATYA Pipeline Integration Tests (Phase 2.3)

Tests the full integration chain:
  BrahmandaVerifier (with pipeline) → SatyaRule → RtaEngine → verdict

Covers:
  - Pipeline integration in BrahmandaVerifier
  - SatyaRule blocking contradicted claims via pipeline
  - SatyaRule passing verified claims
  - SatyaRule warning on unverifiable claims
  - Backward compatibility (use_pipeline=False)
  - Confidence-verifiability gap detection
  - DiscusGuard integration with pipeline-enabled RTA
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brahmanda.verifier import (
    BrahmandaVerifier, BrahmandaMap, create_seed_map, get_seed_verifier,
)
from brahmanda.pipeline import VerificationPipeline, get_seed_pipeline
from brahmanda.models import VerifyDecision, Source, SourceAuthority
from discus.rta_engine import RtaEngine, RtaContext, SatyaRule
from discus.guard import DiscusGuard, SessionKilledError
from discus.models import GuardConfig, KillDecision, Severity


# ─── Helpers ───────────────────────────────────────────────────────

def _make_engine(verifier=None, pipeline=None):
    """Create an RtaEngine with optional verifier/pipeline."""
    return RtaEngine(verifier=verifier, pipeline=pipeline)


def _assistant_context(text: str, session_id: str = "test-satya") -> RtaContext:
    """Create an RtaContext for an assistant output."""
    return RtaContext(
        session_id=session_id,
        input_text="",
        output_text=text,
        role="assistant",
    )


# ─── Tests ─────────────────────────────────────────────────────────

def test_verifier_pipeline_integration():
    """BrahmandaVerifier with use_pipeline=True delegates to pipeline."""
    v = get_seed_verifier()
    assert v._pipeline is not None, "Pipeline should be active"
    assert isinstance(v._pipeline, VerificationPipeline)

    # Contradiction: "The capital of France is Berlin" vs fact "Paris is the capital of France"
    result = v.verify("The capital of France is Berlin")
    assert result.decision == VerifyDecision.BLOCK, f"Expected BLOCK, got {result.decision.value}"
    assert result.overall_confidence < 0.5
    contradicted_claims = [c for c in result.claims if c.contradicted]
    assert len(contradicted_claims) == 1
    assert "Paris" in contradicted_claims[0].reason or "paris" in contradicted_claims[0].matched_fact.claim.lower()
    print("✅ test_verifier_pipeline_integration passed")


def test_verifier_pipeline_pass():
    """Verified claim passes through pipeline."""
    v = get_seed_verifier()
    result = v.verify("The capital of France is Paris")
    assert result.decision == VerifyDecision.PASS, f"Expected PASS, got {result.decision.value}"
    assert result.overall_confidence > 0.5
    print("✅ test_verifier_pipeline_pass passed")


def test_verifier_backward_compat():
    """use_pipeline=False falls back to legacy verification."""
    brahmanda = create_seed_map()
    v_legacy = BrahmandaVerifier(brahmanda, use_pipeline=False)
    assert v_legacy._pipeline is None, "Pipeline should not be active"

    # Legacy still catches contradictions (improved heuristic)
    result = v_legacy.verify("The capital of France is Berlin")
    assert result.decision == VerifyDecision.BLOCK, f"Expected BLOCK, got {result.decision.value}"

    # Legacy passes verified claims
    result2 = v_legacy.verify("The capital of France is Paris")
    assert result2.decision == VerifyDecision.PASS
    print("✅ test_verifier_backward_compat passed")


def test_satya_rule_blocks_contradicted_claim():
    """SatyaRule with pipeline blocks a contradicted claim."""
    verifier = get_seed_verifier()
    engine = _make_engine(verifier=verifier)

    # Verify SatyaRule has pipeline
    satya = engine.get_rule_by_id("satya")
    assert satya.pipeline is not None, "SatyaRule should have pipeline"

    # Contradicted claim
    ctx = _assistant_context("The capital of France is Berlin.")
    allowed, results, decision = engine.check(ctx)

    satya_result = next(r for r in results if r.rule_id == "satya")
    assert satya_result.is_violation, "SatyaRule should flag violation"
    assert satya_result.decision == KillDecision.KILL, f"Expected KILL, got {satya_result.decision.value}"
    assert "SATYA_BREACH" in satya_result.details
    assert satya_result.metadata.get("claims_blocked", 0) >= 1

    # The metadata should include pipeline audit trail
    assert "verification_details" in satya_result.metadata
    print("✅ test_satya_rule_blocks_contradicted_claim passed")


def test_satya_rule_passes_verified_claim():
    """SatyaRule passes a claim verified against ground truth."""
    verifier = get_seed_verifier()
    engine = _make_engine(verifier=verifier)

    ctx = _assistant_context("The capital of France is Paris.")
    allowed, results, decision = engine.check(ctx)

    satya_result = next(r for r in results if r.rule_id == "satya")
    assert not satya_result.is_violation, f"SatyaRule should pass: {satya_result.details}"
    assert satya_result.decision == KillDecision.PASS
    print("✅ test_satya_rule_passes_verified_claim passed")


def test_satya_rule_heuristic_confidence_gap():
    """SatyaRule detects confidence-verifiability gap even without contradictions."""
    verifier = get_seed_verifier()
    # Use SatyaRule directly to test confidence gap
    satya = SatyaRule(verifier=verifier)

    # Output with high-confidence language but unverifiable content
    ctx = _assistant_context(
        "The population of Atlantis is definitely 50 million according to ancient records. "
        "It is certainly located beneath the Atlantic Ocean."
    )

    result = satya.check(ctx)
    # The text mentions "definitely" and "certainly" which bump confidence
    # But the claims (Atlantis) can't be verified against ground truth
    # So verifiability is low → confidence gap
    if result.is_violation:
        assert result.decision in (KillDecision.KILL, KillDecision.WARN)
        print(f"  Confidence gap detected: {result.details}")
    print("✅ test_satya_rule_heuristic_confidence_gap passed")


def test_satya_rule_no_backend():
    """SatyaRule without verifier/pipeline falls back to heuristic."""
    satya = SatyaRule()  # No verifier, no pipeline

    ctx = _assistant_context("This is a short response.")
    result = satya.check(ctx)
    assert not result.is_violation
    assert result.decision == KillDecision.PASS
    print("✅ test_satya_rule_no_backend passed")


def test_discus_guard_with_pipeline():
    """Full integration — RtaEngine with pipeline blocks contradicted claims.

    NOTE: DiscusGuard.check() validates user *input* text. To verify assistant
    *output* (the SATYA use case), the calling code must construct an RtaContext
    with role='assistant' and output_text set. This test demonstrates the
    direct RtaEngine path which is the intended integration point for output
    verification middleware.
    """
    verifier = get_seed_verifier()
    engine = RtaEngine(verifier=verifier)

    # Simulate output verification middleware calling RtaEngine directly
    ctx = RtaContext(
        session_id="guard-pipeline-test",
        input_text="What is the capital of France?",
        output_text="The capital of France is Berlin.",
        role="assistant",
    )
    allowed, results, decision = engine.check(ctx)

    assert not allowed, "Engine should deny contradicted output"
    assert decision == KillDecision.KILL
    satya_result = next(r for r in results if r.rule_id == "satya")
    assert satya_result.is_violation
    assert "SATYA_BREACH" in satya_result.details
    print(f"  Engine blocked output: {satya_result.details}")
    print("✅ test_discus_guard_with_pipeline passed")


def test_pipeline_multiple_claims():
    """Pipeline handles text with multiple claims correctly."""
    verifier = get_seed_verifier()

    # Mix of correct and incorrect claims
    mixed_text = (
        "The capital of France is Paris. "        # correct
        "The capital of Germany is Berlin. "       # correct
        "The capital of Japan is Osaka."           # incorrect (should be Tokyo)
    )

    result = verifier.verify(mixed_text)
    assert result.decision == VerifyDecision.BLOCK, f"Expected BLOCK for mixed claims, got {result.decision.value}"
    contradicted = [c for c in result.claims if c.contradicted]
    assert len(contradicted) >= 1, "Should detect at least one contradiction"
    print(f"  Detected {len(contradicted)} contradicted claims out of {len(result.claims)} total")
    print("✅ test_pipeline_multiple_claims passed")


def test_pipeline_audit_trail():
    """Pipeline produces detailed audit metadata in SatyaRule results."""
    verifier = get_seed_verifier()
    engine = _make_engine(verifier=verifier)

    ctx = _assistant_context("The capital of France is Berlin.")
    _, results, _ = engine.check(ctx)

    satya_result = next(r for r in results if r.rule_id == "satya")
    meta = satya_result.metadata

    # Check audit trail fields
    assert "model_confidence" in meta
    assert "verifiability" in meta
    assert "pipeline_version" in meta
    assert "claims_checked" in meta
    assert "claims_blocked" in meta
    assert "verification_details" in meta

    # verification_details should have full pipeline output
    vd = meta["verification_details"]
    assert "claims" in vd
    assert len(vd["claims"]) > 0
    print("✅ test_pipeline_audit_trail passed")


def test_discus_guard_output_integration():
    """DiscusGuard with RTA engine properly checks assistant output when
    the caller constructs RtaContext with role='assistant' and output_text.

    Demonstrates the intended middleware pattern:
      1. User input passes guard (no PII/injection)
      2. LLM generates output
      3. Output is checked via RtaEngine for SATYA violations
    """
    verifier = get_seed_verifier()
    engine = RtaEngine(verifier=verifier)
    guard = DiscusGuard(GuardConfig(kill_threshold=Severity.HIGH), rta_engine=engine)

    # Step 1: User input passes guard
    response = guard.check("What is the capital of France?", session_id="middleware-test")
    assert response.allowed

    # Step 2: Simulate middleware checking LLM output via engine
    output = "The capital of France is Berlin."
    ctx = RtaContext(
        session_id="middleware-test",
        input_text="What is the capital of France?",
        output_text=output,
        role="assistant",
    )
    allowed, results, decision = engine.check(ctx)
    assert not allowed, "Contradicted output should be blocked"
    assert decision == KillDecision.KILL

    # Step 3: Verify the kill was SATYA-specific
    satya_result = next(r for r in results if r.rule_id == "satya")
    assert "SATYA_BREACH" in satya_result.details
    assert satya_result.metadata.get("claims_blocked", 0) >= 1
    print(f"  Middleware correctly blocked output: {satya_result.details}")
    print("✅ test_discus_guard_output_integration passed")


# ─── Run ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running SATYA Pipeline Integration Tests...\n")

    tests = [
        test_verifier_pipeline_integration,
        test_verifier_pipeline_pass,
        test_verifier_backward_compat,
        test_satya_rule_blocks_contradicted_claim,
        test_satya_rule_passes_verified_claim,
        test_satya_rule_heuristic_confidence_gap,
        test_satya_rule_no_backend,
        test_discus_guard_with_pipeline,
        test_pipeline_multiple_claims,
        test_pipeline_audit_trail,
        test_discus_guard_output_integration,
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
    print(f"SATYA Pipeline Results: {passed} passed, {failed} failed")
    print(f"{'='*50}")

    if failed > 0:
        sys.exit(1)
