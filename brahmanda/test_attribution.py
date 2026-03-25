"""
Test suite for Phase 2.4 — Source Attribution System.

Tests:
  1. Source registration & hierarchy
  2. Source confidence scoring (4 tiers)
  3. Fact provenance tracking & chain of trust
  4. Audit trail (append-only, hash chain, tamper detection)
  5. Fact expiration & confidence decay
  6. Integration: source confidence → verification confidence
  7. BrahmandaMap requires source for every fact

Run with: ``python3 -m pytest brahmanda/test_attribution.py -v``
"""
import sys
import os
import time
import pytest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brahmanda.models import (
    Source, SourceAuthority, GroundTruthFact, FactType,
    FactProvenance, AuditEntry, AuditAction,
    confidence_for_authority, SOURCE_CONFIDENCE_RANGES,
)
from brahmanda.attribution import (
    SourceRegistry, FactProvenanceTracker, AuditTrail, AttributionManager,
)
from brahmanda.verifier import BrahmandaMap, BrahmandaVerifier


# ═══════════════════════════════════════════════════════════════════
# 1. Source Registration & Hierarchy
# ═══════════════════════════════════════════════════════════════════


class TestSourceRegistry:
    """Source registration, CRUD, and hierarchical sources."""

    def test_register_source(self):
        reg = SourceRegistry()
        src = reg.register_source("WHO", SourceAuthority.PRIMARY, 0.98)
        assert src.name == "WHO"
        assert src.authority == SourceAuthority.PRIMARY
        assert src.authority_score == 0.98
        assert reg.count == 1

    def test_register_with_defaults(self):
        reg = SourceRegistry()
        src = reg.register_source("Random Blog")
        assert src.authority == SourceAuthority.TERTIARY  # default
        assert src.authority_score == confidence_for_authority(SourceAuthority.TERTIARY)

    def test_hierarchical_sources(self):
        reg = SourceRegistry()
        who = reg.register_source("WHO", SourceAuthority.PRIMARY, 0.98)
        cdc = reg.register_source("CDC", SourceAuthority.PRIMARY, 0.95, parent_id=who.id)
        state = reg.register_source("CA Dept of Health", SourceAuthority.SECONDARY, 0.85, parent_id=cdc.id)

        chain = reg.get_source_chain(state.id)
        assert len(chain) == 3
        assert chain[0].name == "CA Dept of Health"
        assert chain[1].name == "CDC"
        assert chain[2].name == "WHO"

    def test_children(self):
        reg = SourceRegistry()
        who = reg.register_source("WHO", SourceAuthority.PRIMARY, 0.98)
        cdc = reg.register_source("CDC", SourceAuthority.PRIMARY, 0.95, parent_id=who.id)
        eu_health = reg.register_source("ECDC", SourceAuthority.PRIMARY, 0.93, parent_id=who.id)

        children = reg.get_children(who.id)
        names = {c.name for c in children}
        assert names == {"CDC", "ECDC"}

    def test_invalid_parent_raises(self):
        reg = SourceRegistry()
        with pytest.raises(ValueError, match="not found"):
            reg.register_source("Child", parent_id="nonexistent")

    def test_update_source(self):
        reg = SourceRegistry()
        src = reg.register_source("Test", SourceAuthority.TERTIARY)
        updated = reg.update_source(src.id, name="Updated Test", authority_score=0.9)
        assert updated.name == "Updated Test"
        assert updated.authority_score == 0.9

    def test_list_sources_filter(self):
        reg = SourceRegistry()
        reg.register_source("WHO", SourceAuthority.PRIMARY)
        reg.register_source("Blog", SourceAuthority.TERTIARY)
        reg.register_source("Wikipedia", SourceAuthority.SECONDARY)

        primary = reg.list_sources(authority=SourceAuthority.PRIMARY)
        assert len(primary) == 1
        assert primary[0].name == "WHO"

    def test_source_version_and_expires(self):
        reg = SourceRegistry()
        src = reg.register_source(
            "2024 Census",
            SourceAuthority.PRIMARY,
            version="2.1",
            expires_at="2030-01-01T00:00:00+00:00",
            domain="geography",
        )
        assert src.version == "2.1"
        assert src.expires_at is not None
        assert not src.is_expired()

    def test_source_domain_specialization(self):
        reg = SourceRegistry()
        src = reg.register_source("PubMed", SourceAuthority.PRIMARY, domain="medical")
        assert src.domain_specialization == "medical"


