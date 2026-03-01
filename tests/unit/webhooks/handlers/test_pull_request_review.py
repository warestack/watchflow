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
