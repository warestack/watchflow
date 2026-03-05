"""
Rule Extractor Agent: LLM-powered extraction of rule-like statements from markdown.
"""

import logging
import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.agents.base import AgentResult, BaseAgent
from src.agents.extractor_agent.models import ExtractorOutput
from src.agents.extractor_agent.prompts import EXTRACTOR_PROMPT

logger = logging.getLogger(__name__)


class ExtractorState(BaseModel):
    """State for the extractor (single-node) graph."""

    markdown_content: str = ""
    statements: list[str] = Field(default_factory=list)


class RuleExtractorAgent(BaseAgent):
    """
    Extractor Agent: reads raw markdown and returns a structured list of rule-like statements.
    Single-node LangGraph: extract -> END. Uses LLM with structured output.
    """

    def __init__(self, max_retries: int = 3, timeout: float = 30.0):
        super().__init__(max_retries=max_retries, agent_name="extractor_agent")
        self.timeout = timeout
        logger.info("🔧 RuleExtractorAgent initialized with max_retries=%s, timeout=%ss", max_retries, timeout)

    def _build_graph(self):
        """Single node: run LLM extraction and set state.statements."""
        workflow = StateGraph(ExtractorState)

        async def extract_node(state: ExtractorState) -> dict:
            content = (state.markdown_content or "").strip()
            if not content:
                return {"statements": []}
            prompt = EXTRACTOR_PROMPT.format(markdown_content=content)
            structured_llm = self.llm.with_structured_output(ExtractorOutput)
            result = await structured_llm.ainvoke(prompt)
            return {"statements": result.statements}

        workflow.add_node("extract", extract_node)
        workflow.add_edge(START, "extract")
        workflow.add_edge("extract", END)
        return workflow.compile()

    async def execute(self, **kwargs: Any) -> AgentResult:
        """Extract rule statements from markdown. Expects markdown_content=... in kwargs."""
        markdown_content = kwargs.get("markdown_content") or kwargs.get("content") or ""
        if not isinstance(markdown_content, str):
            markdown_content = str(markdown_content or "")

        start_time = time.time()

        if not markdown_content.strip():
            return AgentResult(
                success=True,
                message="Empty content",
                data={"statements": []},
                metadata={"execution_time_ms": 0},
            )

        try:
            logger.info("🚀 Extractor agent processing markdown (%s chars)", len(markdown_content))
            initial_state = ExtractorState(markdown_content=markdown_content)
            result = await self._execute_with_timeout(
                self.graph.ainvoke(initial_state),
                timeout=self.timeout,
            )
            if isinstance(result, dict):
                statements = result.get("statements", [])
            elif hasattr(result, "statements"):
                statements = result.statements
            else:
                statements = []
            execution_time = time.time() - start_time
            logger.info(
                "✅ Extractor agent completed in %.2fs; extracted %s statements",
                execution_time,
                len(statements),
            )
            return AgentResult(
                success=True,
                message="OK",
                data={"statements": statements},
                metadata={"execution_time_ms": execution_time * 1000},
            )
        except TimeoutError:
            execution_time = time.time() - start_time
            logger.error("❌ Extractor agent timed out after %.2fs", execution_time)
            return AgentResult(
                success=False,
                message=f"Extractor timed out after {self.timeout}s",
                data={"statements": []},
                metadata={"execution_time_ms": execution_time * 1000, "error_type": "timeout"},
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.exception("❌ Extractor agent failed: %s", e)
            return AgentResult(
                success=False,
                message=str(e),
                data={"statements": []},
                metadata={"execution_time_ms": execution_time * 1000, "error_type": type(e).__name__},
            )
