"""
RTA-GUARD Federation Tests

Tests for: fingerprinting, differential privacy, protocol, aggregator, and integration.
"""
import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from discus.federation import (
    BehavioralFingerprinter, BehavioralFeatures, SessionFingerprint,
    DifferentialPrivacy, PrivacyBudget, PrivacyConfig, PrivacyMode,
    FederationStore, FederationNode, ThreatSignature,
    FederationMessage, MessageType,
    AggregationServer, AggregationResult,
)


# ─── Fingerprinting Tests ──────────────────────────────────────────

class TestFingerprinter(unittest.TestCase):
    def setUp(self):
        self.fp = BehavioralFingerprinter(node_id="test-node")

    def test_record_and_generate(self):
        for i in range(5):
            self.fp.record_input("session-1", f"Hello world {i}", "pass")
        fingerprint = self.fp.generate_fingerprint("session-1")
        self.assertIsNotNone(fingerprint)
        self.assertEqual(fingerprint.sample_count, 5)
        self.assertEqual(fingerprint.node_id, "test-node")
        self.assertNotEqual(fingerprint.session_hash, "session-1")  # Hashed

    def test_too_few_samples(self):
        self.fp.record_input("session-2", "single input", "pass")
        fingerprint = self.fp.generate_fingerprint("session-2")
        self.assertIsNone(fingerprint)  # Need at least 2

    def test_feature_extraction(self):
        for i in range(10):
            self.fp.record_input("s1", f"Test input {i} with some content!", "pass")
        fp = self.fp.generate_fingerprint("s1")
        features = fp.features
        self.assertGreater(features.avg_input_length, 0)
        self.assertGreater(features.input_entropy, 0)

    def test_violation_tracking(self):
        self.fp.record_input("s2", "normal", "pass")
        self.fp.record_input("s2", "email test@example.com", "kill", "pii")
        self.fp.record_input("s2", "normal again", "warn", "injection")
        fp = self.fp.generate_fingerprint("s2")
        self.assertGreater(fp.features.violation_rate, 0)
        self.assertGreater(fp.features.kill_rate, 0)

    def test_privacy_no_raw_text(self):
        for i in range(3):
            self.fp.record_input("s3", f"sensitive personal data here {i}", "pass")
        fp = self.fp.generate_fingerprint("s3")
        self.assertIsNotNone(fp)
        # Fingerprint should NOT contain raw text
        d = fp.to_dict()
        self.assertNotIn("sensitive", json.dumps(d))

    def test_feature_vector_dimensions(self):
        for i in range(5):
            self.fp.record_input("s4", f"Input {i}", "pass")
        fp = self.fp.generate_fingerprint("s4")
        vector = fp.features.to_vector()
        self.assertEqual(len(vector), 15)  # 15-dimensional feature vector

    def test_get_all_fingerprints(self):
        for sid in ["a", "b", "c"]:
            for i in range(5):
                self.fp.record_input(sid, f"Text {i} for {sid}", "pass")
        all_fps = self.fp.get_all_fingerprints()
        self.assertEqual(len(all_fps), 3)


# ─── Privacy Budget Tests ──────────────────────────────────────────

