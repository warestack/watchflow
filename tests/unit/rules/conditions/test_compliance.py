import pytest

from src.core.models import Severity
from src.rules.conditions.compliance import ChangelogRequiredCondition, SignedCommitsCondition


class TestChangelogRequiredCondition:
    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_when_missing(self) -> None:
        condition = ChangelogRequiredCondition()
        event = {"changed_files": [{"filename": "src/app.py"}]}
        context = {"parameters": {"require_changelog_update": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "CHANGELOG update" in violations[0].message
        assert violations[0].severity == Severity.MEDIUM

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_present(self) -> None:
        condition = ChangelogRequiredCondition()
        event = {"changed_files": [{"filename": "src/app.py"}, {"filename": "CHANGELOG.md"}]}
        context = {"parameters": {"require_changelog_update": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_no_source_changes(self) -> None:
        condition = ChangelogRequiredCondition()
        event = {"changed_files": [{"filename": "docs/readme.md"}]}
        context = {"parameters": {"require_changelog_update": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestSignedCommitsCondition:
    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_unsigned(self) -> None:
        condition = SignedCommitsCondition()
        event = {
            "commits": [
                {"oid": "abcdef123456", "is_verified": False},
                {"oid": "9876543210ab", "is_verified": True},
            ]
        }
        context = {"parameters": {"require_signed_commits": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "unsigned commit" in violations[0].message
        assert "abcdef1" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_for_all_signed(self) -> None:
        condition = SignedCommitsCondition()
        event = {
            "commits": [
                {"oid": "abcdef123456", "is_verified": True},
            ]
        }
        context = {"parameters": {"require_signed_commits": True}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0
