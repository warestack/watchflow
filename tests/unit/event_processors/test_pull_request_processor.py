import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config import config
from src.core.models import Violation
from src.event_processors.pull_request.enricher import PullRequestEnricher
from src.event_processors.pull_request.processor import PullRequestProcessor
from src.integrations.github.check_runs import CheckRunManager
from src.presentation.github_formatter import (
    RULES_NOT_CONFIGURED_COMMENT_MARKER,
    build_violations_state,
    format_check_run_output,
)
from src.rules.loaders.github_loader import RulesFileNotFoundError
from src.tasks.task_queue import Task


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    return agent


@pytest.fixture
def processor(monkeypatch, mock_agent):
    monkeypatch.setattr("src.event_processors.pull_request.processor.get_agent", lambda x: mock_agent)
    monkeypatch.setattr(config.github, "app_name", "watchflow")

    proc = PullRequestProcessor()

    # Create a mock for the GitHub client that returns a token
    mock_github_client = AsyncMock()
    mock_github_client.get_installation_access_token.return_value = "fake_token"
    mock_github_client.get_issue_comments.return_value = []
    mock_github_client.get_check_runs.return_value = []
    mock_github_client.create_pull_request_comment.return_value = {"id": 1}

    # Patch the instance's github_client
    proc.github_client = mock_github_client

    proc.enricher = MagicMock(spec=PullRequestEnricher)
    proc.enricher.parse_acknowledgments.return_value = {}
    proc.check_run_manager = AsyncMock(spec=CheckRunManager)
    return proc


def missing_rules_task(action: str) -> MagicMock:
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {
        "action": action,
        "repository": {"default_branch": "main"},
        "pull_request": {
            "number": 123,
            "state": "open",
            "head": {"sha": "sha123"},
            # Avoid the unrelated agentic scan in these onboarding tests.
            "base": {"ref": "release"},
        },
    }
    return task


@pytest.mark.asyncio
async def test_process_success(processor, mock_agent):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {"pull_request": {"number": 1, "head": {"sha": "sha123"}}}

    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])
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
async def test_process_fetches_a_fresh_comment_snapshot_before_syncing_violation_report(processor, mock_agent):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.payload = {
        "repository": {"default_branch": "main"},
        "pull_request": {
            "number": 1,
            "head": {"sha": "sha123"},
            "base": {"ref": "release"},
        },
    }
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])
    processor.rule_provider.get_rules = AsyncMock(return_value=[])
    violation = Violation(rule_description="Rule 1", severity="high", message="Violation message")
    mock_agent.execute.return_value = MagicMock(data={"evaluation_result": MagicMock(violations=[violation])})

    await processor.process(task)

    assert processor.github_client.get_issue_comments.await_count == 2
    processor.github_client.get_issue_comments.assert_awaited_with("owner/repo", 1, 1)


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
async def test_initial_violations_create_a_marked_current_report(processor):
    """The first violation result creates the canonical report without a delta alert."""
    from src.core.models import Severity

    task = violation_task()
    violations = [Violation(rule_description="Rule A", severity=Severity.HIGH, message="Message 1")]
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])

    await processor._post_violations_to_github(task, violations)

    processor.github_client.create_pull_request_comment.assert_awaited_once()
    report = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert "watchflow:report=violations-current" in report


@pytest.mark.asyncio
async def test_first_violation_after_a_passing_check_creates_a_full_snapshot(processor):
    task = violation_task()
    violation = Violation(rule_id="description", rule_description="Description", severity="high", message="Missing")

    await processor._post_violations_to_github(task, [])
    await processor._post_violations_to_github(task, [violation])

    processor.github_client.create_pull_request_comment.assert_awaited_once()
    comment = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert "### 🛡️ Watchflow Governance Checks" in comment
    assert "Governance Update" not in comment


def violation_task(event_type: str = "pull_request", action: str = "synchronize") -> MagicMock:
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 1
    task.event_type = event_type
    task.payload = {
        "action": action,
        "pull_request": {"number": 123},
        "review": {"user": {"login": "coderabbitai"}},
    }
    return task


