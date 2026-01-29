"""Tests for access control conditions.

Tests for AuthorTeamCondition, CodeOwnersCondition, and ProtectedBranchesCondition classes.
"""

from unittest.mock import patch

import pytest

from src.rules.conditions.access_control import (
    AuthorTeamCondition,
    CodeOwnersCondition,
    ProtectedBranchesCondition,
)


class TestAuthorTeamCondition:
    """Tests for AuthorTeamCondition class."""

    @pytest.mark.asyncio
    async def test_validate_member_of_team(self) -> None:
        """Test that validate returns True when author is team member."""
        condition = AuthorTeamCondition()

        event = {"sender": {"login": "devops-user"}}

        result = await condition.validate({"team": "devops"}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_not_member_of_team(self) -> None:
        """Test that validate returns False when author is not team member."""
        condition = AuthorTeamCondition()

        event = {"sender": {"login": "random-user"}}

        result = await condition.validate({"team": "devops"}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_team_specified(self) -> None:
        """Test that validate returns False when no team is specified."""
        condition = AuthorTeamCondition()

        event = {"sender": {"login": "devops-user"}}

        result = await condition.validate({}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_sender_in_event(self) -> None:
        """Test that validate returns False when sender is missing."""
        condition = AuthorTeamCondition()

        result = await condition.validate({"team": "devops"}, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_non_member(self) -> None:
        """Test that evaluate returns violations when author is not team member."""
        condition = AuthorTeamCondition()

        event = {"sender": {"login": "random-user"}}
        context = {"parameters": {"team": "devops"}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "not a member of team" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_for_member(self) -> None:
        """Test that evaluate returns empty list when author is team member."""
        condition = AuthorTeamCondition()

        event = {"sender": {"login": "devops-user"}}
        context = {"parameters": {"team": "devops"}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestCodeOwnersCondition:
    """Tests for CodeOwnersCondition class."""

    @pytest.mark.asyncio
    async def test_validate_no_files(self) -> None:
        """Test that validate returns True when no files are present."""
        condition = CodeOwnersCondition()
        result = await condition.validate({}, {"files": []})
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_with_critical_files(self) -> None:
        """Test that validate returns False when critical files are modified."""
        condition = CodeOwnersCondition()

        event = {"files": [{"filename": "src/critical.py"}]}

        with patch("src.rules.utils.codeowners.is_critical_file", return_value=True):
            result = await condition.validate({"critical_owners": ["admin"]}, event)
            assert result is False

    @pytest.mark.asyncio
    async def test_validate_without_critical_files(self) -> None:
        """Test that validate returns True when no critical files are modified."""
        condition = CodeOwnersCondition()

        event = {"files": [{"filename": "src/normal.py"}]}

        with patch("src.rules.utils.codeowners.is_critical_file", return_value=False):
            result = await condition.validate({"critical_owners": ["admin"]}, event)
            assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_critical_files(self) -> None:
        """Test that evaluate returns violations for critical files."""
        condition = CodeOwnersCondition()

        event = {"files": [{"filename": "src/critical.py"}]}
        context = {"parameters": {"critical_owners": ["admin"]}, "event": event}

        with patch("src.rules.utils.codeowners.is_critical_file", return_value=True):
            violations = await condition.evaluate(context)
            assert len(violations) == 1
            assert "code owner review" in violations[0].message


class TestProtectedBranchesCondition:
    """Tests for ProtectedBranchesCondition class."""

    @pytest.mark.asyncio
    async def test_validate_non_protected_branch(self) -> None:
        """Test that validate returns True for non-protected branches."""
        condition = ProtectedBranchesCondition()

        event = {"pull_request_details": {"base": {"ref": "feature-branch"}}}

        result = await condition.validate({"protected_branches": ["main", "develop"]}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_protected_branch(self) -> None:
        """Test that validate returns False for protected branches."""
        condition = ProtectedBranchesCondition()

        event = {"pull_request_details": {"base": {"ref": "main"}}}

        result = await condition.validate({"protected_branches": ["main", "develop"]}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_protected_branches_specified(self) -> None:
        """Test that validate returns True when no protected branches specified."""
        condition = ProtectedBranchesCondition()

        event = {"pull_request_details": {"base": {"ref": "main"}}}

        result = await condition.validate({"protected_branches": []}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_pr_details(self) -> None:
        """Test that validate returns True when PR details are missing."""
        condition = ProtectedBranchesCondition()
        result = await condition.validate({"protected_branches": ["main"]}, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_protected(self) -> None:
        """Test that evaluate returns violations for protected branches."""
        condition = ProtectedBranchesCondition()

        event = {"pull_request_details": {"base": {"ref": "main"}}}
        context = {"parameters": {"protected_branches": ["main"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "protected branch" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_for_non_protected(self) -> None:
        """Test that evaluate returns empty list for non-protected branches."""
        condition = ProtectedBranchesCondition()

        event = {"pull_request_details": {"base": {"ref": "feature"}}}
        context = {"parameters": {"protected_branches": ["main"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0
