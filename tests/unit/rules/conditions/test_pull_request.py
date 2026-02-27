"""Tests for pull request conditions.

Tests for TitlePatternCondition, MinDescriptionLengthCondition, and RequiredLabelsCondition classes.
"""

import pytest

from src.rules.conditions.pull_request import (
    DiffPatternCondition,
    MinApprovalsCondition,
    MinDescriptionLengthCondition,
    RequiredLabelsCondition,
    RequireLinkedIssueCondition,
    SecurityPatternCondition,
    TitlePatternCondition,
    UnresolvedCommentsCondition,
)


class TestMinApprovalsCondition:
    """Tests for MinApprovalsCondition class."""

    @pytest.mark.asyncio
    async def test_validate_sufficient_approvals(self) -> None:
        """Test that validate returns True when enough approvals are present."""
        condition = MinApprovalsCondition()

        event = {
            "reviews": [
                {"state": "APPROVED"},
                {"state": "APPROVED"},
            ]
        }

        result = await condition.validate({"min_approvals": 2}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_insufficient_approvals(self) -> None:
        """Test that validate returns False when not enough approvals."""
        condition = MinApprovalsCondition()

        event = {
            "reviews": [
                {"state": "APPROVED"},
                {"state": "COMMENTED"},
            ]
        }

        result = await condition.validate({"min_approvals": 2}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_reviews(self) -> None:
        """Test that validate returns False when no reviews exist."""
        condition = MinApprovalsCondition()
        result = await condition.validate({"min_approvals": 1}, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations(self) -> None:
        """Test that evaluate returns violations for insufficient approvals."""
        condition = MinApprovalsCondition()

        event = {"reviews": [{"state": "APPROVED"}]}
        context = {"parameters": {"min_approvals": 2}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "requires 2" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_sufficient(self) -> None:
        """Test that evaluate returns empty list when sufficient approvals."""
        condition = MinApprovalsCondition()

        event = {
            "reviews": [
                {"state": "APPROVED"},
                {"state": "APPROVED"},
            ]
        }
        context = {"parameters": {"min_approvals": 2}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestTitlePatternCondition:
    """Tests for TitlePatternCondition class."""

    @pytest.mark.asyncio
    async def test_validate_matching_pattern(self) -> None:
        """Test that validate returns True when title matches pattern."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": "feat: new feature"}}

        result = await condition.validate({"title_pattern": "^feat:"}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_non_matching_pattern(self) -> None:
        """Test that validate returns False when title doesn't match pattern."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": "feat: new feature"}}

        result = await condition.validate({"title_pattern": "^fix:"}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_pattern_returns_true(self) -> None:
        """Test that validate returns True when no pattern is specified."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": "any title"}}

        result = await condition.validate({}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_pr_details_returns_true(self) -> None:
        """Test that validate returns True when PR details are missing."""
        condition = TitlePatternCondition()
        result = await condition.validate({"title_pattern": "^feat:"}, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_empty_title_returns_false(self) -> None:
        """Test that validate returns False when title is empty."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": ""}}

        result = await condition.validate({"title_pattern": "^feat:"}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_on_mismatch(self) -> None:
        """Test that evaluate returns violations when title doesn't match."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": "update readme"}}
        context = {"parameters": {"title_pattern": "^feat:|^fix:"}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "does not match required pattern" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_on_match(self) -> None:
        """Test that evaluate returns empty list when title matches."""
        condition = TitlePatternCondition()

        event = {"pull_request_details": {"title": "feat: add new API"}}
        context = {"parameters": {"title_pattern": "^feat:"}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestMinDescriptionLengthCondition:
    """Tests for MinDescriptionLengthCondition class."""

    @pytest.mark.asyncio
    async def test_validate_sufficient_length(self) -> None:
        """Test that validate returns True when description is long enough."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": "Short desc"}}

        result = await condition.validate({"min_description_length": 5}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_insufficient_length(self) -> None:
        """Test that validate returns False when description is too short."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": "Short desc"}}

        result = await condition.validate({"min_description_length": 20}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_pr_details_returns_true(self) -> None:
        """Test that validate returns True when PR details are missing."""
        condition = MinDescriptionLengthCondition()
        result = await condition.validate({"min_description_length": 10}, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_empty_body_returns_false(self) -> None:
        """Test that validate returns False when body is empty."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": ""}}

        result = await condition.validate({"min_description_length": 5}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_whitespace_only_fails(self) -> None:
        """Test that validate fails for whitespace-only descriptions."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": "   "}}

        result = await condition.validate({"min_description_length": 1}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_short_description(self) -> None:
        """Test that evaluate returns violations for short descriptions."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": "Hi"}}
        context = {"parameters": {"min_description_length": 50}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "too short" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_for_long_description(self) -> None:
        """Test that evaluate returns empty list for adequate descriptions."""
        condition = MinDescriptionLengthCondition()

        event = {"pull_request_details": {"body": "This is a detailed description of the changes made in this PR."}}
        context = {"parameters": {"min_description_length": 10}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestRequiredLabelsCondition:
    """Tests for RequiredLabelsCondition class."""

    @pytest.mark.asyncio
    async def test_validate_all_labels_present(self) -> None:
        """Test that validate returns True when all required labels are present."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": [{"name": "bug"}, {"name": "security"}]}}

        result = await condition.validate({"required_labels": ["bug"]}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_multiple_labels_all_present(self) -> None:
        """Test with multiple required labels all present."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": [{"name": "bug"}, {"name": "security"}]}}

        result = await condition.validate({"required_labels": ["bug", "security"]}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_missing_label(self) -> None:
        """Test that validate returns False when required label is missing."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": [{"name": "bug"}, {"name": "security"}]}}

        result = await condition.validate({"required_labels": ["feature"]}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_no_labels_required_returns_true(self) -> None:
        """Test that validate returns True when no labels are required."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": []}}

        result = await condition.validate({"required_labels": []}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_pr_details_returns_true(self) -> None:
        """Test that validate returns True when PR details are missing."""
        condition = RequiredLabelsCondition()
        result = await condition.validate({"required_labels": ["bug"]}, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_missing_labels(self) -> None:
        """Test that evaluate returns violations for missing labels."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": [{"name": "docs"}]}}
        context = {"parameters": {"required_labels": ["bug", "security"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "Missing required labels" in violations[0].message
        assert "bug" in violations[0].message
        assert "security" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_labels_present(self) -> None:
        """Test that evaluate returns empty list when all labels are present."""
        condition = RequiredLabelsCondition()

        event = {"pull_request_details": {"labels": [{"name": "bug"}, {"name": "security"}]}}
        context = {"parameters": {"required_labels": ["bug"]}, "event": event}

        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestRequireLinkedIssueCondition:
    """Tests for RequireLinkedIssueCondition class."""

    @pytest.mark.asyncio
    async def test_validate_with_issue_ref_in_body(self) -> None:
        """Validate returns True when body contains #123."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Fix bug", "body": "Fixes #123"}}
        result = await condition.validate({"require_linked_issue": True}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_with_issue_ref_in_title(self) -> None:
        """Validate returns True when title contains #456."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Closes #456", "body": ""}}
        result = await condition.validate({"require_linked_issue": True}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_with_plain_hash_number(self) -> None:
        """Validate returns True when body contains plain #789."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Update", "body": "See #789 for context"}}
        result = await condition.validate({"require_linked_issue": True}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_issue_ref_returns_false(self) -> None:
        """Validate returns False when no issue reference in body or title."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Fix bug", "body": "No issue ref here"}}
        result = await condition.validate({"require_linked_issue": True}, event)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_param_false_returns_true(self) -> None:
        """Validate returns True when require_linked_issue is not set."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Fix", "body": "No ref"}}
        result = await condition.validate({}, event)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_pr_details_returns_true(self) -> None:
        """Validate returns True when PR details are missing."""
        condition = RequireLinkedIssueCondition()
        result = await condition.validate({"require_linked_issue": True}, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_evaluate_returns_violation_when_no_ref(self) -> None:
        """Evaluate returns one violation when PR has no issue reference."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Fix", "body": "Description only"}}
        context = {"parameters": {"require_linked_issue": True}, "event": event}
        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "does not reference a linked issue" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_ref_present(self) -> None:
        """Evaluate returns empty list when PR references an issue."""
        condition = RequireLinkedIssueCondition()
        event = {"pull_request_details": {"title": "Fix", "body": "Resolves #42"}}
        context = {"parameters": {"require_linked_issue": True}, "event": event}
        violations = await condition.evaluate(context)
        assert len(violations) == 0


class TestDiffPatternCondition:
    """Tests for DiffPatternCondition."""

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_on_match(self) -> None:
        condition = DiffPatternCondition()
        patch = "@@ -1,3 +1,4 @@\n def func():\n-    pass\n+    console.log('debug')\n+    return True"
        event = {"changed_files": [{"filename": "src/app.js", "patch": patch}]}
        context = {"parameters": {"diff_restricted_patterns": ["console\\.log"]}, "event": event}
        
        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "console" in violations[0].message
        assert "src/app.js" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_returns_empty_when_no_match(self) -> None:
        condition = DiffPatternCondition()
        patch = "@@ -1,2 +1,3 @@\n def func():\n+    return True"
        event = {"changed_files": [{"filename": "src/app.js", "patch": patch}]}
        context = {"parameters": {"diff_restricted_patterns": ["console\\.log"]}, "event": event}
        
        violations = await condition.evaluate(context)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_validate_returns_false_on_match(self) -> None:
        condition = DiffPatternCondition()
        patch = "@@ -1 +1,2 @@\n+TODO: fix this"
        event = {"changed_files": [{"filename": "src/app.js", "patch": patch}]}
        result = await condition.validate({"diff_restricted_patterns": ["TODO:"]}, event)
        assert result is False


class TestSecurityPatternCondition:
    """Tests for SecurityPatternCondition."""

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_on_match(self) -> None:
        condition = SecurityPatternCondition()
        patch = "@@ -1 +1,2 @@\n+api_key = '123456'"
        event = {"changed_files": [{"filename": "src/auth.py", "patch": patch}]}
        context = {"parameters": {"security_patterns": ["api_key"]}, "event": event}
        
        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert violations[0].severity.value == "critical"
        assert "api_key" in violations[0].message


class TestUnresolvedCommentsCondition:
    """Tests for UnresolvedCommentsCondition."""

    @pytest.mark.asyncio
    async def test_evaluate_returns_violations_for_unresolved(self) -> None:
        condition = UnresolvedCommentsCondition()
        event = {
            "review_threads": [
                {"is_resolved": False, "is_outdated": False},
                {"is_resolved": True, "is_outdated": False},
            ]
        }
        context = {"parameters": {"block_on_unresolved_comments": True}, "event": event}
        
        violations = await condition.evaluate(context)
        assert len(violations) == 1
        assert "1 unresolved review comment thread" in violations[0].message

    @pytest.mark.asyncio
    async def test_evaluate_ignores_outdated_or_resolved(self) -> None:
        condition = UnresolvedCommentsCondition()
        event = {
            "review_threads": [
                {"is_resolved": False, "is_outdated": True},
                {"is_resolved": True, "is_outdated": False},
            ]
        }
        context = {"parameters": {"block_on_unresolved_comments": True}, "event": event}
        
        violations = await condition.evaluate(context)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_validate_returns_false_for_unresolved(self) -> None:
        condition = UnresolvedCommentsCondition()
        event = {
            "review_threads": [
                {"is_resolved": False, "is_outdated": False},
            ]
        }
        result = await condition.validate({"require_resolution": True}, event)
        assert result is False
