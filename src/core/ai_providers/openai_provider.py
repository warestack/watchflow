"""
OpenAI AI Provider implementation.
"""

from typing import Any

from .base import BaseAIProvider


class OpenAIProvider(BaseAIProvider):
    """OpenAI AI Provider."""

    def get_chat_model(self) -> Any:
        """Get OpenAI chat model."""
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise RuntimeError(
                "OpenAI provider requires 'langchain-openai' package. Install with: pip install langchain-openai"
            ) from e

        return ChatOpenAI(model=self.model, max_tokens=self.max_tokens, temperature=self.temperature, **self.kwargs)

    def supports_structured_output(self) -> bool:
        """OpenAI supports structured output."""
        return True

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai"
