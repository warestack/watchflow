"""
AWS Bedrock AI Provider implementation.

This provider handles AWS Bedrock API interactions, including both
standard langchain-aws clients and the Anthropic Bedrock client
for inference profile support. All integration logic is consolidated here.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.core.config import config
from src.integrations.providers.base import BaseProvider


class BedrockProvider(BaseProvider):
    """AWS Bedrock Provider with hybrid client support."""

    def get_chat_model(self) -> Any:
        """Get Bedrock chat model using appropriate client."""
        model_id = self.model

        # Check if this is already an inference profile ID
        if model_id.startswith("us.") or model_id.startswith("global.") or model_id.startswith("arn:"):
            return self._get_anthropic_inference_profile_client(model_id)

        # Try to find an inference profile for this model
        inference_profile = self._find_inference_profile(model_id)
        if inference_profile:
            return self._get_anthropic_inference_profile_client(inference_profile)

        # Fallback to direct model access
        if self._is_anthropic_model(model_id):
            # For Anthropic models, try standard client first (supports structured output)
            try:
                return self._get_standard_bedrock_client()
            except Exception:
                # If standard client fails, fall back to Anthropic client
                client = self._get_anthropic_bedrock_client()
                return self._wrap_anthropic_client(client, model_id)
        else:
            # Use standard client for other models
            return self._get_standard_bedrock_client()

    def supports_structured_output(self) -> bool:
        """Bedrock supports structured output."""
        return True

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "bedrock"

    def _get_anthropic_bedrock_client(self) -> Any:
        """Get Anthropic Bedrock client for models requiring inference profiles."""
        try:
            from anthropic import AnthropicBedrock
        except ImportError as e:
            raise RuntimeError(
                "Anthropic Bedrock client requires 'anthropic' package. Install with: pip install anthropic"
            ) from e

        aws_access_key = config.ai.aws_access_key_id
        aws_secret_key = config.ai.aws_secret_access_key
        aws_region = config.ai.bedrock_region or "us-east-1"
        aws_profile = config.ai.aws_profile

        if aws_profile:
            os.environ["AWS_PROFILE"] = aws_profile

        client_kwargs = {
            "aws_region": aws_region,
            "aws_profile": aws_profile,
        }

        if aws_access_key and aws_secret_key:
            client_kwargs.update(
                {
                    "aws_access_key": aws_access_key,
                    "aws_secret_key": aws_secret_key,
                }
            )

        return AnthropicBedrock(**client_kwargs)

    def _get_standard_bedrock_client(self) -> Any:
        """Get standard langchain-aws Bedrock client for on-demand models."""
        try:
            from langchain_aws import ChatBedrock
        except ImportError as e:
            raise RuntimeError(
                "Standard Bedrock client requires 'langchain-aws' package. Install with: pip install langchain-aws"
            ) from e

        aws_access_key = config.ai.aws_access_key_id
        aws_secret_key = config.ai.aws_secret_access_key
        aws_region = config.ai.bedrock_region or "us-east-1"
        aws_profile = config.ai.aws_profile

        if aws_profile:
            os.environ["AWS_PROFILE"] = aws_profile

        client_kwargs = {
            "model_id": self.model,
            "region_name": aws_region,
        }

        if self.model.startswith("arn:") or self.model.startswith("us.") or self.model.startswith("global."):
            if "anthropic" in self.model.lower():
                client_kwargs["provider"] = "anthropic"
            elif "amazon" in self.model.lower():
                client_kwargs["provider"] = "amazon"
            elif "meta" in self.model.lower():
                client_kwargs["provider"] = "meta"

        if aws_access_key and aws_secret_key:
            client_kwargs.update(
                {
                    "aws_access_key_id": aws_access_key,
                    "aws_secret_access_key": aws_secret_key,
                }
            )

        return ChatBedrock(**client_kwargs)

    def _is_anthropic_model(self, model_id: str) -> bool:
        """Check if a model ID is an Anthropic model."""
        return model_id.startswith("anthropic.")

    def _find_inference_profile(self, model_id: str) -> str | None:
        """Find an inference profile that contains the specified model."""
        try:
            import boto3

            aws_region = config.ai.bedrock_region or "us-east-1"
            aws_access_key = config.ai.aws_access_key_id
            aws_secret_key = config.ai.aws_secret_access_key

            client_kwargs = {"region_name": aws_region}
            if aws_access_key and aws_secret_key:
                client_kwargs.update({"aws_access_key_id": aws_access_key, "aws_secret_access_key": aws_secret_key})

            bedrock = boto3.client("bedrock", **client_kwargs)
            response = bedrock.list_inference_profiles()
            profiles = response.get("inferenceProfiles", [])

            for profile in profiles:
                profile_name = profile.get("name", "")
                profile_arn = profile.get("arn", "")

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
            return None

    def _get_anthropic_inference_profile_client(self, inference_profile_id: str) -> Any:
        """Get Anthropic client configured for inference profile models."""
        client = self._get_anthropic_bedrock_client()
        return self._wrap_anthropic_client(client, inference_profile_id)

    def _wrap_anthropic_client(self, client: Any, model_id: str) -> Any:
        """Wrap Anthropic Bedrock client to be langchain-compatible."""

        class AnthropicBedrockWrapper(BaseChatModel):
            """Wrapper for Anthropic Bedrock client to be langchain-compatible."""

            anthropic_client: Any
            model_id: str
            max_tokens: int
            temperature: float

            def __init__(self, anthropic_client: Any, model_id: str, max_tokens: int, temperature: float):
                super().__init__(
                    anthropic_client=anthropic_client,
                    model_id=model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            @property
            def _llm_type(self) -> str:
                return "anthropic_bedrock"

            def with_structured_output(self, output_model: Any) -> Any:
                """Add structured output support."""
                return self

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any | None = None,
            ) -> ChatResult:
                """Generate a response using the Anthropic client."""
                anthropic_messages = []
                for msg in messages:
                    if msg.type == "human":
                        role = "user"
                    elif msg.type == "ai":
                        role = "assistant"
                    elif msg.type == "system":
                        role = "user"
                    else:
                        role = "user"

                    anthropic_messages.append({"role": role, "content": msg.content})

                response = self.anthropic_client.messages.create(
                    model=self.model_id,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=anthropic_messages,
                )

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
                return self._generate(messages, stop, run_manager)

        return AnthropicBedrockWrapper(client, model_id, self.max_tokens, self.temperature)
