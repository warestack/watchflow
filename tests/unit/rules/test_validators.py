from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules.validators import (
    AllowedHoursCondition,
    AuthorTeamCondition,
    CodeOwnersCondition,
    DaysCondition,
    FilePatternCondition,
    MaxFileSizeCondition,
    MinApprovalsCondition,
    MinDescriptionLengthCondition,
    PastContributorApprovalCondition,
    RequiredLabelsCondition,
    RequireLinkedIssueCondition,
    TitlePatternCondition,
    WeekendCondition,
)

# --- Condition Tests ---


@pytest.mark.asyncio
async def test_author_team_condition():
    # Placeholder implementation returns False for now
    condition = AuthorTeamCondition()
    assert await condition.validate({"team": "devs"}, {"sender": {"login": "user"}}) is False


@pytest.mark.asyncio
async def test_require_linked_issue_condition():
    condition = RequireLinkedIssueCondition()

    # Test strict linked issues
    assert await condition.validate({}, {"linked_issues": [1]}) is True

    # Test body keywords
    event_with_valid_body = {"pull_request_details": {"body": "Fixes #123"}}
    assert await condition.validate({}, event_with_valid_body) is True

    event_with_invalid_body = {"pull_request_details": {"body": "No issue linked"}}
    assert await condition.validate({}, event_with_invalid_body) is False


@pytest.mark.asyncio
async def test_file_pattern_condition():
    condition = FilePatternCondition()

    # Mock _get_changed_files or rely on implementation (it returns empty for PR currently except TODO)
    # The implementation checks "files" from event? No, it uses _get_changed_files which uses event type.
    # But checking source: _get_changed_files returns empty list for pull_request (TODO).
    # But checking source again (lines 225+):
    # if event_type == "pull_request": return []
    # So this validator always returns False for PRs currently unless we mock _get_changed_files

    with patch.object(condition, "_get_changed_files", return_value=["src/foo.py"]):
        # Match pattern
        assert await condition.validate({"pattern": "*.py", "condition_type": "files_match_pattern"}, {}) is True
        # Not match pattern
        assert await condition.validate({"pattern": "*.js", "condition_type": "files_match_pattern"}, {}) is False
        # Not match pattern logic
        assert await condition.validate({"pattern": "*.py", "condition_type": "files_not_match_pattern"}, {}) is False


@pytest.mark.asyncio
async def test_min_approvals_condition():
    condition = MinApprovalsCondition()

    event = {"reviews": [{"state": "APPROVED"}, {"state": "COMMENTED"}, {"state": "APPROVED"}]}

    assert await condition.validate({"min_approvals": 2}, event) is True
    assert await condition.validate({"min_approvals": 3}, event) is False


@pytest.mark.asyncio
async def test_days_condition():
    condition = DaysCondition()

    # Merged on Friday
    event = {"pull_request_details": {"merged_at": "2023-10-27T10:00:00Z"}}  # Oct 27 2023 was Friday

    assert await condition.validate({"days": ["Saturday", "Sunday"]}, event) is True  # Not restricted
    assert await condition.validate({"days": ["Friday"]}, event) is False  # Restricted


@pytest.mark.asyncio
async def test_title_pattern_condition():
    condition = TitlePatternCondition()

    event = {"pull_request_details": {"title": "feat: new feature"}}

    assert await condition.validate({"title_pattern": "^feat:"}, event) is True
    assert await condition.validate({"title_pattern": "^fix:"}, event) is False


@pytest.mark.asyncio
async def test_min_description_length_condition():
    condition = MinDescriptionLengthCondition()

    event = {"pull_request_details": {"body": "Short desc"}}

    assert await condition.validate({"min_description_length": 5}, event) is True
    assert await condition.validate({"min_description_length": 20}, event) is False


@pytest.mark.asyncio
async def test_required_labels_condition():
    condition = RequiredLabelsCondition()

    event = {"pull_request_details": {"labels": [{"name": "bug"}, {"name": "security"}]}}

    assert await condition.validate({"required_labels": ["bug"]}, event) is True
    assert await condition.validate({"required_labels": ["bug", "security"]}, event) is True
    assert await condition.validate({"required_labels": ["feature"]}, event) is False


@pytest.mark.asyncio
async def test_max_file_size_condition():
    condition = MaxFileSizeCondition()

    event = {
        "files": [
            {"filename": "small.py", "size": 1024},  # 1KB
            {"filename": "large.bin", "size": 10 * 1024 * 1024 + 1},  # > 10MB
        ]
    }

    assert await condition.validate({"max_file_size_mb": 1}, event) is False
    assert await condition.validate({"max_file_size_mb": 20}, event) is True


