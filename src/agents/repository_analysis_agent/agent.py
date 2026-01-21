# File: src/agents/repository_analysis_agent/agent.py
import logging

from langgraph.graph import END, StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.agents.repository_analysis_agent import nodes
from src.agents.repository_analysis_agent.models import AnalysisState

logger = logging.getLogger(__name__)


class RepositoryAnalysisAgent(BaseAgent):
    """
    Agent responsible for inspecting a repository and suggesting Watchflow rules.
    """

    def __init__(self):
        # We use 'repository_analysis' to look up config like max_tokens
        super().__init__(agent_name="repository_analysis")

    def _build_graph(self) -> StateGraph:
        """
        Flow: Fetch Metadata -> Generate Rules -> END
        """
        workflow = StateGraph(AnalysisState)

        # Register Nodes
        workflow.add_node("fetch_metadata", nodes.fetch_repository_metadata)
        workflow.add_node("generate_rules", nodes.generate_rule_recommendations)

        # Define Edges
        workflow.set_entry_point("fetch_metadata")
        workflow.add_edge("fetch_metadata", "generate_rules")
        workflow.add_edge("generate_rules", END)

        return workflow.compile()

    async def execute(self, repo_full_name: str, is_public: bool = False) -> AgentResult:
        """
        Public entry point for the API.
        """
        initial_state = AnalysisState(repo_full_name=repo_full_name, is_public=is_public)

        try:
            # Execute Graph
            # .model_dump() is required because LangGraph expects a dict input
            result_dict = await self.graph.ainvoke(initial_state.model_dump())

            # Rehydrate State
            final_state = AnalysisState(**result_dict)

            if final_state.error:
                return AgentResult(success=False, message=final_state.error)

            return AgentResult(
                success=True, message="Analysis complete", data={"recommendations": final_state.recommendations}
            )

        except Exception as e:
            logger.exception("RepositoryAnalysisAgent execution failed")
            return AgentResult(success=False, message=str(e))
