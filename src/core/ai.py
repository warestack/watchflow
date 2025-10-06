"""
Provider-agnostic AI chat model factory.

This module provides a simple interface to the AI provider system.
For complex provider logic, see src.core.ai_providers and src.integrations.
"""

from __future__ import annotations

from src.core.ai_providers.factory import get_chat_model as _get_chat_model


def get_chat_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    agent: str | None = None,
    **kwargs,
):
    """
    Return a chat model client based on configuration.

    Args:
        provider: AI provider name (openai, bedrock, vertex_ai)
        model: Model name/ID
        max_tokens: Override max tokens (takes precedence over agent config)
        temperature: Override temperature (takes precedence over agent config)
        agent: Agent name for per-agent configuration ('engine_agent', 'feasibility_agent', 'acknowledgment_agent')
        **kwargs: Additional provider-specific parameters

    Providers:
    - "openai": uses OpenAI API
    - "bedrock": uses AWS Bedrock (supports both standard and Anthropic inference profiles)
    - "vertex_ai": uses GCP Vertex AI
    """
    return _get_chat_model(
        provider=provider, model=model, max_tokens=max_tokens, temperature=temperature, agent=agent, **kwargs
    )
