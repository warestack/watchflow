"""
Unit tests for src/services/recommendation_metrics.py

Covers:
- save_recommendation: creates a new record and computes stats
- save_recommendation: replaces duplicate record (idempotent re-run via --force)
- save_recommendation: caps records list at 200
- record_acceptance: marks reviewer as accepted and increments stats
- record_acceptance: no-ops when no matching record exists
- record_acceptance: no-ops when reviewer was not recommended
- record_acceptance: no-ops on duplicate approval (idempotent)
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.services.recommendation_metrics import record_acceptance, save_recommendation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metrics(records=None) -> dict:
    return {
        "updated_at": "2026-01-01T00:00:00+00:00",
        "records": records or [],
        "stats": {"total_recommendations": 0, "total_acceptances": 0},
    }


def _patched_gh(existing_content=None, write_result=None):
    """Return a patched github_client with controllable get_file_content / create_or_update_file."""
    mock_gh = AsyncMock()
    mock_gh.get_file_content = AsyncMock(return_value=existing_content)
    mock_gh.create_or_update_file = AsyncMock(return_value=write_result or {})
    return mock_gh


# ---------------------------------------------------------------------------
# save_recommendation
# ---------------------------------------------------------------------------


class TestSaveRecommendation:
    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_saves_new_record(self, mock_gh):
        """A recommendation record is appended and stats reflect one recommendation."""
        mock_gh.get_file_content = AsyncMock(return_value=None)
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await save_recommendation(
            repo="owner/repo",
            pr_number=42,
            recommended_reviewers=["alice", "bob"],
            risk_level="high",
            branch="main",
            installation_id=1,
        )

        mock_gh.create_or_update_file.assert_called_once()
        saved = json.loads(mock_gh.create_or_update_file.call_args.kwargs["content"])
        assert len(saved["records"]) == 1
        record = saved["records"][0]
        assert record["pr_number"] == 42
        assert record["recommended_reviewers"] == ["alice", "bob"]
        assert record["risk_level"] == "high"
        assert record["accepted_by"] == []
        assert saved["stats"]["total_recommendations"] == 1
        assert saved["stats"]["total_acceptances"] == 0

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_replaces_duplicate_record_for_same_pr(self, mock_gh):
        """Re-running /reviewers --force overwrites the existing recommendation record."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": 42,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "low",
                    "recommended_reviewers": ["carol"],
                    "accepted_by": [],
                }
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await save_recommendation(
            repo="owner/repo",
            pr_number=42,
            recommended_reviewers=["alice"],
            risk_level="high",
            branch="main",
            installation_id=1,
        )

        saved = json.loads(mock_gh.create_or_update_file.call_args.kwargs["content"])
        # Only one record for PR 42 — old one replaced
        assert len([r for r in saved["records"] if r["pr_number"] == 42]) == 1
        assert saved["records"][-1]["recommended_reviewers"] == ["alice"]
        assert saved["records"][-1]["risk_level"] == "high"

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_caps_records_at_200(self, mock_gh):
        """Records list never grows beyond 200 entries."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": i,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "low",
                    "recommended_reviewers": ["x"],
                    "accepted_by": [],
                }
                for i in range(1, 202)  # 201 existing records
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await save_recommendation(
            repo="owner/repo",
            pr_number=300,
            recommended_reviewers=["alice"],
            risk_level="low",
            branch="main",
            installation_id=1,
        )

        saved = json.loads(mock_gh.create_or_update_file.call_args.kwargs["content"])
        assert len(saved["records"]) == 200

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_save_recommendation_graceful_on_write_failure(self, mock_gh):
        """A write failure is logged but does not propagate as an exception."""
        mock_gh.get_file_content = AsyncMock(return_value=None)
        mock_gh.create_or_update_file = AsyncMock(side_effect=Exception("network error"))

        # Should not raise
        await save_recommendation(
            repo="owner/repo",
            pr_number=10,
            recommended_reviewers=["alice"],
            risk_level="low",
            branch="main",
            installation_id=1,
        )


# ---------------------------------------------------------------------------
# record_acceptance
# ---------------------------------------------------------------------------


class TestRecordAcceptance:
    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_records_approval_from_recommended_reviewer(self, mock_gh):
        """When a recommended reviewer approves, accepted_by is updated and stats reflect it."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": 42,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "high",
                    "recommended_reviewers": ["alice", "bob"],
                    "accepted_by": [],
                }
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await record_acceptance(
            repo="owner/repo",
            pr_number=42,
            reviewer_login="alice",
            branch="main",
            installation_id=1,
        )

        saved = json.loads(mock_gh.create_or_update_file.call_args.kwargs["content"])
        record = next(r for r in saved["records"] if r["pr_number"] == 42)
        assert "alice" in record["accepted_by"]
        assert saved["stats"]["total_acceptances"] == 1

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_noop_when_no_record_for_pr(self, mock_gh):
        """If no recommendation record exists for the PR, nothing is written."""
        existing = _make_metrics(records=[])
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await record_acceptance(
            repo="owner/repo",
            pr_number=99,
            reviewer_login="alice",
            branch="main",
            installation_id=1,
        )

        mock_gh.create_or_update_file.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_noop_when_reviewer_was_not_recommended(self, mock_gh):
        """Approvals from reviewers not in recommended_reviewers are ignored."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": 42,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "low",
                    "recommended_reviewers": ["alice"],
                    "accepted_by": [],
                }
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await record_acceptance(
            repo="owner/repo",
            pr_number=42,
            reviewer_login="charlie",  # was never recommended
            branch="main",
            installation_id=1,
        )

        mock_gh.create_or_update_file.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_duplicate_approval_is_idempotent(self, mock_gh):
        """Recording the same approval twice does not duplicate the entry."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": 42,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "high",
                    "recommended_reviewers": ["alice"],
                    "accepted_by": ["alice"],  # already recorded
                }
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(return_value={})

        await record_acceptance(
            repo="owner/repo",
            pr_number=42,
            reviewer_login="alice",
            branch="main",
            installation_id=1,
        )

        # No write needed — nothing changed
        mock_gh.create_or_update_file.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.recommendation_metrics.github_client")
    async def test_record_acceptance_graceful_on_write_failure(self, mock_gh):
        """Write failure during acceptance recording does not propagate."""
        existing = _make_metrics(
            records=[
                {
                    "pr_number": 5,
                    "recommended_at": "2026-01-01T00:00:00+00:00",
                    "risk_level": "low",
                    "recommended_reviewers": ["bob"],
                    "accepted_by": [],
                }
            ]
        )
        mock_gh.get_file_content = AsyncMock(return_value=json.dumps(existing))
        mock_gh.create_or_update_file = AsyncMock(side_effect=Exception("timeout"))

        # Should not raise
        await record_acceptance(
            repo="owner/repo",
            pr_number=5,
            reviewer_login="bob",
            branch="main",
            installation_id=1,
        )
