"""
Unit tests for src/rules/ai_rules_scan.py.

Covers:
- path_matches_ai_rule_patterns: which paths match AI rule file patterns
- content_has_ai_keywords: keyword detection in content
- filter_tree_entries_for_ai_rules: filtering GitHub tree entries
- scan_repo_for_ai_rule_files: full scan with optional content fetch and has_keywords
"""

import pytest

from src.rules.ai_rules_scan import (
    AI_RULE_FILE_PATTERNS,
    AI_RULE_KEYWORDS,
    content_has_ai_keywords,
    filter_tree_entries_for_ai_rules,
    path_matches_ai_rule_patterns,
    scan_repo_for_ai_rule_files,
)


class TestPathMatchesAiRulePatterns:
    """Tests for path_matches_ai_rule_patterns()."""

    @pytest.mark.parametrize(
        "path",
        [
            "cursor-rules.md",
            "docs/guidelines.md",
            "CONTRIBUTING-guidelines.md",
            "copilot-prompts.md",
            "prompt.md",
            ".cursor/rules/foo.mdc",
            ".cursor/rules/sub/bar.mdc",
            "README-rules-and-conventions.md",
        ],
    )
    def test_matches_candidate_paths(self, path: str) -> None:
        assert path_matches_ai_rule_patterns(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "docs/readme.md",
            "src/main.py",
            "config.yaml",
            "rules.txt",
            "guidelines.txt",
        ],
    )
    def test_rejects_non_candidate_paths(self, path: str) -> None:
        assert path_matches_ai_rule_patterns(path) is False

    def test_empty_or_whitespace_returns_false(self) -> None:
        assert path_matches_ai_rule_patterns("") is False
        assert path_matches_ai_rule_patterns("   ") is False

    def test_normalizes_backslashes(self) -> None:
        assert path_matches_ai_rule_patterns(".cursor\\rules\\x.mdc") is True


class TestContentHasAiKeywords:
    """Tests for content_has_ai_keywords()."""

    @pytest.mark.parametrize(
        "content,keyword",
        [
            ("Cursor rule: Always use type hints", "Cursor rule:"),
            ("Claude: Prefer immutable data", "Claude:"),
            ("We should always use async/await", "always use"),
            ("never commit secrets", "never commit"),
            ("Use Copilot suggestions wisely", "Copilot"),
            ("AI assistant instructions", "AI assistant"),
            ("when writing code follow style guide", "when writing code"),
            ("when generating docs use templates", "when generating"),
        ],
    )
    def test_detects_keywords(self, content: str, keyword: str) -> None:
        assert content_has_ai_keywords(content) is True

    def test_case_insensitive(self) -> None:
        assert content_has_ai_keywords("CURSOR RULE: do something") is True
        assert content_has_ai_keywords("CLAUDE: optional") is True

    def test_no_keywords_returns_false(self) -> None:
        assert content_has_ai_keywords("Just a normal readme.") is False
        assert content_has_ai_keywords("") is False
        assert content_has_ai_keywords(None) is False


class TestFilterTreeEntriesForAiRules:
    """Tests for filter_tree_entries_for_ai_rules()."""

    def test_keeps_only_matching_blobs(self) -> None:
        entries = [
            {"path": "src/main.py", "type": "blob"},
            {"path": "cursor-rules.md", "type": "blob"},
            {"path": "docs/guidelines.md", "type": "blob"},
            {"path": "README.md", "type": "blob"},
            {"path": "docs", "type": "tree"},
        ]
        result = filter_tree_entries_for_ai_rules(entries, blob_only=True)
        assert len(result) == 2
        paths = [e["path"] for e in result]
        assert "cursor-rules.md" in paths
        assert "docs/guidelines.md" in paths

    def test_excludes_trees_when_blob_only(self) -> None:
        entries = [
            {"path": ".cursor/rules", "type": "tree"},
            {"path": ".cursor/rules/guidelines.mdc", "type": "blob"},
        ]
        result = filter_tree_entries_for_ai_rules(entries, blob_only=True)
        assert len(result) == 1
        assert result[0]["path"] == ".cursor/rules/guidelines.mdc"

    def test_empty_list_returns_empty(self) -> None:
        assert filter_tree_entries_for_ai_rules([]) == []

    def test_includes_trees_when_blob_only_false(self) -> None:
        entries = [
            {"path": "docs/guidelines.md", "type": "blob"},
        ]
        result = filter_tree_entries_for_ai_rules(entries, blob_only=False)
        assert len(result) == 1


class TestScanRepoForAiRuleFiles:
    """Tests for scan_repo_for_ai_rule_files() (async)."""

    @pytest.mark.asyncio
    async def test_filter_only_no_content(self) -> None:
        tree_entries = [
            {"path": "cursor-rules.md", "type": "blob"},
            {"path": "src/main.py", "type": "blob"},
        ]
        result = await scan_repo_for_ai_rule_files(
            tree_entries,
            fetch_content=False,
            get_file_content=None,
        )
        assert len(result) == 1
        assert result[0]["path"] == "cursor-rules.md"
        assert result[0]["has_keywords"] is False
        assert result[0]["content"] is None

    @pytest.mark.asyncio
    async def test_fetch_content_sets_has_keywords(self) -> None:
        tree_entries = [
            {"path": "cursor-rules.md", "type": "blob"},
            {"path": "docs/guidelines.md", "type": "blob"},
        ]

        async def mock_get_content(path: str) -> str | None:
            if path == "cursor-rules.md":
                return "Cursor rule: Always use type hints."
            if path == "docs/guidelines.md":
                return "No AI keywords here."
            return None

        result = await scan_repo_for_ai_rule_files(
            tree_entries,
            fetch_content=True,
            get_file_content=mock_get_content,
        )
        assert len(result) == 2
        by_path = {r["path"]: r for r in result}
        assert by_path["cursor-rules.md"]["has_keywords"] is True
        assert by_path["cursor-rules.md"]["content"] == "Cursor rule: Always use type hints."
        assert by_path["docs/guidelines.md"]["has_keywords"] is False
        assert by_path["docs/guidelines.md"]["content"] == "No AI keywords here."

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_has_keywords_false(self) -> None:
        tree_entries = [{"path": "cursor-rules.md", "type": "blob"}]

        async def failing_get_content(path: str) -> str | None:
            raise OSError("Network error")

        result = await scan_repo_for_ai_rule_files(
            tree_entries,
            fetch_content=True,
            get_file_content=failing_get_content,
        )
        assert len(result) == 1
        assert result[0]["path"] == "cursor-rules.md"
        assert result[0]["has_keywords"] is False
        assert result[0]["content"] is None