import respx
from httpx import Response

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.agents.repository_analysis_agent.models import AnalysisState, HygieneMetrics

# Mock data for a repository
MOCK_REPO_URL = "https://github.com/mock/repo"
MOCK_REPO_FULL_NAME = "mock/repo"


@respx.mock
async def test_agent_returns_enhanced_metrics():
    """
    Verifies that the RepositoryAnalysisAgent correctly populates and returns
    the new HygieneMetrics with their default values in the final report.
    """
    # 1. Setup: Mock all necessary GitHub API endpoints for a full run
    respx.get(f"https://api.github.com/repos/{MOCK_REPO_FULL_NAME}").mock(
        return_value=Response(200, json={"default_branch": "main", "description": "A mock repo"})
    )
    respx.get(f"https://api.github.com/repos/{MOCK_REPO_FULL_NAME}/pulls").mock(return_value=Response(200, json=[]))
    respx.get(f"https://api.github.com/repos/{MOCK_REPO_FULL_NAME}/contents/").mock(return_value=Response(200, json=[]))
    # Mock the LLM call to prevent actual network requests - proper OpenAI structure
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"recommendations": []}'},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "model": "gpt-4",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
    )

    # 2. Action: Initialize the agent and invoke the graph directly to get the final state
    agent = RepositoryAnalysisAgent()
    graph = agent._build_graph()
    initial_state = AnalysisState(repo_full_name=MOCK_REPO_FULL_NAME, is_public=True)
    final_graph_state = await graph.ainvoke(initial_state)

    # 3. Assertion: Verify the HygieneMetrics in the final state
    assert final_graph_state is not None
    assert final_graph_state.get("hygiene_summary") is not None
    assert isinstance(final_graph_state["hygiene_summary"], HygieneMetrics)

    # Verify default values for enhanced hygiene metrics (Phase 2)
    metrics = final_graph_state["hygiene_summary"]
    assert metrics.issue_diff_mismatch_rate == 0.0
    assert metrics.ghost_contributor_rate == 0.0
    assert metrics.new_code_test_coverage == 0.0
    assert metrics.codeowner_bypass_rate == 0.0
    assert metrics.ai_generated_rate == 0.0

    # Verify no error occurred
    assert final_graph_state.get("error") is None
