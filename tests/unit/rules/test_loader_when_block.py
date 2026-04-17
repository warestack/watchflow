"""Tests for parsing the `when:` block in GitHubRuleLoader."""

from src.rules.loaders.github_loader import GitHubRuleLoader
from src.rules.models import RuleWhen


def test_parse_rule_without_when_block():
    rule = GitHubRuleLoader._parse_rule(
        {
            "description": "Require changelog",
            "event_types": ["pull_request"],
            "parameters": {"changelog_required": True},
        }
    )
    assert rule.when is None


def test_parse_rule_with_when_contributor_first_time():
    rule = GitHubRuleLoader._parse_rule(
        {
            "description": "Require changelog (first-time only)",
            "event_types": ["pull_request"],
            "parameters": {"changelog_required": True},
            "when": {"contributor": "first_time"},
        }
    )
    assert isinstance(rule.when, RuleWhen)
    assert rule.when.contributor == "first_time"


def test_parse_rule_with_when_files_match_and_pr_count_below():
    rule = GitHubRuleLoader._parse_rule(
        {
            "description": "Stricter checks on auth for newcomers",
            "event_types": ["pull_request"],
            "parameters": {"changelog_required": True},
            "when": {"pr_count_below": 3, "files_match": "src/auth/**"},
        }
    )
    assert rule.when is not None
    assert rule.when.pr_count_below == 3
    assert rule.when.files_match == "src/auth/**"


def test_parse_rule_with_invalid_when_block_is_ignored():
    rule = GitHubRuleLoader._parse_rule(
        {
            "description": "Invalid when",
            "event_types": ["pull_request"],
            "parameters": {"changelog_required": True},
            "when": "not-a-mapping",
        }
    )
    assert rule.when is None
