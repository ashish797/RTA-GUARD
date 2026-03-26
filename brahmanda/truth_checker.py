"""
RTA-GUARD — Truth Checker (R1: SATYA)

Uses NeMo Guardrails' SelfCheckGPT approach for fact verification.

Approach:
1. Claim Detection — is this a factual claim or not?
2. SelfCheckGPT — generate multiple completions, check for agreement
3. Overconfident Pattern Check — flag "definitely", "guaranteed", etc.

Based on: https://arxiv.org/abs/2303.08896 (SelfCheckGPT paper)
Adapted from: NVIDIA NeMo Guardrails hallucination detection
"""
import os
import json
from typing import Optional


class TruthChecker:
    """
    Checks truthfulness of LLM output using SelfCheckGPT.

    Instead of asking LLM to rate its own confidence (which it's bad at),
    we generate multiple completions and check for consistency.
    If completions diverge → likely hallucination/unverified claim.
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

    def is_factual_claim(self, text: str) -> bool:
        """
        Layer 1: Determine if text is a factual claim.

        Returns True if text appears to be making a factual claim.
        Returns False for jokes, questions, commands, greetings, etc.
        """
        text_lower = text.lower().strip()

        # Skip empty or very short
        if len(text_lower) < 10:
            return False

        # Skip questions
        if text.strip().endswith("?"):
            return False

        # Skip greetings
        greeting_patterns = [
            "hello", "hi there", "hey", "good morning", "good afternoon",
            "good evening", "goodbye", "bye", "thank you", "thanks",
            "how are you", "nice to meet", "pleased to meet",
        ]
        for pattern in greeting_patterns:
            if pattern in text_lower:
                return False

        # Skip jokes (punchline indicators)
        joke_patterns = [
            "why don't", "because they", "knock knock", "what do you call",
            "the difference between", "how many", "what's the",
            "a man walks into", "a woman walks into", "two men",
        ]
        for pattern in joke_patterns:
            if pattern in text_lower:
                return False

        # Skip commands/instructions
        if text_lower.startswith((
            "tell me", "give me", "show me", "explain", "help me",
            "write", "create", "generate", "make", "build",
            "can you", "could you", "would you", "please",
        )):
            return False

        # Skip hypotheticals
        hypothetical_patterns = [
            "what if", "imagine", "suppose", "let's say",
            "hypothetically", "in theory", "if you were",
            "let's pretend", "imagine if",
        ]
        for pattern in hypothetical_patterns:
            if pattern in text_lower:
                return False

        # Skip creative writing indicators
        creative_patterns = [
            "once upon a time", "in a world", "the story begins",
            "chapter", "scene", "character", "protagonist",
            "dialogue", "narrator",
        ]
        for pattern in creative_patterns:
            if pattern in text_lower:
                return False

        # It's likely a factual claim
        return True

    def check_selfconsistency(self, text: str) -> Optional[dict]:
        """
        Layer 2: SelfCheckGPT approach.

        Generate multiple completions and check for consistency.
        If completions diverge → likely hallucination.
        """
        client = self._get_client()
        if client is None:
            return None

        try:
            # Generate 2 extra completions with temperature 1.0
            extra_responses = []
            for _ in range(2):
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": text}],
                        temperature=1.0,
                        max_tokens=200,
                    )
                    extra = response.choices[0].message.content
                    if extra:
                        extra_responses.append(extra)
                except Exception:
                    continue

            if len(extra_responses) < 2:
                return None  # Not enough completions

            # Check agreement
            paragraph = ". ".join(extra_responses)
            check_prompt = f"""Does the following statement agree with the paragraph?

Statement: {text}

Paragraph: {paragraph}

Answer "yes" if the statement is consistent with the paragraph, or "no" if it contradicts or is not supported."""

            agreement_response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": check_prompt}],
                temperature=0.0,
                max_tokens=50,
            )

            agreement = agreement_response.choices[0].message.content.lower().strip()

            return {
                "agrees": "yes" in agreement and "no" not in agreement,
                "agreement_text": agreement,
                "extra_responses": extra_responses,
            }

        except Exception as e:
            return None

    def check_overconfident(self, text: str) -> list:
        """
        Layer 3: Overconfident pattern check.

        Detect overconfident language patterns.
        Only flag when used in factual context.
        """
        text_lower = text.lower()

        overconfident_patterns = [
            "this is definitely",
            "this is absolutely",
            "this is certainly",
            "i am 100% sure",
            "without a doubt",
            "guaranteed",
            "no question about it",
            "there is no doubt",
            "it is certain that",
            "it is proven that",
            "studies have shown that",  # without citation
        ]

        found = []
        for pattern in overconfident_patterns:
            if pattern in text_lower:
                found.append(pattern)

        return found

    def check(self, text: str) -> Optional[dict]:
        """
        Full truth check pipeline.

        Returns dict with:
        - is_claim: bool
        - agrees: bool (from SelfCheckGPT)
        - overconfident: list of overconfident patterns
        - confidence: float (0-1)
        """
        # Layer 1: Is this a factual claim?
        if not self.is_factual_claim(text):
            return {"is_claim": False, "agrees": True, "overconfident": [], "confidence": 1.0}

        # Layer 2: SelfCheckGPT
        selfcheck = self.check_selfconsistency(text)

        # Layer 3: Overconfident patterns
        overconfident = self.check_overconfident(text)

        # Compute confidence
        if selfcheck is None:
            # Can't run SelfCheckGPT, use pattern-based only
            confidence = 0.7 if not overconfident else 0.5
            agrees = True
        else:
            agrees = selfcheck["agrees"]
            confidence = 0.9 if agrees else 0.3
            if overconfident:
                confidence -= 0.2 * len(overconfident)

        return {
            "is_claim": True,
            "agrees": agrees,
            "overconfident": overconfident,
            "confidence": max(0.0, min(1.0, confidence)),
        }


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

    result = _checker.check(output)
    if result is None:
        return None

    if not result["is_claim"]:
        return None  # Not a factual claim, skip

    if not result["agrees"]:
        confidence = result["confidence"]
        issues = result.get("overconfident", [])

        if confidence < 0.3 and len(issues) >= 2:
            severity = "HIGH"
        elif confidence < 0.6:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        details = f"Unverified claim: disagreement detected"
        if issues:
            details += f" (overconfident: {', '.join(issues[:2])})"

        return (severity, details, confidence)

    return None