@pytest.mark.asyncio
async def test_code_owners_condition():
    condition = CodeOwnersCondition()

    # Needed mocks
    with (
        patch("src.rules.validators.FilePatternCondition._glob_to_regex", return_value=".*"),
        patch("src.rules.utils.codeowners.is_critical_file", return_value=True),
        patch.object(condition, "_get_changed_files", return_value=["critical.py"]),
    ):
        # If critical file changes, return False (review needed)
        # Wait, validate returns NOT requires_code_owner_review
        # requires_code_owner_review is True if any file is critical
        # So returns False (violation because review IS needed but condition checks "is valid"?)
        # Usually validators return True if PASS (no violation).
        # If review is needed, and we assume it's NOT provided?
        # The condition is "code_owners". Logic:
        # requires_code_owner_review = any(...)
        # return not requires_code_owner_review
        # So if review is REQUIRED, it returns False (Validation Failed).
        # This implies the condition asserts "No code owner validation errors" or "No critical files changed"?
        # Description: "Validates if changes to files require review from code owners"
        # If it returns False, it means "Code owner review REQUIRED (and presumably not present?)"
        # Actually the validator does not check if review is GIVEN. Just if it's needed.
        # So if it's needed, it returns False -> Trigger Violation.
        # Violation message would be "Code owner review required".

        assert await condition.validate({}, {}) is False


@pytest.mark.asyncio
async def test_past_contributor_approval_condition():
    condition = PastContributorApprovalCondition()

    mock_client = AsyncMock()

    event = {
        "pull_request_details": {"user": {"login": "newuser"}},
        "repository": {"full_name": "owner/repo"},
        "installation": {"id": 123},
        "github_client": mock_client,
        "reviews": [{"state": "APPROVED", "user": {"login": "olduser"}}],
    }

    # Mock is_new_contributor
    # It is imported inside the method: from src.rules.utils.contributors import is_new_contributor
    # We need to patch it where it is imported?
    # Or patch the module src.rules.validators.is_new_contributor?
    # No, it's imported inside the function scope.
    # We must patch 'src.rules.utils.contributors.is_new_contributor'.

    with patch("src.rules.utils.contributors.is_new_contributor") as mock_is_new:
        # Case 1: Author is NOT new -> True
        mock_is_new.side_effect = lambda login, *args: False
        assert await condition.validate({}, event) is True

        # Case 2: Author IS new, Reviewer IS old -> True
        mock_is_new.side_effect = lambda login, *args: login == "newuser"
        assert await condition.validate({"min_past_contributors": 1}, event) is True

        # Case 3: Author IS new, Reviewer IS new -> False
        mock_is_new.side_effect = lambda login, *args: True
        assert await condition.validate({"min_past_contributors": 1}, event) is False


@pytest.mark.asyncio
async def test_allowed_hours_condition():
    condition = AllowedHoursCondition()

    # Mock datetime
    # We can't easily mock datetime.now() because it's a built-in type method.
    # But the code does: datetime.now(tz)
    # We can patch datetime in the module.

    with patch("src.rules.validators.datetime") as mock_datetime:
        mock_datetime.now.return_value.hour = 10
        mock_datetime.side_effect = datetime  # To allow other usage if needed? No, generic mock is risky.
        # Better: mock the whole class but that's hard.
        # Alternative: use freezegun or simple patch of 'src.rules.validators.datetime' reference?
        # The file imports `datetime` classes: `from datetime import datetime`.
        # So we patch `src.rules.validators.datetime`.

        mock_dt = MagicMock()
        mock_dt.now.return_value.hour = 10

        with patch("src.rules.validators.datetime", mock_dt):
            assert await condition.validate({"allowed_hours": [9, 10, 11]}, {}) is True
            assert await condition.validate({"allowed_hours": [12, 13]}, {}) is False


@pytest.mark.asyncio
async def test_weekend_condition():
    condition = WeekendCondition()

    mock_dt = MagicMock()
    # Monday = 0
    mock_dt.now.return_value.weekday.return_value = 0

    with patch("src.rules.validators.datetime", mock_dt):
        assert await condition.validate({}, {}) is True

    # Saturday = 5
    mock_dt.now.return_value.weekday.return_value = 5
    with patch("src.rules.validators.datetime", mock_dt):
        assert await condition.validate({}, {}) is False
