"""
RTA-GUARD — Hallucination Detector (R12: MĀYĀ)

Detects hallucinations and ungrounded claims in LLM output.
Uses LLM self-check pattern from NeMo Guardrails.

Approach:
1. Take LLM output
2. Ask LLM: "Is this claim supported by context?"
3. If not supported → warn
4. If confidently wrong → kill
"""
import os
import json
from typing import Optional


class HallucinationChecker:
    """
    Checks if LLM output is grounded in provided context.

    Uses LLM self-check: asks the LLM to verify its own claims.
    Based on NeMo Guardrails' self_check_hallucination pattern.
    """

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

    def check(self, output: str, context: str = "", session_id: str = "") -> Optional[dict]:
        """
        Check if output is grounded in context.

        Returns dict with:
        - grounded: bool (True if grounded)
        - confidence: float (0-1)
        - issues: list of ungrounded claims
        """
        client = self._get_client()
        if client is None:
            return None  # Can't check without LLM

        try:
            # Ask LLM to verify its own output
            prompt = f"""You are a fact-checker. Analyze the following output and determine if it contains any hallucinations or ungrounded claims.

Context (if provided): {context if context else "No context provided — check for general hallucinations"}

Output to verify: {output}

Respond in JSON format:
{{
  "grounded": true/false,
  "confidence": 0.0-1.0,
  "issues": ["list of specific hallucinated or ungrounded claims, if any"]
}}

Be strict. Flag any claim that:
1. Cannot be verified from the context
2. Contains made-up facts, statistics, or dates
3. Confidently states something uncertain
4. Contradicts common knowledge

If there are no issues, return grounded=true with empty issues list."""

            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )

            result_text = response.choices[0].message.content

            # Parse JSON from response
            try:
                # Try to extract JSON from the response
                if "```json" in result_text:
                    json_str = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    json_str = result_text.split("```")[1].split("```")[0].strip()
                else:
                    # Try to find JSON object in text
                    start = result_text.find("{")
                    end = result_text.rfind("}") + 1
                    if start >= 0 and end > start:
                        json_str = result_text[start:end]
                    else:
                        return None

                result = json.loads(json_str)
                return result
            except json.JSONDecodeError:
                return None

        except Exception:
            return None


# Global instance
_checker = None


def check_hallucination(output: str, context: str = "") -> Optional[tuple]:
    """
    Check for hallucinations in LLM output.

    Returns (violation_type, severity, details) or None.
    """
    global _checker
    if _checker is None:
        _checker = HallucinationChecker()

    result = _checker.check(output, context)
    if result is None:
        return None

    if not result.get("grounded", True):
        confidence = result.get("confidence", 0.5)
        issues = result.get("issues", [])

        if confidence < 0.3 and len(issues) >= 2:
            severity = "HIGH"
        elif confidence < 0.6:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        details = f"Hallucination detected: {'; '.join(issues[:3])}"
        return (severity, details, confidence)

    return None
