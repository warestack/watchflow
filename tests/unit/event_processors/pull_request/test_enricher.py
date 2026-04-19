from unittest.mock import AsyncMock, MagicMock

import pytest

from src.event_processors.pull_request.enricher import PullRequestEnricher


@pytest.fixture
def mock_github_client():
    return AsyncMock()


@pytest.fixture
def enricher(mock_github_client):
    return PullRequestEnricher(mock_github_client)


@pytest.fixture
def mock_task():
    task = MagicMock()
    task.repo_full_name = "owner/repo"
    task.installation_id = 12345
    task.payload = {
        "pull_request": {"number": 1, "user": {"login": "author"}},
        "repository": {"full_name": "owner/repo"},
        "organization": {"login": "org"},
        "event_id": "evt_123",
        "timestamp": "2024-01-01T00:00:00Z",
    }
    return task


@pytest.mark.asyncio
async def test_fetch_api_data_success(enricher, mock_github_client):
    mock_github_client.get_pull_request_reviews.return_value = [{"id": 1}]
    mock_github_client.get_pull_request_files.return_value = [{"filename": "f1.txt"}]

    data = await enricher.fetch_api_data("owner/repo", 1, 12345)

    assert data["reviews"] == [{"id": 1}]
    assert data["files"] == [{"filename": "f1.txt"}]
    mock_github_client.get_pull_request_reviews.assert_called_once()
    mock_github_client.get_pull_request_files.assert_called_once()


@pytest.mark.asyncio
async def test_enrich_event_data(enricher, mock_task, mock_github_client):
    mock_github_client.get_pull_request.return_value = {"number": 1, "user": {"login": "author"}}
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = [
        {"filename": "test.py", "status": "added", "additions": 10, "deletions": 0, "patch": "+print('hello')"}
    ]
    mock_github_client.search_merged_pr_count.return_value = 3

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    assert event_data["pull_request_details"]["number"] == 1
    assert event_data["triggering_user"]["login"] == "author"
    assert "reviews" in event_data
    assert "files" in event_data
    assert len(event_data["changed_files"]) == 1
    assert event_data["changed_files"][0]["filename"] == "test.py"
    assert "diff_summary" in event_data
    assert event_data["contributor_context"]["login"] == "author"
    assert event_data["contributor_context"]["merged_pr_count"] == 3
    assert event_data["contributor_context"]["is_first_time"] is False
    assert event_data["contributor_context"]["trusted"] is True


@pytest.mark.asyncio
async def test_enrich_event_data_first_time_contributor(enricher, mock_task, mock_github_client):
    mock_github_client.get_pull_request.return_value = {"number": 1, "user": {"login": "author"}}
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = []
    mock_github_client.search_merged_pr_count.return_value = 0

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    ctx = event_data["contributor_context"]
    assert ctx["merged_pr_count"] == 0
    assert ctx["is_first_time"] is True
    assert ctx["trusted"] is False


@pytest.mark.asyncio
async def test_enrich_event_data_merged_pr_count_unknown(enricher, mock_task, mock_github_client):
    mock_github_client.get_pull_request.return_value = {"number": 1, "user": {"login": "author"}}
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = []
    mock_github_client.search_merged_pr_count.return_value = None

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    ctx = event_data["contributor_context"]
    assert ctx["merged_pr_count"] is None
    assert ctx["is_first_time"] is False  # unknown -> not first-time; fail-open handled in evaluator
    assert ctx["trusted"] is False


@pytest.mark.asyncio
async def test_enrich_event_data_search_api_raises(enricher, mock_task, mock_github_client):
    """Search API raising must not break enrichment — context still present with unknown count."""
    mock_github_client.get_pull_request.return_value = {"number": 1, "user": {"login": "author"}}
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = []
    mock_github_client.search_merged_pr_count.side_effect = Exception("boom")

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    ctx = event_data["contributor_context"]
    assert ctx["login"] == "author"
    assert ctx["merged_pr_count"] is None
    assert ctx["is_first_time"] is False
    assert ctx["trusted"] is False


