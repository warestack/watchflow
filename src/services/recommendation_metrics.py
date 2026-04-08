# File: src/services/recommendation_metrics.py
"""
Tracks reviewer recommendation outcomes in .watchflow/recommendations.json.

Stores which reviewers were recommended per PR and records when a recommended
reviewer subsequently approves that PR, enabling acceptance-rate statistics
that improve future recommendations.
"""

import contextlib
import json
import logging
from datetime import UTC, datetime

from src.integrations.github import github_client

logger = logging.getLogger(__name__)

_METRICS_PATH = ".watchflow/recommendations.json"


def _empty_metrics() -> dict:
    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "records": [],
        "stats": {
            "total_recommendations": 0,
            "total_acceptances": 0,
        },
    }


async def _load_metrics(repo: str, installation_id: int) -> dict:
    """Load metrics JSON from the repo, returning empty structure if absent or invalid."""
    try:
        content = await github_client.get_file_content(repo, _METRICS_PATH, installation_id)
        if content:
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(content)
    except Exception as e:
        logger.debug("recommendation_metrics_load_failed", extra={"reason": str(e)})
    return _empty_metrics()


async def _save_metrics(repo: str, branch: str, metrics: dict, installation_id: int) -> None:
    """Persist metrics JSON back to the repo (best-effort, never raises)."""
    try:
        metrics["updated_at"] = datetime.now(UTC).isoformat()
        await github_client.create_or_update_file(
            repo_full_name=repo,
            path=_METRICS_PATH,
            content=json.dumps(metrics, indent=2),
            message="chore: update recommendation metrics [watchflow]",
            branch=branch,
            installation_id=installation_id,
        )
    except Exception as e:
        logger.warning(
            "recommendation_metrics_save_failed",
            extra={"repo": repo, "reason": str(e)},
        )


def _recompute_stats(metrics: dict) -> None:
    """Recompute aggregate stats from the records list in-place."""
    records: list[dict] = metrics.get("records", [])
    total_recs = len(records)
    total_acc = sum(1 for r in records if r.get("accepted_by"))
    metrics["stats"] = {
        "total_recommendations": total_recs,
        "total_acceptances": total_acc,
    }


async def save_recommendation(
    repo: str,
    pr_number: int,
    recommended_reviewers: list[str],
    risk_level: str,
    branch: str,
    installation_id: int,
) -> None:
    """
    Append a recommendation record to .watchflow/recommendations.json.

    Called after /reviewers successfully posts and assigns reviewers so we can
    later correlate which recommendations led to approvals.
    """
    metrics = await _load_metrics(repo, installation_id)

    # Avoid duplicate records for the same PR (idempotent re-runs via --force)
    records: list[dict] = metrics.setdefault("records", [])
    records = [r for r in records if r.get("pr_number") != pr_number]

    records.append(
        {
            "pr_number": pr_number,
            "recommended_at": datetime.now(UTC).isoformat(),
            "risk_level": risk_level,
            "recommended_reviewers": recommended_reviewers,
            "accepted_by": [],
        }
    )
    # Keep only the 200 most-recent records to bound file size
    metrics["records"] = records[-200:]

    _recompute_stats(metrics)
    await _save_metrics(repo, branch, metrics, installation_id)
    logger.info("recommendation_saved", extra={"repo": repo, "pr_number": pr_number})


async def record_acceptance(
    repo: str,
    pr_number: int,
    reviewer_login: str,
    branch: str,
    installation_id: int,
) -> None:
    """
    Mark a recommended reviewer as having approved the PR they were assigned to.

    Called when a pull_request_review event arrives with action=submitted and
    state=APPROVED for a reviewer who was previously recommended by Watchflow.
    Does nothing if the reviewer was not in the recommendation record.
    """
    metrics = await _load_metrics(repo, installation_id)

    records: list[dict] = metrics.get("records", [])
    record = next((r for r in records if r.get("pr_number") == pr_number), None)
    if record is None:
        # No recommendation on file for this PR — nothing to track
        logger.debug(
            "record_acceptance_skipped_no_record",
            extra={"repo": repo, "pr_number": pr_number, "reviewer": reviewer_login},
        )
        return

    if reviewer_login not in record.get("recommended_reviewers", []):
        # Approval from someone we didn't recommend — ignore
        return

    accepted_by: list[str] = record.setdefault("accepted_by", [])
    if reviewer_login not in accepted_by:
        accepted_by.append(reviewer_login)
        _recompute_stats(metrics)
        await _save_metrics(repo, branch, metrics, installation_id)
        logger.info(
            "acceptance_recorded",
            extra={"repo": repo, "pr_number": pr_number, "reviewer": reviewer_login},
        )
