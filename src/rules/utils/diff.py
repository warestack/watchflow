"""
Rule evaluation utilities for parsing diff and patch contents.
"""

import re


def extract_added_lines(patch: str) -> list[str]:
    """
    Extract lines that were added in a patch.

    Args:
        patch: The unified diff patch string.

    Returns:
        A list of added lines.
    """
    if not patch:
        return []

    added_lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    return added_lines


def extract_removed_lines(patch: str) -> list[str]:
    """
    Extract lines that were removed in a patch.

    Args:
        patch: The unified diff patch string.

    Returns:
        A list of removed lines.
    """
    if not patch:
        return []

    removed_lines = []
    for line in patch.split("\n"):
        if line.startswith("-") and not line.startswith("---"):
            removed_lines.append(line[1:])

    return removed_lines


def match_patterns_in_patch(patch: str, patterns: list[str]) -> list[str]:
    """
    Find matches for regex patterns in the added lines of a patch.

    Args:
        patch: The unified diff patch string.
        patterns: List of regex strings to match against.

    Returns:
        List of matching patterns found.
    """
    if not patch or not patterns:
        return []

    added_lines = extract_added_lines(patch)
    if not added_lines:
        return []

    matched_patterns = []
    compiled_patterns = []

    for p in patterns:
        try:
            compiled_patterns.append((p, re.compile(p)))
        except re.error:
            continue

    for line in added_lines:
        for pattern_str, compiled in compiled_patterns:
            if pattern_str not in matched_patterns and compiled.search(line):
                matched_patterns.append(pattern_str)

    return matched_patterns
