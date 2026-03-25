"""
Test suite for brahmanda Mutation Tracking System (Phase 2.6).

Methodology
-----------
The mutation tracking system logs every change to facts in the Brahmanda Map:
  - CREATE: a new fact is added
  - UPDATE: an existing fact is modified (with structured diff)
  - RETRACT: a fact is retracted
  - EXPIRE: a fact passes its expiration date

Each mutation is recorded with a SHA-256 hash chain for tamper detection.
This is critical for EU AI Act compliance (audit trail traceability).

All tests use in-memory objects — no network calls.

Run with: ``python3 -m pytest brahmanda/test_mutation.py -v``
"""

import sys
import os
import time
import json
import hashlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Lazy import helper
# ---------------------------------------------------------------------------

def _import_mutation():
    """Import mutation symbols, skipping if unavailable."""
    try:
        from brahmanda.mutation import (
            MutationTracker,
            Mutation,
            compute_diff,
        )
        return MutationTracker, Mutation, compute_diff
    except ImportError as exc:
        pytest.skip(f"Mutation module not yet implemented: {exc}")


def _import_tracker():
    MutationTracker, *_ = _import_mutation()
    return MutationTracker


def _import_mutation_cls():
    _, Mutation, _ = _import_mutation()
    return Mutation


def _import_diff():
    _, _, compute_diff = _import_mutation()
    return compute_diff


