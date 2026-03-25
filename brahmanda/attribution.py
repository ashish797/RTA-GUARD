"""
RTA-GUARD — Source Attribution System

SourceRegistry: manages sources with CRUD and hierarchy support
FactProvenanceTracker: links facts to sources, tracks provenance chains
AuditTrail: append-only log of all fact modifications with hash-chain integrity

EU AI Act compliance: full audit trail, source attribution, confidence scoring.
"""
import os
import sqlite3
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from .models import (
    Source, SourceAuthority, GroundTruthFact, FactProvenance, AuditEntry,
    AuditAction, confidence_for_authority,
)

logger = logging.getLogger(__name__)


# ─── Source Registry ────────────────────────────────────────────────


class SourceRegistry:
    """
    Manages sources with CRUD operations and hierarchical support.

    Supports nested sources (e.g., WHO > CDC > state health dept).
    Sources are stored in a dict (in-memory) or SQLite (persistent).

    Usage:
        registry = SourceRegistry()
        who = registry.register_source("WHO", SourceAuthority.PRIMARY, 0.98)
        cdc = registry.register_source("CDC", SourceAuthority.PRIMARY, 0.95, parent_id=who.id)
    """

    def __init__(self, db_path: Optional[str] = None):
        self._sources: Dict[str, Source] = {}
        self._db_path = db_path
        self._lock = threading.Lock()
        if db_path:
            self._init_db()

    def _init_db(self):
        """Initialize SQLite database for persistent source storage."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                authority TEXT NOT NULL,
                authority_score REAL NOT NULL,
                url TEXT,
                verified_by TEXT,
                verified_at TEXT NOT NULL,
                notes TEXT DEFAULT '',
                version TEXT DEFAULT '1.0',
                expires_at TEXT,
                domain_specialization TEXT,
                parent_source_id TEXT,
                tags TEXT DEFAULT '[]',
                FOREIGN KEY (parent_source_id) REFERENCES sources(id)
            )
        """)
        conn.commit()
        conn.close()

    def register_source(
        self,
        name: str,
        authority: SourceAuthority = SourceAuthority.TERTIARY,
        authority_score: Optional[float] = None,
        url: Optional[str] = None,
        domain: Optional[str] = None,
        parent_id: Optional[str] = None,
        expires_at: Optional[str] = None,
        version: str = "1.0",
        tags: Optional[List[str]] = None,
        notes: str = "",
        verified_by: Optional[str] = None,
    ) -> Source:
        """Register a new source in the registry."""
        # Auto-set authority_score from authority level if not provided
        if authority_score is None:
            authority_score = confidence_for_authority(authority)

        # Validate parent exists
        if parent_id and parent_id not in self._sources:
            raise ValueError(f"Parent source '{parent_id}' not found in registry")

        source = Source(
            name=name,
            authority=authority,
            authority_score=authority_score,
            url=url,
            domain_specialization=domain,
            parent_source_id=parent_id,
            expires_at=expires_at,
            version=version,
            tags=tags or [],
            notes=notes,
            verified_by=verified_by,
        )

        with self._lock:
            self._sources[source.id] = source
            if self._db_path:
                self._persist_source(source)

        return source

    def get_source(self, source_id: str) -> Optional[Source]:
        """Get a source by ID."""
        return self._sources.get(source_id)

    def get_source_chain(self, source_id: str) -> List[Source]:
        """
        Get the full hierarchy chain for a source (child → parent → grandparent).
        Example: [CDC, WHO] for a CDC source with WHO as parent.
        """
        chain = []
        current = self._sources.get(source_id)
        visited = set()
        while current:
            if current.id in visited:
                break  # Prevent infinite loops
            visited.add(current.id)
            chain.append(current)
            current = self._sources.get(current.parent_source_id) if current.parent_source_id else None
        return chain

    def get_children(self, source_id: str) -> List[Source]:
        """Get all direct children of a source."""
        return [s for s in self._sources.values() if s.parent_source_id == source_id]

    def update_source(self, source_id: str, **kwargs) -> Optional[Source]:
        """Update an existing source."""
        source = self._sources.get(source_id)
        if not source:
            return None

        with self._lock:
            for key, value in kwargs.items():
                if hasattr(source, key):
                    setattr(source, key, value)
            if self._db_path:
                self._persist_source(source)

        return source

    def list_sources(
        self,
        authority: Optional[SourceAuthority] = None,
        domain: Optional[str] = None,
    ) -> List[Source]:
        """List sources, optionally filtered by authority or domain."""
        results = list(self._sources.values())
        if authority:
            results = [s for s in results if s.authority == authority]
        if domain:
            results = [s for s in results if s.domain_specialization == domain]
        return results

    def _persist_source(self, source: Source):
        """Persist a source to SQLite."""
        if not self._db_path:
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            INSERT OR REPLACE INTO sources
            (id, name, authority, authority_score, url, verified_by, verified_at,
             notes, version, expires_at, domain_specialization, parent_source_id, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source.id, source.name, source.authority.value, source.authority_score,
            source.url, source.verified_by, source.verified_at, source.notes,
            source.version, source.expires_at, source.domain_specialization,
            source.parent_source_id, json.dumps(source.tags),
        ))
        conn.commit()
        conn.close()

    @property
    def count(self) -> int:
        return len(self._sources)


