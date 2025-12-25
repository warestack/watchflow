"""
RepositoryAnalysisAgent orchestrates repository signal gathering and rule generation.
"""

from __future__ import annotations

import time

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

    async def execute(self, **kwargs) -> AgentResult:
        started_at = time.perf_counter()
        request = RepositoryAnalysisRequest(**kwargs)
        state = RepositoryAnalysisState(
            repository_full_name=request.repository_full_name,
            installation_id=request.installation_id,
        )

        try:
            await analyze_repository_structure(state)
            await analyze_pr_history(state, request.max_prs)
            await analyze_contributing_guidelines(state)

            # Only generate recommendations if we have basic repository data
            if not state.repository_features.language:
                raise ValueError("Unable to determine repository language - cannot generate appropriate rules")

            state.recommendations = _default_recommendations(state)
            validate_recommendations(state)
            response = summarize_analysis(state, request)

            latency_ms = int((time.perf_counter() - started_at) * 1000)
            return AgentResult(
                success=True,
                message="Repository analysis completed",
                data={"analysis_response": response},
                metadata={"execution_time_ms": latency_ms},
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            return AgentResult(
                success=False,
                message=f"Repository analysis failed: {exc}",
                data={},
                metadata={"execution_time_ms": latency_ms},
            )
