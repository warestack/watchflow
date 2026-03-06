from datetime import UTC, datetime, timedelta

import pytest

from src.core.models import Severity
from src.rules.conditions.temporal import CommentResponseTimeCondition


class TestCommentResponseTimeCondition:
    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_when_sla_exceeded(self) -> None:
        condition = CommentResponseTimeCondition()
        now = datetime.now(UTC)
        past_time = now - timedelta(hours=25)

        event = {
            "timestamp": now.isoformat(),
            "review_threads": [{"is_resolved": False, "comments": [{"createdAt": past_time.isoformat()}]}],
        }
        context = {"parameters": {"max_comment_response_time_hours": 24}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "exceeded the 24-hour response SLA" in violations[0].message
        assert violations[0].severity == Severity.MEDIUM

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_within_sla(self) -> None:
        condition = CommentResponseTimeCondition()
        now = datetime.now(UTC)
        past_time = now - timedelta(hours=23)

        event = {
            "timestamp": now.isoformat(),
            "review_threads": [{"is_resolved": False, "comments": [{"createdAt": past_time.isoformat()}]}],
        }
        context = {"parameters": {"max_comment_response_time_hours": 24}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_evaluate_ignores_resolved_threads(self) -> None:
        condition = CommentResponseTimeCondition()
        now = datetime.now(UTC)
        past_time = now - timedelta(hours=25)

        event = {
            "timestamp": now.isoformat(),
            "review_threads": [{"is_resolved": True, "comments": [{"createdAt": past_time.isoformat()}]}],
        }
        context = {"parameters": {"max_comment_response_time_hours": 24}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0
