"""
Reviewer Reasoning Agent — generates natural language explanations for reviewer selections.
"""

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.agents.reviewer_reasoning_agent.models import (
    ReviewerProfile,
    ReviewerReasoningInput,
    ReviewerReasoningOutput,
)
from src.agents.reviewer_reasoning_agent.prompts import create_reasoning_prompt, get_system_prompt
from src.integrations.providers import get_chat_model

logger = logging.getLogger(__name__)


class ReviewerReasoningAgent(BaseAgent):
    """Agent that uses LLM reasoning to explain why each reviewer was selected.

    Produces one concise sentence per reviewer grounded in their expertise profile,
    the PR's changed files, and triggered risk signals. Gracefully degrades to
    mechanical reasons on any failure.
    """

    def __init__(self, max_retries: int = 3, timeout: float = 30.0):
        super().__init__(max_retries=max_retries, agent_name="reviewer_reasoning")
        self.timeout = timeout
        logger.info(f"🧠 ReviewerReasoningAgent initialized with timeout: {timeout}s")

    def _build_graph(self) -> Any:
        """Build a single-node LangGraph workflow for reasoning generation."""
        workflow = StateGraph(ReviewerReasoningInput)
        workflow.add_node("generate_reasoning", self._reasoning_node)
        workflow.set_entry_point("generate_reasoning")
        workflow.set_finish_point("generate_reasoning")
        return workflow.compile()

    async def _reasoning_node(self, state: Any) -> dict[str, Any]:
        """LangGraph node that generates reviewer reasoning."""
        try:
            result = await self.generate_reasoning(
                risk_level=state.risk_level,
                changed_files=state.changed_files,
                risk_signals=state.risk_signals,
                reviewers=state.reviewers,
                global_rules=state.global_rules,
                path_rules=state.path_rules,
            )
            return {"result": result}
        except Exception as e:
            logger.error(f"Error in reasoning node: {e}")
            return {"result": AgentResult(success=False, message=str(e))}

    async def generate_reasoning(
        self,
        risk_level: str,
        changed_files: list[str],
        risk_signals: list[str],
        reviewers: list[ReviewerProfile],
        global_rules: list[str] | None = None,
        path_rules: list[str] | None = None,
    ) -> AgentResult:
        """Generate natural language reasoning for each reviewer and labels for global/path rules.

        Returns AgentResult with:
          data["explanations"] = {login: sentence, ...}
          data["rule_labels"]  = {description: label, ...}
        """
        if not reviewers:
            return AgentResult(success=True, message="No reviewers to explain", data={"explanations": {}, "rule_labels": {}})

        start_time = time.time()

        try:
            human_prompt = create_reasoning_prompt(risk_level, changed_files, risk_signals, reviewers, global_rules, path_rules)

            llm = get_chat_model(agent="reviewer_reasoning")
            structured_llm = llm.with_structured_output(ReviewerReasoningOutput)

            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=human_prompt),
            ]

            result: ReviewerReasoningOutput = await self._execute_with_timeout(
                structured_llm.ainvoke(messages), timeout=self.timeout
            )

            if not result or not result.explanations:
                return AgentResult(
                    success=False,
                    message="LLM returned empty reasoning",
                    data={"explanations": {}, "rule_labels": {}},
                )

            explanations = {e.login: e.reasoning for e in result.explanations if e.login and e.reasoning}
            rule_labels = {rl.description: rl.label for rl in (result.rule_labels or []) if rl.description and rl.label}

            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Reviewer reasoning generated for {len(explanations)} reviewer(s) in {latency_ms}ms")

            return AgentResult(
                success=True,
                message=f"Generated reasoning for {len(explanations)} reviewer(s)",
                data={"explanations": explanations, "rule_labels": rule_labels},
                metadata={"latency_ms": latency_ms, "reviewer_count": len(explanations)},
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning(f"Reviewer reasoning failed after {latency_ms}ms: {e}")
            return AgentResult(
                success=False,
                message=f"Reasoning generation failed: {e}",
                data={"explanations": {}, "rule_labels": {}},
                metadata={"latency_ms": latency_ms, "error": str(e)},
            )

    async def execute(self, **kwargs: Any) -> AgentResult:
        """Execute the reviewer reasoning agent."""
        risk_level = kwargs.get("risk_level", "medium")
        changed_files = kwargs.get("changed_files", [])
        risk_signals = kwargs.get("risk_signals", [])
        reviewers = kwargs.get("reviewers", [])
        global_rules = kwargs.get("global_rules", [])
        path_rules = kwargs.get("path_rules", [])

        # Accept raw dicts and convert to ReviewerProfile
        reviewer_profiles = [r if isinstance(r, ReviewerProfile) else ReviewerProfile(**r) for r in reviewers]

        return await self.generate_reasoning(
            risk_level=risk_level,
            changed_files=changed_files,
            risk_signals=risk_signals,
            reviewers=reviewer_profiles,
            global_rules=global_rules,
            path_rules=path_rules,
        )
