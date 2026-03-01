from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import Violation
from src.event_processors.pull_request.enricher import PullRequestEnricher
from src.event_processors.pull_request.processor import PullRequestProcessor
from src.integrations.github.check_runs import CheckRunManager
from src.tasks.task_queue import Task


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    return agent


@pytest.fixture
def processor(monkeypatch, mock_agent):
    monkeypatch.setattr("src.event_processors.pull_request.processor.get_agent", lambda x: mock_agent)

    proc = PullRequestProcessor()

    # Create a mock for the GitHub client that returns a token
    mock_github_client = AsyncMock()
    mock_github_client.get_installation_access_token.return_value = "fake_token"

    # Patch the instance's github_client
    proc.github_client = mock_github_client

    proc.enricher = MagicMock(spec=PullRequestEnricher)
    proc.check_run_manager = AsyncMock(spec=CheckRunManager)
    return proc


@pytest.mark.asyncio
async def test_process_success(processor, mock_agent):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {"pull_request": {"number": 1, "head": {"sha": "sha123"}}}

    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.enricher.fetch_acknowledgments.return_value = {}
    processor.rule_provider.get_rules = AsyncMock(return_value=[])

    mock_agent.execute.return_value = MagicMock(data={"evaluation_result": MagicMock(violations=[])})

    result = await processor.process(task)

    assert result.success is True
    assert result.violations == []
    processor.enricher.enrich_event_data.assert_called_once()
    mock_agent.execute.assert_called_once()
    # Ensure check run manager called for success
    processor.check_run_manager.create_check_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_closed_pr_skipped(processor):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {
        "action": "closed",
        "pull_request": {
            "number": 1,
            "state": "closed",
            "merged": True,
            "head": {"sha": "sha123"},
        },
    }

    result = await processor.process(task)

    assert result.success is True
    assert result.violations == []
    processor.enricher.enrich_event_data.assert_not_called()


@pytest.mark.asyncio
async def test_process_with_violations(processor, mock_agent):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {"pull_request": {"number": 1, "head": {"sha": "sha123"}}}

    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.enricher.fetch_acknowledgments.return_value = {}
    processor.rule_provider.get_rules = AsyncMock(return_value=[])

    violation = Violation(rule_description="Rule 1", severity="high", message="Violation message")
    mock_agent.execute.return_value = MagicMock(data={"evaluation_result": MagicMock(violations=[violation])})

    result = await processor.process(task)

    assert result.success is False
    assert len(result.violations) == 1
    assert result.violations[0].rule_description == "Rule 1"
    # Ensure check run manager called for violation
    processor.check_run_manager.create_check_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_compute_violations_hash_stable_ordering(processor):
    """Test that violations hash is stable regardless of input order."""
    from src.core.models import Severity

    violation1 = Violation(rule_description="Rule A", severity=Severity.HIGH, message="Message 1")
    violation2 = Violation(rule_description="Rule B", severity=Severity.MEDIUM, message="Message 2")

    # Hash should be the same regardless of input order
    hash1 = processor._compute_violations_hash([violation1, violation2])
    hash2 = processor._compute_violations_hash([violation2, violation1])

    assert hash1 == hash2
    assert len(hash1) == 12  # Should be 12 chars


@pytest.mark.asyncio
async def test_compute_violations_hash_different_for_different_violations(processor):
    """Test that different violations produce different hashes."""
    from src.core.models import Severity

    violation1 = Violation(rule_description="Rule A", severity=Severity.HIGH, message="Message 1")
    violation2 = Violation(rule_description="Rule B", severity=Severity.MEDIUM, message="Message 2")

    hash1 = processor._compute_violations_hash([violation1])
    hash2 = processor._compute_violations_hash([violation2])

    assert hash1 != hash2


@pytest.mark.asyncio
async def test_has_duplicate_comment_finds_existing(processor):
    """Test that existing comment with matching hash is detected."""
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[
            {"body": "Some other comment"},
            {"body": "<!-- watchflow-violations-hash:abc123def456 -->\n### Violations\nContent here"},
            {"body": "Another comment"},
        ]
    )

    has_duplicate = await processor._has_duplicate_comment("owner/repo", 123, "abc123def456", 1)

    assert has_duplicate is True


@pytest.mark.asyncio
async def test_has_duplicate_comment_no_match(processor):
    """Test that comments without matching hash are not detected as duplicates."""
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[
            {"body": "Some other comment"},
            {"body": "<!-- watchflow-violations-hash:different123 -->\n### Violations\nContent here"},
        ]
    )

    has_duplicate = await processor._has_duplicate_comment("owner/repo", 123, "abc123def456", 1)

    assert has_duplicate is False


@pytest.mark.asyncio
async def test_has_duplicate_comment_no_existing_comments(processor):
    """Test that no duplicate is found when there are no comments."""
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])

    has_duplicate = await processor._has_duplicate_comment("owner/repo", 123, "abc123def456", 1)

    assert has_duplicate is False


@pytest.mark.asyncio
async def test_has_duplicate_comment_fails_open_on_error(processor):
    """Test that duplicate check fails open (returns False) if API call fails."""
    processor.github_client.get_issue_comments = AsyncMock(side_effect=Exception("API error"))

    has_duplicate = await processor._has_duplicate_comment("owner/repo", 123, "abc123def456", 1)

    assert has_duplicate is False  # Fail open to allow posting


@pytest.mark.asyncio
async def test_post_violations_skips_duplicate(processor):
    """Test that posting is skipped when identical comment already exists."""
    from src.core.models import Severity

    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {"pull_request": {"number": 123}}

    violations = [Violation(rule_description="Rule A", severity=Severity.HIGH, message="Message 1")]

    # Mock that a duplicate exists
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[{"body": "<!-- watchflow-violations-hash:abc123def456 -->\nContent"}]
    )

    # Compute the hash (we'll mock it to match)
    with MagicMock() as mock_hash:
        processor._compute_violations_hash = MagicMock(return_value="abc123def456")

        await processor._post_violations_to_github(task, violations)

        # Should NOT have called create_pull_request_comment
        processor.github_client.create_pull_request_comment.assert_not_called()


@pytest.mark.asyncio
async def test_post_violations_posts_when_no_duplicate(processor):
    """Test that posting proceeds when no duplicate comment exists."""
    from src.core.models import Severity

    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {"pull_request": {"number": 123}}

    violations = [Violation(rule_description="Rule A", severity=Severity.HIGH, message="Message 1")]

    # Mock that no duplicate exists
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])
    processor.github_client.create_pull_request_comment = AsyncMock()

    await processor._post_violations_to_github(task, violations)

    # Should have called create_pull_request_comment
    processor.github_client.create_pull_request_comment.assert_called_once()
