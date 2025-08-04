"""
Base agent classes and utilities for agents.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from langchain_openai import ChatOpenAI

from src.core.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AgentResult:
    """Result from an agent execution."""

    def __init__(
        self,
        success: bool,
        message: str,
        data: dict[str, Any] = None,
        metadata: dict[str, Any] = None,
    ):
        self.success = success
        self.message = message
        self.data = data or {}
        self.metadata = metadata or {}


class BaseAgent(ABC):
    """
    Base class for all Watchflow agents with enhanced error handling and retry logic.

    Features:
    - Retry logic with exponential backoff for structured output
    - Timeout handling for all operations
    - Enhanced error reporting and logging
    - Performance metrics tracking
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )
        self.graph = self._build_graph()
        logger.info(f"🔧 {self.__class__.__name__} initialized with max_retries={max_retries}")

    @abstractmethod
    def _build_graph(self):
        """Build the LangGraph workflow for this agent."""
        pass

    async def _retry_structured_output(self, llm, output_model, prompt, **kwargs) -> T:
        """
        Retry structured output with exponential backoff.

        Args:
            llm: The LLM client
            output_model: Pydantic model for structured output
            prompt: The prompt to send to the LLM
            **kwargs: Additional arguments for the LLM call

        Returns:
            Structured output conforming to the output_model

        Raises:
            Exception: If all retries fail
        """
        structured_llm = llm.with_structured_output(output_model)

        for attempt in range(self.max_retries):
            try:
                result = await structured_llm.ainvoke(prompt, **kwargs)
                if attempt > 0:
                    logger.info(f"✅ Structured output succeeded on attempt {attempt + 1}")
                return result
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"❌ Structured output failed after {self.max_retries} attempts: {e}")
                    raise Exception(f"Structured output failed after {self.max_retries} attempts: {str(e)}") from e

                wait_time = self.retry_delay * (2**attempt)
                logger.warning(f"⚠️ Structured output attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

        raise Exception(f"Structured output failed after {self.max_retries} attempts")

    async def _execute_with_timeout(self, coro, timeout: float = 30.0):
        """
        Execute a coroutine with timeout handling.

        Args:
            coro: The coroutine to execute
            timeout: Timeout in seconds

        Returns:
            The result of the coroutine

        Raises:
            Exception: If the operation times out
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as err:
            raise Exception(f"Operation timed out after {timeout} seconds") from err

    @abstractmethod
    async def execute(self, **kwargs) -> AgentResult:
        """Execute the agent with given parameters."""
        pass


class SupervisorAgent(BaseAgent):
    """
    Supervisor agent that coordinates multiple sub-agents.
    """

    def __init__(self, sub_agents: dict[str, BaseAgent] = None, **kwargs):
        self.sub_agents = sub_agents or {}
        super().__init__(**kwargs)

    async def coordinate_agents(self, task: str, **kwargs) -> AgentResult:
        """
        Coordinate multiple agents to complete a complex task.

        Args:
            task: Description of the task to coordinate
            **kwargs: Additional parameters for the task

        Returns:
            AgentResult with the coordinated results
        """
        # This is a template for supervisor coordination
        # Subclasses should implement specific coordination logic
        raise NotImplementedError("Subclasses must implement coordinate_agents")