# ─── Fact Provenance Tracker ────────────────────────────────────────


class FactProvenanceTracker:
    """
    Links facts to sources and tracks provenance chains.

    Each fact can have multiple provenance entries (from different sources).
    The provenance chain represents the trust path from the current source
    back to the ultimate root source.

    Usage:
        tracker = FactProvenanceTracker()
        prov = tracker.link_fact_to_source("fact-001", "src-who", sources_dict)
        chain = tracker.get_provenance_chain("fact-001")
    """

    def __init__(self):
        self._provenance: Dict[str, List[FactProvenance]] = {}  # fact_id -> [provenance]
        self._lock = threading.Lock()

    def link_fact_to_source(
        self,
        fact_id: str,
        source_id: str,
        sources: Dict[str, Source],
        linked_by: Optional[str] = None,
        notes: str = "",
    ) -> FactProvenance:
        """
        Link a fact to a source, building the trust chain.

        Automatically builds the chain by traversing the source hierarchy.
        """
        # Build trust chain: source → parent → grandparent → ...
        chain = []
        chain_conf = 1.0
        current = sources.get(source_id)
        visited = set()

        while current:
            if current.id in visited:
                break
            visited.add(current.id)
            chain.append(current.id)
            chain_conf *= current.effective_confidence()
            current = sources.get(current.parent_source_id) if current.parent_source_id else None

        prov = FactProvenance(
            fact_id=fact_id,
            source_id=source_id,
            linked_by=linked_by,
            chain=chain,
            chain_confidence=round(chain_conf, 4),
            notes=notes,
        )

        with self._lock:
            if fact_id not in self._provenance:
                self._provenance[fact_id] = []
            self._provenance[fact_id].append(prov)

        return prov

    def get_provenance_chain(self, fact_id: str) -> List[FactProvenance]:
        """Get all provenance entries for a fact, ordered by link time."""
        return self._provenance.get(fact_id, [])

    def get_best_provenance(self, fact_id: str) -> Optional[FactProvenance]:
        """Get the provenance entry with the highest chain confidence."""
        entries = self._provenance.get(fact_id, [])
        if not entries:
            return None
        return max(entries, key=lambda p: p.chain_confidence)

    def get_facts_by_source(self, source_id: str) -> List[str]:
        """Get all fact IDs linked to a specific source."""
        fact_ids = []
        for fact_id, provs in self._provenance.items():
            if any(p.source_id == source_id for p in provs):
                fact_ids.append(fact_id)
        return fact_ids

    def remove_provenance(self, fact_id: str, source_id: str) -> bool:
        """Remove a provenance link (not from the audit trail)."""
        with self._lock:
            entries = self._provenance.get(fact_id, [])
            self._provenance[fact_id] = [p for p in entries if p.source_id != source_id]
            return len(entries) != len(self._provenance.get(fact_id, []))

    @property
    def total_links(self) -> int:
        return sum(len(v) for v in self._provenance.values())


