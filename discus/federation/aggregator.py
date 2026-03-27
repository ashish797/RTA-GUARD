"""
RTA-GUARD Federation — Aggregation Server

Collects anonymized fingerprints from multiple nodes,
aggregates drift signals, and shares threat intelligence.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from .fingerprint import BehavioralFingerprinter, SessionFingerprint
from .privacy import DifferentialPrivacy, PrivacyConfig, PrivacyMode
from .protocol import (
    FederationStore, FederationNode, ThreatSignature,
    FederationMessage, MessageType,
)

logger = logging.getLogger("discus.federation.aggregator")


@dataclass
class AggregationResult:
    """Result of a multi-node aggregation."""
    baseline_vector: List[float]
    participant_count: int
    anomaly_scores: Dict[str, float]  # node_id → anomaly score
    shared_threats: List[ThreatSignature]
    privacy_budget_remaining: Dict[str, float]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_vector": self.baseline_vector,
            "participant_count": self.participant_count,
            "anomaly_scores": self.anomaly_scores,
            "shared_threats": [t.to_dict() for t in self.shared_threats],
            "privacy_budget_remaining": self.privacy_budget_remaining,
            "timestamp": self.timestamp,
        }


class AggregationServer:
    """
    Federation aggregation server.

    Responsibilities:
    1. Receive anonymized fingerprints from nodes
    2. Compute global baseline from aggregated data
    3. Detect anomalous nodes (those deviating from baseline)
    4. Share threat intelligence across nodes
    5. Enforce privacy budgets
    """

    def __init__(self, node_id: str = "aggregator",
                 privacy_mode: PrivacyMode = PrivacyMode.BALANCED,
                 db_path: Optional[str] = None):
        self.node_id = node_id
        self.config = PrivacyConfig.for_mode(privacy_mode)
        self.privacy = DifferentialPrivacy(self.config)
        self.store = FederationStore(db_path=Path(db_path) if db_path else None)

        # In-memory aggregation state
        self._fingerprints: Dict[str, List[List[float]]] = {}  # node_id → vectors
        self._baseline: Optional[List[float]] = None
        self._last_aggregation: float = 0

    # ─── Node Management ────────────────────────────────────────────

    def register_node(self, node: FederationNode) -> Dict[str, Any]:
        """Register a new federation node."""
        self.store.register_node(node)
        logger.info(f"Node registered: {node.node_id} at {node.url}")
        return {"status": "registered", "node_id": node.node_id}

    def list_nodes(self) -> List[Dict[str, Any]]:
        """List all registered nodes."""
        return [n.to_dict() for n in self.store.list_nodes()]

    def heartbeat(self, node_id: str) -> Dict[str, Any]:
        """Process heartbeat from a node."""
        self.store.update_heartbeat(node_id)
        return {"status": "ok", "node_id": node_id, "timestamp": time.time()}

    # ─── Fingerprint Aggregation ────────────────────────────────────

    def submit_fingerprints(self, node_id: str,
                            fingerprints: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Receive anonymized fingerprints from a node.
        Each fingerprint should have: session_hash, feature_vector, sample_count.
        """
        if not self.privacy.budget.can_spend(node_id, self.config.epsilon):
            return {"status": "budget_exhausted", "remaining": self.privacy.budget.remaining(node_id)}

        received = 0
        for fp in fingerprints:
            # Store in database
            self.store.store_fingerprint(
                session_hash=fp["session_hash"],
                source_node=node_id,
                feature_vector=fp["feature_vector"],
                sample_count=fp.get("sample_count", 0),
            )
            # Add to in-memory aggregation
            if node_id not in self._fingerprints:
                self._fingerprints[node_id] = []
            self._fingerprints[node_id].append(fp["feature_vector"])
            received += 1

        # Spend budget
        self.privacy.budget.spend(node_id, self.config.epsilon)

        logger.info(f"Received {received} fingerprints from {node_id}")
        return {
            "status": "accepted",
            "received": received,
            "budget_remaining": self.privacy.budget.remaining(node_id),
        }

    def run_aggregation(self) -> AggregationResult:
        """
        Run global aggregation across all submitted fingerprints.

        1. Collect all vectors from all nodes
        2. Add differential privacy noise (already done per-node)
        3. Compute global baseline (average)
        4. Score each node's deviation from baseline
        5. Identify shared threats
        """
        all_vectors = []
        node_ids = []

        for nid, vectors in self._fingerprints.items():
            for vec in vectors:
                all_vectors.append(vec)
                node_ids.append(nid)

        if not all_vectors:
            return AggregationResult(
                baseline_vector=[], participant_count=0,
                anomaly_scores={}, shared_threats=[],
                privacy_budget_remaining={}, timestamp=time.time(),
            )

        # Compute baseline (average of all vectors)
        dim = len(all_vectors[0])
        baseline = [0.0] * dim
        for vec in all_vectors:
            for i in range(dim):
                baseline[i] += vec[i]
        baseline = [v / len(all_vectors) for v in baseline]
        self._baseline = baseline

        # Compute per-node anomaly scores
        anomaly_scores = {}
        node_vectors = {}
        for vec, nid in zip(all_vectors, node_ids):
            if nid not in node_vectors:
                node_vectors[nid] = []
            node_vectors[nid].append(vec)

        for nid, vecs in node_vectors.items():
            # Average vector for this node
            node_avg = [0.0] * dim
            for vec in vecs:
                for i in range(dim):
                    node_avg[i] += vec[i]
            node_avg = [v / len(vecs) for v in node_avg]

            # Distance from global baseline
            _, distance = self.privacy.detect_anomaly_from_baseline(node_avg, baseline)
            anomaly_scores[nid] = distance

        # Gather threat intel
        threats = self.store.get_threats(min_confidence=0.5)

        # Budget status
        budget_status = {}
        for nid in set(node_ids):
            budget_status[nid] = self.privacy.budget.remaining(nid)

        self._last_aggregation = time.time()

        return AggregationResult(
            baseline_vector=baseline,
            participant_count=len(set(node_ids)),
            anomaly_scores=anomaly_scores,
            shared_threats=threats,
            privacy_budget_remaining=budget_status,
            timestamp=time.time(),
        )

    # ─── Threat Intelligence ────────────────────────────────────────

    def submit_threat(self, node_id: str, threat: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a threat signature from a node.
        Deduplicates by pattern_hash.
        """
        pattern_hash = threat.get("pattern_hash", "")
        if not pattern_hash:
            return {"status": "invalid", "reason": "missing pattern_hash"}

        # Check for existing signature
        existing = self.store.get_threats(threat_type=threat.get("threat_type"))
        for sig in existing:
            if sig.pattern_hash == pattern_hash:
                # Increment count
                self.store.increment_threat_count(sig.signature_id)
                return {"status": "updated", "signature_id": sig.signature_id,
                        "seen_count": sig.seen_count + 1}

        # New threat
        sig_id = hashlib.sha256(f"{node_id}:{pattern_hash}:{time.time()}".encode()).hexdigest()[:16]
        sig = ThreatSignature(
            signature_id=sig_id,
            threat_type=threat["threat_type"],
            pattern_hash=pattern_hash,
            severity=threat.get("severity", "warn"),
            confidence=threat.get("confidence", 0.5),
            source_node=node_id,
            tags=threat.get("tags", []),
        )
        self.store.store_threat(sig)
        logger.info(f"New threat signature: {sig.threat_type} from {node_id}")
        return {"status": "created", "signature_id": sig_id}

    def get_threat_intel(self, threat_type: Optional[str] = None,
                         min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Get shared threat intelligence."""
        threats = self.store.get_threats(threat_type=threat_type, min_confidence=min_confidence)
        return [t.to_dict() for t in threats]

    # ─── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get federation statistics."""
        store_stats = self.store.get_stats()
        return {
            **store_stats,
            "privacy_budget": self.privacy.budget.stats(),
            "privacy_mode": self.config.mode.value,
            "last_aggregation": self._last_aggregation,
            "active_nodes_in_memory": len(self._fingerprints),
            "baseline_computed": self._baseline is not None,
        }

    def get_node_anomaly(self, node_id: str) -> Dict[str, Any]:
        """Get anomaly assessment for a specific node."""
        if self._baseline is None:
            return {"node_id": node_id, "status": "no_baseline"}

        vectors = self._fingerprints.get(node_id, [])
        if not vectors:
            return {"node_id": node_id, "status": "no_data"}

        dim = len(vectors[0])
        node_avg = [0.0] * dim
        for vec in vectors:
            for i in range(dim):
                node_avg[i] += vec[i]
        node_avg = [v / len(vectors) for v in node_avg]

        is_anomalous, distance = self.privacy.detect_anomaly_from_baseline(
            node_avg, self._baseline
        )

        return {
            "node_id": node_id,
            "is_anomalous": is_anomalous,
            "distance_from_baseline": round(distance, 4),
            "sample_count": len(vectors),
            "baseline_dim": len(self._baseline),
        }
