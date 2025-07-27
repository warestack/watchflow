from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.event_processors.pull_request import PullRequestProcessor
from src.rules.validators import RequiredChecksValidator
from src.tasks.task_queue import Task, TaskStatus


class TestStatusCheckIntegration:
    """Test suite for status check requirement integration."""

    @pytest.mark.asyncio
    async def test_required_checks_validator_with_passing_checks(self):
        """Test that RequiredChecksValidator correctly validates when all checks pass."""
        validator = RequiredChecksValidator()

        # Mock event data with passing checks
        event_data = {
            "checks": [
                {"name": "ci/test", "conclusion": "success", "status": "completed"},
                {"name": "lint", "conclusion": "success", "status": "completed"},
                {"context": "build", "state": "success"},
            ]
        }

        parameters = {"required_checks": ["ci/test", "lint", "build"]}

        # Should return True (no violation) when all checks pass
        result = await validator.validate(parameters, event_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_required_checks_validator_with_failing_checks(self):
        """Test that RequiredChecksValidator correctly identifies failing checks."""
        validator = RequiredChecksValidator()

        # Mock event data with failing checks
        event_data = {
            "checks": [
                {"name": "ci/test", "conclusion": "failure", "status": "completed"},
                {"name": "lint", "conclusion": "success", "status": "completed"},
            ]
        }

        parameters = {
            "required_checks": ["ci/test", "lint", "build"]  # build is missing
        }

        # Should return False (violation) when checks fail or are missing
        result = await validator.validate(parameters, event_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_required_checks_validator_with_missing_checks(self):
        """Test that RequiredChecksValidator correctly identifies missing checks."""
        validator = RequiredChecksValidator()

        # Mock event data with missing required checks
        event_data = {"checks": [{"name": "ci/test", "conclusion": "success", "status": "completed"}]}

        parameters = {"required_checks": ["ci/test", "lint", "security-scan"]}

        # Should return False (violation) when required checks are missing
        result = await validator.validate(parameters, event_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_required_checks_validator_with_legacy_status_api(self):
        """Test that RequiredChecksValidator works with legacy status API."""
        validator = RequiredChecksValidator()

        # Mock event data with legacy status format
        event_data = {
            "checks": [
                {"context": "continuous-integration/travis-ci/pr", "state": "success"},
                {"context": "codecov/patch", "state": "failure"},
            ]
        }

        parameters = {"required_checks": ["continuous-integration/travis-ci/pr", "codecov/patch"]}

        # Should return False (violation) when any check fails
        result = await validator.validate(parameters, event_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_required_checks_validator_no_required_checks(self):
        """Test that RequiredChecksValidator passes when no checks are required."""
        validator = RequiredChecksValidator()

        event_data = {"checks": []}

        parameters = {
            "required_checks": []  # No checks required
        }

        # Should return True (no violation) when no checks are required
        result = await validator.validate(parameters, event_data)
        assert result is True

    @pytest.mark.asyncio
    @patch("src.event_processors.pull_request.RuleEngineAgent")
    async def test_pull_request_processor_fetches_checks(self, mock_agent_class):
        """Test that PullRequestProcessor fetches check data for rules evaluation."""
        # Mock the RuleEngineAgent class to avoid OpenAI dependency
        mock_agent = AsyncMock()
        mock_agent_class.return_value = mock_agent

        # Create processor instance
        processor = PullRequestProcessor()

        # Mock the GitHub client on the processor instance
        processor.github_client = AsyncMock()
        processor.github_client.get_pull_request_reviews.return_value = []
        processor.github_client.get_pull_request_files.return_value = []
        processor.github_client.get_pr_checks.return_value = [
            {"name": "ci/test", "conclusion": "failure", "status": "completed"}
        ]

        # Create a mock task
        task = Task(
            id="test-task",
            event_type="pull_request",
            repo_full_name="owner/repo",
            installation_id=123456,
            payload={"pull_request": {"number": 42}},
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
        )

        # Test that checks are fetched via prepare_api_data
        api_data = await processor.prepare_api_data(task)

        assert "checks" in api_data
        assert len(api_data["checks"]) == 1
        assert api_data["checks"][0]["name"] == "ci/test"
        assert api_data["checks"][0]["conclusion"] == "failure"

        # Test that checks are also fetched via _prepare_event_data_for_agent
        event_data = await processor._prepare_event_data_for_agent(task, "mock-token")

        assert "checks" in event_data
        assert len(event_data["checks"]) == 1
        assert event_data["checks"][0]["name"] == "ci/test"
        assert event_data["checks"][0]["conclusion"] == "failure"

        # Verify the GitHub API was called twice (once for each method)
        assert processor.github_client.get_pr_checks.call_count == 2
        processor.github_client.get_pr_checks.assert_called_with("owner/repo", 42, 123456)


if __name__ == "__main__":
    pytest.main([__file__])
