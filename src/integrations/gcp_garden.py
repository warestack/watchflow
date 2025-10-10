"""
GCP Vertex AI integration for AI model access.

This module handles Google Cloud Platform Vertex AI API interactions
for AI model access through Model Garden.
"""

from __future__ import annotations

import os
from typing import Any

from src.core.config import config


def get_garden_client() -> Any:
    """
    Get GCP Model Garden client for accessing both Google and third-party models.
    
    Returns:
        Model Garden client instance
    """
    # Use Model Garden client for better model selection
    return get_model_garden_client()


def get_model_garden_client() -> Any:
    """
    Get GCP Model Garden client for accessing both Google and third-party models.
    
    This client provides access to models from various providers through
    Google's Model Garden marketplace, including:
    - Google models: gemini-1.0-pro, gemini-1.5-pro, gemini-2.0-flash-exp
    - Third-party models: Claude, Llama, etc. (when available)
    
    Returns:
        Model Garden client instance
    """
    # Get GCP credentials from config
    project_id = config.ai.gcp_project
    location = config.ai.gcp_location or 'us-central1'
    service_account_key_base64 = config.ai.gcp_service_account_key_base64
    model = config.ai.get_model_for_provider('garden')
    
    if not project_id:
        raise ValueError(
            "GCP project ID required for Model Garden. Set GCP_PROJECT_ID in config"
        )

    # Handle base64 encoded service account key
    if service_account_key_base64:
        import base64
        import tempfile
        
        try:
            # Decode the base64 key
            key_data = base64.b64decode(service_account_key_base64).decode('utf-8')
            
            # Create a temporary file with the key
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(key_data)
                credentials_path = f.name
                
            # Set the environment variable for Google Cloud to use
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
            
        except Exception as e:
            raise ValueError(f"Failed to decode GCP service account key: {e}") from e

    # Check if it's a Claude model
    if 'claude' in model.lower():
        return get_claude_model_garden_client(project_id, location, model)
    else:
        return get_gemini_model_garden_client(project_id, location, model)


def get_claude_model_garden_client(project_id: str, location: str, model: str) -> Any:
    """
    Get Claude model via GCP Model Garden using Anthropic Vertex SDK.
    
    Args:
        project_id: GCP project ID
        location: GCP location/region
        model: Model name (e.g., claude-3-opus@20240229)
        
    Returns:
        Claude client instance
    """
    try:
        from anthropic import AnthropicVertex
    except ImportError as e:
        raise RuntimeError(
            "Claude Model Garden client requires 'anthropic[vertex]' package. "
            "Install with: pip install 'anthropic[vertex]'"
        ) from e

    # Create Anthropic Vertex client
    client = AnthropicVertex(region=location, project_id=project_id)
    
    # Wrap it to match LangChain interface
    return ClaudeModelGardenWrapper(client, model)


def get_gemini_model_garden_client(project_id: str, location: str, model: str) -> Any:
    """
    Get Gemini model via GCP Model Garden using LangChain.
    
    Args:
        project_id: GCP project ID
        location: GCP location/region
        model: Model name (e.g., gemini-pro)
        
    Returns:
        Gemini client instance
    """
    try:
        from langchain_google_vertexai import ChatVertexAI
    except ImportError as e:
        raise RuntimeError(
            "Gemini Model Garden client requires 'langchain-google-vertexai' package. "
            "Install with: pip install langchain-google-vertexai"
        ) from e

    # Try multiple Gemini model names in order of preference
    model_candidates = [model, "gemini-pro", "gemini-1.5-pro", "gemini-1.5-flash"]
    
    for candidate_model in model_candidates:
        try:
            return ChatVertexAI(
                model=candidate_model,
                project=project_id,
                location=location,
            )
        except Exception as e:
            if "not found" in str(e).lower() or "404" in str(e):
                continue  # Try next model
            else:
                raise  # Re-raise if it's not a model not found error
    
    # If all models fail, raise an error
    raise RuntimeError(
        f"None of the Gemini models are available in your GCP project. "
        f"Tried: {', '.join(model_candidates)}. "
        f"Please check your GCP project configuration and model access."
    )


class ClaudeModelGardenWrapper:
    """
    Wrapper for Claude Model Garden client to match LangChain interface.
    """
    
    def __init__(self, client, model: str):
        self.client = client
        self.model = model
    
    async def ainvoke(self, messages, **kwargs):
        """Async invoke method."""
        # Convert LangChain messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            if hasattr(msg, 'content'):
                content = msg.content
                role = "user" if msg.type == "human" else "assistant"
            else:
                content = str(msg)
                role = "user"
            
            anthropic_messages.append({
                "role": role,
                "content": content
            })
        
        # Call Claude API
        response = self.client.messages.create(
            model=self.model,
            messages=anthropic_messages,
            max_tokens=kwargs.get('max_tokens', 4096),
            temperature=kwargs.get('temperature', 0.1),
        )
        
        # Convert response to LangChain format
        from langchain_core.messages import AIMessage
        return AIMessage(content=response.content[0].text)
    
    def invoke(self, messages, **kwargs):
        """Sync invoke method."""
        import asyncio
        return asyncio.run(self.ainvoke(messages, **kwargs))
    
    def with_structured_output(self, schema, **kwargs):
        """Structured output method."""
        # For now, return self and handle structured output in ainvoke
        self._output_schema = schema
        return self
