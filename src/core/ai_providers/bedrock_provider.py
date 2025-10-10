"""
AWS Bedrock AI Provider implementation.

This provider handles both standard Bedrock models and Anthropic models
requiring inference profiles.
"""

from typing import Any

from src.integrations.aws_bedrock import get_bedrock_client

from .base import BaseAIProvider


class BedrockProvider(BaseAIProvider):
    """AWS Bedrock AI Provider with hybrid client support."""

    def get_chat_model(self) -> Any:
        """Get Bedrock chat model using appropriate client."""
        # Get the appropriate Bedrock client (uses config directly)
        client = get_bedrock_client()

        return client

    def supports_structured_output(self) -> bool:
        """Bedrock supports structured output."""
        return True

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "bedrock"

    def get_model_info(self) -> dict[str, Any]:
        """Get enhanced model information."""
        info = super().get_model_info()
        model_id = self.kwargs.get("model_id", self.model)
        info.update(
            {
                "model_id": model_id,
                "supports_inference_profiles": model_id.startswith("anthropic."),
            }
        )
        return info
