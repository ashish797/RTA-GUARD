"""
RTA-GUARD — Dynamic PII Detector (NER-based)

Uses spaCy Named Entity Recognition to detect PII that doesn't follow
regex patterns: names, addresses, organizations, financial data, etc.

Falls back gracefully if spaCy not installed.
"""
import os
import re
from typing import Optional

# --- Contextual patterns that indicate PII follows ---
PII_CONTEXT_PATTERNS = [
    # Personal identifiers
    (r"\bmy\s+name\s+is\b", "PERSON", "Name introduction"),
    (r"\bI\s+am\s+called\b", "PERSON", "Name introduction"),
    (r"\bcall\s+me\b", "PERSON", "Name introduction"),
    (r"\bI'm\s+(?:a|an|the)\s+\w+", "PERSON", "Self-identification"),

    # Address indicators
    (r"\b(?:my|our|the)\s+(?:home|house|office|apartment|flat)\s+(?:is\s+(?:at|on|in)|address)", "GPE", "Address context"),
    (r"\bI\s+live\s+(?:at|on|in)\b", "GPE", "Address context"),
    (r"\bI\s+reside\s+(?:at|in)\b", "GPE", "Address context"),
    (r"\b(?:my|our)\s+address\s+is\b", "GPE", "Address context"),

    # Financial context
    (r"\bmy\s+(?:salary|income|earnings)\s+is\b", "MONEY", "Financial context"),
    (r"\bI\s+earn\b", "MONEY", "Financial context"),
    (r"\bmy\s+(?:bank|savings|current)\s+account\b", "MONEY", "Financial context"),
    (r"\baccount\s+(?:number|no)\b", "FIN_ACCOUNT", "Account number"),

    # Medical context
    (r"\bmy\s+(?:blood\s+type|diagnosis|condition|medication|prescription)\b", "MEDICAL", "Medical context"),
    (r"\bI\s+(?:have|suffer\s+from|was\s+diagnosed\s+with)\b", "MEDICAL", "Medical context"),
    (r"\bmy\s+(?:health|medical)\s+(?:record|history|data)\b", "MEDICAL", "Medical context"),

    # Phone/contact context
    (r"\b(?:call|reach|contact)\s+me\s+(?:at|on)\b", "PHONE", "Contact context"),
    (r"\bmy\s+(?:phone|mobile|cell)\s+(?:number|no)\b", "PHONE", "Phone context"),

    # Family/personal context
    (r"\bmy\s+(?:father|mother|spouse|husband|wife|son|daughter|child)\b", "PERSON", "Family context"),
    (r"\bmy\s+(?:date\s+of\s+birth|birthday|dob)\s+is\b", "DOB", "DOB context"),
]

# --- Sensitive entity types from spaCy ---
SENSITIVE_ENTITY_TYPES = {
    "PERSON": "Personal name",
    "ORG": "Organization",
    "GPE": "Geopolitical entity (city/country)",
    "LOC": "Location",
    "DATE": "Date (potential DOB)",
    "MONEY": "Financial amount",
    "CARDINAL": "Number (potential ID)",
    "NORP": "Nationality/religion",
    "FAC": "Facility (address component)",
}

# High-sensitivity entities (always flag)
HIGH_SENSITIVITY_ENTITIES = {"PERSON", "MONEY", "GPE", "LOC"}

# Generic dates that should NOT be flagged
GENERIC_DATES = {
    "today", "yesterday", "tomorrow", "now", "this morning",
    "this afternoon", "this evening", "tonight", "last night",
    "this week", "last week", "next week", "this month",
    "last month", "next month", "this year", "last year",
    "next year", "recently", "currently", "lately",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "morning", "afternoon", "evening", "night",
}