@pytest.mark.asyncio
async def test_identical_violations_leave_current_report_untouched(processor):
    violations = [
        Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")
    ]

    await processor._post_violations_to_github(violation_task(), violations, build_violations_state(violations), True)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_improved_violations_refresh_checks_without_a_timeline_comment(processor):
    previous = [
        Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing"),
        Violation(rule_id="changelog", rule_description="Changelog", severity="medium", message="Missing"),
        Violation(rule_id="body", rule_description="Body", severity="medium", message="Empty"),
    ]
    current = previous[:2]
    await processor._post_violations_to_github(
        violation_task("pull_request_review", "submitted"), current, build_violations_state(previous), True
    )

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_violation_posts_a_regression_alert_without_editing_the_snapshot(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")]
    added = Violation(rule_id="changelog", rule_description="Changelog", severity="high", message="Missing")
    await processor._post_violations_to_github(
        violation_task("pull_request_review", "submitted"), [*previous, added], build_violations_state(previous), True
    )

    processor.github_client.create_pull_request_comment.assert_awaited_once()
    alert = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert "review was submitted by @coderabbitai" in alert
    assert "New **high** violation: Changelog" in alert
    assert "highlights only new or worsened findings" in alert


@pytest.mark.asyncio
async def test_severity_increase_posts_regression_alert(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="low", message="Missing")]
    worsened = Violation(rule_id="description", rule_description="Description", severity="high", message="Missing")
    await processor._post_violations_to_github(violation_task(), [worsened], build_violations_state(previous), True)

    alert = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert "increased from **low** to **high**" in alert


def test_mixed_severity_changes_for_the_same_rule_do_not_create_a_false_regression(processor):
    previous = [
        {"id": "rule-a", "severity": "high"},
        {"id": "rule-a", "severity": "low"},
    ]
    current = [Violation(rule_id="rule-a", rule_description="Rule A", severity="medium", message="Missing")]

    added, worsened = processor._find_violation_regressions(previous, current)

    assert added == []
    assert worsened == []


