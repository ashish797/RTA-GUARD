"""
RTA-GUARD — Mutation Tracking System (Phase 2.6)

MutationTracker: wraps AuditTrail to track every change to facts.
Provides detailed diff-based tracking, history retrieval, filtered audit trail,
and hash-chain integrity verification with tamper detection.

EU AI Act compliance: full traceability of who changed what, when, and why.
"""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from .models import (
    GroundTruthFact, AuditEntry, AuditAction,
)

logger = logging.getLogger(__name__)


# ─── Mutation Model ─────────────────────────────────────────────────


@dataclass
class Mutation:
    """
    Represents a single mutation (change) to a fact in the Brahmanda Map.

    Captures: what changed (old→new), who changed it, when, and why.
    This is the primary audit unit for EU AI Act traceability.
    """
    id: str = field(default_factory=lambda: f"mut-{__import__('uuid').uuid4().hex[:12]}")
    fact_id: str = ""
    mutation_type: str = "create"  # create | update | retract | expire
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    diff: Optional[Dict[str, Any]] = None  # Changed fields only
    reason: str = ""
    actor: str = "system"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    previous_hash: Optional[str] = None
    entry_hash: Optional[str] = field(default=None)

    def __post_init__(self):
        if self.entry_hash is None:
            self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash for tamper-evident chain."""
        import hashlib
        content = json.dumps({
            "id": self.id,
            "fact_id": self.fact_id,
            "mutation_type": self.mutation_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "diff": self.diff,
            "reason": self.reason,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify this mutation entry hasn't been tampered with."""
        return self.entry_hash == self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fact_id": self.fact_id,
            "mutation_type": self.mutation_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "diff": self.diff,
            "reason": self.reason,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


# ─── Diff Utility ───────────────────────────────────────────────────


