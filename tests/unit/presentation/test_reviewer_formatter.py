"""
Unit tests for reviewer recommendation formatter functions.
"""

from src.agents.base import AgentResult
from src.presentation.github_formatter import (
    format_reviewer_recommendation_comment,
    format_risk_assessment_comment,
)


def _risk_result(**overrides) -> AgentResult:
    data = {
        "risk_level": "high",
        "risk_score": 8,
        "risk_signals": [
            {"label": "Sensitive paths", "description": "src/auth/login.py", "points": 5},
            {"label": "Large changeset", "description": "55 files changed", "points": 3},
        ],
        "pr_files_count": 55,
        "candidates": [],
        "llm_ranking": None,
        "pr_author": "dev",
    }
    data.update(overrides)
    return AgentResult(success=True, message="ok", data=data)


def _reviewer_result(**overrides) -> AgentResult:
    data = {
        "risk_level": "high",
        "risk_score": 8,
        "risk_signals": [{"label": "Sensitive paths", "description": "src/billing/", "points": 5}],
        "pr_files_count": 10,
        "llm_ranking": {
            "ranked_reviewers": [
                {"username": "alice", "reason": "billing expert, 80% ownership"},
                {"username": "bob", "reason": "config owner"},
            ],
            "summary": "2 experienced reviewers recommended.",
        },
        "pr_author": "dev",
    }
    data.update(overrides)
    return AgentResult(success=True, message="ok", data=data)


# ---------------------------------------------------------------------------
# format_risk_assessment_comment
# ---------------------------------------------------------------------------


class TestFormatRiskAssessmentComment:
    def test_shows_risk_level_and_score(self):
        comment = format_risk_assessment_comment(_risk_result())
        assert "High" in comment
        assert "score: 8" in comment

    def test_shows_correct_emoji_for_risk_level(self):
        assert "🔴" in format_risk_assessment_comment(_risk_result(risk_level="critical"))
        assert "🟠" in format_risk_assessment_comment(_risk_result(risk_level="high"))
        assert "🟡" in format_risk_assessment_comment(_risk_result(risk_level="medium"))
        assert "🟢" in format_risk_assessment_comment(_risk_result(risk_level="low"))

    def test_shows_risk_signals(self):
        comment = format_risk_assessment_comment(_risk_result())
        assert "Sensitive paths" in comment
        assert "+5 pts" in comment
        assert "Large changeset" in comment

    def test_no_signals_shows_fallback_message(self):
        comment = format_risk_assessment_comment(_risk_result(risk_signals=[]))
        assert "No significant risk signals detected" in comment

    def test_shows_files_count(self):
        comment = format_risk_assessment_comment(_risk_result())
        assert "55" in comment

    def test_includes_reviewers_cta(self):
        comment = format_risk_assessment_comment(_risk_result())
        assert "/reviewers" in comment

    def test_failure_result_shows_error(self):
        bad = AgentResult(success=False, message="GitHub API error", data={})
        comment = format_risk_assessment_comment(bad)
        assert "❌" in comment
        assert "GitHub API error" in comment


# ---------------------------------------------------------------------------
# format_reviewer_recommendation_comment
# ---------------------------------------------------------------------------


class TestFormatReviewerRecommendationComment:
    def test_shows_risk_level(self):
        comment = format_reviewer_recommendation_comment(_reviewer_result())
        assert "High" in comment

    def test_shows_ranked_reviewers(self):
        comment = format_reviewer_recommendation_comment(_reviewer_result())
        assert "@alice" in comment
        assert "@bob" in comment
        assert "billing expert" in comment

    def test_shows_summary(self):
        comment = format_reviewer_recommendation_comment(_reviewer_result())
        assert "2 experienced reviewers recommended." in comment

    def test_no_candidates_shows_fallback(self):
        comment = format_reviewer_recommendation_comment(_reviewer_result(llm_ranking=None))
        assert "No reviewer candidates found" in comment

    def test_risk_signals_in_collapsible(self):
        comment = format_reviewer_recommendation_comment(_reviewer_result())
        assert "<details>" in comment
        assert "Sensitive paths" in comment

    def test_failure_result_shows_error(self):
        bad = AgentResult(success=False, message="Timeout", data={})
        comment = format_reviewer_recommendation_comment(bad)
        assert "❌" in comment
        assert "Timeout" in comment

    def test_empty_reviewers_shows_fallback(self):
        result = _reviewer_result(llm_ranking={"ranked_reviewers": [], "summary": ""})
        comment = format_reviewer_recommendation_comment(result)
        assert "No reviewer candidates found" in comment
