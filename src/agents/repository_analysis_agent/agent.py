"""
RepositoryAnalysisAgent orchestrates repository signal gathering and rule generation.
"""

from __future__ import annotations



from src.agents.base import AgentResult, BaseAgent
from src.agents.repository_analysis_agent.models import RepositoryAnalysisRequest, RepositoryAnalysisState
from src.agents.repository_analysis_agent.nodes import (
    _default_recommendations,
    analyze_contributing_guidelines,
    analyze_pr_history,
    analyze_repository_structure,
    summarize_analysis,
    validate_recommendations,
)


class RepositoryAnalysisAgent(BaseAgent):
    """Agent that inspects a repository and proposes Watchflow rules."""

    def _build_graph(self):
        # Graph orchestration is handled procedurally in execute for clarity.
        return None


        try:
            await analyze_repository_structure(state)
            await analyze_pr_history(state, request.max_prs)
            await analyze_contributing_guidelines(state)


            latency_ms = int((time.perf_counter() - started_at) * 1000)
            return AgentResult(

            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            return AgentResult(
                success=False,
                message=f"Repository analysis failed: {exc}",
                data={},
            )