# ═══════════════════════════════════════════════════════════════════
# 2. Source Confidence Scoring
# ═══════════════════════════════════════════════════════════════════


class TestSourceConfidence:
    """Source confidence tiers: primary, secondary, tertiary, uncertain."""

    def test_primary_confidence_range(self):
        src = Source(name="WHO", authority=SourceAuthority.PRIMARY, authority_score=1.0)
        conf = src.effective_confidence()
        assert conf >= 0.9

    def test_secondary_confidence_range(self):
        src = Source(name="Wikipedia", authority=SourceAuthority.SECONDARY, authority_score=1.0)
        conf = src.effective_confidence()
        assert 0.6 <= conf <= 0.9

    def test_tertiary_confidence_range(self):
        src = Source(name="Blog", authority=SourceAuthority.TERTIARY, authority_score=1.0)
        conf = src.effective_confidence()
        assert 0.3 <= conf <= 0.6

    def test_uncertain_confidence_range(self):
        src = Source(name="Rumor", authority=SourceAuthority.UNCERTAIN, authority_score=1.0)
        conf = src.effective_confidence()
        assert 0.1 <= conf <= 0.3

    def test_confidence_interpolates_authority_score(self):
        # PRIMARY (0.9-1.0) with authority_score=0.5 should give midpoint-ish
        src = Source(name="Test", authority=SourceAuthority.PRIMARY, authority_score=0.5)
        conf = src.effective_confidence()
        assert 0.9 <= conf <= 0.95

    def test_confidence_for_authority_helper(self):
        assert confidence_for_authority(SourceAuthority.PRIMARY) == 0.95
        assert confidence_for_authority(SourceAuthority.UNCERTAIN) == 0.2


# ═══════════════════════════════════════════════════════════════════
# 3. Fact Provenance & Chain of Trust
# ═══════════════════════════════════════════════════════════════════


class TestFactProvenance:
    """Provenance linking facts to sources with chain of trust."""

    def test_link_fact_to_source(self):
        tracker = FactProvenanceTracker()
        sources = {
            "src-1": Source(id="src-1", name="WHO", authority=SourceAuthority.PRIMARY, authority_score=0.98),
        }
        prov = tracker.link_fact_to_source("fact-1", "src-1", sources)
        assert prov.fact_id == "fact-1"
        assert prov.source_id == "src-1"
        assert prov.chain == ["src-1"]

    def test_chain_of_trust(self):
        tracker = FactProvenanceTracker()
        who = Source(id="src-who", name="WHO", authority=SourceAuthority.PRIMARY, authority_score=0.98)
        cdc = Source(id="src-cdc", name="CDC", authority=SourceAuthority.PRIMARY, authority_score=0.95, parent_source_id="src-who")
        state = Source(id="src-state", name="CA Health", authority=SourceAuthority.SECONDARY, authority_score=0.85, parent_source_id="src-cdc")

        sources = {"src-who": who, "src-cdc": cdc, "src-state": state}
        prov = tracker.link_fact_to_source("fact-1", "src-state", sources)

        assert len(prov.chain) == 3
        assert prov.chain == ["src-state", "src-cdc", "src-who"]
        assert prov.chain_confidence < 1.0  # Product of confidences
        assert prov.chain_confidence > 0.5  # But still reasonable

    def test_best_provenance(self):
        tracker = FactProvenanceTracker()
        sources = {
            "src-1": Source(id="src-1", name="WHO", authority=SourceAuthority.PRIMARY, authority_score=0.98),
            "src-2": Source(id="src-2", name="Blog", authority=SourceAuthority.TERTIARY, authority_score=0.4),
        }
        tracker.link_fact_to_source("fact-1", "src-1", sources)
        tracker.link_fact_to_source("fact-1", "src-2", sources)

        best = tracker.get_best_provenance("fact-1")
        assert best.source_id == "src-1"  # WHO > Blog

    def test_get_facts_by_source(self):
        tracker = FactProvenanceTracker()
        sources = {"src-1": Source(id="src-1", name="WHO")}
        tracker.link_fact_to_source("fact-1", "src-1", sources)
        tracker.link_fact_to_source("fact-2", "src-1", sources)

        facts = tracker.get_facts_by_source("src-1")
        assert set(facts) == {"fact-1", "fact-2"}


