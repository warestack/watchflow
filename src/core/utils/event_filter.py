"""
Event filtering for GitHub webhooks.

Centralized logic to skip rule evaluation on irrelevant events:
branch deletions, closed/merged PRs, archived repos, etc.
"""

from dataclasses import dataclass

import structlog

from src.core.models import EventType, WebhookEvent

logger = structlog.get_logger()

NULL_SHA = "0000000000000000000000000000000000000000"

PR_ACTIONS_PROCESS = frozenset({"opened", "synchronize", "reopened"})


@dataclass
class FilterResult:
    """Result of event filter check."""

    should_process: bool
    reason: str = ""


def should_process_event(event: WebhookEvent) -> FilterResult:
    """
    Determine if an event should trigger rule evaluation.

    Returns FilterResult with should_process=True to process, False to skip.
    Logs filtered events for observability.
    """
    payload = event.payload
    event_type = event.event_type

    result = _apply_filters(event_type, payload)
    if not result.should_process:
        logger.info(
            "event_filtered",
            event_type=event_type.value if hasattr(event_type, "value") else str(event_type),
            repo=event.repo_full_name,
            reason=result.reason,
        )
    return result


def _apply_filters(event_type: EventType, payload: dict) -> FilterResult:
    if _is_repo_archived(payload):
        return FilterResult(should_process=False, reason="Repository is archived")

    if event_type == EventType.PULL_REQUEST:
        return _filter_pull_request(payload)
    if event_type == EventType.PUSH:
        return _filter_push(payload)
    return FilterResult(should_process=True)


def _filter_pull_request(payload: dict) -> FilterResult:
    action = payload.get("action")
    if action not in PR_ACTIONS_PROCESS:
        return FilterResult(should_process=False, reason=f"PR action '{action}' not processed")

    pr = payload.get("pull_request", {})
    state = pr.get("state", "")
    if state != "open":
        return FilterResult(should_process=False, reason=f"PR state '{state}' not open")

    if pr.get("merged"):
        return FilterResult(should_process=False, reason="PR already merged")

    if pr.get("draft"):
        return FilterResult(should_process=False, reason="PR is draft")

    return FilterResult(should_process=True)


def _filter_push(payload: dict) -> FilterResult:
    if payload.get("deleted"):
        return FilterResult(should_process=False, reason="Branch deletion event")

    after = payload.get("after")
    if not after or after == NULL_SHA:
        return FilterResult(should_process=False, reason="No valid commit SHA (deleted or empty push)")

    return FilterResult(should_process=True)


def _is_repo_archived(payload: dict) -> bool:
    repo = payload.get("repository", {})
    return isinstance(repo, dict) and bool(repo.get("archived"))
