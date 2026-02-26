"""
Scan for AI assistant rule files in a repository (Cursor, Claude, Copilot, etc.).
Used by the repo-scanning flow to find *rules*.md, *guidelines*.md, *prompt*.md
and .cursor/rules/*.mdc, then optionally flag files that contain instruction keywords.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from src.core.utils.patterns import matches_any

logger = logging.getLogger(__name__)

# --- Path patterns (globs) ---
AI_RULE_FILE_PATTERNS = [
    "*rules*.md",
    "*guidelines*.md",
    "*prompt*.md",
    "**/*rules*.md",
    "**/*guidelines*.md",
    "**/*prompt*.md",
    ".cursor/rules/*.mdc",
    ".cursor/rules/**/*.mdc",
]

# --- Keywords (content) ---
AI_RULE_KEYWORDS = [
    "Cursor rule:",
    "Claude:",
    "always use",
    "never commit",
    "Copilot",
    "AI assistant",
    "when writing code",
    "when generating",
]


def path_matches_ai_rule_patterns(path: str) -> bool:
    """Return True if path matches any of the AI rule file glob patterns."""
    if not path or not path.strip():
        return False
    normalized = path.replace("\\", "/").strip()
    return matches_any(normalized, AI_RULE_FILE_PATTERNS)


def content_has_ai_keywords(content: str | None) -> bool:
    """Return True if content contains any of the AI rule keywords (case-insensitive)."""
    if not content:
        return False
    lower = content.lower()
    return any(kw.lower() in lower for kw in AI_RULE_KEYWORDS)


def filter_tree_entries_for_ai_rules(
    tree_entries: list[dict[str, Any]],
    *,
    blob_only: bool = True,
    ) -> list[dict[str, Any]]:
    """
    From a GitHub tree response (list of { path, type, ... }), return entries
    that match AI rule file patterns. By default only 'blob' (files) are included.
    """
    result = []
    for entry in tree_entries:
        if blob_only and entry.get("type") != "blob":
            continue
        path = entry.get("path") or ""
        if path_matches_ai_rule_patterns(path):
            result.append(entry)
    return cast("list[dict[str, Any]]", result)


GetContentFn = Callable[[str], Awaitable[str | None]]


async def scan_repo_for_ai_rule_files(
    tree_entries: list[dict[str, Any]],
    *,
    fetch_content: bool = False,
    get_file_content: GetContentFn | None = None,
    ) -> list[dict[str, Any]]:
    """
    Filter tree entries to AI-rule candidates, optionally fetch content and set has_keywords.

    Returns list of { "path", "has_keywords", "content" }. content is only set when fetch_content
    is True and get_file_content is provided.
    """
    candidates = filter_tree_entries_for_ai_rules(tree_entries, blob_only=True)
    results: list[dict[str, Any]] = []

    for entry in candidates:
        path = entry.get("path") or ""
        has_keywords = False
        content: str | None = None

        if fetch_content and get_file_content:
            try:
                content = await get_file_content(path)
                has_keywords = content_has_ai_keywords(content)
            except Exception as e:
                logger.warning("ai_rules_scan_fetch_failed path=%s error=%s", path, str(e))

        results.append({
            "path": path,
            "has_keywords": has_keywords,
            "content": content,
        })

    return cast("list[dict[str, Any]]", results)