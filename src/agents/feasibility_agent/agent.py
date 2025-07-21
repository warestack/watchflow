"""
Rule Feasibility Agent implementation.
"""

import logging

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent

from .models import FeasibilityState
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

        # Add edges with conditional logic
        workflow.add_edge(START, "analyze_feasibility")

        # Conditional edge: only generate YAML if feasible
        workflow.add_conditional_edges(
            "analyze_feasibility",
            lambda state: "generate_yaml" if state.is_feasible else END,
            {"generate_yaml": "generate_yaml", END: END},
        )

        workflow.add_edge("generate_yaml", END)

        logger.info("🔧 FeasibilityAgent graph built with conditional structured output workflow")
        return workflow.compile()

    async def execute(self, rule_description: str) -> AgentResult:
        """
        Check if a rule description is feasible and return YAML or feedback.
        """
        try:
            logger.info(f"🚀 Starting feasibility analysis for rule: {rule_description[:100]}...")

            # Prepare initial state
            initial_state = FeasibilityState(rule_description=rule_description)

            # Run the graph
            result = await self.graph.ainvoke(initial_state)

            # Convert dict result back to FeasibilityState if needed
            if isinstance(result, dict):
                result = FeasibilityState(**result)

            logger.info(f"✅ Feasibility analysis completed: feasible={result.is_feasible}, type={result.rule_type}")

            # Convert to AgentResult
            return AgentResult(
                success=result.is_feasible,
                message=result.feedback,
                data={
                    "is_feasible": result.is_feasible,
                    "yaml_content": result.yaml_content,
                    "confidence_score": result.confidence_score,
                    "rule_type": result.rule_type,
                    "analysis_steps": result.analysis_steps,
                },
            )

        except Exception as e:
            logger.error(f"❌ Error in rule feasibility check: {e}")
            return AgentResult(success=False, message=f"Feasibility check failed: {str(e)}", data={})
