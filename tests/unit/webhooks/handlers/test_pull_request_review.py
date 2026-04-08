from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import EventType, WebhookEvent
from src.webhooks.handlers.pull_request_review import PullRequestReviewEventHandler


class TestPullRequestReviewEventHandler:
    @pytest.fixture
    def handler(self) -> PullRequestReviewEventHandler:
        return PullRequestReviewEventHandler()

    @pytest.fixture
    def mock_event(self) -> WebhookEvent:
        return WebhookEvent(
            event_type=EventType.PULL_REQUEST_REVIEW,
            payload={"action": "submitted", "pull_request": {"number": 123}, "repository": {"full_name": "owner/repo"}},
            delivery_id="test-delivery-id",
        )

    @pytest.mark.asyncio
    async def test_can_handle(self, handler: PullRequestReviewEventHandler, mock_event: WebhookEvent) -> None:
        assert await handler.can_handle(mock_event) is True

        # Test wrong event type
        mock_event.event_type = EventType.PUSH
        assert await handler.can_handle(mock_event) is False

    @pytest.mark.asyncio
    async def test_handle_ignores_unsupported_actions(
        self, handler: PullRequestReviewEventHandler, mock_event: WebhookEvent
    ) -> None:
        mock_event.payload["action"] = "edited"
        response = await handler.handle(mock_event)
        assert response.status == "ignored"
        assert "Action edited ignored" in response.detail

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.pull_request_review.task_queue")
    async def test_handle_enqueues_task(
        self, mock_task_queue: MagicMock, handler: PullRequestReviewEventHandler, mock_event: WebhookEvent
    ) -> None:
        mock_task_queue.enqueue = AsyncMock(return_value=True)

        response = await handler.handle(mock_event)

        assert response.status == "ok"
        mock_task_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.pull_request_review.task_queue")
    async def test_handle_returns_ignored_for_duplicate(
        self, mock_task_queue: MagicMock, handler: PullRequestReviewEventHandler, mock_event: WebhookEvent
    ) -> None:
        mock_task_queue.enqueue = AsyncMock(return_value=False)

        response = await handler.handle(mock_event)

        assert response.status == "ignored"
        assert "Duplicate event" in response.detail


# ---------------------------------------------------------------------------
# Acceptance recording on APPROVED review
# ---------------------------------------------------------------------------


class TestPullRequestReviewAcceptanceRecording:
    """PullRequestReviewEventHandler calls record_acceptance when action=submitted + APPROVED."""

    def _make_approved_event(self, pr_number: int = 42, reviewer: str = "alice") -> WebhookEvent:
        return WebhookEvent(
            event_type=EventType.PULL_REQUEST_REVIEW,
            payload={
                "action": "submitted",
                "review": {"state": "APPROVED", "user": {"login": reviewer}},
                "pull_request": {"number": pr_number, "base": {"ref": "main"}},
                "repository": {"full_name": "owner/repo"},
                "installation": {"id": 99},
            },
            delivery_id="delivery-approved",
        )

    def _make_changes_requested_event(self) -> WebhookEvent:
        return WebhookEvent(
            event_type=EventType.PULL_REQUEST_REVIEW,
            payload={
                "action": "submitted",
                "review": {"state": "CHANGES_REQUESTED", "user": {"login": "bob"}},
                "pull_request": {"number": 42, "base": {"ref": "main"}},
                "repository": {"full_name": "owner/repo"},
                "installation": {"id": 99},
            },
            delivery_id="delivery-cr",
        )

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.pull_request_review.task_queue")
    @patch("src.webhooks.handlers.pull_request_review.record_acceptance", new_callable=AsyncMock)
    async def test_approved_review_calls_record_acceptance(self, mock_record, mock_task_queue):
        from src.webhooks.handlers.pull_request_review import PullRequestReviewEventHandler

        mock_task_queue.enqueue = AsyncMock(return_value=True)
        handler = PullRequestReviewEventHandler()

        response = await handler.handle(self._make_approved_event())

        assert response.status == "ok"
        mock_record.assert_called_once_with(
            repo="owner/repo",
            pr_number=42,
            reviewer_login="alice",
            branch="main",
            installation_id=99,
        )

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.pull_request_review.task_queue")
    @patch("src.webhooks.handlers.pull_request_review.record_acceptance", new_callable=AsyncMock)
    async def test_changes_requested_does_not_call_record_acceptance(self, mock_record, mock_task_queue):
        from src.webhooks.handlers.pull_request_review import PullRequestReviewEventHandler

        mock_task_queue.enqueue = AsyncMock(return_value=True)
        handler = PullRequestReviewEventHandler()

        response = await handler.handle(self._make_changes_requested_event())

        assert response.status == "ok"
        mock_record.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.webhooks.handlers.pull_request_review.task_queue")
    @patch("src.webhooks.handlers.pull_request_review.record_acceptance", new_callable=AsyncMock)
    async def test_record_acceptance_failure_does_not_break_handler(self, mock_record, mock_task_queue):
        """record_acceptance errors are caught; handler still returns ok."""
        from src.webhooks.handlers.pull_request_review import PullRequestReviewEventHandler

        mock_record.side_effect = Exception("network error")
        mock_task_queue.enqueue = AsyncMock(return_value=True)
        handler = PullRequestReviewEventHandler()

        response = await handler.handle(self._make_approved_event())

        assert response.status == "ok"
