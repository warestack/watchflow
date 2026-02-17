import pytest

from src.core.models import EventType, WebhookEvent
from src.core.utils.event_filter import FilterResult, should_process_event


def _make_event(event_type: EventType, payload: dict) -> WebhookEvent:
    return WebhookEvent(event_type=event_type, payload=payload)


def test_pull_request_opened_processes():
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_synchronize_processes():
    payload = {
        "action": "synchronize",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_reopened_processes():
    payload = {
        "action": "reopened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is True


def test_pull_request_closed_action_filtered():
    payload = {
        "action": "closed",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "closed", "merged": True},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "closed" in result.reason or "not processed" in result.reason


def test_pull_request_merged_filtered():
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "closed", "merged": True, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "merged" in result.reason or "not open" in result.reason


def test_pull_request_draft_filtered():
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"state": "open", "merged": False, "draft": True},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "draft" in result.reason


def test_push_valid_processes():
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
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/feature",
        "deleted": True,
        "after": "0000000000000000000000000000000000000000",
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False
    assert "deletion" in result.reason or "Branch" in result.reason


def test_push_null_sha_filtered():
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
        "after": "0000000000000000000000000000000000000000",
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False


def test_push_empty_after_filtered():
    payload = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/main",
        "deleted": False,
        "after": "",
    }
    result = should_process_event(_make_event(EventType.PUSH, payload))
    assert result.should_process is False


def test_archived_repo_filtered():
    payload = {
        "repository": {"full_name": "owner/repo", "archived": True},
        "action": "opened",
        "pull_request": {"state": "open", "merged": False, "draft": False},
    }
    result = should_process_event(_make_event(EventType.PULL_REQUEST, payload))
    assert result.should_process is False
    assert "archived" in result.reason


def test_other_event_types_process():
    payload = {"repository": {"full_name": "owner/repo"}}
    for evt in (EventType.CHECK_RUN, EventType.DEPLOYMENT, EventType.DEPLOYMENT_STATUS):
        result = should_process_event(_make_event(evt, payload))
        assert result.should_process is True
