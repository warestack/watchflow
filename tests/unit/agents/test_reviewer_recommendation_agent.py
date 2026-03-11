"""
Unit tests for the ReviewerRecommendationAgent.

Covers:
- Risk scoring logic (assess_risk node)
- CODEOWNERS parsing helper
- Watchflow rule matching
- Reviewer candidate scoring (recommend_reviewers node, pre-LLM)
- Load balancing penalties
- Revert / dependency / breaking change detection
- Agent factory registration
- AgentResult output shape
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.reviewer_recommendation_agent.models import (
    RecommendationState,
)
from src.agents.reviewer_recommendation_agent.nodes import (
    _match_watchflow_rules,
    _parse_codeowners,
    assess_risk,
    recommend_reviewers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> RecommendationState:
    defaults = {"repo_full_name": "owner/repo", "pr_number": 1, "installation_id": 42}
    defaults.update(kwargs)
    return RecommendationState(**defaults)


# ---------------------------------------------------------------------------
# _parse_codeowners
# ---------------------------------------------------------------------------


class TestParseCodeowners:
    def test_simple_ownership(self):
        # More specific rule must come last — last match wins in CODEOWNERS
        content = "*.py @bob\nsrc/billing/ @alice"
        result = _parse_codeowners(content, ["src/billing/charge.py", "utils/helper.py"])
        assert "alice" in result.get("src/billing/charge.py", [])
        assert "bob" in result.get("utils/helper.py", [])

    def test_org_team_stripped(self):
        content = "infra/ @myorg/devops"
        result = _parse_codeowners(content, ["infra/k8s/deploy.yaml"])
        # team name after org/ prefix is kept
        assert "devops" in result.get("infra/k8s/deploy.yaml", [])

    def test_last_rule_wins(self):
        content = "*.py @first\nsrc/*.py @second"
        result = _parse_codeowners(content, ["src/main.py"])
        owners = result.get("src/main.py", [])
        assert "second" in owners
        assert "first" not in owners

    def test_comments_and_blank_lines_ignored(self):
        content = "# This is a comment\n\n*.md @carol"
        result = _parse_codeowners(content, ["README.md"])
        assert "carol" in result.get("README.md", [])

    def test_no_match_returns_empty(self):
        content = "src/ @alice"
        result = _parse_codeowners(content, ["docs/readme.md"])
        assert result.get("docs/readme.md") is None


# ---------------------------------------------------------------------------
# assess_risk
# ---------------------------------------------------------------------------


class TestAssessRisk:
    @pytest.mark.asyncio
    async def test_low_risk_small_pr(self):
        # Set pr_author_association to MEMBER to avoid first-time contributor signal
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_additions=10,
            pr_deletions=5,
            pr_author_association="MEMBER",
        )
        result = await assess_risk(state)
        assert result.risk_level == "low"
        assert result.risk_score <= 3

    @pytest.mark.asyncio
    async def test_high_file_count_raises_risk(self):
        state = _make_state(pr_files=[f"src/file{i}.py" for i in range(60)])
        result = await assess_risk(state)
        assert result.risk_score >= 3
        assert any("files changed" in s.description for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_many_lines_raises_risk(self):
        state = _make_state(pr_files=["src/main.py"], pr_additions=1500, pr_deletions=600)
        result = await assess_risk(state)
        assert result.risk_score >= 2
        assert any("lines" in s.description for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_sensitive_path_raises_risk(self):
        state = _make_state(pr_files=["src/auth/login.py", "config/prod.yaml"])
        result = await assess_risk(state)
        assert any("Security-sensitive" in s.label for s in result.risk_signals)
        assert result.risk_score >= 2

    @pytest.mark.asyncio
    async def test_no_tests_in_pr_raises_risk(self):
        state = _make_state(pr_files=["src/service.py", "src/handler.py"])
        result = await assess_risk(state)
        assert any("test" in s.label.lower() for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_test_files_present_no_coverage_signal(self):
        state = _make_state(pr_files=["src/service.py", "tests/test_service.py"])
        result = await assess_risk(state)
        assert not any("test" in s.label.lower() for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_first_time_contributor_raises_risk(self):
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author="newdev",
            pr_author_association="FIRST_TIME_CONTRIBUTOR",
        )
        result = await assess_risk(state)
        assert any("contributor" in s.label.lower() for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_error_state_passes_through(self):
        state = _make_state(error="Something went wrong")
        result = await assess_risk(state)
        # Should not overwrite the existing error
        assert result.error == "Something went wrong"
        assert result.risk_signals == []

    @pytest.mark.asyncio
    async def test_risk_level_critical(self):
        # Large changeset + sensitive paths + first-time contributor + many lines
        files = [f"src/auth/file{i}.py" for i in range(55)]
        state = _make_state(
            pr_files=files,
            pr_additions=2500,
            pr_deletions=500,
            pr_author_association="FIRST_TIME_CONTRIBUTOR",
        )
        result = await assess_risk(state)
        assert result.risk_level in ("high", "critical")

    @pytest.mark.asyncio
    async def test_watchflow_rule_matches_compound_severity(self):
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author_association="MEMBER",
            matched_rules=[
                {"description": "No force push", "severity": "critical"},
                {"description": "Require tests", "severity": "high"},
            ],
        )
        result = await assess_risk(state)
        assert any("Watchflow rule" in s.label for s in result.risk_signals)
        # critical=5 + high=3 = 8 points from rules alone
        rule_signal = next(s for s in result.risk_signals if "Watchflow rule" in s.label)
        assert rule_signal.points >= 8

    @pytest.mark.asyncio
    async def test_revert_pr_raises_risk(self):
        state = _make_state(
            pr_files=["src/main.py"],
            pr_title='Revert "Add new feature"',
            pr_author_association="MEMBER",
        )
        result = await assess_risk(state)
        assert any("Revert" in s.label for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_dependency_changes_raises_risk(self):
        state = _make_state(
            pr_files=["package.json", "package-lock.json", "src/app.ts"],
            pr_author_association="MEMBER",
        )
        result = await assess_risk(state)
        assert any("Dependency" in s.label for s in result.risk_signals)

    @pytest.mark.asyncio
    async def test_breaking_changes_raises_risk(self):
        state = _make_state(
            pr_files=["api/v2/users.py", "src/handler.py"],
            pr_author_association="MEMBER",
        )
        result = await assess_risk(state)
        assert any("breaking" in s.label.lower() for s in result.risk_signals)


# ---------------------------------------------------------------------------
# _match_watchflow_rules
# ---------------------------------------------------------------------------


class TestMatchWatchflowRules:
    def _make_rule(self, description: str, severity: str, params: dict) -> MagicMock:
        rule = MagicMock()
        rule.description = description
        rule.severity = MagicMock(value=severity)
        rule.parameters = params
        rule.event_types = [MagicMock(value="pull_request")]
        return rule

    def test_path_based_rule_matches(self):
        rule = self._make_rule("Billing rules", "critical", {"protected_paths": ["src/billing/*"]})
        result = _match_watchflow_rules([rule], ["src/billing/charge.py", "README.md"])
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_non_path_rule_always_matches_for_pr(self):
        rule = self._make_rule("Require linked issue", "medium", {"require_linked_issue": True})
        result = _match_watchflow_rules([rule], ["src/main.py"])
        assert len(result) == 1

    def test_no_match_for_unrelated_path(self):
        rule = self._make_rule("Billing rules", "critical", {"protected_paths": ["src/billing/*"]})
        result = _match_watchflow_rules([rule], ["docs/readme.md"])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# recommend_reviewers (pre-LLM scoring only, LLM mocked)
# ---------------------------------------------------------------------------


class TestRecommendReviewers:
    def _make_mock_llm(self, ranked: list[dict]) -> MagicMock:
        """Returns a mock LLM whose structured output returns a fixed ranking."""
        from src.agents.reviewer_recommendation_agent.models import LLMReviewerRanking

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=LLMReviewerRanking(ranked_reviewers=ranked, summary="LLM summary")
        )
        mock_llm.with_structured_output.return_value = mock_structured
        return mock_llm

    @pytest.mark.asyncio
    async def test_codeowners_owner_becomes_top_candidate(self):
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content="src/billing/ @alice",
            contributors=[],
            file_experts={},
        )
        mock_llm = self._make_mock_llm([{"username": "alice", "reason": "billing owner"}])
        result = await recommend_reviewers(state, mock_llm)
        assert any(c.username == "alice" for c in result.candidates)
        top = max(result.candidates, key=lambda c: c.score)
        assert top.username == "alice"

    @pytest.mark.asyncio
    async def test_pr_author_excluded_from_candidates(self):
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author="alice",
            codeowners_content="src/ @alice",
            contributors=[{"login": "alice", "contributions": 100}],
            file_experts={"src/main.py": ["alice", "bob"]},
        )
        mock_llm = self._make_mock_llm([{"username": "bob", "reason": "expert"}])
        result = await recommend_reviewers(state, mock_llm)
        assert not any(c.username == "alice" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_file_expert_gets_points(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[],
            file_experts={"src/utils.py": ["bob", "carol"]},
        )
        mock_llm = self._make_mock_llm([{"username": "bob", "reason": "expert"}])
        result = await recommend_reviewers(state, mock_llm)
        bob = next((c for c in result.candidates if c.username == "bob"), None)
        assert bob is not None
        assert bob.score > 0

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_gracefully(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content="src/ @alice",
            contributors=[],
            file_experts={},
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        # Should still have a fallback ranking
        assert result.llm_ranking is not None
        assert len(result.llm_ranking.ranked_reviewers) > 0

    @pytest.mark.asyncio
    async def test_no_candidates_returns_empty(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[],
            file_experts={},
        )
        mock_llm = self._make_mock_llm([])
        result = await recommend_reviewers(state, mock_llm)
        assert result.llm_ranking is None or result.llm_ranking.ranked_reviewers == []

    @pytest.mark.asyncio
    async def test_load_balancing_penalizes_overloaded_reviewer(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content="src/ @alice @bob",
            contributors=[],
            file_experts={},
            # alice has way more reviews than bob
            reviewer_load={"alice": 10, "bob": 2, "carol": 3},
        )
        mock_llm = self._make_mock_llm(
            [
                {"username": "bob", "reason": "less loaded"},
                {"username": "alice", "reason": "overloaded"},
            ]
        )
        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        bob = next((c for c in result.candidates if c.username == "bob"), None)
        assert alice is not None and bob is not None
        # Alice's score should be penalized relative to bob's
        assert alice.score <= bob.score or any("penalty" in r.lower() for r in alice.reasons)

    @pytest.mark.asyncio
    async def test_high_severity_rules_boost_experienced_candidates(self):
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content="src/billing/ @alice",
            contributors=[],
            file_experts={"src/billing/charge.py": ["alice"]},
            matched_rules=[{"description": "Billing critical", "severity": "critical"}],
        )
        mock_llm = self._make_mock_llm([{"username": "alice", "reason": "expert"}])
        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        assert alice is not None
        assert any("critical" in r.lower() or "high" in r.lower() for r in alice.reasons)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


class TestReviewerRecommendationAgentFactory:
    @patch("src.agents.reviewer_recommendation_agent.agent.ReviewerRecommendationAgent.__init__", return_value=None)
    def test_factory_returns_correct_type(self, mock_init):
        from src.agents.factory import get_agent
        from src.agents.reviewer_recommendation_agent import ReviewerRecommendationAgent

        agent = get_agent("reviewer_recommendation")
        assert isinstance(agent, ReviewerRecommendationAgent)

    def test_factory_raises_for_unknown_type(self):
        from src.agents.factory import get_agent

        with pytest.raises(ValueError, match="Unsupported agent type"):
            get_agent("nonexistent_agent")


# ---------------------------------------------------------------------------
# Agent execute() — missing required params
# ---------------------------------------------------------------------------


class TestReviewerRecommendationAgentExecute:
    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__", return_value=None)
    async def test_execute_returns_failure_on_missing_params(self, mock_init):
        from src.agents.reviewer_recommendation_agent.agent import ReviewerRecommendationAgent

        agent = ReviewerRecommendationAgent.__new__(ReviewerRecommendationAgent)
        agent.max_retries = 3
        agent.retry_delay = 1.0
        agent.agent_name = "reviewer_recommendation"
        agent.graph = MagicMock()

        result = await agent.execute()  # no kwargs
        assert result.success is False
        assert "required" in result.message

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__", return_value=None)
    async def test_execute_returns_failure_on_timeout(self, mock_init):
        from src.agents.reviewer_recommendation_agent.agent import ReviewerRecommendationAgent

        agent = ReviewerRecommendationAgent.__new__(ReviewerRecommendationAgent)
        agent.max_retries = 3
        agent.retry_delay = 1.0
        agent.agent_name = "reviewer_recommendation"

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(side_effect=TimeoutError())
        agent.graph = mock_graph

        result = await agent.execute(repo_full_name="owner/repo", pr_number=1, installation_id=42)
        assert result.success is False
        assert "timed out" in result.message.lower()