@pytest.mark.asyncio
async def test_enrich_event_data_client_without_search_method(mock_task):
    """Older GitHub clients without search_merged_pr_count must still produce a context."""

    class LegacyClient:
        async def get_pull_request(self, *args, **kwargs):
            return None

        async def get_pull_request_reviews(self, *args, **kwargs):
            return []

        async def get_pull_request_files(self, *args, **kwargs):
            return []

        async def get_file_content(self, *args, **kwargs):
            return None

    enricher = PullRequestEnricher(LegacyClient())

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    ctx = event_data["contributor_context"]
    assert ctx["login"] == "author"
    assert ctx["merged_pr_count"] is None
    assert ctx["is_first_time"] is False
    assert ctx["trusted"] is False


@pytest.mark.asyncio
async def test_enrich_event_data_refreshes_pr_details(enricher, mock_task, mock_github_client):
    """Stale webhook requested_reviewers is replaced by fresh PR details from the API.

    Simulates the synchronize+review_requested race: the webhook payload's
    requested_reviewers is empty, but a fresh GET /pulls/:num shows alice was
    requested. The enricher must surface the fresh state so CODEOWNERS rules
    don't false-positive.
    """
    mock_task.payload["pull_request"] = {
        "number": 1,
        "user": {"login": "author"},
        "requested_reviewers": [],
        "requested_teams": [],
    }
    mock_github_client.get_pull_request.return_value = {
        "number": 1,
        "user": {"login": "author"},
        "requested_reviewers": [{"login": "alice"}],
        "requested_teams": [],
    }
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = []
    mock_github_client.search_merged_pr_count.return_value = 1

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    assert event_data["pull_request_details"]["requested_reviewers"] == [{"login": "alice"}]
    mock_github_client.get_pull_request.assert_called_once_with("owner/repo", 1, 12345)


@pytest.mark.asyncio
async def test_enrich_event_data_falls_back_to_webhook_pr_when_refresh_fails(enricher, mock_task, mock_github_client):
    """If the refresh API call fails or returns None, the webhook payload PR data is kept."""
    mock_task.payload["pull_request"] = {
        "number": 1,
        "user": {"login": "author"},
        "requested_reviewers": [{"login": "bob"}],
    }
    mock_github_client.get_pull_request.return_value = None
    mock_github_client.get_pull_request_reviews.return_value = []
    mock_github_client.get_pull_request_files.return_value = []
    mock_github_client.search_merged_pr_count.return_value = 1

    event_data = await enricher.enrich_event_data(mock_task, "fake_token")

    assert event_data["pull_request_details"]["requested_reviewers"] == [{"login": "bob"}]


@pytest.mark.asyncio
async def test_fetch_acknowledgments(enricher, mock_github_client):
    mock_github_client.get_issue_comments.return_value = [
        {
            "body": "🚨 Watchflow Rule Violations Detected\n\n**Reason:** valid reason\n\n---\nThe following violations have been overridden:\n• PR has 1 approvals, requires 2\n",
            "user": {"login": "reviewer"},
        }
    ]

    acks = await enricher.fetch_acknowledgments("owner/repo", 1, 12345)

    assert "min-pr-approvals" in acks
    assert acks["min-pr-approvals"].reason == "valid reason"
    assert acks["min-pr-approvals"].commenter == "reviewer"


def test_summarize_files_truncates(enricher):
    files = [
        {
            "filename": "large.py",
            "status": "modified",
            "additions": 100,
            "deletions": 50,
            "patch": "\n".join([f"+line {i}" for i in range(20)]),
        }
    ]

    summary = enricher.summarize_files(files, max_files=1, max_patch_lines=5)

    assert "- large.py (modified, +100/-50)" in summary
    assert "line 4" in summary
    assert "line 5" not in summary
    assert "... (diff truncated)" in summary


def test_summarize_files_empty(enricher):
    assert enricher.summarize_files([]) == ""


def test_prepare_webhook_data(enricher, mock_task):
    data = enricher.prepare_webhook_data(mock_task)

    assert data["event_type"] == "pull_request"
    assert data["pull_request"]["number"] == 1
    assert data["pull_request"]["user"] == "author"
