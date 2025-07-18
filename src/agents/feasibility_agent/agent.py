"""
Rule Feasibility Agent implementation.
"""

import logging

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent

from .models import FeasibilityResult, FeasibilityState
from .nodes import analyze_rule_feasibility, generate_yaml_config

logger = logging.getLogger(__name__)


class RuleFeasibilityAgent(BaseAgent):
    """
    LangGraph agent for checking if a user's natural language rule is feasible.
    """

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for rule feasibility checking."""
        workflow = StateGraph(FeasibilityState)

        # Add nodes
        workflow.add_node("analyze_feasibility", analyze_rule_feasibility)
        workflow.add_node("generate_yaml", generate_yaml_config)

        # Add edges
        workflow.add_edge(START, "analyze_feasibility")
        workflow.add_edge("analyze_feasibility", "generate_yaml")
        workflow.add_edge("generate_yaml", END)

        return workflow.compile()

    async def execute(self, rule_description: str) -> AgentResult:
        """
        Check if a rule description is feasible and return YAML or feedback.
        """
        try:
            # Prepare initial state
            initial_state = FeasibilityState(rule_description=rule_description)

            # Run the graph
            result = await self.graph.ainvoke(initial_state)

            # Convert to AgentResult
            return AgentResult(
                success=result.get("is_feasible", False),
                message=result.get("feedback", ""),
                data={
                    "is_feasible": result.get("is_feasible", False),
                    "yaml_content": result.get("yaml_content", ""),
                    "confidence_score": result.get("confidence_score", 0.0),
                    "rule_type": result.get("rule_type", ""),
                    "analysis_steps": result.get("analysis_steps", []),
                },
            )

        except Exception as e:
            logger.error(f"Error in rule feasibility check: {e}")
            return AgentResult(success=False, message=f"Feasibility check failed: {str(e)}", data={})

    async def check_feasibility(self, rule_description: str) -> FeasibilityResult:
        """
        Legacy method for backwards compatibility.
        """
        result = await self.execute(rule_description)

        return FeasibilityResult(
            is_feasible=result.data.get("is_feasible", False),
            yaml_content=result.data.get("yaml_content", ""),
            feedback=result.message,
            confidence_score=result.data.get("confidence_score"),
            rule_type=result.data.get("rule_type"),
        )
