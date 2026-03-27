"""
RTA-GUARD Federation — Client

Connects to a federation aggregation server.
Sends local fingerprints and receives threat intelligence.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from .fingerprint import BehavioralFingerprinter, SessionFingerprint
from .privacy import DifferentialPrivacy, PrivacyConfig, PrivacyMode
from .protocol import FederationMessage, MessageType

logger = logging.getLogger("discus.federation.client")


class FederationClient:
    """
    Client for connecting to a federation aggregation server.

    Usage:
        client = FederationClient(
            node_id="node-us-east-1",
            server_url="https://aggregator.rta-guard.example.com",
        )
        client.register()
        client.send_fingerprints(local_fingerprints)
        threats = client.get_threat_intel()
    """

    def __init__(self, node_id: str, server_url: str,
                 privacy_mode: PrivacyMode = PrivacyMode.BALANCED,
                 api_key: str = ""):
        self.node_id = node_id
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.config = PrivacyConfig.for_mode(privacy_mode)
        self.privacy = DifferentialPrivacy(self.config)
        self.fingerprinter = BehavioralFingerprinter(node_id=node_id)
        self._client = httpx.Client(timeout=30.0)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._client.post(f"{self.server_url}{path}", json=data, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        resp = self._client.get(f"{self.server_url}{path}", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    # ─── Registration ───────────────────────────────────────────────

    def register(self, local_url: str = "") -> Dict[str, Any]:
        """Register this node with the federation server."""
        return self._post("/api/federation/nodes/register", {
            "node_id": self.node_id,
            "url": local_url,
            "privacy_mode": self.config.mode.value,
        })

    def heartbeat(self) -> Dict[str, Any]:
        """Send heartbeat to server."""
        return self._post("/api/federation/nodes/heartbeat", {
            "node_id": self.node_id,
        })

    # ─── Fingerprint Sharing ────────────────────────────────────────

    def send_fingerprints(self, fingerprints: List[SessionFingerprint]) -> Dict[str, Any]:
        """
        Send anonymized fingerprints to the federation server.
        Applies differential privacy before sending.
        """
        anonymized = []
        for fp in fingerprints:
            noisy_vector = self.privacy.anonymize_fingerprint(
                fp.features.to_vector(), self.node_id
            )
            if noisy_vector is None:
                logger.warning(f"Privacy budget exhausted, skipping fingerprint")
                break
            anonymized.append({
                "session_hash": fp.session_hash,
                "feature_vector": noisy_vector,
                "sample_count": fp.sample_count,
            })

        if not anonymized:
            return {"status": "no_data", "reason": "budget_exhausted_or_no_fingerprints"}

        return self._post("/api/federation/fingerprints/submit", {
            "node_id": self.node_id,
            "fingerprints": anonymized,
        })

    def send_local_fingerprints(self) -> Dict[str, Any]:
        """Generate and send fingerprints from local session data."""
        fps = self.fingerprinter.get_all_fingerprints()
        return self.send_fingerprints(fps)

    # ─── Threat Intelligence ────────────────────────────────────────

    def submit_threat(self, threat_type: str, pattern_hash: str,
                      severity: str = "warn", confidence: float = 0.5,
                      tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Submit a threat signature to the federation."""
        return self._post("/api/federation/threats/submit", {
            "node_id": self.node_id,
            "threat": {
                "threat_type": threat_type,
                "pattern_hash": pattern_hash,
                "severity": severity,
                "confidence": confidence,
                "tags": tags or [],
            },
        })

    def get_threat_intel(self, threat_type: Optional[str] = None,
                         min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Get shared threat intelligence from the federation."""
        params = {"min_confidence": min_confidence}
        if threat_type:
            params["threat_type"] = threat_type
        result = self._get("/api/federation/threats", params=params)
        return result.get("threats", [])

    # ─── Aggregation ────────────────────────────────────────────────

    def request_aggregation(self) -> Dict[str, Any]:
        """Request the server to run aggregation."""
        return self._post("/api/federation/aggregate", {})

    def get_baseline(self) -> Optional[List[float]]:
        """Get the current global baseline vector."""
        try:
            result = self._get("/api/federation/baseline")
            return result.get("baseline_vector")
        except Exception:
            return None

    def get_anomaly_score(self) -> Optional[float]:
        """Get this node's anomaly score from the server."""
        try:
            result = self._get(f"/api/federation/anomaly/{self.node_id}")
            return result.get("distance_from_baseline")
        except Exception:
            return None

    # ─── Stats ──────────────────────────────────────────────────────

    def get_federation_stats(self) -> Dict[str, Any]:
        """Get federation-wide statistics."""
        return self._get("/api/federation/stats")

    def get_privacy_status(self) -> Dict[str, Any]:
        """Get this node's privacy budget status."""
        return {
            "node_id": self.node_id,
            "mode": self.config.mode.value,
            "epsilon": self.config.epsilon,
            "max_budget": self.config.max_budget,
            "budget_remaining": self.privacy.budget.remaining(self.node_id),
            "budget_used": self.privacy.budget.used(self.node_id),
            "queries": self.privacy.budget.query_count(self.node_id),
        }

    def close(self):
        self._client.close()
