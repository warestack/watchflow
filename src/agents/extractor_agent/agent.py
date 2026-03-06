"""
Rule Extractor Agent: LLM-powered extraction of rule-like statements from markdown.
"""

import logging
import re
import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.agents.base import AgentResult, BaseAgent
from src.agents.extractor_agent.models import ExtractorOutput
from src.agents.extractor_agent.prompts import EXTRACTOR_PROMPT

logger = logging.getLogger(__name__)

# Max length/byte cap for markdown input to reduce prompt-injection and token cost
MAX_EXTRACTOR_INPUT_LENGTH = 16_000

# Patterns to redact (replaced with [REDACTED]) before sending to LLM
_REDACT_PATTERNS = [
    (re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[\w\-]{20,}['\"]?", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"(?i)token\s*[:=]\s*['\"]?[\w\-\.]{20,}['\"]?", re.IGNORECASE), "[REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[\w\-\.]+", re.IGNORECASE), "Bearer [REDACTED]"),
]


def redact_and_cap(text: str, max_length: int = MAX_EXTRACTOR_INPUT_LENGTH) -> str:
    """Sanitize and cap input: redact secret/PII-like patterns and enforce max length."""
    if not text or not isinstance(text, str):
        return ""
    out = text.strip()
    for pattern, replacement in _REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    if len(out) > max_length:
        out = out[:max_length].rstrip() + "\n\n[truncated]"
    return out


class ExtractorState(BaseModel):
    """State for the extractor (single-node) graph."""

    markdown_content: str = ""
    statements: list[str] = Field(default_factory=list)
    decision: str = ""
    confidence: float = 1.0
    reasoning: str = ""
    recommendations: list[str] = Field(default_factory=list)
    strategy_used: str = ""


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
            raw = (state.markdown_content or "").strip()
            if not raw:
                return {"statements": [], "decision": "none", "confidence": 0.0, "reasoning": "Empty input", "recommendations": [], "strategy_used": ""}
            content = redact_and_cap(raw)
            if not content:
                return {"statements": [], "decision": "none", "confidence": 0.0, "reasoning": "Empty after sanitization", "recommendations": [], "strategy_used": ""}
            prompt = EXTRACTOR_PROMPT.format(markdown_content=content)
            structured_llm = self.llm.with_structured_output(ExtractorOutput)
            result = await structured_llm.ainvoke(prompt)
            return {
                "statements": result.statements,
                "decision": result.decision or "extracted",
                "confidence": result.confidence,
                "reasoning": result.reasoning or "",
                "recommendations": result.recommendations or [],
                "strategy_used": result.strategy_used or "",
            }

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
                data={
                    "statements": [],
                    "decision": "none",
                    "confidence": 0.0,
                    "reasoning": "Empty content",
                    "recommendations": [],
                    "strategy_used": "",
                },
                metadata={"execution_time_ms": 0},
            )

        try:
            sanitized = redact_and_cap(markdown_content)
            logger.info("🚀 Extractor agent processing markdown (%s chars)", len(sanitized))
            initial_state = ExtractorState(markdown_content=sanitized)
            result = await self._execute_with_timeout(
                self.graph.ainvoke(initial_state),
                timeout=self.timeout,
            )
            execution_time = time.time() - start_time
            meta_base = {"execution_time_ms": execution_time * 1000}

            if isinstance(result, dict):
                statements = result.get("statements", [])
                decision = result.get("decision", "extracted")
                confidence = float(result.get("confidence", 1.0))
                reasoning = result.get("reasoning", "")
                recommendations = result.get("recommendations", []) or []
                strategy_used = result.get("strategy_used", "")
            elif hasattr(result, "statements"):
                statements = result.statements
                decision = getattr(result, "decision", "extracted")
                confidence = float(getattr(result, "confidence", 1.0))
                reasoning = getattr(result, "reasoning", "") or ""
                recommendations = getattr(result, "recommendations", []) or []
                strategy_used = getattr(result, "strategy_used", "") or ""
            else:
                statements = []
                decision = "none"
                confidence = 0.0
                reasoning = ""
                recommendations = []
                strategy_used = ""

            payload = {
                "statements": statements,
                "decision": decision,
                "confidence": confidence,
                "reasoning": reasoning,
                "recommendations": recommendations,
                "strategy_used": strategy_used,
            }

            if confidence < 0.5:
                logger.info(
                    "Extractor confidence below threshold (%.2f); routing to human review",
                    confidence,
                )
                return AgentResult(
                    success=False,
                    message="Low confidence; routed to human review",
                    data=payload,
                    metadata={**meta_base, "routing": "human_review"},
                )
            logger.info(
                "✅ Extractor agent completed in %.2fs; extracted %s statements (confidence=%.2f)",
                execution_time,
                len(statements),
                confidence,
            )
            return AgentResult(
                success=True,
                message="OK",
                data=payload,
                metadata={**meta_base},
            )
        except TimeoutError:
            execution_time = time.time() - start_time
            logger.error("❌ Extractor agent timed out after %.2fs", execution_time)
            return AgentResult(
                success=False,
                message=f"Extractor timed out after {self.timeout}s",
                data={
                    "statements": [],
                    "decision": "none",
                    "confidence": 0.0,
                    "reasoning": "Timeout",
                    "recommendations": [],
                    "strategy_used": "",
                },
                metadata={"execution_time_ms": execution_time * 1000, "error_type": "timeout", "routing": "human_review"},
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.exception("❌ Extractor agent failed: %s", e)
            return AgentResult(
                success=False,
                message=str(e),
                data={
                    "statements": [],
                    "decision": "none",
                    "confidence": 0.0,
                    "reasoning": str(e)[:500],
                    "recommendations": [],
                    "strategy_used": "",
                },
                metadata={"execution_time_ms": execution_time * 1000, "error_type": type(e).__name__, "routing": "human_review"},
            )