def _import_models():
    """Import models needed for testing."""
    try:
        from brahmanda.models import (
            GroundTruthFact, Source, SourceAuthority, FactType,
        )
        from brahmanda.attribution import AttributionManager
        from brahmanda.verifier import BrahmandaMap
        return GroundTruthFact, Source, SourceAuthority, FactType, AttributionManager, BrahmandaMap
    except ImportError as exc:
        pytest.skip(f"Models not available: {exc}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tracker():
    """Create a fresh MutationTracker."""
    MutationTracker = _import_tracker()
    return MutationTracker()


def _make_fact(claim="Paris is the capital of France", domain="general",
               confidence=0.95, source_name="Test Source"):
    """Create a GroundTruthFact with a source."""
    GroundTruthFact, Source, SourceAuthority, FactType, AttributionManager, _ = _import_models()
    attr = AttributionManager()
    src = attr.register_source(name=source_name, authority=SourceAuthority.PRIMARY,
                               authority_score=0.95)
    fact = GroundTruthFact(
        claim=claim,
        domain=domain,
        confidence=confidence,
        source=src,
        fact_type=FactType.ENTITY,
    )
    return fact, attr


def _make_map():
    """Create a BrahmandaMap."""
    _, _, _, _, _, BrahmandaMap = _import_models()
    return BrahmandaMap()


# ===========================================================================
# 1. Mutation Model
# ===========================================================================

class TestMutationModel:
    """Mutation dataclass basics."""

    def test_mutation_has_required_fields(self):
        Mutation = _import_mutation_cls()
        m = Mutation(
            fact_id="f-001",
            mutation_type="create",
            reason="test",
        )
        assert m.fact_id == "f-001"
        assert m.mutation_type == "create"
        assert m.reason == "test"
        assert m.timestamp is not None

    def test_mutation_has_unique_id(self):
        Mutation = _import_mutation_cls()
        m1 = Mutation(fact_id="f-001", mutation_type="create")
        m2 = Mutation(fact_id="f-002", mutation_type="create")
        assert m1.id != m2.id

    def test_mutation_has_hash_chain(self):
        Mutation = _import_mutation_cls()
        m = Mutation(fact_id="f-001", mutation_type="create")
        assert m.entry_hash is not None
        assert len(m.entry_hash) == 64  # SHA-256 hex

    def test_mutation_hash_is_deterministic(self):
        Mutation = _import_mutation_cls()
        m1 = Mutation(fact_id="f-001", mutation_type="create", reason="test")
        # Compute hash again
        computed = m1._compute_hash()
        assert computed == m1.entry_hash

    def test_mutation_verify_integrity(self):
        Mutation = _import_mutation_cls()
        m = Mutation(fact_id="f-001", mutation_type="create")
        assert m.verify_integrity() is True

    def test_mutation_to_dict(self):
        Mutation = _import_mutation_cls()
        m = Mutation(
            fact_id="f-001",
            mutation_type="update",
            old_value={"x": 1},
            new_value={"x": 2},
            reason="correction",
        )
        d = m.to_dict()
        assert d["fact_id"] == "f-001"
        assert d["mutation_type"] == "update"
        assert d["old_value"] == {"x": 1}
        assert d["new_value"] == {"x": 2}
        assert d["reason"] == "correction"
        assert "entry_hash" in d


# ===========================================================================
# 2. Compute Diff
# ===========================================================================

class TestComputeDiff:
    """Structured diff computation."""

    def test_no_changes(self):
        compute_diff = _import_diff()
        old = {"a": 1, "b": "hello"}
        new = {"a": 1, "b": "hello"}
        diff = compute_diff(old, new)
        assert diff["changed"] == {}
        assert diff["added"] == {}
        assert diff["removed"] == {}

    def test_field_changed(self):
        compute_diff = _import_diff()
        old = {"a": 1, "b": "hello"}
        new = {"a": 2, "b": "hello"}
        diff = compute_diff(old, new)
        assert "a" in diff["changed"]
        assert diff["changed"]["a"]["old"] == 1
        assert diff["changed"]["a"]["new"] == 2

    def test_field_added(self):
        compute_diff = _import_diff()
        old = {"a": 1}
        new = {"a": 1, "b": "new"}
        diff = compute_diff(old, new)
        assert "b" in diff["added"]
        assert diff["added"]["b"] == "new"

    def test_field_removed(self):
        compute_diff = _import_diff()
        old = {"a": 1, "b": "bye"}
        new = {"a": 1}
        diff = compute_diff(old, new)
        assert "b" in diff["removed"]
        assert diff["removed"]["b"] == "bye"

    def test_mixed_changes(self):
        compute_diff = _import_diff()
        old = {"a": 1, "b": "old", "c": 3}
        new = {"a": 1, "b": "new", "d": 4}
        diff = compute_diff(old, new)
        assert "b" in diff["changed"]
        assert "d" in diff["added"]
        assert "c" in diff["removed"]

    def test_nested_dict_changes(self):
        compute_diff = _import_diff()
        old = {"source": {"name": "WHO", "score": 0.9}}
        new = {"source": {"name": "WHO", "score": 0.8}}
        diff = compute_diff(old, new)
        assert "source" in diff["changed"]

    def test_empty_dicts(self):
        compute_diff = _import_diff()
        diff = compute_diff({}, {})
        assert diff["changed"] == {}
        assert diff["added"] == {}
        assert diff["removed"] == {}


# ===========================================================================
# 3. Creation Tracking
# ===========================================================================

class TestCreationTracking:
    """Track fact creation via MutationTracker."""

    def test_track_creation_returns_mutation(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        m = tracker.track_creation(fact, source_name="Test Source", reason="Seed data")
        assert m is not None
        assert m.mutation_type == "create"
        assert m.fact_id == fact.id

    def test_creation_has_new_value(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        m = tracker.track_creation(fact, source_name="Test Source")
        assert m.new_value is not None
        assert m.new_value["claim"] == fact.claim
        assert m.old_value is None

    def test_creation_reason_includes_source(self):
        tracker = _make_tracker()
        fact, _ = _make_fact(source_name="WHO")
        m = tracker.track_creation(fact, source_name="WHO", reason="Seed")
        assert "WHO" in m.reason

    def test_creation_increments_count(self):
        tracker = _make_tracker()
        assert tracker.mutation_count == 0
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        assert tracker.mutation_count == 1

    def test_creation_tracks_fact(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        assert tracker.tracked_fact_count == 1


# ===========================================================================
# 4. Update Tracking with Diff
# ===========================================================================

class TestUpdateTracking:
    """Track fact updates with old/new diff."""

    def test_track_update_returns_mutation(self):
        tracker = _make_tracker()
        old = {"claim": "Paris is the capital of France", "confidence": 0.9}
        new = {"claim": "Paris is the capital of France", "confidence": 0.95}
        m = tracker.track_update("f-001", old, new, reason="Confidence correction")
        assert m is not None
        assert m.mutation_type == "update"
        assert m.fact_id == "f-001"

    def test_update_has_diff(self):
        tracker = _make_tracker()
        old = {"claim": "Paris is the capital of France", "confidence": 0.9}
        new = {"claim": "Paris is the capital of France", "confidence": 0.95}
        m = tracker.track_update("f-001", old, new)
        assert m.diff is not None
        assert "confidence" in m.diff["changed"]
        assert m.diff["changed"]["confidence"]["old"] == 0.9
        assert m.diff["changed"]["confidence"]["new"] == 0.95

    def test_update_stores_old_and_new(self):
        tracker = _make_tracker()
        old = {"claim": "Old claim", "confidence": 0.8}
        new = {"claim": "New claim", "confidence": 0.95}
        m = tracker.track_update("f-001", old, new, reason="Claim corrected")
        assert m.old_value == old
        assert m.new_value == new

    def test_update_with_added_fields(self):
        tracker = _make_tracker()
        old = {"claim": "test", "version": 1}
        new = {"claim": "test", "version": 2, "tags": ["geo"]}
        m = tracker.track_update("f-001", old, new)
        assert "tags" in m.diff["added"]
        assert "version" in m.diff["changed"]

    def test_update_reason_preserved(self):
        tracker = _make_tracker()
        old = {"x": 1}
        new = {"x": 2}
        m = tracker.track_update("f-001", old, new, reason="Corrected typo")
        assert m.reason == "Corrected typo"


# ===========================================================================
# 5. Retraction Tracking
# ===========================================================================

class TestRetractionTracking:
    """Track fact retractions."""

    def test_track_retraction_returns_mutation(self):
        tracker = _make_tracker()
        m = tracker.track_retraction("f-001", reason="Fact debunked")
        assert m is not None
        assert m.mutation_type == "retract"
        assert m.fact_id == "f-001"

    def test_retraction_has_reason(self):
        tracker = _make_tracker()
        m = tracker.track_retraction("f-001", reason="Source retracted the claim")
        assert m.reason == "Source retracted the claim"

    def test_retraction_with_snapshot(self):
        tracker = _make_tracker()
        snapshot = {"claim": "test", "confidence": 0.9, "retracted": False}
        m = tracker.track_retraction("f-001", reason="Debunked", fact_snapshot=snapshot)
        assert m.old_value == snapshot
        assert m.new_value["retracted"] is True
        assert m.new_value["confidence"] == 0.0

    def test_retraction_default_actor(self):
        tracker = _make_tracker()
        m = tracker.track_retraction("f-001", reason="test")
        assert m.actor == "system"

    def test_retraction_custom_actor(self):
        tracker = _make_tracker()
        m = tracker.track_retraction("f-001", reason="test", actor="admin@rta")
        assert m.actor == "admin@rta"


# ===========================================================================
# 6. Expiration Tracking
# ===========================================================================

class TestExpirationTracking:
    """Track fact auto-expiration."""

    def test_track_expiration_returns_mutation(self):
        tracker = _make_tracker()
        m = tracker.track_expiration("f-001")
        assert m is not None
        assert m.mutation_type == "expire"
        assert m.fact_id == "f-001"

    def test_expiration_reason_is_automatic(self):
        tracker = _make_tracker()
        m = tracker.track_expiration("f-001")
        assert "expiration" in m.reason.lower()

    def test_expiration_with_snapshot(self):
        tracker = _make_tracker()
        snapshot = {"claim": "test", "expires_at": "2020-01-01", "expired": False}
        m = tracker.track_expiration("f-001", fact_snapshot=snapshot)
        assert m.old_value == snapshot
        assert m.new_value["expired"] is True

    def test_expiration_marks_new_state(self):
        tracker = _make_tracker()
        m = tracker.track_expiration("f-001")
        assert m.new_value["expired"] is True
        assert "expiration_logged_at" in m.new_value


# ===========================================================================
# 7. History Retrieval
# ===========================================================================

class TestHistoryRetrieval:
    """Get full mutation history for a fact."""

    def test_history_returns_all_mutations(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2}, reason="First update")
        tracker.track_update("f-001", {"x": 2}, {"x": 3}, reason="Second update")
        history = tracker.get_history("f-001")
        assert len(history) == 2

    def test_history_is_chronological(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2}, reason="First")
        time.sleep(0.01)  # Ensure different timestamps
        tracker.track_update("f-001", {"x": 2}, {"x": 3}, reason="Second")
        history = tracker.get_history("f-001")
        assert history[0].reason == "First"
        assert history[1].reason == "Second"

    def test_history_empty_for_unknown_fact(self):
        tracker = _make_tracker()
        history = tracker.get_history("nonexistent")
        assert history == []

    def test_history_includes_all_types(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        tracker.track_update(fact.id, {"x": 1}, {"x": 2})
        tracker.track_retraction(fact.id, reason="test")
        history = tracker.get_history(fact.id)
        types = [m.mutation_type for m in history]
        assert "create" in types
        assert "update" in types
        assert "retract" in types


# ===========================================================================
# 8. Audit Trail Filtering
# ===========================================================================

class TestAuditTrailFiltering:
    """Filtered audit trail queries."""

    def test_filter_by_fact_id(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-002", {"x": 1}, {"x": 2})
        results = tracker.get_audit_trail(fact_id="f-001")
        assert all(m.fact_id == "f-001" for m in results)

    def test_filter_by_mutation_type(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        tracker.track_update(fact.id, {"x": 1}, {"x": 2})
        results = tracker.get_audit_trail(mutation_type="create")
        assert len(results) == 1
        assert results[0].mutation_type == "create"

    def test_filter_by_actor(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2}, actor="system")
        tracker.track_update("f-002", {"x": 1}, {"x": 2}, actor="admin")
        results = tracker.get_audit_trail(actor="admin")
        assert len(results) == 1
        assert results[0].actor == "admin"

    def test_filter_by_date_range(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        # Use broad date range to include our mutation
        results = tracker.get_audit_trail(
            from_date="2020-01-01T00:00:00+00:00",
            to_date="2099-12-31T23:59:59+00:00",
        )
        assert len(results) >= 1

    def test_audit_trail_newest_first(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2}, reason="First")
        time.sleep(0.01)
        tracker.track_update("f-001", {"x": 2}, {"x": 3}, reason="Second")
        results = tracker.get_audit_trail(fact_id="f-001")
        # Newest first
        assert results[0].reason == "Second"
        assert results[1].reason == "First"

    def test_audit_trail_limit(self):
        tracker = _make_tracker()
        for i in range(10):
            tracker.track_update(f"f-{i}", {"x": i}, {"x": i + 1})
        results = tracker.get_audit_trail(limit=3)
        assert len(results) == 3

    def test_combined_filters(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2}, actor="system")
        tracker.track_update("f-001", {"x": 2}, {"x": 3}, actor="admin")
        tracker.track_update("f-002", {"x": 1}, {"x": 2}, actor="admin")
        results = tracker.get_audit_trail(fact_id="f-001", actor="admin")
        assert len(results) == 1


# ===========================================================================
# 9. Hash Chain Integrity Verification
# ===========================================================================

class TestHashChainIntegrity:
    """Verify hash chain integrity on demand."""

    def test_empty_chain_is_valid(self):
        tracker = _make_tracker()
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is True
        assert error is None
        assert issues == []

    def test_valid_chain_passes(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        tracker.track_update(fact.id, {"x": 1}, {"x": 2})
        tracker.track_retraction(fact.id, reason="test")
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is True
        assert issues == []

    def test_chain_links_are_correct(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-001", {"x": 2}, {"x": 3})
        # Second mutation's previous_hash should be first mutation's entry_hash
        assert tracker._mutations[1].previous_hash == tracker._mutations[0].entry_hash

    def test_each_entry_has_correct_hash(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        entry = tracker._mutations[0]
        assert entry.verify_integrity()

    def test_tamper_report_structure(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        report = tracker.get_tamper_report()
        assert "chain_valid" in report
        assert "total_mutations" in report
        assert "issues" in report
        assert "mutation_types" in report
        assert report["chain_valid"] is True
        assert report["total_mutations"] == 1

    def test_stats(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        tracker.track_update(fact.id, {"x": 1}, {"x": 2})
        stats = tracker.get_stats()
        assert stats["total_mutations"] == 2
        assert stats["total_facts_tracked"] == 1
        assert stats["chain_intact"] is True
        assert stats["mutation_types"]["create"] == 1
        assert stats["mutation_types"]["update"] == 1


# ===========================================================================
# 10. Tamper Detection
# ===========================================================================

class TestTamperDetection:
    """Detect tampering in the mutation chain."""

    def test_hash_mismatch_detected(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        # Tamper with the mutation
        tracker._mutations[0].reason = "TAMPERED"
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is False
        assert len(issues) == 1
        assert issues[0]["type"] == "hash_mismatch"

    def test_chain_break_detected(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-001", {"x": 2}, {"x": 3})
        # Break the chain by modifying previous_hash
        tracker._mutations[1].previous_hash = "fake_hash_value"
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is False
        assert any(i["type"] == "chain_break" for i in issues)

    def test_tampered_entry_fails_self_verification(self):
        Mutation = _import_mutation_cls()
        m = Mutation(fact_id="f-001", mutation_type="create")
        original_hash = m.entry_hash
        m.reason = "changed after creation"
        assert m.verify_integrity() is False

    def test_tamper_report_shows_issues(self):
        tracker = _make_tracker()
        fact, _ = _make_fact()
        tracker.track_creation(fact)
        tracker.track_update(fact.id, {"x": 1}, {"x": 2})
        # Tamper
        tracker._mutations[0].reason = "TAMPERED"
        report = tracker.get_tamper_report()
        assert report["chain_valid"] is False
        assert report["issues_found"] >= 1
        assert any("hash_mismatch" in i["type"] for i in report["issues"])

    def test_multiple_tamper_types_detected(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-001", {"x": 2}, {"x": 3})
        tracker.track_update("f-001", {"x": 3}, {"x": 4})
        # Tamper first entry hash AND break chain at third
        tracker._mutations[0].reason = "TAMPERED"
        tracker._mutations[2].previous_hash = "bad_hash"
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is False
        assert len(issues) >= 2


# ===========================================================================
# 11. BrahmandaMap Integration
# ===========================================================================

class TestBrahmandaMapIntegration:
    """BrahmandaMap operations automatically track mutations."""

    def test_add_fact_creates_mutation(self):
        bm = _make_map()
        bm.add_fact(claim="Paris is the capital of France", domain="general")
        assert bm.mutation_tracker.mutation_count >= 1
        creates = bm.mutation_tracker.get_audit_trail(mutation_type="create")
        assert len(creates) >= 1

    def test_update_fact_creates_update_mutation(self):
        bm = _make_map()
        fact = bm.add_fact(claim="Paris is the capital", domain="general")
        bm.update_fact(fact.id, claim="Paris is the capital of France")
        updates = bm.mutation_tracker.get_audit_trail(mutation_type="update")
        assert len(updates) >= 1
        update = updates[0]
        assert update.diff is not None

    def test_retract_fact_creates_retract_mutation(self):
        bm = _make_map()
        fact = bm.add_fact(claim="Paris is the capital", domain="general")
        bm.retract_fact(fact.id, reason="Debunked")
        retractions = bm.mutation_tracker.get_audit_trail(mutation_type="retract")
        assert len(retractions) >= 1
        assert retractions[0].reason == "Debunked"

    def test_update_tracks_old_and_new_values(self):
        bm = _make_map()
        fact = bm.add_fact(claim="Paris is the capital", confidence=0.9)
        bm.update_fact(fact.id, confidence=0.95)
        updates = bm.mutation_tracker.get_audit_trail(mutation_type="update")
        assert len(updates) >= 1
        update = updates[0]
        assert update.old_value is not None
        assert update.new_value is not None

    def test_history_across_operations(self):
        bm = _make_map()
        fact = bm.add_fact(claim="Test claim", domain="general")
        bm.update_fact(fact.id, confidence=0.99)
        bm.retract_fact(fact.id, reason="No longer valid")
        history = bm.mutation_tracker.get_history(fact.id)
        types = [m.mutation_type for m in history]
        assert "create" in types
        assert "update" in types
        assert "retract" in types

    def test_chain_integrity_after_operations(self):
        bm = _make_map()
        fact = bm.add_fact(claim="Test", domain="general")
        bm.update_fact(fact.id, confidence=0.99)
        bm.retract_fact(fact.id, reason="test")
        is_valid, error, issues = bm.mutation_tracker.verify_integrity()
        assert is_valid is True
        assert issues == []


# ===========================================================================
# 12. Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Boundary conditions for mutation tracking."""

    def test_empty_diff_no_changes(self):
        compute_diff = _import_diff()
        diff = compute_diff({"a": 1}, {"a": 1})
        assert not diff["changed"]
        assert not diff["added"]
        assert not diff["removed"]

    def test_update_with_empty_reason(self):
        tracker = _make_tracker()
        m = tracker.track_update("f-001", {"x": 1}, {"x": 2}, reason="")
        assert m.reason == ""

    def test_multiple_facts_tracked(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-002", {"x": 1}, {"x": 2})
        tracker.track_update("f-003", {"x": 1}, {"x": 2})
        assert tracker.tracked_fact_count == 3
        assert tracker.mutation_count == 3

    def test_history_for_nonexistent_fact(self):
        tracker = _make_tracker()
        history = tracker.get_history("does_not_exist")
        assert history == []

    def test_audit_trail_no_filters(self):
        tracker = _make_tracker()
        tracker.track_update("f-001", {"x": 1}, {"x": 2})
        tracker.track_update("f-002", {"x": 1}, {"x": 2})
        results = tracker.get_audit_trail()
        assert len(results) == 2

    def test_hash_chain_across_many_mutations(self):
        """Hash chain should be valid after 100 mutations."""
        tracker = _make_tracker()
        for i in range(100):
            tracker.track_update(f"f-{i % 10}", {"x": i}, {"x": i + 1})
        is_valid, error, issues = tracker.verify_integrity()
        assert is_valid is True

    def test_mutation_serialisation(self):
        """Mutations should be JSON-serialisable."""
        tracker = _make_tracker()
        fact, _ = _make_fact()
        m = tracker.track_creation(fact)
        d = m.to_dict()
        j = json.dumps(d)
        parsed = json.loads(j)
        assert parsed["mutation_type"] == "create"
