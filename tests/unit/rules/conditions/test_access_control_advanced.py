import pytest

from src.core.models import Severity
from src.rules.conditions.access_control_advanced import CrossTeamApprovalCondition, NoSelfApprovalCondition


class TestNoSelfApprovalCondition:
    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_self_approval(self) -> None:
        condition = NoSelfApprovalCondition()
        event = {
            "pull_request_details": {"user": {"login": "author_dev"}},
            "reviews": [{"author": "other_dev", "state": "COMMENTED"}, {"author": "author_dev", "state": "APPROVED"}],
        }
        context = {"parameters": {"block_self_approval": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "approved by its own author" in violations[0].message
        assert violations[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_approved_by_others(self) -> None:
        condition = NoSelfApprovalCondition()
        event = {
            "pull_request_details": {"user": {"login": "author_dev"}},
            "reviews": [{"author": "other_dev", "state": "APPROVED"}],
        }
        context = {"parameters": {"block_self_approval": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestCrossTeamApprovalCondition:
    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_when_missing_teams(self) -> None:
        condition = CrossTeamApprovalCondition()
        event = {"pull_request_details": {"requested_teams": [{"slug": "backend"}]}, "reviews": []}
        context = {"parameters": {"required_team_approvals": ["@org/backend", "@org/security"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "security" in violations[0].message
        assert "backend" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_teams_approved(self) -> None:
        condition = CrossTeamApprovalCondition()
        event = {
            "pull_request_details": {"requested_teams": [{"slug": "backend"}, {"slug": "security"}]},
            "reviews": [{"state": "APPROVED"}],
        }
        context = {"parameters": {"required_team_approvals": ["backend", "security"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0
