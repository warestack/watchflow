import logging
import time
from datetime import datetime
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.agents.repository_analysis_agent.models import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryAnalysisState,
)
from src.agents.repository_analysis_agent.nodes import (
    analyze_contributing_guidelines,
    analyze_repository_structure,
    generate_rule_recommendations,
    summarize_analysis,
    validate_recommendations,
)

logger = logging.getLogger(__name__)


class RepositoryAnalysisAgent(BaseAgent):
    """
    Agent that analyzes GitHub repositories to generate Watchflow rule recommendations.

    This agent performs multi-step analysis:
    1. Analyzes repository structure and features
    2. Parses contributing guidelines for patterns
    3. Reviews commit/PR patterns
    4. Generates rule recommendations with confidence scores
    5. Validates recommendations are valid YAML

    Returns structured recommendations that can be directly used as Watchflow rules.
    """

    def __init__(self, max_retries: int = 3, timeout: float = 120.0):
        super().__init__(max_retries=max_retries, agent_name="repository_analysis_agent")
        self.timeout = timeout

        logger.info("Repository Analysis Agent initialized")
        logger.info(f"Max retries: {max_retries}, Timeout: {timeout}s")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for repository analysis."""
        workflow = StateGraph(RepositoryAnalysisState)

        # Add nodes
        workflow.add_node("analyze_repository_structure", analyze_repository_structure)
        workflow.add_node("analyze_pr_history", analyze_pr_history)
        workflow.add_node("analyze_contributing_guidelines", analyze_contributing_guidelines)
        workflow.add_node("generate_rule_recommendations", generate_rule_recommendations)
        workflow.add_node("validate_recommendations", validate_recommendations)
        workflow.add_node("summarize_analysis", summarize_analysis)

        # Define workflow edges
        workflow.add_edge(START, "analyze_repository_structure")
        workflow.add_edge("analyze_repository_structure", "analyze_pr_history")
        workflow.add_edge("analyze_pr_history", "analyze_contributing_guidelines")
        workflow.add_edge("analyze_contributing_guidelines", "generate_rule_recommendations")
        workflow.add_edge("generate_rule_recommendations", "validate_recommendations")
        workflow.add_edge("validate_recommendations", "summarize_analysis")
        workflow.add_edge("summarize_analysis", END)

        return workflow.compile()

    async def execute(
        self,
        repository_full_name: str,
        installation_id: int | None = None,
        **kwargs
    ) -> AgentResult:
        """
        Analyze a repository and generate rule recommendations.

        Args:
            repository_full_name: Full repository name (owner/repo)
            installation_id: Optional GitHub App installation ID for private repos
            **kwargs: Additional parameters

        Returns:
            AgentResult containing analysis results and recommendations
        """
        start_time = time.time()

        try:
            logger.info(f"Starting repository analysis for {repository_full_name}")

            # Validate input
            if not repository_full_name or "/" not in repository_full_name:
                return AgentResult(
                    success=False,
                    message="Invalid repository name format. Expected 'owner/repo'",
                    data={},
                    metadata={"execution_time_ms": 0}
                )

           
            initial_state = RepositoryAnalysisState(
                repository_full_name=repository_full_name,
                installation_id=installation_id,
                analysis_steps=[],
                errors=[],
            )

            logger.info("Initial state prepared, starting analysis workflow")

            
            result = await self._execute_with_timeout(
                self.graph.ainvoke(initial_state),
                timeout=self.timeout
            )

            execution_time = time.time() - start_time
            logger.info(f"Analysis completed in {execution_time:.2f}s")

          
            if isinstance(result, dict):
                state = RepositoryAnalysisState(**result)
            else:
                state = result

         
            response = RepositoryAnalysisResponse(
                repository_full_name=repository_full_name,
                recommendations=state.recommendations,
                analysis_summary=state.analysis_summary,
                analyzed_at=datetime.now().isoformat(),
                total_recommendations=len(state.recommendations),
            )

            # Check for errors
            has_errors = len(state.errors) > 0
            success_message = (
                f"Analysis completed successfully with {len(state.recommendations)} recommendations"
            )
            if has_errors:
                success_message += f" ({len(state.errors)} errors encountered)"

            logger.info(f"Analysis result: {len(state.recommendations)} recommendations, {len(state.errors)} errors")

            return AgentResult(
                success=not has_errors,  
                message=success_message,
                data={"analysis_response": response},
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "recommendations_count": len(state.recommendations),
                    "errors_count": len(state.errors),
                    "analysis_steps": state.analysis_steps,
                }
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error in repository analysis: {e}")

            return AgentResult(
                success=False,
                message=f"Repository analysis failed: {str(e)}",
                data={},
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "error_type": type(e).__name__,
                }
            )

    async def analyze_repository(self, request: RepositoryAnalysisRequest) -> RepositoryAnalysisResponse:
        """
        Convenience method for analyzing a repository using the request model.

        Args:
            request: Repository analysis request

        Returns:
            Repository analysis response
        """
        result = await self.execute(
            repository_full_name=request.repository_full_name,
            installation_id=request.installation_id,
        )

        if result.success and "analysis_response" in result.data:
            return result.data["analysis_response"]
        else:
           
            return RepositoryAnalysisResponse(
                repository_full_name=request.repository_full_name,
                recommendations=[],
                analysis_summary={"error": result.message},
                analyzed_at=datetime.now().isoformat(),
                total_recommendations=0,
            )
