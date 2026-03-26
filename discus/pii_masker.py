"""
RTA-GUARD — PII Masking (from NeMo Guardrails)

Replaces detected PII with placeholders instead of blocking.
Based on Presidio AnonymizerEngine.

Usage:
- Kill mode: block the entire message (current behavior)
- Mask mode: replace PII with [TYPE] placeholders (new)
"""
from typing import Optional


def mask_pii_presidio(text: str, score_threshold: float = 0.4) -> Optional[str]:
    """
    Mask PII in text using Presidio Anonymizer.

    Replaces detected PII with placeholders like [EMAIL], [SSN], [PERSON].
    Returns masked text or None if Presidio unavailable.

    Example:
        Input:  "My email is john@example.com and SSN is 123-45-6789"
        Output: "My email is [EMAIL_ADDRESS] and SSN is [US_SSN]"
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig
    except ImportError:
        return None  # Presidio not installed

    try:
        # Create analyzer (reuse from presidio_detector if available)
        from .presidio_detector import _get_presidio_analyzer
        analyzer = _get_presidio_analyzer(score_threshold)
    except Exception:
        # Fallback: create new analyzer
        try:
            configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
            analyzer = AnalyzerEngine(nlp_engine=nlp_engine, default_score_threshold=score_threshold)
        except Exception:
            return None

    # Entities to mask (same as our HIGH_CONFIDENCE_PII)
    entities = [
        "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
        "IP_ADDRESS", "IBAN_CODE", "INDIAN_PAN", "INDIAN_AADHAAR",
        "PERSON", "LOCATION", "MEDICAL_LICENSE",
    ]

    try:
        # Analyze text
        results = analyzer.analyze(text=text, language="en", entities=entities)

        if not results:
            return None  # No PII found

        # Mask detected PII
        anonymizer = AnonymizerEngine()
        operators = {entity: OperatorConfig("replace") for entity in entities}
        masked = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)

        return masked.text

    except Exception:
        return None


def mask_pii_simple(text: str) -> str:
    """
    Simple PII masking using regex patterns (no ML required).

    Replaces common PII patterns with placeholders.
    Less accurate than Presidio but works without dependencies.
    """
    import re

    # Email
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        '[EMAIL]',
        text
    )

    # Phone numbers
    text = re.sub(
        r'\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        '[PHONE]',
        text
    )

    # SSN
    text = re.sub(
        r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',
        '[SSN]',
        text
    )

    # Credit card
    text = re.sub(
        r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
        '[CREDIT_CARD]',
        text
    )

    # IP address
    text = re.sub(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        '[IP_ADDRESS]',
        text
    )

    # Indian PAN
    text = re.sub(
        r'\b[A-Z]{5}\d{4}[A-Z]\b',
        '[PAN]',
        text
    )

    # Aadhaar
    text = re.sub(
        r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
        '[AADHAAR]',
        text
    )

    return text


def mask_pii(text: str, use_presidio: bool = True) -> str:
    """
    Mask PII in text. Uses Presidio if available, falls back to regex.

    Args:
        text: Text to mask
        use_presidio: If True, use Presidio (more accurate). If False, use regex.

    Returns:
        Masked text with PII replaced by placeholders.
    """
    if use_presidio:
        masked = mask_pii_presidio(text)
        if masked is not None:
            return masked

    # Fallback to regex
    return mask_pii_simple(text)
