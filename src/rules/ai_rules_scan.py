"""
Scan for AI assistant rule files in a repository (Cursor, Claude, Copilot, etc.).
Used by the repo-scanning flow to find *rules*.md, *guidelines*.md, *prompt*.md
and .cursor/rules/*.mdc, then optionally flag files that contain instruction keywords.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, cast
from src.core.utils.patterns import matches_any
import yaml

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
    "pr title",
    "pr description",
    "pr size",
    "pr approvals",
    "pr reviews",
    "pr comments",
    "pr files",
    "pr commits",
    "pr branches",
    "pr tags",
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

def is_relevant_push(payload: dict[str, Any]) -> bool:
    """
    Return True if we should run agentic scan for this push.
    Relevant when: push is to default branch, or any changed file matches AI rule path patterns.
    """
    ref = (payload.get("ref") or "").strip()
    repo = payload.get("repository") or {}
    default_branch = repo.get("default_branch") or "main"
    if ref == f"refs/heads/{default_branch}":
        return True
    for commit in payload.get("commits") or []:
        for path in (commit.get("added") or []) + (commit.get("modified") or []) + (commit.get("removed") or []):
            if path and path_matches_ai_rule_patterns(path):
                return True
    return False


def is_relevant_pr(payload: dict[str, Any]) -> bool:
    """
    Return True if we should run agentic scan for this PR.
    Relevant when: PR targets the repo's default branch.
    """
    pr = payload.get("pull_request") or {}
    base = pr.get("base") or {}
    default_branch = (
        (base.get("repo") or {}).get("default_branch")
        or (payload.get("repository") or {}).get("default_branch")
        or "main"
    )
    return base.get("ref") == default_branch

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
"""Type alias: async function that takes a file path and returns file content or None."""


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


# --- Deterministic extraction (parsing) ---

# Line prefixes that indicate a rule statement (strip prefix, use rest of line or next line).
EXTRACTOR_LINE_PREFIXES = [
    "cursor rule:",
    "claude:",
    "copilot:",
    "rule:",
    "guideline:",
    "instruction:",
] 

# Phrases that suggest a rule (include the whole line if it contains one of these).
EXTRACTOR_PHRASE_MARKERS = [
    "always use",
    "never commit",
    "must have",
    "should have",
    "required to",
    "prs must",
    "pull requests must",
    "every pr",
    "all prs",
]

def extract_rule_statements_from_markdown(content: str) -> list[str]:
    """
    Parse markdown content and return a list of rule-like statements (deterministic).
    Uses line prefixes (Cursor rule:, Claude:, etc.) and phrase markers (always use, never commit, etc.).
    """
    if not content or not content.strip():
        return []
    statements: list[str] = []
    seen: set[str] = set()
    lines = content.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 500:
            continue
        lower = stripped.lower()

        # 1) Line starts with a known prefix -> rest of line is the statement
        for prefix in EXTRACTOR_LINE_PREFIXES:
            if lower.startswith(prefix):
                rest = stripped[len(prefix) :].strip()
                if rest:
                    normalized = _normalize_statement(rest)
                    if normalized and normalized not in seen:
                        statements.append(rest)
                        seen.add(normalized)
                break
        else:
            # 2) Line contains a phrase marker -> treat whole line as statement
            for marker in EXTRACTOR_PHRASE_MARKERS:
                if marker in lower:
                    normalized = _normalize_statement(stripped)
                    if normalized and normalized not in seen:
                        statements.append(stripped)
                        seen.add(normalized)
                    break

    return statements


def _normalize_statement(s: str) -> str:
    """Normalize for deduplication: lowercase, collapse whitespace."""
    return " ".join(s.lower().split()) if s else ""


# --- Mapping layer (known phrase -> fixed YAML rule; no LLM) ---

# Each entry: (list of regex patterns or substrings to match, rule dict for .watchflow/rules.yaml)
# Match is case-insensitive. First match wins.
STATEMENT_TO_YAML_MAPPINGS: list[tuple[list[str], dict[str, Any]]] = [
    # PRs must have a linked issue
    (
        ["prs must have a linked issue", "pull requests must reference", "require linked issue", "must link an issue"],
        {
            "description": "PRs must reference an issue (e.g. Fixes #123)",
            "enabled": True,
            "severity": "medium",
            "event_types": ["pull_request"],
            "parameters": {"require_linked_issue": True},
        },
    ),
    # PR title pattern (conventional commits)
    (
        ["pr title must match", "use conventional commits", "title must follow convention"],
        {
            "description": "PR title must follow conventional commits (feat, fix, docs, etc.)",
            "enabled": True,
            "severity": "medium",
            "event_types": ["pull_request"],
            "parameters": {"title_pattern": "^feat|^fix|^docs|^style|^refactor|^test|^chore|^perf|^ci|^build|^revert"},
        },
    ),
    # Min description length
    (
        ["pr description must be", "description length", "min description", "meaningful pr description"],
        {
            "description": "PR description must be at least 50 characters",
            "enabled": True,
            "severity": "medium",
            "event_types": ["pull_request"],
            "parameters": {"min_description_length": 50},
        },
    ),
    # Max PR size
    (
        ["pr size", "max lines", "limit pr size", "keep prs small"],
        {
            "description": "PR must not exceed 500 lines changed",
            "enabled": True,
            "severity": "medium",
            "event_types": ["pull_request"],
            "parameters": {"max_lines": 500},
        },
    ),
    # Min approvals
    (
        ["min approvals", "at least one approval", "require approval", "prs need approval"],
        {
            "description": "PRs require at least one approval",
            "enabled": True,
            "severity": "high",
            "event_types": ["pull_request"],
            "parameters": {"min_approvals": 1},
        },
    ),
]

def try_map_statement_to_yaml(statement: str) -> dict[str, Any] | None:
    """
    If the statement matches a known phrase, return the corresponding rule dict (one entry for rules: []).
    Otherwise return None (caller should use feasibility agent).
    """
    if not statement or not statement.strip():
        return None
    lower = statement.lower()
    # for patterns, rule_dict in STATEMENT_TO_YAML_MAPPINGS:
    #     for p in patterns:
    #         if p in lower:
    #             return dict(rule_dict)
    # return None

    for patterns, rule_dict in STATEMENT_TO_YAML_MAPPINGS:
        for p in patterns:
            if p in lower:
                logger.debug(
                    "deterministic_mapping_matched statement=%r pattern=%r",
                    statement[:100],
                    p,
                )
                return dict(rule_dict)
    return None

# --- Translate pipeline (extract -> map or feasibility -> merge YAML) ---

async def translate_ai_rule_files_to_yaml(
    candidates: list[dict[str, Any]],
    *,
    get_feasibility_agent: Callable[[], Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
    """
    From candidate files (each with "path" and "content"), extract statements, translate to
    Watchflow rules (mapping layer first, then feasibility agent), merge into one YAML string.

    Returns:
        (rules_yaml_str, ambiguous_list, rule_sources)
        - rules_yaml_str: full "rules:\n  - ..." YAML.
        - ambiguous_list: [{"statement", "path", "reason"}] for statements that could not be translated.
        - rule_sources: one of "mapping" or "agent" per rule (same order as rules in rules_yaml).
    """
    all_rules: list[dict[str, Any]] = []
    rule_sources: list[str] = []
    ambiguous: list[dict[str, Any]] = []

    if get_feasibility_agent is None:
        from src.agents import get_agent
        def _default_agent():
            return get_agent("feasibility")
        get_feasibility_agent = _default_agent

    for cand in candidates:
        content = cand.get("content") if isinstance(cand.get("content"), str) else None
        path = cand.get("path") or ""
        if not content:
            continue
        statements = extract_rule_statements_from_markdown(content)
        for st in statements:
            # 1) Try deterministic mapping first
            mapped = try_map_statement_to_yaml(st)
            if mapped is not None:
                all_rules.append(mapped)
                rule_sources.append("mapping")
                continue
            # 2) Fall back to feasibility agent
            try:
                agent = get_feasibility_agent()
                result = await agent.execute(rule_description=st)
                data = result.data or {}
                is_feasible = data.get("is_feasible")
                yaml_content_raw = data.get("yaml_content")
                confidence = data.get("confidence_score", 0.0)
                if not result.success:
                    ambiguous.append({"statement": st, "path": path, "reason": result.message or "Agent failed"})
                elif not is_feasible or not yaml_content_raw:
                    ambiguous.append({"statement": st, "path": path, "reason": result.message or "Not feasible"})
                elif confidence < 0.5:
                    ambiguous.append(
                        {"statement": st, "path": path, "reason": f"Low confidence (confidence_score={confidence})"}
                    )
                else:
                    yaml_content = yaml_content_raw.strip()
                    parsed = yaml.safe_load(yaml_content)
                    if isinstance(parsed, dict) and "rules" in parsed and isinstance(parsed["rules"], list):
                        for r in parsed["rules"]:
                            if isinstance(r, dict):
                                all_rules.append(r)
                                rule_sources.append("agent")
                    else:
                        ambiguous.append({"statement": st, "path": path, "reason": "Feasibility agent returned invalid YAML"})
            except Exception as e:
                ambiguous.append({"statement": st, "path": path, "reason": str(e)})

    rules_yaml = yaml.dump({"rules": all_rules}, indent=2, sort_keys=False) if all_rules else "rules: []\n"
    return rules_yaml, ambiguous, rule_sources