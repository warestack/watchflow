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
    fetch_pr_data,
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
        individuals, teams = _parse_codeowners(content, ["src/billing/charge.py", "utils/helper.py"])
        assert "alice" in individuals.get("src/billing/charge.py", [])
        assert "bob" in individuals.get("utils/helper.py", [])

    def test_org_team_goes_to_team_owners(self):
        """@org/team entries must be in team_owners (not individual_owners) with slug only."""
        content = "infra/ @myorg/devops"
        individuals, teams = _parse_codeowners(content, ["infra/k8s/deploy.yaml"])
        # team slug in team_owners
        assert "devops" in teams.get("infra/k8s/deploy.yaml", [])
        # NOT treated as an individual user
        assert "devops" not in individuals.get("infra/k8s/deploy.yaml", [])

    def test_individual_and_team_mixed(self):
        """Lines with both @user and @org/team entries split correctly."""
        content = "src/ @alice @myorg/frontend"
        individuals, teams = _parse_codeowners(content, ["src/app.py"])
        assert "alice" in individuals.get("src/app.py", [])
        assert "frontend" in teams.get("src/app.py", [])
        assert "frontend" not in individuals.get("src/app.py", [])

    def test_last_rule_wins(self):
        content = "*.py @first\nsrc/*.py @second"
        individuals, _ = _parse_codeowners(content, ["src/main.py"])
        owners = individuals.get("src/main.py", [])
        assert "second" in owners
        assert "first" not in owners

    def test_comments_and_blank_lines_ignored(self):
        content = "# This is a comment\n\n*.md @carol"
        individuals, _ = _parse_codeowners(content, ["README.md"])
        assert "carol" in individuals.get("README.md", [])

    def test_no_match_returns_empty(self):
        content = "src/ @alice"
        individuals, teams = _parse_codeowners(content, ["docs/readme.md"])
        assert individuals.get("docs/readme.md") is None
        assert teams.get("docs/readme.md") is None


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
            risk_level="high",  # ensures both alice and bob are in top-3
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


# ---------------------------------------------------------------------------
# Rules-first risk scoring: hardcoded patterns are fallback only
# ---------------------------------------------------------------------------


class TestRulesFirstRiskScoring:
    @pytest.mark.asyncio
    async def test_hardcoded_patterns_skipped_when_rules_exist(self):
        """When matched_rules exist, sensitive path / dependency / breaking patterns are not used."""
        state = _make_state(
            pr_files=["src/auth/login.py", "config/prod.yaml", "package.json", "api/v2/users.py"],
            pr_additions=10,
            pr_deletions=5,
            pr_author_association="MEMBER",
            matched_rules=[{"description": "Protect auth", "severity": "critical"}],
        )
        result = await assess_risk(state)
        labels = [s.label for s in result.risk_signals]
        assert "Watchflow rule matches" in labels
        assert "Security-sensitive paths" not in labels
        assert "Dependency changes" not in labels
        assert "Potential breaking changes" not in labels

    @pytest.mark.asyncio
    async def test_hardcoded_patterns_used_as_fallback_when_no_rules(self):
        """When no matched_rules, hardcoded patterns provide risk signals."""
        state = _make_state(
            pr_files=["src/auth/login.py", "package.json"],
            pr_additions=10,
            pr_deletions=5,
            pr_author_association="MEMBER",
            matched_rules=[],
        )
        result = await assess_risk(state)
        labels = [s.label for s in result.risk_signals]
        assert "Watchflow rule matches" not in labels
        assert "Security-sensitive paths" in labels
        assert "Dependency changes" in labels


# ---------------------------------------------------------------------------
# Edge case: repo with no commit history
# ---------------------------------------------------------------------------


