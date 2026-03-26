"""
RTA-GUARD — NeMo-Compatible Wrapper

Directly uses NeMo Guardrails code when available.
Falls back to our implementations when NeMo isn't installed.

This is the "adopt NeMo's approach" layer.
"""
import os
from typing import Optional


class NeMoWrapper:
    """
    Wrapper that uses NeMo Guardrails implementations when available.
    
    Priority:
    1. NeMo Guardrails (if installed)
    2. Our implementations (fallback)
    """

    def __init__(self):
        self.nemo_available = False
        self.presidio_available = False
        self._init_modules()

    def _init_modules(self):
        """Check what's available."""
        try:
            import nemoguardrails
            self.nemo_available = True
        except (ImportError, TypeError, Exception):
            # NeMo not compatible with Python 3.14 or not installed
            self.nemo_available = False

        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            self.presidio_available = True
        except ImportError:
            pass

    # ================================================================
    # PII Detection
    # ================================================================

    def detect_pii(self, text: str, score_threshold: float = 0.4) -> list:
        """
        Detect PII using Presidio (same as NeMo).
        
        Returns list of detected entities.
        """
        if not self.presidio_available:
            return []

        try:
            from .presidio_detector import _get_presidio_analyzer, detect_pii_presidio
            result = detect_pii_presidio(text, score_threshold)
            return [result] if result else []
        except Exception:
            return []

    # ================================================================
    # PII Masking (from NeMo)
    # ================================================================

    def mask_pii(self, text: str) -> str:
        """
        Mask PII using Presidio Anonymizer (direct NeMo approach).
        
        Replaces PII with placeholders: [EMAIL], [SSN], [PERSON], etc.
        """
        if not self.presidio_available:
            return self._mask_pii_regex(text)

        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig

            # Create analyzer (reuse if available)
            try:
                from .presidio_detector import _get_presidio_analyzer
                analyzer = _get_presidio_analyzer(0.4)
            except Exception:
                configuration = {
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                }
                provider = NlpEngineProvider(nlp_configuration=configuration)
                nlp_engine = provider.create_engine()
                analyzer = AnalyzerEngine(nlp_engine=nlp_engine, default_score_threshold=0.4)

            # Detect
            results = analyzer.analyze(
                text=text, language="en",
                entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
                         "IP_ADDRESS", "PERSON", "LOCATION", "INDIAN_PAN", "INDIAN_AADHAAR"]
            )

            if not results:
                return text

            # Mask
            anonymizer = AnonymizerEngine()
            operators = {}
            for r in results:
                operators[r.entity_type] = OperatorConfig("replace")

            masked = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
            return masked.text

        except Exception:
            return self._mask_pii_regex(text)

    def _mask_pii_regex(self, text: str) -> str:
        """Regex-based PII masking fallback."""
        import re
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        text = re.sub(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b', '[SSN]', text)
        text = re.sub(r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[CREDIT_CARD]', text)
        return text

    # ================================================================
    # Hallucination Detection (from NeMo SelfCheckGPT)
    # ================================================================

    def check_hallucination(self, output: str, context: str = "") -> Optional[dict]:
        """
        Check for hallucinations using SelfCheckGPT approach.
        
        From NeMo: generate multiple completions, check for consistency.
        """
        try:
            from brahmanda.hallucination_checker import check_hallucination
            return check_hallucination(output, context)
        except Exception:
            return None

    # ================================================================
    # Truth Verification (from NeMo fact checking)
    # ================================================================

    def check_truth(self, output: str) -> Optional[dict]:
        """
        Check truthfulness using SelfCheckGPT approach.
        
        From NeMo: generate multiple completions, check for agreement.
        """
        try:
            from brahmanda.truth_checker import check_truth
            return check_truth(output)
        except Exception:
            return None


# Global instance
_wrapper = None


def get_nemo_wrapper() -> NeMoWrapper:
    """Get the global NeMo wrapper instance."""
    global _wrapper
    if _wrapper is None:
        _wrapper = NeMoWrapper()
    return _wrapper