@pytest.mark.asyncio
async def test_resolved_violations_do_not_create_a_timeline_comment(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")]

    await processor._post_violations_to_github(violation_task(), [], build_violations_state(previous), True)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_violation_reintroduced_after_resolution_posts_a_regression_alert(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")]

    await processor._post_violations_to_github(violation_task(), [], build_violations_state(previous), True)
    await processor._post_violations_to_github(violation_task(), previous, build_violations_state(previous), True)

    processor.github_client.create_pull_request_comment.assert_awaited_once()
    alert = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert "Governance Update" in alert
    assert "New **medium** violation: Description" in alert


@pytest.mark.asyncio
async def test_previous_state_is_loaded_from_the_prior_check_on_a_new_commit(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")]
    task = violation_task("pull_request", "synchronize")
    task.payload["before"] = "previous-sha"
    processor.github_client.get_check_runs.return_value = [
        {
            "id": 7,
            "name": "Watchflow Rules",
            "output": format_check_run_output(previous),
        }
    ]

    state, has_previous_report = await processor._get_previous_violation_state(task, "current-sha", 1)

    assert state == build_violations_state(previous)
    assert has_previous_report is True
    processor.github_client.get_check_runs.assert_awaited_once_with("owner/repo", "previous-sha", 1)
    processor.github_client.get_issue_comments.assert_not_awaited()


@pytest.mark.asyncio
async def test_passing_check_without_a_report_keeps_the_first_violation_eligible_for_a_snapshot(processor):
    task = violation_task("pull_request", "synchronize")
    task.payload["before"] = "previous-sha"
    processor.github_client.get_check_runs.return_value = [
        {
            "id": 7,
            "name": "Watchflow Rules",
            "output": format_check_run_output([]),
        }
    ]

    state, has_previous_report = await processor._get_previous_violation_state(task, "current-sha", 1)

    assert state == []
    assert has_previous_report is False
    processor.github_client.get_issue_comments.assert_awaited_once_with("owner/repo", 123, 1)


@pytest.mark.asyncio
async def test_legacy_report_is_adopted_silently_and_non_watchflow_markers_are_ignored(processor):
    violations = [
        Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")
    ]
    legacy = {
        "id": 2,
        "body": "<!-- watchflow-violations-hash:legacy -->\nold report",
        "user": {"login": "watchflow[bot]"},
    }
    imitation = {
        "id": 3,
        "body": "<!-- watchflow-violations-hash:fake -->",
        "user": {"login": "someone-else"},
    }
    processor.github_client.get_issue_comments.return_value = [imitation, legacy]

    previous_state, has_previous_report = await processor._get_previous_violation_state(violation_task(), "sha123", 1)
    await processor._post_violations_to_github(violation_task(), violations, previous_state, has_previous_report)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_violation_comment_lookup_failure_does_not_create_comments(processor):
    processor.github_client.get_issue_comments.return_value = None
    violations = [Violation(rule_description="Description", severity="medium", message="Missing")]

    previous_state, has_previous_report = await processor._get_previous_violation_state(violation_task(), "sha123", 1)
    await processor._post_violations_to_github(violation_task(), violations, previous_state, has_previous_report)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_remediation_does_not_create_a_follow_up_comment(processor):
    previous = [
        Violation(
            rule_id="description",
            rule_description="Description",
            severity="medium",
            message="Missing",
            how_to_fix="Add a description.",
        )
    ]
    current = [
        Violation(
            rule_id="description",
            rule_description="Description",
            severity="medium",
            message="Missing",
            how_to_fix="Explain the implementation and tests.",
        )
    ]
    await processor._post_violations_to_github(violation_task(), current, build_violations_state(previous), True)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_violation_sync_posts_one_regression_alert(processor):
    previous = [Violation(rule_id="description", rule_description="Description", severity="medium", message="Missing")]
    current = [
        *previous,
        Violation(rule_id="changelog", rule_description="Changelog", severity="high", message="Missing"),
    ]
    await asyncio.gather(
        processor._post_violations_to_github(violation_task(), current, build_violations_state(previous), True),
        processor._post_violations_to_github(violation_task(), current, build_violations_state(previous), True),
    )

    processor.github_client.create_pull_request_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_opened_pr_without_rules_posts_one_setup_awareness_comment(processor):
    task = missing_rules_task("opened")
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))
    processor.github_client.get_issue_comments = AsyncMock(return_value=[])
    processor.github_client.create_pull_request_comment = AsyncMock(return_value={"id": 1})

    result = await processor.process(task)

    assert result.success is True
    processor.check_run_manager.create_check_run.assert_awaited_once()
    processor.github_client.create_pull_request_comment.assert_awaited_once()
    comment = processor.github_client.create_pull_request_comment.call_args.args[2]
    assert RULES_NOT_CONFIGURED_COMMENT_MARKER in comment


@pytest.mark.asyncio
async def test_opened_pr_with_existing_setup_awareness_comment_does_not_post_again(processor):
    task = missing_rules_task("opened")
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[
            {
                "body": RULES_NOT_CONFIGURED_COMMENT_MARKER,
                "user": {"login": "watchflow[bot]"},
            }
        ]
    )

    await processor.process(task)

    processor.check_run_manager.create_check_run.assert_awaited_once()
    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_opened_pr_with_legacy_setup_awareness_comment_does_not_post_again(processor):
    task = missing_rules_task("opened")
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[
            {
                "body": "## ⚙️ Watchflow rules not configured\n\nNo rules file found.",
                "user": {"login": "watchflow[bot]"},
            }
        ]
    )

    await processor.process(task)

    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", ["synchronize", "reopened", "ready_for_review", "submitted", "dismissed", "resolved", "unresolved"]
)
async def test_non_opened_events_without_rules_do_not_post_setup_awareness_comment(processor, action):
    task = missing_rules_task(action)
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))

    await processor.process(task)

    processor.check_run_manager.create_check_run.assert_awaited_once()
    processor.github_client.get_issue_comments.assert_not_awaited()
    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_awareness_lookup_failure_does_not_post_comment(processor):
    task = missing_rules_task("opened")
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))
    processor.github_client.get_issue_comments = AsyncMock(return_value=None)

    await processor.process(task)

    processor.check_run_manager.create_check_run.assert_awaited_once()
    processor.github_client.create_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_marker_from_non_watchflow_user_does_not_suppress_setup_awareness(processor):
    task = missing_rules_task("opened")
    processor.enricher.enrich_event_data.return_value = {"enriched": "data"}
    processor.rule_provider.get_rules = AsyncMock(side_effect=RulesFileNotFoundError("rules missing"))
    processor.github_client.get_issue_comments = AsyncMock(
        return_value=[{"body": RULES_NOT_CONFIGURED_COMMENT_MARKER, "user": {"login": "someone-else"}}]
    )
    processor.github_client.create_pull_request_comment = AsyncMock(return_value={"id": 1})

    await processor.process(task)

    processor.github_client.create_pull_request_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_opened_events_post_one_setup_awareness_comment(processor):
    task = missing_rules_task("opened")
    existing_comments: list[dict] = []

    async def get_comments(*_args):
        return list(existing_comments)

    async def create_comment(_repo, _pr_number, comment, _installation_id):
        await asyncio.sleep(0)
        existing_comments.append({"body": comment, "user": {"login": "watchflow[bot]"}})
        return {"id": 1}

    processor.github_client.get_issue_comments = AsyncMock(side_effect=get_comments)
    processor.github_client.create_pull_request_comment = AsyncMock(side_effect=create_comment)

    await asyncio.gather(
        processor._post_rules_not_configured_comment(task, 123, 1),
        processor._post_rules_not_configured_comment(task, 123, 1),
    )

    processor.github_client.create_pull_request_comment.assert_awaited_once()
