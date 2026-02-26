from src.core.models import EventType, WebhookEvent
from src.core.utils.event_filter import (
    NULL_SHA,
    PR_ACTIONS_PROCESS,
    FilterResult,
    should_process_event,
)


def _make_event(event_type: EventType, payload: dict, delivery_id: str | None = None) -> WebhookEvent:
    return WebhookEvent(event_type=event_type, payload=payload, delivery_id=delivery_id)


def test_pull_request_opened_processes():
    """Test that opened PR events are processed."""
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_synchronize_processes():
    """Test that synchronize PR events are processed."""
    payload = {
        "action": "synchronize",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_reopened_processes():
    """Test that reopened PR events are processed."""
    payload = {
        "action": "reopened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_closed_action_filtered():
    """Test that closed PR action is filtered."""
    payload = {
        "action": "closed",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "closed", "merged": True},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "closed" in result.reason or "not processed" in result.reason


def test_pull_request_merged_filtered():
    """Test that merged PRs are filtered."""
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "closed", "merged": True, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "merged" in result.reason or "not open" in result.reason


def test_pull_request_draft_filtered():
    """Test that draft PRs are filtered."""
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": True},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "draft" in result.reason


def test_pull_request_closed_state_filtered():
    """Test that closed state (not merged) PRs are filtered."""
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "closed", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "not open" in result.reason


def test_push_valid_processes():
    """Test that valid push events are processed."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
        "after": "abc123",
        "commits": [{}],
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is True


def test_push_deleted_branch_filtered():
    """Test that deleted branch push events are filtered."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/feature",
        "deleted": True,
        "after": NULL_SHA,
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False
    assert "deletion" in result.reason or "Branch" in result.reason


def test_push_null_sha_filtered():
    """Test that null SHA push events are filtered."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
        "after": NULL_SHA,
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False


def test_push_empty_after_filtered():
    """Test that empty 'after' push events are filtered."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
        "after": "",
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False


def test_push_missing_after_filtered():
    """Test that missing 'after' push events are filtered."""
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False


def test_archived_repo_filtered():
    """Test that archived repositories are filtered."""
    payload = {
        "repository": {"full_name": "owner/repo", "archived": True},
        "action": "opened",
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "archived" in result.reason


def test_other_event_types_process():
    """Test that other event types are processed (not filtered)."""
    payload = {"repository": {"full_name": "owner/repo"}}
    for evt in (EventType.CHECK_RUN, EventType.DEPLOYMENT, EventType.DEPLOYMENT_STATUS):
        result = should_process_event(_make_event(evt, payload))
        assert result.should_process is True


def test_filter_result_dataclass():
    """Test FilterResult dataclass properties."""
    result = FilterResult(should_process=True, reason="test reason")
    assert result.should_process is True
    assert result.reason == "test reason"


def test_filter_result_frozen():
    """Test that FilterResult is frozen (immutable)."""
    result = FilterResult(should_process=True, reason="test")
    # Attempting to modify should raise an error
    try:
        result.should_process = False
        assert False, "Should have raised FrozenInstanceError"
    except Exception:
        pass  # Expected


def test_pr_actions_process_constant():
    """Test PR_ACTIONS_PROCESS contains expected actions."""
    assert "opened" in PR_ACTIONS_PROCESS
    assert "synchronize" in PR_ACTIONS_PROCESS
    assert "reopened" in PR_ACTIONS_PROCESS
    assert len(PR_ACTIONS_PROCESS) == 3


def test_null_sha_constant():
    """Test NULL_SHA has expected value."""
    assert NULL_SHA == "0000000000000000000000000000000000000000"
    assert len(NULL_SHA) == 40


def test_pull_request_labeled_action_filtered():
    """Test that labeled PR action is filtered."""
    payload = {
        "action": "labeled",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "not processed" in result.reason


def test_pull_request_unlabeled_action_filtered():
    """Test that unlabeled PR action is filtered."""
    payload = {
        "action": "unlabeled",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "not processed" in result.reason