class TestCodeownersTeamHandling:
    """Team entries in CODEOWNERS are treated as team slugs, not individual user logins."""

    @pytest.mark.asyncio
    async def test_team_slug_becomes_candidate_with_team_reason(self):
        state = _make_state(
            pr_files=["infra/k8s/deploy.yaml"],
            pr_author="dev",
            codeowners_content="infra/ @myorg/devops",
            contributors=[],
            file_experts={},
            risk_level="medium",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        devops = next((c for c in result.candidates if c.username == "devops"), None)
        assert devops is not None
        assert any("team" in r.lower() for r in devops.reasons)

    @pytest.mark.asyncio
    async def test_team_slugs_stored_in_state(self):
        state = _make_state(
            pr_files=["src/app.py"],
            pr_author="dev",
            codeowners_content="src/ @alice @myorg/frontend",
            contributors=[],
            file_experts={},
            risk_level="medium",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert "frontend" in result.codeowners_team_slugs
        # alice is individual — must NOT be in team slugs
        assert "alice" not in result.codeowners_team_slugs


class TestTimedecayCodeowners:
    """Stale CODEOWNERS owners (no recent commits) get reduced score."""

    @pytest.mark.asyncio
    async def test_active_codeowner_gets_full_score(self):
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content="src/billing/ @alice",
            contributors=[],
            file_experts={"src/billing/charge.py": ["alice"]},  # alice is active
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next(c for c in result.candidates if c.username == "alice")
        assert alice.score >= 5
        assert not any("no recent activity" in r for r in alice.reasons)

    @pytest.mark.asyncio
    async def test_stale_codeowner_gets_reduced_score(self):
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content="src/billing/ @alice",
            contributors=[],
            file_experts={"src/billing/charge.py": ["bob"]},  # alice NOT in recent commits
            risk_level="medium",  # return 2 candidates so alice isn't cut off
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        assert alice is not None
        assert alice.score <= 2
        assert any("no recent activity" in r for r in alice.reasons)


class TestRiskBasedReviewerCount:
    """Reviewer count scales with risk level."""

    @pytest.mark.asyncio
    async def test_low_risk_returns_one_reviewer(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content="src/ @alice @bob @carol",
            contributors=[],
            file_experts={"src/utils.py": ["alice", "bob", "carol"]},
            risk_level="low",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert len(result.candidates) == 1

    @pytest.mark.asyncio
    async def test_medium_risk_returns_two_reviewers(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content="src/ @alice @bob @carol",
            contributors=[],
            file_experts={"src/utils.py": ["alice", "bob", "carol"]},
            risk_level="medium",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert len(result.candidates) == 2

    @pytest.mark.asyncio
    async def test_critical_risk_returns_three_reviewers(self):
        state = _make_state(
            pr_files=["src/auth/login.py"],
            pr_author="dev",
            codeowners_content="src/ @alice @bob @carol @dave",
            contributors=[],
            file_experts={"src/auth/login.py": ["alice", "bob", "carol", "dave"]},
            risk_level="critical",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert len(result.candidates) == 3


class TestRuleInferredOwnership:
    """When no CODEOWNERS, critical/high rules + commit history infer implicit owners."""

    @pytest.mark.asyncio
    async def test_rule_inferred_owner_gets_boosted(self):
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content=None,  # no CODEOWNERS
            contributors=[],
            file_experts={"src/billing/charge.py": ["alice", "bob"]},
            matched_rules=[{"description": "Protect billing paths", "severity": "critical"}],
            risk_level="critical",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        assert alice is not None
        assert any("Inferred owner" in r for r in alice.reasons)
        assert alice.score >= 4

    @pytest.mark.asyncio
    async def test_low_severity_rule_does_not_infer_ownership(self):
        state = _make_state(
            pr_files=["src/utils.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[],
            file_experts={"src/utils.py": ["alice"]},
            matched_rules=[{"description": "Low severity rule", "severity": "low"}],
            risk_level="low",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        # alice may still appear from file_experts, but NOT via rule-inferred ownership
        if alice:
            assert not any("Inferred owner" in r for r in alice.reasons)


class TestNoCommitHistory:
    @pytest.mark.asyncio
    async def test_no_file_experts_still_recommends(self):
        """Repo with no commit history should still produce candidates from CODEOWNERS/contributors."""
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author="dev",
            codeowners_content="src/ @alice",
            contributors=[{"login": "bob", "contributions": 50}],
            file_experts={},
            pr_author_association="MEMBER",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=MagicMock(
                ranked_reviewers=[MagicMock(username="alice", reason="owner")],
                summary="ok",
            )
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert len(result.candidates) > 0
        assert any(c.username == "alice" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_no_experts_no_codeowners_uses_contributors(self):
        """No commit history and no CODEOWNERS: falls back to top repo contributors."""
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[{"login": "alice", "contributions": 100}, {"login": "bob", "contributions": 50}],
            file_experts={},
            pr_author_association="MEMBER",
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=MagicMock(
                ranked_reviewers=[MagicMock(username="alice", reason="contributor")],
                summary="ok",
            )
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert len(result.candidates) > 0
        usernames = [c.username for c in result.candidates]
        assert "alice" in usernames or "bob" in usernames


# ---------------------------------------------------------------------------
# Expertise profiles: scoring and persistence
# ---------------------------------------------------------------------------


class TestExpertiseProfilesScoring:
    """Stored expertise profiles from .watchflow/expertise.json boost candidates with historical expertise."""

    @pytest.mark.asyncio
    async def test_stored_expertise_boosts_candidate(self):
        """Candidate with historical expertise in changed files gets extra score points."""
        state = _make_state(
            pr_files=["src/billing/charge.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[],
            file_experts={},
            risk_level="medium",
            expertise_profiles={
                "alice": {"file_paths": ["src/billing/charge.py", "src/billing/invoice.py"], "commit_count": 12},
            },
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        assert alice is not None
        assert alice.score >= 1
        assert any("Historical expertise" in r for r in alice.reasons)

    @pytest.mark.asyncio
    async def test_stored_expertise_pr_author_excluded(self):
        """PR author is excluded even if they appear in expertise profiles."""
        state = _make_state(
            pr_files=["src/main.py"],
            pr_author="alice",
            codeowners_content=None,
            contributors=[],
            file_experts={},
            expertise_profiles={
                "alice": {"file_paths": ["src/main.py"], "commit_count": 20},
            },
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        assert not any(c.username == "alice" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_no_overlap_in_expertise_profiles_gives_no_bonus(self):
        """Expertise profiles for unrelated files don't boost the candidate."""
        state = _make_state(
            pr_files=["src/payments/stripe.py"],
            pr_author="dev",
            codeowners_content=None,
            contributors=[],
            file_experts={},
            risk_level="medium",
            expertise_profiles={
                "alice": {"file_paths": ["src/unrelated/other.py"], "commit_count": 5},
            },
        )
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=MagicMock(ranked_reviewers=[], summary="ok"))
        mock_llm.with_structured_output.return_value = mock_structured

        result = await recommend_reviewers(state, mock_llm)
        alice = next((c for c in result.candidates if c.username == "alice"), None)
        # alice may appear from contributors fallback but NOT from expertise
        if alice:
            assert not any("Historical expertise" in r for r in alice.reasons)


class TestExpertisePersistence:
    """fetch_pr_data reads and writes .watchflow/expertise.json via GitHub API."""

    @pytest.mark.asyncio
    @patch("src.agents.reviewer_recommendation_agent.nodes.github_client")
    async def test_expertise_profiles_saved_after_fetch(self, mock_gh):
        """After computing file_experts, expertise.json is written to the repo."""
        mock_gh.get_pull_request = AsyncMock(
            return_value={
                "user": {"login": "dev"},
                "additions": 10,
                "deletions": 5,
                "commits": 2,
                "author_association": "MEMBER",
                "title": "fix: stuff",
                "base": {"ref": "main"},
            }
        )
        mock_gh.get_pr_files = AsyncMock(return_value=[{"filename": "src/billing/charge.py"}])
        mock_gh.get_codeowners = AsyncMock(return_value={})
        mock_gh.get_repository_contributors = AsyncMock(return_value=[])
        mock_gh.get_commits_for_file = AsyncMock(
            return_value=[
                {"author": {"login": "alice"}},
                {"author": {"login": "bob"}},
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=None)  # no existing profile
        mock_gh.create_or_update_file = AsyncMock(return_value={})
        mock_gh.fetch_recent_pull_requests = AsyncMock(return_value=[])

        from src.rules.loaders.github_loader import GitHubRuleLoader

        with patch.object(GitHubRuleLoader, "get_rules", AsyncMock(return_value=[])):
            state = _make_state()
            await fetch_pr_data(state)

        mock_gh.create_or_update_file.assert_called_once()
        call_kwargs = mock_gh.create_or_update_file.call_args.kwargs
        assert call_kwargs["path"] == ".watchflow/expertise.json"
        assert call_kwargs["branch"] == "main"
        import json

        saved = json.loads(call_kwargs["content"])
        assert "alice" in saved["contributors"]
        assert "src/billing/charge.py" in saved["contributors"]["alice"]["file_paths"]

    @pytest.mark.asyncio
    @patch("src.agents.reviewer_recommendation_agent.nodes.github_client")
    async def test_expertise_persistence_failure_is_graceful(self, mock_gh):
        """If writing expertise.json fails, fetch_pr_data still succeeds."""
        mock_gh.get_pull_request = AsyncMock(
            return_value={
                "user": {"login": "dev"},
                "additions": 5,
                "deletions": 2,
                "commits": 1,
                "author_association": "MEMBER",
                "title": "fix: x",
                "base": {"ref": "main"},
            }
        )
        mock_gh.get_pr_files = AsyncMock(return_value=[{"filename": "src/utils.py"}])
        mock_gh.get_codeowners = AsyncMock(return_value={})
        mock_gh.get_repository_contributors = AsyncMock(return_value=[])
        mock_gh.get_commits_for_file = AsyncMock(return_value=[])
        mock_gh.get_file_content = AsyncMock(side_effect=Exception("network error"))
        mock_gh.create_or_update_file = AsyncMock(return_value={})
        mock_gh.fetch_recent_pull_requests = AsyncMock(return_value=[])

        from src.rules.loaders.github_loader import GitHubRuleLoader

        with patch.object(GitHubRuleLoader, "get_rules", AsyncMock(return_value=[])):
            state = _make_state()
            result = await fetch_pr_data(state)

        assert result.error is None
        assert result.expertise_profiles == {}
