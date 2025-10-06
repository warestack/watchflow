"""
AI Provider Factory.

This module provides a factory function to create the appropriate
AI provider based on configuration.
"""

from typing import Any

from src.core.config import config

from .base import BaseAIProvider
from .bedrock_provider import BedrockProvider
from .garden_provider import GardenProvider
from .openai_provider import OpenAIProvider


def get_ai_provider(
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    agent: str | None = None,
    **kwargs,
) -> BaseAIProvider:
    """
    Get the appropriate AI provider based on configuration.

    Args:
        provider: AI provider name (openai, bedrock, vertex_ai)
        model: Model name/ID
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        agent: Agent name for per-agent configuration
        **kwargs: Additional provider-specific parameters

    Returns:
        Configured AI provider instance
    """
    # Use config defaults if not provided
    provider = provider or config.ai.provider or "openai"

    # Get model with fallbacks handled by config
    if not model:
        model = config.ai.get_model_for_provider(provider)

    # Determine tokens and temperature with precedence: explicit params > agent config > global config
    if max_tokens is not None:
        tokens = max_tokens
    else:
        tokens = config.ai.get_max_tokens_for_agent(agent)

    if temperature is not None:
        temp = temperature
    else:
        temp = config.ai.get_temperature_for_agent(agent)

    # Create provider-specific parameters
    provider_kwargs = kwargs.copy()

    if provider.lower() == "openai":
        provider_kwargs.update(
            {
                "api_key": config.ai.api_key,
            }
        )
        return OpenAIProvider(model=model, max_tokens=tokens, temperature=temp, **provider_kwargs)

    elif provider.lower() == "bedrock":
        return BedrockProvider(
            model=model,
            max_tokens=tokens,
            temperature=temp,
        )

    elif provider.lower() in ["garden", "model_garden", "gcp"]:
        return GardenProvider(
            model=model,
            max_tokens=tokens,
            temperature=temp,
        )

    else:
        raise ValueError(f"Unsupported AI provider: {provider}")


def get_chat_model(
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    agent: str | None = None,
    **kwargs,
) -> Any:
    """
    Get a chat model instance using the appropriate provider.

    This is a convenience function that creates a provider and returns its chat model.
    """
    provider_instance = get_ai_provider(
        provider=provider, model=model, max_tokens=max_tokens, temperature=temperature, agent=agent, **kwargs
    )

    return provider_instance.get_chat_model()
