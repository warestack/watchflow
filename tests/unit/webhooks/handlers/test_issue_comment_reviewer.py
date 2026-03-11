"""
Unit tests for /risk and /reviewers slash commands in IssueCommentEventHandler.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult
from src.core.models import EventType, WebhookEvent
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
        self.handler = IssueCommentEventHandler()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_risk_command_posts_comment(self, mock_gh, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/risk"))

        assert response.status == "ok"
        mock_get_agent.assert_called_once_with("reviewer_recommendation")
        mock_agent.execute.assert_called_once_with(repo_full_name="owner/repo", pr_number=42, installation_id=99)
        mock_gh.create_pull_request_comment.assert_called_once()
        # Verify the posted comment includes expected content
        posted_body = mock_gh.create_pull_request_comment.call_args.kwargs["comment"]
        assert "Risk Assessment" in posted_body
        assert "High" in posted_body

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
        self.handler = IssueCommentEventHandler()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_command_posts_comment(self, mock_gh, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers"))

        assert response.status == "ok"
        mock_get_agent.assert_called_once_with("reviewer_recommendation")
        mock_gh.create_pull_request_comment.assert_called_once()
        posted_body = mock_gh.create_pull_request_comment.call_args.kwargs["comment"]
        assert "Reviewer Recommendation" in posted_body
        assert "@alice" in posted_body

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_reviewers_force_flag_also_runs(self, mock_gh, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=_MOCK_AGENT_RESULT)
        mock_get_agent.return_value = mock_agent
        mock_gh.create_pull_request_comment = AsyncMock(return_value={})

        response = await self.handler.handle(_make_event("/reviewers --force"))

        assert response.status == "ok"
        mock_agent.execute.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.issue_comment.get_agent")
    @patch("src.webhooks.handlers.issue_comment.github_client")
    async def test_bot_comment_is_ignored(self, mock_gh, mock_get_agent):
        event = _make_event("/reviewers")
        event.payload["comment"]["user"]["login"] = "watchflow[bot]"

        response = await self.handler.handle(event)

        assert response.status == "ignored"
        mock_get_agent.assert_not_called()
