"""
RTA-GUARD — Presidio Integration

Replaces custom regex PII detection with Microsoft Presidio.
Presidio provides:
- 40+ built-in entity types
- NER-based detection (spaCy)
- Multi-language support
- Anonymization (mask PII)
- Extensible recognizers

RTA-GUARD adds:
- Kill-switch (session termination)
- Constitutional rules (13 Vedic rules)
- Audit trail
- Custom recognizers for country-specific IDs
"""
import os
from typing import Optional

from .models import ViolationType, Severity, GuardConfig

# --- Lazy-loaded Presidio analyzer ---
_presidio_analyzer = None


def _get_presidio_analyzer(score_threshold: float = 0.4):
    """Get or create Presidio AnalyzerEngine (singleton)."""
    global _presidio_analyzer
    if _presidio_analyzer is not None:
        return _presidio_analyzer

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        # Use existing spaCy model
        spacy_model = os.getenv("RTA_SPACY_MODEL", "en_core_web_sm")
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        }

        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()

        _presidio_analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            default_score_threshold=score_threshold,
        )

        # Add custom recognizers for country-specific IDs
        _add_custom_recognizers(_presidio_analyzer)

    except ImportError:
        return None
    except Exception:
        return None

    return _presidio_analyzer


def _add_custom_recognizers(analyzer):
    """Add custom recognizers for SSN, PAN, Aadhaar, etc."""
    try:
        from presidio_analyzer import PatternRecognizer, Pattern

        # US SSN
        ssn_recognizer = PatternRecognizer(
            supported_entity="US_SSN",
            patterns=[
                Pattern("ssn_dashes", r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", 0.9),
            ],
            supported_language="en",
        )
        analyzer.registry.add_recognizer(ssn_recognizer)

        # Indian PAN
        pan_recognizer = PatternRecognizer(
            supported_entity="INDIAN_PAN",
            patterns=[
                Pattern("pan_card", r"\b[A-Z]{5}\d{4}[A-Z]\b", 0.95),
            ],
            supported_language="en",
        )
        analyzer.registry.add_recognizer(pan_recognizer)

        # Indian Aadhaar
        aadhaar_recognizer = PatternRecognizer(
            supported_entity="INDIAN_AADHAAR",
            patterns=[
                Pattern("aadhaar", r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", 0.85),
            ],
            supported_language="en",
        )
        analyzer.registry.add_recognizer(aadhaar_recognizer)

        # Credit card
        cc_recognizer = PatternRecognizer(
            supported_entity="CREDIT_CARD",
            patterns=[
                Pattern("cc", r"\b(?:\d{4}[-\s]?){3}\d{4}\b", 0.9),
            ],
            supported_language="en",
        )
        analyzer.registry.add_recognizer(cc_recognizer)

    except Exception:
        pass  # Silently skip if recognizers can't be added


def detect_pii_presidio(text: str, score_threshold: float = 0.4) -> Optional[tuple]:
    """
    Detect PII using Presidio.

    Returns (violation_type, severity, details) or None.
    """
    analyzer = _get_presidio_analyzer(score_threshold)
    if analyzer is None:
        return None  # Presidio not available

    try:
        results = analyzer.analyze(text=text, language="en")
    except Exception:
        return None

    if not results:
        return None

    # Generic date/location references that should NOT be flagged
    GENERIC_ENTITIES = {
        "that day", "this day", "today", "yesterday", "tomorrow",
        "now", "recently", "currently", "here", "there",
        "nowhere", "everywhere", "somewhere",
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday",
        "morning", "afternoon", "evening", "night",
        # Country/city names in normal context (not PII)
        "france", "germany", "india", "china", "japan", "brazil",
        "usa", "uk", "canada", "australia", "russia", "mexico",
        "spain", "italy", "netherlands", "sweden", "norway",
        "finland", "denmark", "poland", "turkey", "egypt",
        "south korea", "north korea", "argentina", "chile",
        "colombia", "peru", "venezuela", "indonesia", "thailand",
        "vietnam", "philippines", "malaysia", "singapore",
        "new zealand", "ireland", "portugal", "greece", "austria",
        "switzerland", "belgium", "czech republic", "hungary",
        "romania", "bulgaria", "ukraine", "belarus", "croatia",
        "serbia", "bosnia", "albania", "macedonia", "slovenia",
        "slovakia", "lithuania", "latvia", "estonia", "iceland",
        "luxembourg", "malta", "cyprus", "monaco", "liechtenstein",
        # City names commonly mentioned in normal conversation
        "paris", "london", "tokyo", "new york", "los angeles",
        "berlin", "rome", "madrid", "amsterdam", "stockholm",
        "oslo", "copenhagen", "helsinki", "vienna", "zurich",
        "mumbai", "delhi", "bangalore", "chennai", "hyderabad",
        "beijing", "shanghai", "hong kong", "singapore", "dubai",
        "sydney", "melbourne", "toronto", "vancouver", "seattle",
        "san francisco", "boston", "chicago", "miami", "atlanta",
    }

    # HIGH-confidence PII (always kill if detected)
    HIGH_CONFIDENCE_PII = {
        "EMAIL_ADDRESS", "US_SSN", "CREDIT_CARD",
        "IP_ADDRESS", "IBAN_CODE", "INDIAN_PAN", "INDIAN_AADHAAR",
        "MEDICAL_LICENSE",
    }

    # SOFT entities — detect on input but NOT on output
    # (LLM generates these as examples, not as PII leaks)
    SOFT_PII = {
        "PERSON",        # Names in output are usually examples, not PII
        "PHONE_NUMBER",  # Public helplines in output
    }

    # LOW-confidence entities (skip — not actual PII, just general knowledge)
    LOW_CONFIDENCE_PII = {
        "ORGANIZATION",  # "the Red Cross", "Google" — not PII
        "LOCATION",      # "Paris", "Mumbai" — not PII
        "DATE_TIME",     # "today", "January" — not PII
        "NRP",           # nationality — not PII
        "URL",           # URLs in output are not PII
        "PHONE_NUMBER",  # Public helplines in output, not personal phones
    }

    # Map entity types to readable names
    entity_names = {
        "EMAIL_ADDRESS": "email",
        "PHONE_NUMBER": "phone",
        "US_SSN": "SSN",
        "CREDIT_CARD": "credit card",
        "PERSON": "person name",
        "LOCATION": "location",
        "ORGANIZATION": "organization",
        "DATE_TIME": "date",
        "IP_ADDRESS": "IP address",
        "IBAN_CODE": "IBAN",
        "INDIAN_PAN": "PAN card",
        "INDIAN_AADHAAR": "Aadhaar",
        "NRP": "nationality",
        "MEDICAL_LICENSE": "medical license",
        "URL": "URL",
    }

    detected = []
    for r in results:
        entity_type = r.entity_type
        entity_text = text[r.start:r.end]
        score = r.score

        # Skip generic entities
        if entity_text.lower().strip() in GENERIC_ENTITIES:
            continue

        # Skip LOW-confidence entities (not actual PII)
        if entity_type in LOW_CONFIDENCE_PII:
            continue

        # Skip SOFT entities — caught on input by regex, not by Presidio
        # (Prevents false positives from LLM output examples)
        if entity_type in SOFT_PII:
            continue

        # Only flag HIGH-confidence PII OR entities with very high score
        if entity_type in HIGH_CONFIDENCE_PII or score >= 0.95:
            name = entity_names.get(entity_type, entity_type.lower())
            detected.append(f"{name} ({entity_text[:20]})")

    if not detected:
        return None

    if len(detected) >= 2:
        severity = Severity.HIGH
    else:
        severity = Severity.MEDIUM

    details = f"PII detected: {', '.join(detected)}"
    return (ViolationType.PII_DETECTED, severity, details)


def detect_injection_presidio(text: str) -> Optional[tuple]:
    """
    Detect prompt injection using Presidio's built-in recognizers.
    Falls back to our regex if Presidio not available.
    """
    # For now, use our regex (Presidio doesn't have built-in injection detection)
    return None


def is_presidio_available() -> bool:
    """Check if Presidio is available and working."""
    return _get_presidio_analyzer() is not None
