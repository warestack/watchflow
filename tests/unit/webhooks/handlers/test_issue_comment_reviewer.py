"""
Unit tests for /risk and /reviewers slash commands in IssueCommentEventHandler.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult
from src.core.models import EventType, WebhookEvent
from src.webhooks.handlers import issue_comment as ic_module
from src.webhooks.handlers.issue_comment import IssueCommentEventHandler


def _make_event(comment_body: str, pr_number: int = 42) -> WebhookEvent:
    return WebhookEvent(
        event_type=EventType.ISSUE_COMMENT,
        payload={
            "comment": {"body": comment_body, "user": {"login": "human-user"}},
            "issue": {"number": pr_number},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 99},
        },
        delivery_id="test-delivery",
    )


_MOCK_AGENT_RESULT = AgentResult(
    success=True,
    message="ok",
    data={
        "risk_level": "high",
        "risk_score": 7,
        "risk_signals": [{"label": "Sensitive paths", "description": "src/auth/", "points": 5}],
        "pr_files_count": 12,
        "llm_ranking": {
            "ranked_reviewers": [{"username": "alice", "reason": "auth expert"}],
            "summary": "1 reviewer recommended.",
        },
        "pr_author": "dev",
        "candidates": [],
        "codeowners_team_slugs": [],
    },
)

# Result where recommendations include a team slug alongside an individual user
_MOCK_AGENT_RESULT_WITH_TEAM = AgentResult(
    success=True,
    message="ok",
    data={
        "risk_level": "high",
        "risk_score": 8,
        "risk_signals": [],
        "pr_files_count": 5,
        "llm_ranking": {
            "ranked_reviewers": [
                {"username": "alice", "reason": "billing expert"},
                {"username": "frontend", "reason": "CODEOWNERS team"},
            ],
            "summary": "2 reviewers recommended.",
        },
        "pr_author": "dev",
        "candidates": [],
        "codeowners_team_slugs": ["frontend"],  # "frontend" is a team, not a user
    },
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


class TestSlashCommandDetection:
    def setup_method(self):
        self.handler = IssueCommentEventHandler()

    def test_detects_risk_command(self):
        assert self.handler._is_risk_comment("/risk") is True
        assert self.handler._is_risk_comment("/risk\n") is True

    def test_rejects_partial_risk_command(self):
        assert self.handler._is_risk_comment("please /risk this") is False
        assert self.handler._is_risk_comment("/risks") is False

    def test_detects_reviewers_command(self):
        assert self.handler._is_reviewers_comment("/reviewers") is True
        assert self.handler._is_reviewers_comment("/reviewers --force") is True

    def test_rejects_partial_reviewers_command(self):
        assert self.handler._is_reviewers_comment("run /reviewers please") is False
        assert self.handler._is_reviewers_comment("/reviewer") is False


# ---------------------------------------------------------------------------
# /risk command flow
# ---------------------------------------------------------------------------


class TestRiskCommand:
    def setup_method(self):
        ic_module._COMMAND_COOLDOWN.clear()
        self.handler = IssueCommentEventHandler()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_risk_command_posts_comment_and_labels(self, mock_gh, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/risk"))

        assert response.status == "ok"
        mock_get_agent.assert_called_once_with("reviewer_recommendation")
        mock_agent.execute.assert_called_once_with(repo_full_name="owner/repo", pr_number=42, installation_id=99)
        mock_gh.create_pull_request_comment.assert_called_once()
        # Verify the posted comment includes expected content
        posted_body = mock_gh.create_pull_request_comment.call_args.kwargs["comment"]
        assert "Risk Assessment" in posted_body
        assert "High" in posted_body
        # Verify label is applied
        mock_gh.add_labels_to_issue.assert_called_once_with(
            repo="owner/repo", issue_number=42, labels=["watchflow:risk-high"], installation_id=99
        )

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_risk_command_ignored_without_pr_number(self, mock_gh, mock_get_agent):
        event = WebhookEvent(
            event_type=EventType.ISSUE_COMMENT,
            payload={
                "comment": {"body": "/risk", "user": {"login": "human-user"}},
                "repository": {"full_name": "owner/repo"},
                "installation": {"id": 99},
                # no 'issue' key
            },
            delivery_id="test-delivery",
        )
        response = await self.handler.handle(event)
        assert response.status == "ignored"
        mock_get_agent.assert_not_called()


# ---------------------------------------------------------------------------
# /reviewers command flow
# ---------------------------------------------------------------------------


class TestReviewersCommand:
    def setup_method(self):
        ic_module._COMMAND_COOLDOWN.clear()
        self.handler = IssueCommentEventHandler()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.save_recommendation", new_callable=AsyncMock)
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_command_posts_comment_and_labels(self, mock_gh, mock_get_agent, mock_save):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})
        mock_gh.request_reviewers = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers"))

        assert response.status == "ok"
        mock_get_agent.assert_called_once_with("reviewer_recommendation")
        mock_gh.create_pull_request_comment.assert_called_once()
        posted_body = mock_gh.create_pull_request_comment.call_args.kwargs["comment"]
        assert "Reviewer Recommendation" in posted_body
        assert "@alice" in posted_body
        # Verify labels are applied (risk level + reviewer-recommendation)
        mock_gh.add_labels_to_issue.assert_called_once_with(
            repo="owner/repo",
            issue_number=42,
            labels=["watchflow:risk-high", "watchflow:reviewer-recommendation"],
            installation_id=99,
        )

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.save_recommendation", new_callable=AsyncMock)
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_force_flag_also_runs(self, mock_gh, mock_get_agent, mock_save):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})
        mock_gh.request_reviewers = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers --force"))

        assert response.status == "ok"
        mock_agent.execute.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.save_recommendation", new_callable=AsyncMock)
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_command_assigns_individual_reviewers_to_pr(self, mock_gh, mock_get_agent, mock_save):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})
        mock_gh.request_reviewers = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers"))

        assert response.status == "ok"
        mock_gh.request_reviewers.assert_called_once_with(
            repo="owner/repo",
            pr_number=42,
            reviewers=["alice"],  # individual user
            team_reviewers=[],  # no teams in this result
            installation_id=99,
        )

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.save_recommendation", new_callable=AsyncMock)
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_team_slugs_go_to_team_reviewers_field(self, mock_gh, mock_get_agent, mock_save):
        """Team slugs from CODEOWNERS must be passed to team_reviewers, not reviewers."""
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT_WITH_TEAM)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})
        mock_gh.request_reviewers = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers"))

        assert response.status == "ok"
        mock_gh.request_reviewers.assert_called_once_with(
            repo="owner/repo",
            pr_number=42,
            reviewers=["alice"],  # individual user only
            team_reviewers=["frontend"],  # team slug goes here, NOT in reviewers
            installation_id=99,
        )

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_bot_comment_is_ignored(self, mock_gh, mock_get_agent):
        event = _make_event("/reviewers")
        event.payload["comment"]["user"]["login"] = "watchflow[bot]"

        response = await self.handler.handle(event)

        assert response.status == "ignored"
        mock_get_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Cooldown / rate limiting
# ---------------------------------------------------------------------------


class TestSlashCommandCooldown:
    def setup_method(self):
        self.handler = IssueCommentEventHandler()
        # Clear cooldown state between tests
        ic_module._COMMAND_COOLDOWN.clear()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_risk_cooldown_blocks_repeated_calls(self, mock_gh, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})

        # First call succeeds
        response = await self.handler.handle(_make_event("/risk"))
        assert response.status == "ok"

        # Second call within cooldown is ignored
        response = await self.handler.handle(_make_event("/risk"))
        assert response.status == "ignored"
        assert "cooldown" in response.detail.lower()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.save_recommendation", new_callable=AsyncMock)
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_force_bypasses_cooldown(self, mock_gh, mock_get_agent, mock_save):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})
        mock_gh.add_labels_to_issue = AsyncMock(return_value=[])
        mock_gh.remove_label_from_issue = AsyncMock(return_value={})
        mock_gh.request_reviewers = AsyncMock(return_value={})

        # First call succeeds
        response = await self.handler.handle(_make_event("/reviewers"))
        assert response.status == "ok"

        # --force bypasses cooldown
        response = await self.handler.handle(_make_event("/reviewers --force"))
        assert response.status == "ok"
        assert mock_agent.execute.call_count == 2
