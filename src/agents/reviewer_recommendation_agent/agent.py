# File: src/agents/reviewer_recommendation_agent/agent.py

from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.agents.reviewer_recommendation_agent import nodes
from src.agents.reviewer_recommendation_agent.models import RecommendationState

logger = structlog.get_logger()


class ReviewerRecommendationAgent(BaseAgent):
    """
    Agent that recommends reviewers for a PR based on:
    1. CODEOWNERS ownership of changed files
    2. Commit history expertise (who recently touched the same files)
    3. Deterministic risk assessment (file count, sensitive paths, contributor status)
    4. LLM-powered ranking with natural-language reasoning

    Outputs both a risk breakdown and ranked reviewer suggestions.
    """

    def __init__(self) -> None:
        super().__init__(agent_name="reviewer_recommendation")

    def _build_graph(self) -> Any:
        workflow: StateGraph[RecommendationState] = StateGraph(RecommendationState)

        llm = self.llm

        async def _recommend_reviewers(state: RecommendationState) -> RecommendationState:
            return await nodes.recommend_reviewers(state, llm)

        workflow.add_node("fetch_pr_data", nodes.fetch_pr_data)
        workflow.add_node("assess_risk", nodes.assess_risk)
        workflow.add_node("recommend_reviewers", _recommend_reviewers)

        workflow.set_entry_point("fetch_pr_data")
        workflow.add_edge("fetch_pr_data", "assess_risk")
        workflow.add_edge("assess_risk", "recommend_reviewers")
        workflow.add_edge("recommend_reviewers", END)

        return workflow.compile()

    async def execute(self, **kwargs: Any) -> AgentResult:
        """
        Args:
            repo_full_name: str  — owner/repo
            pr_number: int       — PR number
            installation_id: int — GitHub App installation ID
        """
        repo_full_name: str | None = kwargs.get("repo_full_name")
        pr_number: int | None = kwargs.get("pr_number")
        installation_id: int | None = kwargs.get("installation_id")

        if not repo_full_name or not pr_number or not installation_id:
            return AgentResult(success=False, message="repo_full_name, pr_number, and installation_id are required")

        initial_state = RecommendationState(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            installation_id=installation_id,
        )

        try:
            result = await self._execute_with_timeout(self.graph.ainvoke(initial_state), timeout=45.0)
            final_state = RecommendationState(**result) if isinstance(result, dict) else result

            if final_state.error:
                return AgentResult(success=False, message=final_state.error)

            return AgentResult(
                success=True,
                message="Recommendation complete",
                data={
                    "risk_level": final_state.risk_level,
                    "risk_score": final_state.risk_score,
                    "risk_signals": [s.model_dump() for s in final_state.risk_signals],
                    "candidates": [c.model_dump() for c in final_state.candidates],
                    "llm_ranking": final_state.llm_ranking.model_dump() if final_state.llm_ranking else None,
                    "pr_files_count": len(final_state.pr_files),
                    "pr_author": final_state.pr_author,
                    "codeowners_team_slugs": final_state.codeowners_team_slugs,
                },
            )

        except TimeoutError:
            logger.error("agent_execution_timeout", agent="reviewer_recommendation", repo=repo_full_name)
            return AgentResult(success=False, message="Recommendation timed out after 45 seconds")
        except Exception as e:
            logger.exception("agent_execution_failed", agent="reviewer_recommendation", error=str(e))
            return AgentResult(success=False, message=str(e))
