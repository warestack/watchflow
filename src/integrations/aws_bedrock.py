"""
AWS Bedrock integration for AI model access.

This module handles AWS Bedrock API interactions, including both
standard langchain-aws clients and the Anthropic Bedrock client
for inference profile support.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.core.config import config


def get_anthropic_bedrock_client() -> Any:
    """
    Get Anthropic Bedrock client for models requiring inference profiles.

    This client handles newer Anthropic models that require inference profiles
    instead of direct on-demand access.
    Uses AWS profile authentication if explicit credentials are not provided.

    Returns:
        AnthropicBedrock client instance
    """
    try:
        from anthropic import AnthropicBedrock
    except ImportError as e:
        raise RuntimeError(
            "Anthropic Bedrock client requires 'anthropic' package. Install with: pip install anthropic"
        ) from e

    # Get AWS credentials from config
    aws_access_key = config.ai.aws_access_key_id
    aws_secret_key = config.ai.aws_secret_access_key
    aws_region = config.ai.bedrock_region or "us-east-1"

    # Set AWS profile if specified in config
    aws_profile = config.ai.aws_profile
    if aws_profile:
        os.environ["AWS_PROFILE"] = aws_profile

    # Prepare client parameters - following the official Anthropic client pattern
    client_kwargs = {
        "aws_region": aws_region,
        "aws_profile": aws_profile,
    }

    # Add credentials only if they are provided
    if aws_access_key and aws_secret_key:
        client_kwargs.update(
            {
                "aws_access_key": aws_access_key,
                "aws_secret_key": aws_secret_key,
            }
        )
    # If no explicit credentials, boto3 will use AWS profile/default credentials

    return AnthropicBedrock(**client_kwargs)


def get_standard_bedrock_client() -> Any:
    """
    Get standard langchain-aws Bedrock client for on-demand models.

    This client works with models that have direct on-demand access enabled.
    Uses AWS profile authentication if explicit credentials are not provided.

    Returns:
        ChatBedrock client instance
    """
    try:
        from langchain_aws import ChatBedrock
    except ImportError as e:
        raise RuntimeError(
            "Standard Bedrock client requires 'langchain-aws' package. Install with: pip install langchain-aws"
        ) from e

    # Get AWS credentials from config
    aws_access_key = config.ai.aws_access_key_id
    aws_secret_key = config.ai.aws_secret_access_key
    aws_region = config.ai.bedrock_region or "us-east-1"

    # Set AWS profile if specified in config
    aws_profile = config.ai.aws_profile
    if aws_profile:
        os.environ["AWS_PROFILE"] = aws_profile

    # Get model ID from config
    model_id = config.ai.get_model_for_provider("bedrock")
    client_kwargs = {
        "model_id": model_id,
        "region_name": aws_region,
    }

    # If using an ARN or inference profile ID, we need to specify the provider
    if model_id.startswith("arn:") or model_id.startswith("us.") or model_id.startswith("global."):
        # Extract provider from model ID
        if "anthropic" in model_id.lower():
            client_kwargs["provider"] = "anthropic"
        elif "amazon" in model_id.lower():
            client_kwargs["provider"] = "amazon"
        elif "meta" in model_id.lower():
            client_kwargs["provider"] = "meta"

    # Add credentials only if they are provided
    if aws_access_key and aws_secret_key:
        client_kwargs.update(
            {
                "aws_access_key_id": aws_access_key,
                "aws_secret_access_key": aws_secret_key,
            }
        )
    # If no explicit credentials, boto3 will use AWS profile/default credentials

    return ChatBedrock(**client_kwargs)


def is_anthropic_model(model_id: str) -> bool:
    """Check if a model ID is an Anthropic model."""
    return model_id.startswith("anthropic.")


def _find_inference_profile(model_id: str) -> str | None:
    """
    Find an inference profile that contains the specified model.

    Args:
        model_id: The model identifier to find a profile for

    Returns:
        Inference profile ARN if found, None otherwise
    """
    try:
        import boto3

        # Get AWS credentials from config
        aws_region = config.ai.bedrock_region or "us-east-1"
        aws_access_key = config.ai.aws_access_key_id
        aws_secret_key = config.ai.aws_secret_access_key

        # Create Bedrock client
        client_kwargs = {"region_name": aws_region}
        if aws_access_key and aws_secret_key:
            client_kwargs.update({"aws_access_key_id": aws_access_key, "aws_secret_access_key": aws_secret_key})

        bedrock = boto3.client("bedrock", **client_kwargs)

        # List inference profiles
        response = bedrock.list_inference_profiles()
        profiles = response.get("inferenceProfiles", [])

        # Look for profiles that might contain this model
        for profile in profiles:
            profile_name = profile.get("name", "")
            profile_arn = profile.get("arn", "")

            # Check if this profile likely contains the model
            if any(keyword in profile_name.lower() for keyword in ["claude", "anthropic", "general", "default"]):
                if "anthropic" in model_id.lower() or "claude" in model_id.lower():
                    return profile_arn
            elif any(keyword in profile_name.lower() for keyword in ["amazon", "titan", "nova"]):
                if "amazon" in model_id.lower() or "titan" in model_id.lower() or "nova" in model_id.lower():
                    return profile_arn
            elif any(keyword in profile_name.lower() for keyword in ["meta", "llama"]):
                if "meta" in model_id.lower() or "llama" in model_id.lower():
                    return profile_arn

        return None

    except Exception:
        # If we can't find inference profiles, return None
        return None


def get_bedrock_client() -> Any:
    """
    Get the appropriate Bedrock client based on configured model type.

    Returns:
        Appropriate Bedrock client (Anthropic or standard)
    """
    # Get model ID from config
    model_id = config.ai.get_model_for_provider("bedrock")

    # Check if this is already an inference profile ID
    if model_id.startswith("us.") or model_id.startswith("global.") or model_id.startswith("arn:"):
        # This is already an inference profile ID, use Anthropic client directly
        return get_anthropic_inference_profile_client(model_id)

    # First, try to find an inference profile for this model
    inference_profile = _find_inference_profile(model_id)

    if inference_profile:
        # Use inference profile with Anthropic client
        return get_anthropic_inference_profile_client(inference_profile)

    # Fallback to direct model access
    if is_anthropic_model(model_id):
        # For Anthropic models, try standard client first (supports structured output)
        try:
            return get_standard_bedrock_client()
        except Exception:
            # If standard client fails, fall back to Anthropic client
            client = get_anthropic_bedrock_client()
            return _wrap_anthropic_client(client, model_id)
    else:
        # Use standard client for other models (requires on-demand access)
        return get_standard_bedrock_client()


def _wrap_anthropic_client(client: Any, model_id: str) -> Any:
    """
    Wrap Anthropic Bedrock client to be langchain-compatible.

    This creates a wrapper that implements the langchain interface
    while using the Anthropic client under the hood.
    """

    class AnthropicBedrockWrapper(BaseChatModel):
        """Wrapper for Anthropic Bedrock client to be langchain-compatible."""

        anthropic_client: Any
        model_id: str
        max_tokens: int
        temperature: float

        def __init__(self, anthropic_client: Any, model_id: str):
            super().__init__(
                anthropic_client=anthropic_client,
                model_id=model_id,
                max_tokens=config.ai.engine_agent.max_tokens if config.ai.engine_agent else config.ai.max_tokens,
                temperature=config.ai.engine_agent.temperature if config.ai.engine_agent else config.ai.temperature,
            )

        @property
        def _llm_type(self) -> str:
            return "anthropic_bedrock"

        def with_structured_output(self, output_model: Any) -> Any:
            """Add structured output support to the Anthropic wrapper."""
            # For now, return self and let the calling code handle structured output
            # This is a temporary solution - we'll implement proper structured output later
            return self

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any | None = None,
        ) -> ChatResult:
            """Generate a response using the Anthropic client."""
            # Convert langchain messages to Anthropic format
            anthropic_messages = []
            for msg in messages:
                # Convert LangChain message types to Anthropic format
                if msg.type == "human":
                    role = "user"
                elif msg.type == "ai":
                    role = "assistant"
                elif msg.type == "system":
                    role = "user"  # Anthropic doesn't have system role, use user
                else:
                    role = "user"  # Default to user

                anthropic_messages.append({"role": role, "content": msg.content})

            # Call Anthropic API
            response = self.anthropic_client.messages.create(
                model=self.model_id,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=anthropic_messages,
            )

            # Convert response back to langchain format
            content = response.content[0].text if response.content else ""
            message = BaseMessage(content=content, type="assistant")
            generation = ChatGeneration(message=message)

            return ChatResult(generations=[generation])

        async def _agenerate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any | None = None,
        ) -> ChatResult:
            """Async generate using the Anthropic client."""
            # For now, just call the sync version
            # TODO: Implement proper async support
            return self._generate(messages, stop, run_manager)

    return AnthropicBedrockWrapper(client, model_id)


def get_anthropic_inference_profile_client(inference_profile_id: str) -> Any:
    """
    Get Anthropic client configured for inference profile models.

    This is the key function that uses the inference profile ID directly
    as the model ID, following the Anthropic client pattern.

    Args:
        inference_profile_id: The inference profile ID (e.g., 'us.anthropic.claude-3-5-haiku-20241022-v1:0')

    Returns:
        Wrapped Anthropic client that works with LangChain
    """
    # Get the base Anthropic client
    client = get_anthropic_bedrock_client()

    # Wrap it with the inference profile ID as the model
    return _wrap_anthropic_client(client, inference_profile_id)
