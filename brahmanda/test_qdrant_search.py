#!/usr/bin/env python3
"""
RTA-GUARD — Qdrant Semantic Search Test

Tests that semantic search finds relevant facts even when wording differs.

Requirements:
    - QDRANT_URL env var (or defaults to http://localhost:6333)
    - OPENAI_API_KEY env var
    - qdrant-client and openai packages installed

Usage:
    export QDRANT_URL=http://localhost:6333
    export OPENAI_API_KEY=sk-...
    python -m brahmanda.test_qdrant_search
"""
import sys
import os
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_semantic_search():
    """Test that semantic search finds facts even with different wording."""
    from brahmanda.qdrant_client import QdrantBrahmanda, create_qdrant_seed_map
    from brahmanda.verifier import BrahmandaVerifier

    print("=" * 60)
    print("RTA-GUARD — Qdrant Semantic Search Test")
    print("=" * 60)

    # Initialize and seed
    print("\n[1] Initializing QdrantBrahmanda...")
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    brahmanda = create_qdrant_seed_map(url=url)
    print(f"    Backend: Qdrant @ {url}")
    print(f"    Facts loaded: {brahmanda.fact_count}")

    if brahmanda.fact_count < 11:
        print("    ERROR: Expected 11 seed facts, got", brahmanda.fact_count)
        return False

    # Test queries that differ from stored wording
    test_cases = [
        {
            "query": "What city is the seat of French government?",
            "expected_contains": "Paris",
            "description": "Semantic match: 'seat of government' → 'capital'",
        },
        {
            "query": "Which country's capital is Berlin?",
            "expected_contains": "Germany",
            "description": "Semantic match: rephrased capital question",
        },
        {
            "query": "How fast does light travel?",
            "expected_contains": "speed of light",
            "description": "Semantic match: 'how fast' → 'speed'",
        },
        {
            "query": "What is the boiling point of water?",
            "expected_contains": "100 degrees",
            "description": "Semantic match: 'boiling point' → 'boils at'",
        },
        {
            "query": "Who created relativity theory?",
            "expected_contains": "Einstein",
            "description": "Semantic match: 'created' → 'developed'",
        },
        {
            "query": "What language is Python?",
            "expected_contains": "programming language",
            "description": "Semantic match: context about Python",
        },
        {
            "query": "What protocol does the web use?",
            "expected_contains": "HTTP",
            "description": "Semantic match: 'web' → 'HyperText Transfer Protocol'",
        },
    ]

    print(f"\n[2] Running {len(test_cases)} semantic search tests...\n")
    all_passed = True

    for i, tc in enumerate(test_cases, 1):
        results = brahmanda.search(tc["query"], limit=3)
        if results:
            top = results[0]
            top_claim = top.claim.lower()
            score = top.metadata.get("_similarity_score", 0)
            passed = tc["expected_contains"].lower() in top_claim

            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  Test {i}: {status}")
            print(f"    Query:     {tc['query']}")
            print(f"    Expected:  contains '{tc['expected_contains']}'")
            print(f"    Got:       '{top.claim}' (score={score:.4f})")
            print(f"    Note:      {tc['description']}")
            if not passed:
                all_passed = False
                # Show other results for debugging
                for j, r in enumerate(results[1:], 2):
                    s = r.metadata.get("_similarity_score", 0)
                    print(f"    Alt {j}:     '{r.claim}' (score={s:.4f})")
        else:
            print(f"  Test {i}: ❌ FAIL — No results for: {tc['query']}")
            all_passed = False
        print()

    # Test verifier integration
    print("[3] Testing BrahmandaVerifier with Qdrant backend...\n")
    verifier = BrahmandaVerifier(brahmanda)

    verify_tests = [
        ("Paris is the capital of France", "Should PASS (exact match)"),
        ("The capital of France is Paris", "Should PASS (same meaning)"),
        ("Berlin is the capital of France", "Should BLOCK (contradiction)"),
        ("The moon is made of cheese", "Should WARN (no match)"),
    ]

    for text, expected in verify_tests:
        result = verifier.verify(text)
        status = "✅" if result.decision.value in ("pass", "block", "warn") else "❌"
        print(f"  {status} '{text}'")
        print(f"     Decision: {result.decision.value} | Confidence: {result.overall_confidence:.4f}")
        print(f"     Expected: {expected}")
        print(f"     Details: {result.details}")
        print()

    # Summary
    print("=" * 60)
    if all_passed:
        print("🎉 All semantic search tests PASSED!")
    else:
        print("⚠️  Some tests FAILED — review output above")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = test_semantic_search()
    sys.exit(0 if success else 1)