def compute_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute a structured diff between old and new fact states.

    Returns dict with 'changed', 'added', 'removed' keys showing
    exactly what changed between the two states.
    """
    diff: Dict[str, Any] = {
        "changed": {},   # field: {"old": v, "new": v}
        "added": {},     # field: value (present in new, not old)
        "removed": {},   # field: value (present in old, not new)
    }

    all_keys = set(old.keys()) | set(new.keys())

    for key in all_keys:
        in_old = key in old
        in_new = key in new

        if in_old and in_new:
            old_val = old[key]
            new_val = new[key]
            # Deep comparison for dicts/lists, simple for scalars
            if _values_differ(old_val, new_val):
                diff["changed"][key] = {"old": old_val, "new": new_val}
        elif in_new and not in_old:
            diff["added"][key] = new[key]
        elif in_old and not in_new:
            diff["removed"][key] = old[key]

    return diff


def _values_differ(a: Any, b: Any) -> bool:
    """Compare two values, handling dicts/lists via JSON normalization."""
    try:
        return json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return a != b


# ─── Mutation Tracker ───────────────────────────────────────────────


class MutationTracker:
    """
    Tracks every mutation to facts in the Brahmanda Map.

    Wraps the AuditTrail to provide mutation-specific tracking with:
    - Diff-based change recording (old→new with structured diff)
    - Fact-centric history (all changes to a specific fact)
    - Filtered audit trail queries (by date range, actor, type)
    - Hash-chain integrity verification
    - Tamper detection with detailed reports

    Each mutation is recorded in two places:
    1. The internal mutation log (for fast history queries)
    2. The AuditTrail (for compliance-grade tamper-evident chain)

    Usage:
        tracker = MutationTracker()
        tracker.track_creation(fact, source, "Initial seed")
        tracker.track_update("f-001", old_dict, new_dict, "Correction")
        history = tracker.get_history("f-001")
        valid, report = tracker.verify_integrity()
    """

    def __init__(self, attribution_manager=None):
        """
        Initialize the MutationTracker.

        Args:
            attribution_manager: Optional AttributionManager instance.
                If provided, mutations are also logged to the AuditTrail.
        """
        self._mutations: List[Mutation] = []
        self._fact_index: Dict[str, List[str]] = {}  # fact_id → [mutation_ids]
        self._last_hash: Optional[str] = None
        self._lock = threading.Lock()
        self._attribution = attribution_manager

    def track_creation(
        self,
        fact: GroundTruthFact,
        source_name: str = "",
        reason: str = "Fact created",
        actor: str = "system",
    ) -> Mutation:
        """
        Log the creation of a new fact.

        Args:
            fact: The newly created GroundTruthFact
            source_name: Name of the source that provided this fact
            reason: Why this fact was created
            actor: Who created it

        Returns:
            The Mutation entry created
        """
        new_value = fact.to_dict()

        mutation = Mutation(
            fact_id=fact.id,
            mutation_type="create",
            old_value=None,
            new_value=new_value,
            diff={"added": new_value},
            reason=f"{reason} (source: {source_name or fact.source.name})",
            actor=actor,
            previous_hash=self._last_hash,
        )

        self._record_mutation(mutation)

        # Also log to AuditTrail if available
        if self._attribution:
            self._attribution.audit.log(
                action=AuditAction.CREATE,
                fact_id=fact.id,
                source_id=fact.source.id,
                actor=actor,
                details={
                    "mutation_id": mutation.id,
                    "reason": reason,
                    "source_name": source_name,
                    "claim": fact.claim,
                    "confidence": fact.confidence,
                },
                after=new_value,
            )

        return mutation

    def track_update(
        self,
        fact_id: str,
        old_value: Dict[str, Any],
        new_value: Dict[str, Any],
        reason: str = "Fact updated",
        actor: str = "system",
    ) -> Mutation:
        """
        Log an update to an existing fact with a structured diff.

        Args:
            fact_id: ID of the fact being updated
            old_value: Complete fact state before the update (dict)
            new_value: Complete fact state after the update (dict)
            reason: Why this update was made
            actor: Who made the update

        Returns:
            The Mutation entry created
        """
        diff = compute_diff(old_value, new_value)

        mutation = Mutation(
            fact_id=fact_id,
            mutation_type="update",
            old_value=old_value,
            new_value=new_value,
            diff=diff,
            reason=reason,
            actor=actor,
            previous_hash=self._last_hash,
        )

        self._record_mutation(mutation)

        # Also log to AuditTrail if available
        if self._attribution:
            self._attribution.audit.log(
                action=AuditAction.UPDATE,
                fact_id=fact_id,
                source_id=old_value.get("source", {}).get("id"),
                actor=actor,
                details={
                    "mutation_id": mutation.id,
                    "reason": reason,
                    "changed_fields": list(diff.get("changed", {}).keys()),
                    "added_fields": list(diff.get("added", {}).keys()),
                    "removed_fields": list(diff.get("removed", {}).keys()),
                },
                before=old_value,
                after=new_value,
            )

        return mutation

    def track_retraction(
        self,
        fact_id: str,
        reason: str = "Fact retracted",
        actor: str = "system",
        fact_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Mutation:
        """
        Log the retraction of a fact.

        Args:
            fact_id: ID of the fact being retracted
            reason: Why this fact is being retracted
            actor: Who retracted it
            fact_snapshot: Optional snapshot of the fact before retraction

        Returns:
            The Mutation entry created
        """
        retracted_state = {
            "retracted": True,
            "retraction_reason": reason,
            "confidence": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        mutation = Mutation(
            fact_id=fact_id,
            mutation_type="retract",
            old_value=fact_snapshot,
            new_value=retracted_state,
            diff={"changed": {"retracted": {"old": False, "new": True}}},
            reason=reason,
            actor=actor,
            previous_hash=self._last_hash,
        )

        self._record_mutation(mutation)

        # Also log to AuditTrail if available
        if self._attribution:
            self._attribution.audit.log(
                action=AuditAction.RETRACT,
                fact_id=fact_id,
                actor=actor,
                details={
                    "mutation_id": mutation.id,
                    "reason": reason,
                },
                before=fact_snapshot,
                after=retracted_state,
            )

        return mutation

    def track_expiration(
        self,
        fact_id: str,
        actor: str = "system",
        fact_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Mutation:
        """
        Log the auto-expiration of a fact.

        Args:
            fact_id: ID of the fact that expired
            actor: Who triggered the expiration check (usually system)
            fact_snapshot: Optional snapshot of the fact at expiration

        Returns:
            The Mutation entry created
        """
        expiration_state = {
            "expired": True,
            "expiration_logged_at": datetime.now(timezone.utc).isoformat(),
        }

        mutation = Mutation(
            fact_id=fact_id,
            mutation_type="expire",
            old_value=fact_snapshot,
            new_value=expiration_state,
            diff={"changed": {"expired": {"old": False, "new": True}}},
            reason="Fact passed expiration date",
            actor=actor,
            previous_hash=self._last_hash,
        )

        self._record_mutation(mutation)

        # Also log to AuditTrail if available
        if self._attribution:
            self._attribution.audit.log(
                action=AuditAction.EXPIRATION,
                fact_id=fact_id,
                source_id=fact_snapshot.get("source", {}).get("id") if fact_snapshot else None,
                actor=actor,
                details={
                    "mutation_id": mutation.id,
                    "expires_at": fact_snapshot.get("expires_at") if fact_snapshot else None,
                },
                before=fact_snapshot,
                after=expiration_state,
            )

        return mutation

    def get_history(self, fact_id: str) -> List[Mutation]:
        """
        Get the complete mutation history for a fact, oldest first.

        Args:
            fact_id: ID of the fact

        Returns:
            List of Mutation entries ordered by timestamp (oldest first)
        """
        mutation_ids = self._fact_index.get(fact_id, [])
        # Build a lookup for efficiency
        id_to_mutation = {m.id: m for m in self._mutations}
        history = [id_to_mutation[mid] for mid in mutation_ids if mid in id_to_mutation]
        history.sort(key=lambda m: m.timestamp)
        return history

    def get_audit_trail(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        fact_id: Optional[str] = None,
        mutation_type: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 100,
    ) -> List[Mutation]:
        """
        Get filtered audit trail entries.

        Args:
            from_date: ISO timestamp — only entries after this date
            to_date: ISO timestamp — only entries before this date
            fact_id: Filter by fact ID
            mutation_type: Filter by type (create/update/retract/expire)
            actor: Filter by actor
            limit: Maximum entries to return

        Returns:
            List of Mutation entries matching filters, newest first
        """
        results = list(self._mutations)

        if fact_id:
            results = [m for m in results if m.fact_id == fact_id]
        if mutation_type:
            results = [m for m in results if m.mutation_type == mutation_type]
        if actor:
            results = [m for m in results if m.actor == actor]
        if from_date:
            results = [m for m in results if m.timestamp >= from_date]
        if to_date:
            results = [m for m in results if m.timestamp <= to_date]

        # Newest first
        results.sort(key=lambda m: m.timestamp, reverse=True)
        return results[:limit]

    def verify_integrity(self) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
        """
        Verify the integrity of the entire mutation hash chain.

        Checks:
        1. Each mutation entry's hash matches its content
        2. The chain linkage is intact (each previous_hash matches prior entry_hash)

        Returns:
            (is_valid, error_message, tamper_report)
            - is_valid: True if no tampering detected
            - error_message: First error found, or None
            - tamper_report: List of all issues found (empty if valid)
        """
        if not self._mutations:
            return True, None, []

        issues: List[Dict[str, Any]] = []

        for i, mutation in enumerate(self._mutations):
            # Check entry hash integrity
            if not mutation.verify_integrity():
                issue = {
                    "type": "hash_mismatch",
                    "index": i,
                    "mutation_id": mutation.id,
                    "fact_id": mutation.fact_id,
                    "expected_hash": mutation._compute_hash(),
                    "stored_hash": mutation.entry_hash,
                    "detail": f"Mutation {mutation.id} has been tampered with — hash mismatch",
                }
                issues.append(issue)

            # Check chain linkage (except first entry)
            if i > 0:
                expected_prev = self._mutations[i - 1].entry_hash
                if mutation.previous_hash != expected_prev:
                    issue = {
                        "type": "chain_break",
                        "index": i,
                        "mutation_id": mutation.id,
                        "fact_id": mutation.fact_id,
                        "expected_previous_hash": expected_prev,
                        "actual_previous_hash": mutation.previous_hash,
                        "detail": (
                            f"Chain break at mutation {mutation.id} (index {i}): "
                            f"expected previous_hash={expected_prev[:16]}..., "
                            f"got {mutation.previous_hash[:16] if mutation.previous_hash else 'None'}..."
                        ),
                    }
                    issues.append(issue)

        is_valid = len(issues) == 0
        error_msg = issues[0]["detail"] if issues else None
        return is_valid, error_msg, issues

    def get_tamper_report(self) -> Dict[str, Any]:
        """
        Generate a detailed tamper detection report.

        Returns:
            Dict with chain statistics and any issues found
        """
        is_valid, error_msg, issues = self.verify_integrity()

        return {
            "chain_valid": is_valid,
            "total_mutations": len(self._mutations),
            "total_facts_tracked": len(self._fact_index),
            "issues_found": len(issues),
            "issues": issues,
            "mutation_types": {
                "create": sum(1 for m in self._mutations if m.mutation_type == "create"),
                "update": sum(1 for m in self._mutations if m.mutation_type == "update"),
                "retract": sum(1 for m in self._mutations if m.mutation_type == "retract"),
                "expire": sum(1 for m in self._mutations if m.mutation_type == "expire"),
            },
            "first_mutation": self._mutations[0].timestamp if self._mutations else None,
            "last_mutation": self._mutations[-1].timestamp if self._mutations else None,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get mutation tracking statistics."""
        return {
            "total_mutations": len(self._mutations),
            "total_facts_tracked": len(self._fact_index),
            "chain_intact": self.verify_integrity()[0],
            "mutation_types": {
                "create": sum(1 for m in self._mutations if m.mutation_type == "create"),
                "update": sum(1 for m in self._mutations if m.mutation_type == "update"),
                "retract": sum(1 for m in self._mutations if m.mutation_type == "retract"),
                "expire": sum(1 for m in self._mutations if m.mutation_type == "expire"),
            },
        }

    def _record_mutation(self, mutation: Mutation) -> None:
        """Record a mutation in the internal log and fact index."""
        with self._lock:
            self._mutations.append(mutation)
            self._last_hash = mutation.entry_hash

            if mutation.fact_id not in self._fact_index:
                self._fact_index[mutation.fact_id] = []
            self._fact_index[mutation.fact_id].append(mutation.id)

    @property
    def mutation_count(self) -> int:
        """Total number of mutations tracked."""
        return len(self._mutations)

    @property
    def tracked_fact_count(self) -> int:
        """Number of unique facts with mutations."""
        return len(self._fact_index)
