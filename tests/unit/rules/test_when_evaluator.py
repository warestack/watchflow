"""Tests for the `when:` predicate evaluator used to conditionally skip rules."""

import pytest

from src.rules.models import RuleWhen
from src.rules.when_evaluator import should_apply_rule


def _ctx(merged: int) -> dict:
    return {
        "login": "alice",
        "merged_pr_count": merged,
        "is_first_time": merged == 0,
        "trusted": merged > 0,
    }


def test_no_when_block_applies_rule():
    applies, reason = should_apply_rule(None, {})
    assert applies is True
    assert reason == ""


def test_contributor_first_time_matches():
    when = RuleWhen(contributor="first_time")
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(0)})
    assert applies is True


def test_contributor_first_time_does_not_match_established():
    when = RuleWhen(contributor="first_time")
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(5)})
    assert applies is False
    assert "not first-time" in reason


def test_contributor_trusted_matches_established():
    when = RuleWhen(contributor="trusted")
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(5)})
    assert applies is True


def test_contributor_trusted_does_not_match_first_time():
    when = RuleWhen(contributor="trusted")
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(0)})
    assert applies is False
    assert "not trusted" in reason


def test_pr_count_below_matches():
    when = RuleWhen(pr_count_below=3)
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(2)})
    assert applies is True


def test_pr_count_below_does_not_match_at_boundary():
    when = RuleWhen(pr_count_below=3)
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(3)})
    assert applies is False
    assert "3 merged PRs" in reason
    assert "threshold: 3" in reason


def test_pr_count_below_with_none_merged_count_fails_open():
    """When merged_pr_count is None (API failure), rule is applied (fail-open)."""
    when = RuleWhen(pr_count_below=3)
    ctx = {"login": "alice", "merged_pr_count": None, "is_first_time": False, "trusted": False}
    applies, reason = should_apply_rule(when, {"contributor_context": ctx})
    assert applies is True


@pytest.mark.parametrize(
    "pattern,files,expected",
    [
        ("src/auth/**", [{"filename": "src/auth/login.py"}], True),
        ("src/auth/**", [{"filename": "src/ui/page.tsx"}], False),
        (["**.md", "docs/**"], [{"filename": "README.md"}], True),
        (["**.md", "docs/**"], [{"filename": "src/main.py"}], False),
    ],
)
def test_files_match_predicate(pattern, files, expected):
    when = RuleWhen(files_match=pattern)
    applies, reason = should_apply_rule(when, {"changed_files": files})
    assert applies is expected
    if not expected:
        assert "no changed files match" in reason


def test_combined_predicates_all_must_hold():
    when = RuleWhen(contributor="first_time", files_match="src/auth/**")
    # first-time but wrong path -> skip
    applies, reason = should_apply_rule(
        when,
        {
            "contributor_context": _ctx(0),
            "changed_files": [{"filename": "README.md"}],
        },
    )
    assert applies is False
    assert "no changed files match" in reason

    # first-time AND matching path -> apply
    applies, reason = should_apply_rule(
        when,
        {
            "contributor_context": _ctx(0),
            "changed_files": [{"filename": "src/auth/login.py"}],
        },
    )
    assert applies is True


def test_missing_contributor_context_fails_open():
    """When context is missing, the rule is applied (fail-open) instead of silently skipped."""
    when = RuleWhen(contributor="first_time")
    applies, reason = should_apply_rule(when, {})
    assert applies is True


def test_unknown_contributor_predicate_is_ignored():
    when = RuleWhen(contributor="mystery")
    applies, reason = should_apply_rule(when, {"contributor_context": _ctx(0)})
    assert applies is True