class NerPiiDetector:
    """
    NER-based PII detector using spaCy.

    Detects sensitive entities that regex patterns miss:
    - Person names ("John Smith")
    - Addresses ("42 MG Road, Mumbai")
    - Financial amounts ("₹50,000")
    - Medical information ("Type 2 diabetes")
    - Organizations ("Google", "Apollo Hospital")
    """

    def __init__(self, model_name: str = "en_core_web_sm"):
        self.nlp = None
        self._load_model(model_name)

    def _load_model(self, model_name: str):
        """Load spaCy model. Fallback to regex-only if unavailable."""
        try:
            import spacy
            self.nlp = spacy.load(model_name)
        except Exception:
            self.nlp = None

    def is_available(self) -> bool:
        return self.nlp is not None

    def detect(self, text: str) -> list[dict]:
        """
        Detect PII entities using NER + contextual analysis.

        Returns list of detected entities:
        [{"type": "PERSON", "value": "John Smith", "reason": "Named entity"}, ...]
        """
        detected = []

        if not self.nlp:
            # Fallback: contextual pattern matching only
            return self._contextual_detection(text)

        # NER analysis
        doc = self.nlp(text)
        for ent in doc.ents:
            if ent.label_ not in SENSITIVE_ENTITY_TYPES:
                continue

            # Skip generic dates (e.g., "today", "yesterday")
            if ent.label_ == "DATE" and ent.text.lower().strip() in GENERIC_DATES:
                continue

            # Skip generic location references (e.g., "here", "there")
            if ent.label_ in ("GPE", "LOC") and ent.text.lower().strip() in {"here", "there", "everywhere", "nowhere"}:
                continue

            # Skip common NER false positives (tech terms, common words)
            if ent.label_ == "PERSON":
                false_positives = {
                    "python", "java", "json", "xml", "sql", "api", "http", "https",
                    "aim", "let", "the", "you", "what", "how", "why", "where",
                    "when", "who", "which", "that", "this", "these", "those",
                    "performance", "function", "class", "method", "variable",
                    "array", "object", "string", "number", "boolean", "null",
                    "true", "false", "none", "undefined", "nan", "infinity",
                    "example", "sample", "test", "demo", "hello", "world",
                }
                if ent.text.lower().strip() in false_positives:
                    continue

            detected.append({
                "type": ent.label_,
                "value": ent.text,
                "reason": f"NER: {SENSITIVE_ENTITY_TYPES[ent.label_]}",
                "start": ent.start_char,
                "end": ent.end_char,
            })

        # Contextual pattern matching (catches things NER misses)
        contextual = self._contextual_detection(text)
        for item in contextual:
            # Don't duplicate if NER already caught it
            if not any(d["value"] == item["value"] for d in detected):
                detected.append(item)

        return detected

    def _contextual_detection(self, text: str) -> list[dict]:
        """
        Detect PII using contextual patterns.

        Looks for patterns like "my name is", "I live at", etc.
        and extracts the value that follows.
        """
        detected = []
        text_lower = text.lower()

        for pattern, entity_type, reason in PII_CONTEXT_PATTERNS:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                # Extract the value after the pattern (next 20-50 chars)
                start = match.end()
                # Look for end of meaningful value (comma, period, etc.)
                end_match = re.search(r'[,.\n]', text[start:])
                if end_match:
                    value_end = start + end_match.start()
                else:
                    value_end = min(start + 50, len(text))

                value = text[start:value_end].strip()
                if value and len(value) > 2:
                    detected.append({
                        "type": entity_type,
                        "value": value,
                        "reason": f"Context: {reason}",
                    })

        return detected

    def detect_sensitive_content(self, text: str) -> Optional[tuple[str, str]]:
        """
        Detect sensitive content using NER + context.

        Returns (violation_details, severity) or None.
        """
        entities = self.detect(text)

        if not entities:
            return None

        # Check for high-sensitivity entities
        high_sensitivity = [
            e for e in entities
            if e["type"] in HIGH_SENSITIVITY_ENTITIES
        ]

        if high_sensitivity:
            names = [f'{e["type"]}({e["value"][:30]})' for e in high_sensitivity]
            details = f"Sensitive entities detected: {', '.join(names)}"
            return (details, "HIGH")

        # Lower-sensitivity entities (organizations, products, etc.)
        if len(entities) >= 2:
            names = [f'{e["type"]}({e["value"][:30]})' for e in entities]
            details = f"Sensitive entities detected: {', '.join(names)}"
            return (details, "MEDIUM")

        return None


# --- Global instance (lazy-loaded) ---
_ner_detector: Optional[NerPiiDetector] = None


def get_ner_detector() -> Optional[NerPiiDetector]:
    """Get the global NER detector instance. Returns None if spaCy unavailable."""
    global _ner_detector
    if _ner_detector is None:
        _ner_detector = NerPiiDetector()
    return _ner_detector if _ner_detector.is_available() else None