# ═══════════════════════════════════════════════════════════════════
# 4. Audit Trail
# ═══════════════════════════════════════════════════════════════════


class TestAuditTrail:
    """Append-only audit trail with hash chain integrity."""

    def test_append_entry(self):
        trail = AuditTrail()
        entry = trail.log(AuditAction.CREATE, fact_id="f-001", details={"claim": "Paris"})
        assert entry.action == AuditAction.CREATE
        assert entry.fact_id == "f-001"
        assert trail.count == 1

    def test_hash_chain(self):
        trail = AuditTrail()
        e1 = trail.log(AuditAction.CREATE, fact_id="f-001")
        e2 = trail.log(AuditAction.UPDATE, fact_id="f-001")
        e3 = trail.log(AuditAction.RETRACT, fact_id="f-001")

        assert e2.previous_hash == e1.entry_hash
        assert e3.previous_hash == e2.entry_hash

    def test_append_only_no_delete(self):
        """AuditTrail has no delete method — entries are immutable."""
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.UPDATE, fact_id="f-001")

        # Verify there's no _entries.pop or similar
        # The API only exposes log() and get_entries()
        assert trail.count == 2
        assert not hasattr(trail, 'delete') or not callable(getattr(trail, 'delete', None))

    def test_chain_verification(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.UPDATE, fact_id="f-001")
        trail.log(AuditAction.RETRACT, fact_id="f-001")

        valid, error = trail.verify_chain()
        assert valid is True
        assert error is None

    def test_tamper_detection(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")

        # Tamper with an entry
        trail._entries[0].details = {"tampered": True}

        valid, error = trail.verify_chain()
        assert valid is False
        assert "hash mismatch" in error

    def test_chain_break_detection(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.UPDATE, fact_id="f-001")

        # Simulate a chain break by swapping entries without changing their hashes:
        # Create a new trail where we inject an entry with a mismatched previous_hash
        # but valid self-hash (mimicking a real chain-break attack)
        trail2 = AuditTrail()
        trail2.log(AuditAction.CREATE, fact_id="f-001")
        e2 = trail2.log(AuditAction.UPDATE, fact_id="f-001")
        # Manually create a third entry with wrong previous_hash but valid hash
        # This simulates inserting a forged entry
        forged = AuditEntry(
            action=AuditAction.RETRACT,
            fact_id="f-001",
            previous_hash="forged_prev_hash",  # doesn't match e2
        )
        # The forged entry's own hash will be valid since it was just computed
        trail2._entries.append(forged)

        valid, error = trail2.verify_chain()
        assert valid is False
        assert "Chain break" in error

    def test_query_by_fact_id(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.CREATE, fact_id="f-002")
        trail.log(AuditAction.UPDATE, fact_id="f-001")

        entries = trail.get_entries(fact_id="f-001")
        assert len(entries) == 2

    def test_query_by_action(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.UPDATE, fact_id="f-001")
        trail.log(AuditAction.CREATE, fact_id="f-002")

        creates = trail.get_entries(action=AuditAction.CREATE)
        assert len(creates) == 2

    def test_fact_history_ordered(self):
        trail = AuditTrail()
        trail.log(AuditAction.CREATE, fact_id="f-001")
        trail.log(AuditAction.UPDATE, fact_id="f-001")
        trail.log(AuditAction.RETRACT, fact_id="f-001")

        history = trail.get_fact_history("f-001")
        assert len(history) == 3
        assert history[0].action == AuditAction.CREATE
        assert history[-1].action == AuditAction.RETRACT

    def test_integrity_is_auditable(self):
        """Entry hash is deterministic — re-verification always works."""
        trail = AuditTrail()
        entry = trail.log(AuditAction.CREATE, fact_id="f-001")
        assert entry.verify_integrity()
        # Even if we re-check later
        assert entry.verify_integrity()


# ═══════════════════════════════════════════════════════════════════
# 5. Fact Expiration & Confidence Decay
# ═══════════════════════════════════════════════════════════════════


class TestFactExpiration:
    """Fact expiration with aggressive confidence decay."""

    def test_fresh_fact_not_expired(self):
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        fact = GroundTruthFact(claim="test", expires_at=future)
        assert not fact.is_expired()

    def test_expired_fact_detected(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        fact = GroundTruthFact(claim="test", expires_at=past)
        assert fact.is_expired()

    def test_no_expiration_date(self):
        fact = GroundTruthFact(claim="test")
        assert not fact.is_expired()

    def test_expired_confidence_decays_aggressively(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        fact = GroundTruthFact(
            claim="test",
            confidence=0.9,
            source=Source(authority=SourceAuthority.PRIMARY, authority_score=0.95),
            expires_at=past,
        )
        effective = fact.calculate_effective_confidence()
        # Should be much lower than base confidence
        assert effective < 0.5

    def test_expired_confidence_decays_over_time(self):
        """More expired = lower confidence."""
        expired_recently = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        expired_long_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        src = Source(authority=SourceAuthority.PRIMARY, authority_score=0.95)

        fact_recent = GroundTruthFact(claim="test", confidence=0.9, source=src, expires_at=expired_recently)
        fact_old = GroundTruthFact(claim="test", confidence=0.9, source=src, expires_at=expired_long_ago)

        assert fact_recent.calculate_effective_confidence() > fact_old.calculate_effective_confidence()

    def test_brahmanda_checks_expired_facts(self):
        bm = BrahmandaMap()
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        src = bm.attribution.register_source("Test", authority=SourceAuthority.PRIMARY)
        bm.add_fact("Expired fact", source=src, expires_at=past)

        expired = bm.check_expired_facts()
        assert len(expired) == 1

        # Second call should not re-audit
        expired2 = bm.check_expired_facts()
        assert len(expired2) == 0


# ═══════════════════════════════════════════════════════════════════
# 6. Integration: Source Confidence → Verification Confidence
# ═══════════════════════════════════════════════════════════════════


class TestVerifierIntegration:
    """Source confidence feeds into verification confidence."""

    def test_brahmanda_requires_source(self):
        """BrahmandaMap creates a default source if none provided."""
        bm = BrahmandaMap()
        fact = bm.add_fact("Paris is the capital of France")
        assert fact.source is not None
        assert fact.source.name == "RTA-GUARD Default"

    def test_high_confidence_source_better_verification(self):
        """Facts from primary sources should verify with higher confidence."""
        bm_high = BrahmandaMap()
        src_high = bm_high.attribution.register_source("WHO", authority=SourceAuthority.PRIMARY, authority_score=0.98)
        bm_high.add_fact("Paris is the capital of France", source=src_high, confidence=0.98)

        bm_low = BrahmandaMap()
        src_low = bm_low.attribution.register_source("Blog", authority=SourceAuthority.TERTIARY, authority_score=0.4)
        bm_low.add_fact("Paris is the capital of France", source=src_low, confidence=0.98)

        fact_high = list(bm_high._facts.values())[0]
        fact_low = list(bm_low._facts.values())[0]

        assert fact_high.calculate_effective_confidence() > fact_low.calculate_effective_confidence()

    def test_verification_audited(self):
        """Verifying text creates audit entries."""
        bm = BrahmandaMap()
        src = bm.attribution.register_source("Test", authority=SourceAuthority.PRIMARY)
        bm.add_fact("Paris is the capital of France", source=src)

        verifier = BrahmandaVerifier(bm, use_pipeline=False)
        result = verifier.verify("Paris is the capital of France")

        # Check audit trail has verification entries
        entries = bm.attribution.audit.get_entries(action=AuditAction.VERIFICATION)
        assert len(entries) >= 1

    def test_add_verified_fact_uses_attribution(self):
        verifier = BrahmandaVerifier(use_pipeline=False)
        fact = verifier.add_verified_fact(
            "Berlin is the capital of Germany",
            source_name="Wikipedia",
            source_authority=SourceAuthority.SECONDARY,
        )
        assert fact.source.name == "Wikipedia"
        assert fact.source.authority == SourceAuthority.SECONDARY


# ═══════════════════════════════════════════════════════════════════
# 7. Attribution Manager (Unified Facade)
# ═══════════════════════════════════════════════════════════════════


class TestAttributionManager:
    """Unified attribution facade."""

    def test_full_lifecycle(self):
        """Register source → add fact → link → verify integrity."""
        attr = AttributionManager()

        src = attr.register_source("WHO", authority=SourceAuthority.PRIMARY, authority_score=0.98)
        prov = attr.link_fact("f-001", src.id)

        assert prov.fact_id == "f-001"
        assert prov.source_id == src.id

        valid, err = attr.verify_integrity()
        assert valid

    def test_stats(self):
        attr = AttributionManager()
        src = attr.register_source("Test", SourceAuthority.SECONDARY)
        attr.link_fact("f-001", src.id)
        attr.log_fact_retract("f-001", reason="outdated")

        stats = attr.get_stats()
        assert stats["sources_registered"] == 1
        assert stats["provenance_links"] == 1
        assert stats["audit_entries"] >= 1
        assert stats["chain_valid"] is True

    def test_audit_fact_changes(self):
        attr = AttributionManager()
        src = attr.register_source("Test", SourceAuthority.SECONDARY)
        attr.link_fact("f-001", src.id)
        attr.log_verification("f-001", "test claim", "pass", 0.9, src.id)

        changes = attr.audit_fact_changes("f-001")
        assert len(changes) >= 2  # source_change + verification
        actions = [c.action for c in changes]
        assert AuditAction.SOURCE_CHANGE in actions
        assert AuditAction.VERIFICATION in actions


# ═══════════════════════════════════════════════════════════════════
# 8. Source Expiration
# ═══════════════════════════════════════════════════════════════════


class TestSourceExpiration:
    """Source-level expiration."""

    def test_expired_source(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        src = Source(name="Old Census", authority=SourceAuthority.PRIMARY, expires_at=past)
        assert src.is_expired()

    def test_unexpired_source(self):
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        src = Source(name="Census 2024", authority=SourceAuthority.PRIMARY, expires_at=future)
        assert not src.is_expired()


# ═══════════════════════════════════════════════════════════════════
# 9. SQLite Persistence
# ═══════════════════════════════════════════════════════════════════


class TestPersistence:
    """SQLite persistence for sources and audit trail."""

    def test_source_persistence(self, tmp_path):
        db = str(tmp_path / "test.db")
        reg = SourceRegistry(db_path=db)
        src = reg.register_source("WHO", SourceAuthority.PRIMARY, 0.98)
        assert reg.count == 1

    def test_audit_persistence(self, tmp_path):
        db = str(tmp_path / "test.db")
        trail = AuditTrail(db_path=db)
        trail.log(AuditAction.CREATE, fact_id="f-001")
        assert trail.count == 1
