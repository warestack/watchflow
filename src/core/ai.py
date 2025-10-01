"""
Provider-agnostic AI chat model factory.

This module returns a LangChain-compatible chat model based on configuration,
supporting OpenAI (default), AWS Bedrock, and GCP Model Garden (Vertex AI).

All returned clients must provide:
- with_structured_output(pydantic_model)
- ainvoke(messages_or_prompt)

Notes:
- Dependencies for Bedrock/Vertex are optional. We raise clear errors if missing.
"""

from __future__ import annotations

from typing import Any

from src.core.config import config


def get_chat_model(*, max_tokens: int | None = None, temperature: float | None = None):
    """
    Return a chat model client based on `config.ai.provider`.

    Providers:
    - "openai": uses langchain_openai.ChatOpenAI
    - "bedrock": uses AWS Bedrock via langchain_aws.ChatBedrock (optional dep)
    - "garden" or "vertex": uses Google Vertex AI via langchain_google_vertexai.ChatVertexAI (optional dep)
    """

    provider = (config.ai.provider or "openai").lower()
    model = config.ai.model
    tokens = max_tokens if max_tokens is not None else config.ai.max_tokens
    temp = temperature if temperature is not None else config.ai.temperature

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI  # type: ignore
        except Exception as err:  # pragma: no cover - import-time error path
            raise RuntimeError(
                "OpenAI provider selected but langchain_openai is not installed."
            ) from err

        return ChatOpenAI(api_key=config.ai.api_key, model=model, max_tokens=tokens, temperature=temp)

    if provider == "bedrock":
        # Prefer langchain_aws (new) if available, fallback to community package
        chat_cls = None
        import_error: Exception | None = None
        try:
            from langchain_aws import ChatBedrock as BedrockChat  # type: ignore

            chat_cls = BedrockChat
        except Exception as err1:  # pragma: no cover - optional import
            import_error = err1
            try:
                # Older community integration
                from langchain_community.chat_models.bedrock import (  # type: ignore
                    ChatBedrock as BedrockChat,
                )

                chat_cls = BedrockChat
            except Exception as err2:  # pragma: no cover - optional import
                import_error = err2

        if chat_cls is None:
            raise RuntimeError(
                "Bedrock provider selected but no Bedrock chat integration found. Install `langchain-aws` "
                "or `langchain-community` and configure AWS credentials."
            ) from import_error

        region = getattr(config.ai, "bedrock_region", None)
        model_id = getattr(config.ai, "bedrock_model_id", model)

        kwargs: dict[str, Any] = {"model": model_id, "temperature": temp, "max_tokens": tokens}
        if region:
            kwargs["region_name"] = region

        return chat_cls(**kwargs)

    if provider in {"garden", "vertex", "vertexai", "model_garden"}:
        try:
            from langchain_google_vertexai import ChatVertexAI  # type: ignore
        except Exception as err:  # pragma: no cover - optional import
            raise RuntimeError(
                "GCP Garden/Vertex provider selected but `langchain-google-vertexai` is not installed."
            ) from err

        project = getattr(config.ai, "gcp_project", None)
        location = getattr(config.ai, "gcp_location", None)

        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temp,
            "max_output_tokens": tokens,
        }
        if project:
            kwargs["project"] = project
        if location:
            kwargs["location"] = location

        return ChatVertexAI(**kwargs)

    # Unknown provider
    raise ValueError(f"Unsupported AI provider: {provider}")