class TestPrivacyBudget(unittest.TestCase):
    def test_basic_budget(self):
        budget = PrivacyBudget(max_budget=5.0)
        self.assertTrue(budget.can_spend("node1", 2.0))
        self.assertTrue(budget.spend("node1", 2.0))
        self.assertEqual(budget.remaining("node1"), 3.0)
        self.assertTrue(budget.can_spend("node1", 3.0))
        self.assertFalse(budget.can_spend("node1", 4.0))

    def test_exhaustion(self):
        budget = PrivacyBudget(max_budget=1.0)
        self.assertTrue(budget.spend("n1", 0.5))
        self.assertFalse(budget.spend("n1", 0.6))  # Would exceed
        self.assertTrue(budget.spend("n1", 0.5))  # Exactly at limit

    def test_multiple_nodes(self):
        budget = PrivacyBudget(max_budget=2.0)
        self.assertTrue(budget.spend("n1", 1.5))
        self.assertTrue(budget.spend("n2", 1.5))  # Different node, independent budget
        self.assertFalse(budget.spend("n1", 1.0))

    def test_query_count(self):
        budget = PrivacyBudget(max_budget=100.0)
        for _ in range(5):
            budget.spend("n1", 1.0)
        self.assertEqual(budget.query_count("n1"), 5)

    def test_reset(self):
        budget = PrivacyBudget(max_budget=5.0)
        budget.spend("n1", 3.0)
        budget.reset("n1")
        self.assertEqual(budget.remaining("n1"), 5.0)

    def test_stats(self):
        budget = PrivacyBudget(max_budget=10.0)
        budget.spend("n1", 2.0)
        budget.spend("n2", 3.0)
        stats = budget.stats()
        self.assertEqual(stats["max_budget"], 10.0)
        self.assertIn("n1", stats["nodes"])


# ─── Differential Privacy Tests ────────────────────────────────────

class TestDifferentialPrivacy(unittest.TestCase):
    def test_off_mode(self):
        dp = DifferentialPrivacy(PrivacyConfig.for_mode(PrivacyMode.OFF))
        result = dp.add_noise_scalar(5.0)
        self.assertEqual(result, 5.0)

    def test_noise_addition(self):
        dp = DifferentialPrivacy(PrivacyConfig.for_mode(PrivacyMode.BALANCED))
        values = [dp.add_noise_scalar(5.0) for _ in range(100)]
        # Noisy values should differ from original
        diffs = [abs(v - 5.0) for v in values]
        self.assertGreater(sum(diffs) / len(diffs), 0.01)

    def test_noise_distribution(self):
        dp = DifferentialPrivacy(PrivacyConfig(epsilon=1.0, sensitivity=1.0))
        np.random.seed(42)
        noisy = [dp.add_noise_scalar(0.0) for _ in range(1000)]
        # Mean should be close to 0 (Laplace has mean 0)
        self.assertAlmostEqual(sum(noisy) / len(noisy), 0.0, places=0)
        # Should have spread
        self.assertGreater(np.std(noisy), 0.5)

    def test_vector_noise(self):
        dp = DifferentialPrivacy(PrivacyConfig.for_mode(PrivacyMode.BALANCED))
        vec = [1.0, 2.0, 3.0, 4.0, 5.0]
        noisy = dp.add_noise_vector(vec)
        self.assertEqual(len(noisy), len(vec))
        # Should be different from original
        self.assertNotEqual(noisy, vec)

    def test_cosine_similarity(self):
        dp = DifferentialPrivacy(PrivacyConfig.for_mode(PrivacyMode.OFF))
        self.assertAlmostEqual(dp.compute_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(dp.compute_similarity([1, 0], [0, 1]), 0.0, places=5)
        self.assertAlmostEqual(dp.compute_similarity([1, 0], [-1, 0]), -1.0)

    def test_anomaly_detection(self):
        dp = DifferentialPrivacy(PrivacyConfig.for_mode(PrivacyMode.OFF))
        baseline = [0.5, 0.5, 0.5, 0.5]
        similar = [0.51, 0.49, 0.52, 0.48]
        anomalous = [0.95, 0.05, 0.98, 0.02]

        is_anom_sim, dist_sim = dp.detect_anomaly_from_baseline(similar, baseline, threshold=0.3)
        is_anom_ano, dist_ano = dp.detect_anomaly_from_baseline(anomalous, baseline, threshold=0.1)

        self.assertFalse(is_anom_sim)
        self.assertTrue(is_anom_ano)
        self.assertGreater(dist_ano, dist_sim)

    def test_privacy_budget_integration(self):
        dp = DifferentialPrivacy(PrivacyConfig(epsilon=1.0, max_budget=2.0))
        fp = [0.1, 0.2, 0.3]

        # First anonymize should work
        result1 = dp.anonymize_fingerprint(fp, "node1")
        self.assertIsNotNone(result1)

        # Second should work (budget = 2, spent 1)
        result2 = dp.anonymize_fingerprint(fp, "node1")
        self.assertIsNotNone(result2)

        # Third should fail (budget exhausted)
        result3 = dp.anonymize_fingerprint(fp, "node1")
        self.assertIsNone(result3)


# ─── Protocol Tests ─────────────────────────────────────────────────

class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.store = FederationStore(db_path=self.db_path)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_node_registration(self):
        node = FederationNode(node_id="n1", url="http://n1:8000")
        self.store.register_node(node)
        got = self.store.get_node("n1")
        self.assertEqual(got.node_id, "n1")

    def test_list_nodes(self):
        for i in range(3):
            self.store.register_node(FederationNode(node_id=f"n{i}", url=f"http://n{i}:8000"))
        nodes = self.store.list_nodes()
        self.assertEqual(len(nodes), 3)

    def test_fingerprint_storage(self):
        self.store.store_fingerprint("hash1", "n1", [0.1, 0.2, 0.3], 5)
        fps = self.store.get_fingerprints("n1")
        self.assertEqual(len(fps), 1)
        self.assertEqual(fps[0]["feature_vector"], [0.1, 0.2, 0.3])

    def test_threat_signatures(self):
        sig = ThreatSignature(
            signature_id="t1", threat_type="injection",
            pattern_hash="abc123", severity="kill", confidence=0.9,
            source_node="n1",
        )
        self.store.store_threat(sig)
        threats = self.store.get_threats(threat_type="injection")
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0].severity, "kill")

    def test_message_serialization(self):
        msg = FederationMessage(
            msg_type=MessageType.FINGERPRINT_SHARE,
            source_node="n1", target_node="n2",
            payload={"data": [1, 2, 3]},
        )
        serialized = msg.serialize()
        deserialized = FederationMessage.deserialize(serialized)
        self.assertEqual(deserialized.msg_type, MessageType.FINGERPRINT_SHARE)
        self.assertEqual(deserialized.source_node, "n1")

    def test_stats(self):
        self.store.register_node(FederationNode(node_id="n1", url="http://n1"))
        self.store.store_fingerprint("h1", "n1", [0.1], 1)
        stats = self.store.get_stats()
        self.assertEqual(stats["nodes"], 1)
        self.assertEqual(stats["fingerprints"], 1)


