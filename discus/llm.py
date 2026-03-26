"""
RTA-GUARD Discus — LLM Providers

Real LLM integration layer. Wraps OpenAI, Anthropic, and any OpenAI-compatible API.
Each provider goes through DiscusGuard before hitting the API.
"""
import os
from typing import Optional, AsyncIterator
from abc import ABC, abstractmethod

from .guard import DiscusGuard, SessionKilledError
from .models import GuardConfig


class LLMProvider(ABC):
    """Base class for LLM providers."""

    def __init__(self, guard: Optional[DiscusGuard] = None, **kwargs):
        self.guard = guard or DiscusGuard()

    @abstractmethod
    def chat(self, message: str, session_id: str = "default", **kwargs) -> str:
        """Send a message and get a response. Raises SessionKilledError if blocked."""
        pass

    @abstractmethod
    async def achat(self, message: str, session_id: str = "default", **kwargs) -> str:
        """Async version of chat."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI GPT integration."""

    def __init__(
        self,
        guard: Optional[DiscusGuard] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(guard, **kwargs)
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")

        self.client = openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url
        )
        self.async_client = openai.AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url
        )
        self.model = model

    def chat(
        self,
        message: str,
        session_id: str = "default",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> str:
        # Kill-switch check on INPUT
        self.guard.check(message, session_id)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        output = response.choices[0].message.content

        # Kill-switch check on OUTPUT — catches PII the input guard missed
        # Uses same session_id so kill propagates to main session
        try:
            self.guard.check(output, session_id, check_output=True)
        except SessionKilledError:
            # Output contains PII — kill session and return safe message
            raise SessionKilledError(
                type('FakeEvent', (), {
                    'session_id': session_id,
                    'details': f'LLM output contained PII that passed input check',
                    'decision': type('D', (), {'value': 'kill'})(),
                })()
            )

        return output

    async def achat(
        self,
        message: str,
        session_id: str = "default",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> str:
        self.guard.check(message, session_id)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        output = response.choices[0].message.content

        # OUTPUT guard — catches PII the input guard missed
        try:
            self.guard.check(output, session_id, check_output=True)
        except SessionKilledError:
            # Re-raise with clear message
            raise

        return output


class AnthropicProvider(LLMProvider):
    """Anthropic Claude integration."""

    def __init__(
        self,
        guard: Optional[DiscusGuard] = None,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        **kwargs
    ):
        super().__init__(guard, **kwargs)
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")

        self.client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY")
        )
        self.model = model

    def chat(
        self,
        message: str,
        session_id: str = "default",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> str:
        self.guard.check(message, session_id)

        kwargs_msg = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature}
        if system_prompt:
            kwargs_msg["system"] = system_prompt
        kwargs_msg["messages"] = [{"role": "user", "content": message}]

        response = self.client.messages.create(**kwargs_msg)
        output = response.content[0].text

        # OUTPUT guard — catches PII the input guard missed
        try:
            self.guard.check(output, session_id, check_output=True)
        except SessionKilledError:
            # Output contains PII — re-raise to kill session
            raise

        return output


class OpenAICompatibleProvider(LLMProvider):
    """
    Any OpenAI-compatible API (Ollama, LM Studio, vLLM, etc.)
    Just set base_url to your local server.
    """

    def __init__(
        self,
        guard: Optional[DiscusGuard] = None,
        api_key: str = "not-needed",
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3",
        **kwargs
    ):
        super().__init__(guard, **kwargs)
        import openai

        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(
        self,
        message: str,
        session_id: str = "default",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> str:
        self.guard.check(message, session_id)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        output = response.choices[0].message.content

        # OUTPUT guard — catches PII the input guard missed
        try:
            self.guard.check(output, session_id, check_output=True)
        except SessionKilledError:
            # Output contains PII — re-raise to kill session
            raise

        return output

    async def achat(self, message: str, session_id: str = "default", **kwargs) -> str:
        raise NotImplementedError("Async not yet implemented for OpenAI-compatible provider")
