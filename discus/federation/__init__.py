"""
RTA-GUARD Federation

Privacy-preserving federated learning for multi-node AI agent security.
Shares behavioral fingerprints and threat intelligence without exposing raw data.
"""
from .fingerprint import BehavioralFingerprinter, BehavioralFeatures, SessionFingerprint
from .privacy import DifferentialPrivacy, PrivacyBudget, PrivacyConfig, PrivacyMode
from .protocol import (
    FederationStore, FederationNode, ThreatSignature,
    FederationMessage, MessageType,
)
from .aggregator import AggregationServer, AggregationResult
from .client import FederationClient

__all__ = [
    "BehavioralFingerprinter", "BehavioralFeatures", "SessionFingerprint",
    "DifferentialPrivacy", "PrivacyBudget", "PrivacyConfig", "PrivacyMode",
    "FederationStore", "FederationNode", "ThreatSignature",
    "FederationMessage", "MessageType",
    "AggregationServer", "AggregationResult",
    "FederationClient",
]
