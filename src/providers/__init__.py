"""
AI Provider package for managing different AI service providers.

This package provides a unified interface for accessing various AI providers
including OpenAI, AWS Bedrock, and Google Vertex AI.

The main entry point is the factory functions:
- get_provider() - Get a provider instance
- get_chat_model() - Get a ready-to-use chat model
"""

from src.providers.factory import get_chat_model, get_provider

__all__ = [
    "get_provider",
    "get_chat_model",
]
