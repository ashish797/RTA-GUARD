"""
RTA-GUARD — Truth Checker (R1: SATYA)

Detects unverified claims and overconfident statements.
Uses LLM self-check pattern from NeMo Guardrails.

Approach:
1. Take LLM output
2. Ask LLM: "Rate the confidence of this claim"
3. If confidence < threshold → warn
4. Track verification history
"""
import os
import json
from typing import Optional


class TruthChecker:
    """
    Checks if LLM output contains unverified or overconfident claims.

    Uses LLM self-check: asks the LLM to rate its own confidence.
    Based on NeMo Guardrails' self_check_facts pattern.
    """

    # Overconfident patterns
    # Only flag specific overconfident claims (not common words)
    OVERCONFIDENT_PATTERNS = [
        "this is definitely",
        "this is absolutely",
        "this is certainly",
        "i am 100% sure",
        "without a doubt",
        "guaranteed",
        "no question",
    ]

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self.model = model or "google/gemini-2.0-flash-001"
        self._client = None

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except ImportError:
                return None
        return self._client

    def _check_overconfident(self, text: str) -> list:
        """Check for overconfident language patterns."""
        text_lower = text.lower()
        found = []
        for pattern in self.OVERCONFIDENT_PATTERNS:
            if pattern in text_lower:
                found.append(pattern)
        return found

    def check(self, output: str, context: str = "") -> Optional[dict]:
        """
        Check truthfulness of output.

        Returns dict with:
        - verified: bool
        - confidence: float (0-1)
        - overconfident: list of overconfident claims
        - unverified: list of unverified claims
        """
        # First, check for overconfident language (fast, no LLM)
        overconfident = self._check_overconfident(output)

        client = self._get_client()
        if client is None:
            # Can't check without LLM, just return overconfident results
            if overconfident:
                return {
                    "verified": True,  # Can't verify without LLM
                    "confidence": 0.7,  # Neutral
                    "overconfident": overconfident,
                    "unverified": [],
                }
            return None

        try:
            # Ask LLM to verify the output
            prompt = f"""You are a truth-checker. Analyze the following output and determine if it contains any unverified or overconfident claims.

Context (if provided): {context if context else "No context provided"}

Output to verify: {output}

Overconfident phrases detected: {overconfident if overconfident else "None"}

Respond in JSON format:
{{
  "verified": true/false,
  "confidence": 0.0-1.0,
  "overconfident": ["list of overconfident claims"],
  "unverified": ["list of unverified claims"]
}}

Flag claims that:
1. Are stated as absolute fact but are actually uncertain
2. Use overconfident language without evidence
3. Make predictions or guarantees without basis
4. Contradict common knowledge"""

            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )

            result_text = response.choices[0].message.content

            # Parse JSON from response
            try:
                if "```json" in result_text:
                    json_str = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    json_str = result_text.split("```")[1].split("```")[0].strip()
                else:
                    start = result_text.find("{")
                    end = result_text.rfind("}") + 1
                    if start >= 0 and end > start:
                        json_str = result_text[start:end]
                    else:
                        return None

                result = json.loads(json_str)

                # Merge with our overconfident findings
                if overconfident:
                    result["overconfident"] = list(set(
                        result.get("overconfident", []) + overconfident
                    ))

                return result
            except json.JSONDecodeError:
                return None

        except Exception:
            return None


# Global instance
_checker = None


def check_truth(output: str, context: str = "") -> Optional[tuple]:
    """
    Check truthfulness of LLM output.

    Returns (severity, details, confidence) or None.
    """
    global _checker
    if _checker is None:
        _checker = TruthChecker()

    result = _checker.check(output, context)
    if result is None:
        return None

    if not result.get("verified", True):
        confidence = result.get("confidence", 0.5)
        overconfident = result.get("overconfident", [])
        unverified = result.get("unverified", [])

        issues = overconfident + unverified

        if confidence < 0.3 and len(issues) >= 2:
            severity = "HIGH"
        elif confidence < 0.6:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        details = f"Truth issue: {'; '.join(issues[:3])}"
        return (severity, details, confidence)

    return None
