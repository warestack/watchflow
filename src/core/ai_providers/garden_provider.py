"""
GCP Model Garden Provider implementation.
"""

from typing import Any

from src.integrations.gcp_garden import get_garden_client

from .base import BaseAIProvider


class GardenProvider(BaseAIProvider):
    """GCP Model Garden Provider."""

    def get_chat_model(self) -> Any:
        """Get Model Garden chat model."""
        return get_garden_client()

    def supports_structured_output(self) -> bool:
        """Model Garden supports structured output."""
        return True

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "garden"
