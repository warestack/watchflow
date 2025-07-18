"""
Base classes and interfaces for WatchFlow agents.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

from src.core.config import config

logger = None  # Will be initialized in __init__


@dataclass
class AgentResult:
    """Base result class for all agent operations."""

    success: bool
    message: str
    data: dict[str, Any]


class BaseAgent(ABC):
    """Base class for all WatchFlow agents with centralized OpenAI configuration."""

    def __init__(self):
        global logger
        if logger is None:
            import logging

            logger = logging.getLogger(__name__)

        self._validate_config()
        self.llm = self._create_llm_client()
        self.graph = self._build_graph()

    def _validate_config(self):
        """Validate OpenAI configuration."""
        if not config.ai.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")

        if not config.ai.model:
            raise ValueError("AI model is required. Set AI_MODEL environment variable.")

    def _create_llm_client(self) -> ChatOpenAI:
        """Create and configure OpenAI client."""
        return ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )

    @abstractmethod
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for this agent."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> AgentResult:
        """Execute the agent with given parameters."""
        pass
