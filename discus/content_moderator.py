"""
RTA-GUARD — Content Moderation (OpenAI API)

Integrates OpenAI's free content moderation API.
From NeMo Guardrails' moderation integrations.

OpenAI Moderation API detects:
- Hate speech
- Harassment
- Self-harm
- Sexual content
- Violence
- Political content
- Illegal activity
"""
import os
from typing import Optional


class ContentModerator:
    """
    Content moderation using OpenAI's free API.
    
    Based on NeMo Guardrails' integration pattern.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = None

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                return None
        return self._client

    def check(self, text: str) -> Optional[dict]:
        """
        Check text for harmful content using OpenAI Moderation API.

        Returns dict with:
        - flagged: bool
        - categories: dict of category scores
        - highest_category: str
        """
        if not self.api_key:
            return None  # No API key configured

        client = self._get_client()
        if client is None:
            return None

        try:
            response = client.moderations.create(input=text)
            result = response.results[0]

            return {
                "flagged": result.flagged,
                "categories": {
                    "hate": result.categories.hate,
                    "hate_threatening": result.categories.hate_threatening,
                    "harassment": result.categories.harassment,
                    "harassment_threatening": result.categories.harassment_threatening,
                    "self_harm": result.categories.self_harm,
                    "self_harm_intent": result.categories.self_harm_intent,
                    "self_harm_instructions": result.categories.self_harm_instructions,
                    "sexual": result.categories.sexual,
                    "sexual_minors": result.categories.sexual_minors,
                    "violence": result.categories.violence,
                    "violence_graphic": result.categories.violence_graphic,
                },
                "highest_category": max(
                    result.category_scores.__dict__.items(),
                    key=lambda x: x[1]
                )[0],
            }

        except Exception:
            return None


# Global instance
_moderator = None


def check_content_moderation(text: str) -> Optional[tuple]:
    """
    Check text for harmful content.

    Returns (severity, details, category) or None.
    """
    global _moderator
    if _moderator is None:
        _moderator = ContentModerator()

    result = _moderator.check(text)
    if result is None:
        return None

    if result["flagged"]:
        category = result["highest_category"]
        return ("HIGH", f"Harmful content: {category}", category)

    return None