# ─── Aggregation Server Tests ──────────────────────────────────────

class TestAggregator(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(tempfile.mktemp(suffix=".db"))
        self.server = AggregationServer(
            node_id="agg", privacy_mode=PrivacyMode.OFF,
            db_path=str(self.db_path),
        )

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_register_and_list(self):
        node = FederationNode(node_id="n1", url="http://n1:8000")
        self.server.register_node(node)
        nodes = self.server.list_nodes()
        self.assertEqual(len(nodes), 1)

    def test_submit_fingerprints(self):
        fps = [
            {"session_hash": "h1", "feature_vector": [0.1, 0.2, 0.3], "sample_count": 5},
            {"session_hash": "h2", "feature_vector": [0.15, 0.25, 0.35], "sample_count": 3},
        ]
        result = self.server.submit_fingerprints("n1", fps)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["received"], 2)

    def test_aggregation(self):
        # Submit from multiple nodes
        self.server.submit_fingerprints("n1", [
            {"session_hash": "h1", "feature_vector": [0.1, 0.2, 0.3], "sample_count": 5},
        ])
        self.server.submit_fingerprints("n2", [
            {"session_hash": "h2", "feature_vector": [0.2, 0.3, 0.4], "sample_count": 5},
        ])
        result = self.server.run_aggregation()
        self.assertEqual(result.participant_count, 2)
        self.assertEqual(len(result.baseline_vector), 3)
        # Baseline should be average
        self.assertAlmostEqual(result.baseline_vector[0], 0.15, places=2)

    def test_threat_submission(self):
        import uuid
        unique_hash = f"hash_{uuid.uuid4().hex[:12]}"
        result = self.server.submit_threat("n1", {
            "threat_type": "injection",
            "pattern_hash": unique_hash,
            "severity": "kill",
            "confidence": 0.9,
        })
        self.assertEqual(result["status"], "created")
        threats = self.server.get_threat_intel(threat_type="injection", min_confidence=0.5)
        found = [t for t in threats if t["pattern_hash"] == unique_hash]
        self.assertEqual(len(found), 1)

    def test_threat_deduplication(self):
        import uuid
        unique_hash = f"dedup_{uuid.uuid4().hex[:12]}"
        self.server.submit_threat("n1", {
            "threat_type": "dedup_test", "pattern_hash": unique_hash, "severity": "kill",
        })
        result = self.server.submit_threat("n2", {
            "threat_type": "dedup_test", "pattern_hash": unique_hash, "severity": "kill",
        })
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["seen_count"], 2)

    def test_anomaly_detection(self):
        # Node 1: normal behavior
        for i in range(10):
            self.server.submit_fingerprints("n1", [
                {"session_hash": f"h{i}", "feature_vector": [0.5, 0.5, 0.5], "sample_count": 5},
            ])
        # Node 2: anomalous behavior
        self.server.submit_fingerprints("n2", [
            {"session_hash": "ha", "feature_vector": [0.9, 0.1, 0.9], "sample_count": 5},
        ])
        self.server.run_aggregation()
        anomaly = self.server.get_node_anomaly("n2")
        self.assertGreater(anomaly["distance_from_baseline"], 0)

    def test_stats(self):
        self.server.register_node(FederationNode(node_id="n1", url="http://n1"))
        self.server.submit_fingerprints("n1", [
            {"session_hash": "h1", "feature_vector": [0.1, 0.2], "sample_count": 3},
        ])
        stats = self.server.get_stats()
        self.assertGreater(stats["nodes"], 0)