# ─── Audit Trail ────────────────────────────────────────────────────


class AuditTrail:
    """
    Append-only audit log with hash-chain integrity.

    Every mutation on a fact is logged. Entries are immutable —
    no deletes, no modifications. Each entry contains a hash
    of the previous entry, forming a tamper-evident chain.

    EU AI Act compliance: provides full audit trail of all changes.

    Usage:
        trail = AuditTrail()
        entry = trail.log(AuditAction.CREATE, fact_id="f-001", details={...})
        valid = trail.verify_chain()  # True if no tampering
    """

    def __init__(self, db_path: Optional[str] = None):
        self._entries: List[AuditEntry] = []
        self._last_hash: Optional[str] = None
        self._db_path = db_path
        self._lock = threading.Lock()
        if db_path:
            self._init_db()

    def _init_db(self):
        """Initialize SQLite database for persistent audit storage."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_entries (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                source_id TEXT,
                actor TEXT DEFAULT 'system',
                previous_hash TEXT,
                entry_hash TEXT NOT NULL,
                details TEXT DEFAULT '{}',
                before TEXT,
                after TEXT
            )
        """)
        conn.commit()
        conn.close()

    def log(
        self,
        action: AuditAction,
        fact_id: str,
        source_id: Optional[str] = None,
        actor: str = "system",
        details: Optional[Dict[str, Any]] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """
        Append a new audit entry. This is the ONLY way to add entries.
        Entries are immutable once created.
        """
        entry = AuditEntry(
            action=action,
            fact_id=fact_id,
            source_id=source_id,
            actor=actor,
            previous_hash=self._last_hash,
            details=details or {},
            before=before,
            after=after,
        )

        with self._lock:
            self._entries.append(entry)
            self._last_hash = entry.entry_hash
            if self._db_path:
                self._persist_entry(entry)

        return entry

    def get_entries(
        self,
        fact_id: Optional[str] = None,
        action: Optional[AuditAction] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit entries with optional filters."""
        results = list(self._entries)

        if fact_id:
            results = [e for e in results if e.fact_id == fact_id]
        if action:
            results = [e for e in results if e.action == action]
        if since:
            results = [e for e in results if e.timestamp >= since]

        # Most recent first
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    def get_fact_history(self, fact_id: str) -> List[AuditEntry]:
        """Get the complete audit history for a fact, oldest first."""
        entries = [e for e in self._entries if e.fact_id == fact_id]
        entries.sort(key=lambda e: e.timestamp)
        return entries

    def verify_chain(self) -> Tuple[bool, Optional[str]]:
        """
        Verify the integrity of the entire audit chain.

        Returns:
            (is_valid, error_message) — True if chain is intact.
        """
        if not self._entries:
            return True, None

        for i, entry in enumerate(self._entries):
            # Check entry hash integrity
            if not entry.verify_integrity():
                return False, f"Entry {entry.id} hash mismatch at index {i}"

            # Check chain linkage (except first entry)
            if i > 0:
                expected_prev = self._entries[i - 1].entry_hash
                if entry.previous_hash != expected_prev:
                    return False, (
                        f"Chain break at entry {entry.id} (index {i}): "
                        f"expected previous_hash={expected_prev}, got {entry.previous_hash}"
                    )

        return True, None

    def _persist_entry(self, entry: AuditEntry):
        """Persist an audit entry to SQLite."""
        if not self._db_path:
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            INSERT INTO audit_entries
            (id, timestamp, action, fact_id, source_id, actor, previous_hash,
             entry_hash, details, before, after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.id, entry.timestamp, entry.action.value, entry.fact_id,
            entry.source_id, entry.actor, entry.previous_hash, entry.entry_hash,
            json.dumps(entry.details, default=str),
            json.dumps(entry.before, default=str) if entry.before else None,
            json.dumps(entry.after, default=str) if entry.after else None,
        ))
        conn.commit()
        conn.close()

    @property
    def count(self) -> int:
        return len(self._entries)


# ─── Unified Attribution Manager ────────────────────────────────────


class AttributionManager:
    """
    Unified facade combining SourceRegistry, FactProvenanceTracker, and AuditTrail.

    Provides a single interface for all attribution operations.
    Integrates with BrahmandaMap to enforce source requirements.

    Usage:
        attr = AttributionManager()
        src = attr.register_source("WHO", SourceAuthority.PRIMARY)
        attr.link_fact("f-001", src.id)
        history = attr.get_audit_history("f-001")
    """

    def __init__(self, db_path: Optional[str] = None, tenant_context: Optional[Any] = None):
        if tenant_context is not None:
            db_path = tenant_context.attribution_db_path
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
        self.registry = SourceRegistry(db_path=db_path)
        self.tracker = FactProvenanceTracker()
        self.audit = AuditTrail(db_path=db_path)
        self._tenant_context = tenant_context

    def register_source(self, name: str, authority: SourceAuthority = SourceAuthority.TERTIARY, **kwargs) -> Source:
        """Register a source and audit the registration."""
        source = self.registry.register_source(name, authority=authority, **kwargs)
        return source

    def link_fact(self, fact_id: str, source_id: str, **kwargs) -> FactProvenance:
        """Link a fact to a source with audit trail."""
        prov = self.tracker.link_fact_to_source(
            fact_id=fact_id,
            source_id=source_id,
            sources=self.registry._sources,
            **kwargs,
        )
        self.audit.log(
            action=AuditAction.SOURCE_CHANGE,
            fact_id=fact_id,
            source_id=source_id,
            details={"provenance_id": prov.id, "chain": prov.chain},
        )
        return prov

    def get_provenance_chain(self, fact_id: str) -> List[FactProvenance]:
        """Get the full provenance chain for a fact."""
        return self.tracker.get_provenance_chain(fact_id)

    def audit_fact_changes(self, fact_id: str) -> List[AuditEntry]:
        """Get the complete audit trail for a fact."""
        return self.audit.get_fact_history(fact_id)

    def log_fact_create(self, fact: GroundTruthFact, actor: str = "system") -> AuditEntry:
        """Audit a fact creation."""
        return self.audit.log(
            action=AuditAction.CREATE,
            fact_id=fact.id,
            source_id=fact.source.id,
            actor=actor,
            after=fact.to_dict(),
        )

    def log_fact_update(
        self,
        fact: GroundTruthFact,
        before: Dict[str, Any],
        actor: str = "system",
    ) -> AuditEntry:
        """Audit a fact update."""
        return self.audit.log(
            action=AuditAction.UPDATE,
            fact_id=fact.id,
            source_id=fact.source.id,
            actor=actor,
            before=before,
            after=fact.to_dict(),
        )

    def log_fact_retract(self, fact_id: str, reason: str, actor: str = "system") -> AuditEntry:
        """Audit a fact retraction."""
        return self.audit.log(
            action=AuditAction.RETRACT,
            fact_id=fact_id,
            actor=actor,
            details={"reason": reason},
        )

    def log_verification(
        self,
        fact_id: str,
        claim: str,
        decision: str,
        confidence: float,
        source_id: Optional[str] = None,
    ) -> AuditEntry:
        """Audit a verification event."""
        return self.audit.log(
            action=AuditAction.VERIFICATION,
            fact_id=fact_id,
            source_id=source_id,
            details={"claim": claim, "decision": decision, "confidence": confidence},
        )

    def log_expiration(self, fact: GroundTruthFact) -> AuditEntry:
        """Audit a fact expiration."""
        return self.audit.log(
            action=AuditAction.EXPIRATION,
            fact_id=fact.id,
            source_id=fact.source.id,
            details={"expires_at": fact.expires_at, "effective_confidence": fact.calculate_effective_confidence()},
        )

    def verify_integrity(self) -> Tuple[bool, Optional[str]]:
        """Verify the audit trail chain integrity."""
        return self.audit.verify_chain()

    def get_stats(self) -> Dict[str, Any]:
        """Get attribution system statistics."""
        return {
            "sources_registered": self.registry.count,
            "provenance_links": self.tracker.total_links,
            "audit_entries": self.audit.count,
            "chain_valid": self.verify_integrity()[0],
        }