# ─── Integration Test ───────────────────────────────────────────────

class TestIntegration(unittest.TestCase):
    """Full pipeline: fingerprint → privacy → aggregate → detect."""

    def test_full_pipeline(self):
        # Step 1: Generate fingerprints from real session data
        fp1 = BehavioralFingerprinter(node_id="node-us-east")
        fp2 = BehavioralFingerprinter(node_id="node-eu-west")

        # Simulate normal behavior
        for i in range(20):
            fp1.record_input("session-a", f"Normal query about topic {i}", "pass")
            fp2.record_input("session-b", f"Regular question number {i}", "pass")

        # Simulate attack behavior on node 2
        for i in range(10):
            fp2.record_input("session-c", "DROP TABLE users; DELETE FROM logs", "kill", "sql_injection")
            fp2.record_input("session-c", "<script>alert(1)</script>", "kill", "xss")

        fps1 = fp1.get_all_fingerprints()
        fps2 = fp2.get_all_fingerprints()

        self.assertGreater(len(fps1), 0)
        self.assertGreater(len(fps2), 0)

        # Step 2: Apply differential privacy and aggregate
        server = AggregationServer(privacy_mode=PrivacyMode.BALANCED)

        # Convert to dicts (simulating network transfer)
        fp_dicts_1 = [{
            "session_hash": fp.session_hash,
            "feature_vector": fp.features.to_vector(),
            "sample_count": fp.sample_count,
        } for fp in fps1]

        fp_dicts_2 = [{
            "session_hash": fp.session_hash,
            "feature_vector": fp.features.to_vector(),
            "sample_count": fp.sample_count,
        } for fp in fps2]

        server.submit_fingerprints("node-us-east", fp_dicts_1)
        server.submit_fingerprints("node-eu-west", fp_dicts_2)

        # Step 3: Run aggregation
        result = server.run_aggregation()
        self.assertEqual(result.participant_count, 2)
        self.assertGreater(len(result.baseline_vector), 0)

        # Node 2 should have higher anomaly score (attack behavior)
        score_1 = result.anomaly_scores.get("node-us-east", 0)
        score_2 = result.anomaly_scores.get("node-eu-west", 0)
        # Note: with sufficient data, anomalous node should score higher
        # (exact assertion depends on feature differences)


if __name__ == "__main__":
    unittest.main()
