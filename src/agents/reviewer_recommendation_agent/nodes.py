# File: src/agents/reviewer_recommendation_agent/nodes.py

import asyncio
import re
from typing import Any

import structlog

from src.agents.reviewer_recommendation_agent.models import (
    LLMReviewerRanking,
    RankedReviewer,
    RecommendationState,
    ReviewerCandidate,
    RiskSignal,
)
from src.integrations.github import github_client

logger = structlog.get_logger()

# Paths that indicate high-risk changes (fallback when no Watchflow rules exist)
_SENSITIVE_PATH_PATTERNS = [
    r"auth",
    r"billing",
    r"payment",
    r"secret",
    r"credential",
    r"password",
    r"config/prod",
    r"config/staging",
    r"\.env",
    r"migration",
    r"schema",
    r"infra",
    r"deploy",
    r"\.github/workflows",
    r"dockerfile",
    r"helm",
]

# Dependency file patterns (for dependency-change risk signal)
_DEPENDENCY_FILE_PATTERNS = [
    r"package\.json$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"requirements\.txt$",
    r"requirements.*\.txt$",
    r"Pipfile\.lock$",
    r"poetry\.lock$",
    r"pyproject\.toml$",
    r"go\.mod$",
    r"go\.sum$",
    r"Gemfile\.lock$",
    r"Cargo\.lock$",
    r"composer\.lock$",
]

# Patterns that indicate breaking changes (public API / migration)
_BREAKING_CHANGE_PATTERNS = [
    r"migration",
    r"openapi",
    r"swagger",
    r"api/v\d+",
    r"proto/",
    r"graphql/schema",
]

_SEVERITY_POINTS = {
    "critical": 5,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
    "error": 3,
    "warning": 2,
}

_RISK_THRESHOLDS = {
    "low": 3,
    "medium": 6,
    "high": 10,
    "critical": 999,
}


def _risk_level_from_score(score: int) -> str:
    if score <= _RISK_THRESHOLDS["low"]:
        return "low"
    elif score <= _RISK_THRESHOLDS["medium"]:
        return "medium"
    elif score <= _RISK_THRESHOLDS["high"]:
        return "high"
    return "critical"


def _parse_codeowners(content: str, changed_files: list[str]) -> dict[str, list[str]]:
    """
    Returns a mapping of file_path -> list of owner logins that own it
    based on a simple CODEOWNERS parse (last matching rule wins, like GitHub).
    Handles @org/team and @username entries; strips @ prefix.
    """
    rules: list[tuple[str, list[str]]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        owners = [o.lstrip("@").split("/")[-1] for o in parts[1:]]  # strip org/ prefix for teams
        rules.append((pattern, owners))

    ownership: dict[str, list[str]] = {}
    for file_path in changed_files:
        matched_owners: list[str] = []
        for pattern, owners in rules:
            # Convert glob-style to regex
            regex = re.escape(pattern).replace(r"\*", "[^/]*").replace(r"\*\*", ".*")
            if not regex.startswith("/"):
                regex = ".*" + regex
            if re.search(regex, "/" + file_path, re.IGNORECASE):
                matched_owners = owners  # last match wins
        if matched_owners:
            ownership[file_path] = matched_owners
    return ownership


def _match_watchflow_rules(rules: list[Any], changed_files: list[str]) -> list[dict[str, str]]:
    """
    Match loaded Watchflow Rule objects against changed files.
    Returns list of {description, severity} for rules whose parameters
    contain path patterns that match any changed file.
    """
    matched: list[dict[str, str]] = []
    for rule in rules:
        severity = rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity)
        params = rule.parameters if hasattr(rule, "parameters") else {}

        # Check path-based parameters
        path_patterns: list[str] = []
        for key in ("protected_paths", "sensitive_paths", "critical_owners", "file_patterns"):
            val = params.get(key)
            if isinstance(val, list):
                path_patterns.extend(val)
            elif isinstance(val, str):
                path_patterns.append(val)

        if path_patterns:
            for file_path in changed_files:
                for pattern in path_patterns:
                    regex = re.escape(pattern).replace(r"\*", ".*")
                    if re.search(regex, file_path, re.IGNORECASE):
                        matched.append({"description": rule.description, "severity": severity})
                        break
                else:
                    continue
                break
        else:
            # Non-path rules always match for pull_request event types
            event_types = [e.value if hasattr(e, "value") else str(e) for e in (rule.event_types or [])]
            if "pull_request" in event_types:
                matched.append({"description": rule.description, "severity": severity})

    return matched


async def fetch_pr_data(state: RecommendationState) -> RecommendationState:
    """Fetch PR metadata, changed files, CODEOWNERS, rules, commit experts, and review load."""
    repo = state.repo_full_name
    pr_number = state.pr_number
    installation_id = state.installation_id

    # PR details
    pr_data = await github_client.get_pull_request(repo, pr_number, installation_id)
    if not pr_data:
        state.error = f"Could not fetch PR #{pr_number}"
        return state

    state.pr_author = pr_data.get("user", {}).get("login", "")
    state.pr_additions = pr_data.get("additions", 0)
    state.pr_deletions = pr_data.get("deletions", 0)
    state.pr_commits_count = pr_data.get("commits", 0)
    state.pr_author_association = pr_data.get("author_association", "NONE")
    state.pr_title = pr_data.get("title", "")

    # Changed files
    files_data = await github_client.get_pr_files(repo, pr_number, installation_id)
    state.pr_files = [f.get("filename", "") for f in files_data if f.get("filename")]

    # CODEOWNERS
    codeowners = await github_client.get_codeowners(repo, installation_id)
    state.codeowners_content = codeowners.get("content")

    # Contributors (top 20 for scoring)
    contributors = await github_client.get_repository_contributors(repo, installation_id)
    state.contributors = contributors[:20]

    # Load Watchflow rules from .watchflow/rules.yaml and match against changed files
    try:
        from src.rules.loaders.github_loader import GitHubRuleLoader

        loader = GitHubRuleLoader(github_client)
        rules = await loader.get_rules(repo, installation_id)
        state.matched_rules = _match_watchflow_rules(rules, state.pr_files)
    except Exception as e:
        logger.info("watchflow_rules_not_loaded", reason=str(e))
        state.matched_rules = []

    # Expertise: fetch recent committers for the top 8 changed files (batched with semaphore)
    file_experts: dict[str, list[str]] = {}
    sem = asyncio.Semaphore(3)  # limit concurrent GitHub API calls to avoid rate limits

    async def _fetch_experts(fp: str) -> tuple[str, list[str]]:
        async with sem:
            commits = await github_client.get_commits_for_file(repo, fp, installation_id, limit=15)
        authors = []
        for c in commits:
            login = c.get("author", {}).get("login", "") if c.get("author") else ""
            if login and login not in authors:
                authors.append(login)
        return fp, authors

    results = await asyncio.gather(*[_fetch_experts(fp) for fp in state.pr_files[:8]], return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            logger.warning("file_expert_fetch_failed", error=str(res))
            continue
        fp, authors = res
        if authors:
            file_experts[fp] = authors
    state.file_experts = file_experts

    # Load balancing: fetch recent merged PRs and count review activity per reviewer
    try:
        recent_prs = await github_client.fetch_recent_pull_requests(repo, installation_id=installation_id, limit=20)
        reviewer_load: dict[str, int] = {}
        for pr in recent_prs[:15]:
            rpr_number = pr.get("pr_number") or pr.get("number")
            if not rpr_number:
                continue
            reviews = await github_client.get_pull_request_reviews(repo, rpr_number, installation_id)
            for review in reviews:
                reviewer_login = review.get("user", {}).get("login", "")
                if reviewer_login:
                    reviewer_load[reviewer_login] = reviewer_load.get(reviewer_login, 0) + 1
        state.reviewer_load = reviewer_load
    except Exception as e:
        logger.info("reviewer_load_fetch_failed", reason=str(e))
        state.reviewer_load = {}

    return state


async def assess_risk(state: RecommendationState) -> RecommendationState:
    """Calculate a deterministic risk score from PR signals + matched Watchflow rules."""
    if state.error:
        return state

    signals: list[RiskSignal] = []
    score = 0

    # --- Rules-first approach: use Watchflow rules as primary risk source ---
    # Hardcoded pattern matching is only used as fallback when no rules exist.
    has_rules = bool(state.matched_rules)

    if has_rules:
        rule_score = 0
        for rule_match in state.matched_rules:
            severity = rule_match.get("severity", "medium")
            rule_score += _SEVERITY_POINTS.get(severity, 1)
        # Cap at 10 to prevent one-sided dominance
        rule_score = min(rule_score, 10)
        descriptions = [f"`{r['description']}` ({r['severity']})" for r in state.matched_rules[:5]]
        signals.append(
            RiskSignal(
                label="Watchflow rule matches",
                description=f"{len(state.matched_rules)} rule(s) matched: {', '.join(descriptions)}",
                points=rule_score,
            )
        )
        score += rule_score

    # --- File count ---
    file_count = len(state.pr_files)
    if file_count > 50:
        signals.append(RiskSignal(label="Large changeset", description=f"{file_count} files changed", points=3))
        score += 3
    elif file_count > 20:
        signals.append(RiskSignal(label="Moderate changeset", description=f"{file_count} files changed", points=1))
        score += 1

    # --- Lines changed ---
    lines = state.pr_additions + state.pr_deletions
    if lines > 2000:
        signals.append(RiskSignal(label="Many lines changed", description=f"{lines} lines added/removed", points=2))
        score += 2
    elif lines > 500:
        signals.append(
            RiskSignal(label="Significant lines changed", description=f"{lines} lines added/removed", points=1)
        )
        score += 1

    # --- Fallback pattern matching (only when no Watchflow rules exist) ---
    if not has_rules:
        # Sensitive paths
        sensitive_hits: list[str] = []
        for file_path in state.pr_files:
            for pattern in _SENSITIVE_PATH_PATTERNS:
                if re.search(pattern, file_path, re.IGNORECASE):
                    sensitive_hits.append(file_path)
                    break

        if sensitive_hits:
            pts = min(len(sensitive_hits), 5)
            signals.append(
                RiskSignal(
                    label="Security-sensitive paths",
                    description=f"Changes to: {', '.join(sensitive_hits[:5])}",
                    points=pts,
                )
            )
            score += pts

        # Dependency changes
        dep_files = [
            f for f in state.pr_files if any(re.search(p, f, re.IGNORECASE) for p in _DEPENDENCY_FILE_PATTERNS)
        ]
        if dep_files:
            signals.append(
                RiskSignal(
                    label="Dependency changes",
                    description=f"Modified: {', '.join(dep_files[:3])}",
                    points=2,
                )
            )
            score += 2

        # Breaking changes (public API / migrations)
        breaking_hits = [
            f for f in state.pr_files if any(re.search(p, f, re.IGNORECASE) for p in _BREAKING_CHANGE_PATTERNS)
        ]
        if breaking_hits:
            signals.append(
                RiskSignal(
                    label="Potential breaking changes",
                    description=f"Modified: {', '.join(breaking_hits[:3])}",
                    points=3,
                )
            )
            score += 3

    # --- Test coverage ---
    has_test_files = any(re.search(r"test|spec", f, re.IGNORECASE) for f in state.pr_files)
    only_src_changes = any(re.search(r"\.(py|js|ts|go|java|rb)$", f) for f in state.pr_files)
    if only_src_changes and not has_test_files:
        signals.append(RiskSignal(label="No test coverage", description="Code changes without test files", points=2))
        score += 2

    # --- First-time contributor ---
    if state.pr_author_association in ("FIRST_TIME_CONTRIBUTOR", "NONE", "FIRST_TIMER"):
        signals.append(
            RiskSignal(label="First-time contributor", description=f"@{state.pr_author} is a new contributor", points=2)
        )
        score += 2

    # --- Revert detection ---
    if state.pr_title and re.search(r"^revert", state.pr_title, re.IGNORECASE):
        signals.append(RiskSignal(label="Revert PR", description="This PR reverts previous changes", points=2))
        score += 2

    state.risk_score = score
    state.risk_level = _risk_level_from_score(score)
    state.risk_signals = signals
    return state


async def recommend_reviewers(state: RecommendationState, llm: object) -> RecommendationState:
    """Score reviewer candidates with load balancing, then use LLM to rank and explain."""
    if state.error:
        return state

    candidates: dict[str, ReviewerCandidate] = {}

    def get_or_create(username: str) -> ReviewerCandidate:
        if username not in candidates:
            candidates[username] = ReviewerCandidate(username=username)
        return candidates[username]

    # CODEOWNERS ownership
    if state.codeowners_content:
        ownership_map = _parse_codeowners(state.codeowners_content, state.pr_files)
        for file_path, owners in ownership_map.items():
            for owner in owners:
                c = get_or_create(owner)
                c.score += 5
                reason = f"CODEOWNERS owner of `{file_path}`"
                if reason not in c.reasons:
                    c.reasons.append(reason)

    # Commit history expertise
    all_file_authors: dict[str, int] = {}  # login -> count of files they recently touched
    for file_path, authors in state.file_experts.items():
        for rank, login in enumerate(authors):
            if login == state.pr_author:
                continue  # skip PR author
            pts = max(3 - rank, 1)  # first author gets 3pts, second 2pts, rest 1pt
            c = get_or_create(login)
            c.score += pts
            all_file_authors[login] = all_file_authors.get(login, 0) + 1
            reason = f"Recent commits to `{file_path}`"
            if reason not in c.reasons:
                c.reasons.append(reason)

    # Boost candidates whose expertise matches high-severity rule matches
    if state.matched_rules:
        high_sev_rules = [r for r in state.matched_rules if r.get("severity") in ("critical", "high")]
        if high_sev_rules:
            for c in candidates.values():
                if c.score >= 5:
                    c.score += 2
                    c.reasons.append("Experienced reviewer (critical/high-severity rules matched)")

    # Overall contributors fallback (add any top contributors not yet in candidates)
    for contrib in state.contributors[:10]:
        login = contrib.get("login", "")
        if not login or login == state.pr_author:
            continue
        c = get_or_create(login)
        if not c.reasons:
            c.reasons.append(f"Top repository contributor ({contrib.get('contributions', 0)} commits)")

    # Remove PR author from candidates
    candidates.pop(state.pr_author, None)

    # --- Load balancing: penalize overloaded reviewers ---
    if state.reviewer_load:
        median_load = sorted(state.reviewer_load.values())[len(state.reviewer_load) // 2] if state.reviewer_load else 0
        for login, load_count in state.reviewer_load.items():
            if login in candidates and load_count > median_load + 2:
                c = candidates[login]
                penalty = min(load_count - median_load, 3)
                c.score = max(c.score - penalty, 0)
                c.reasons.append(f"Load penalty: {load_count} recent reviews (heavy queue)")

    # Sort by score, keep top 5
    sorted_candidates = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:5]

    # Compute ownership percentage per candidate
    total_files = len(state.pr_files) or 1
    for c in sorted_candidates:
        touched = all_file_authors.get(c.username, 0)
        c.ownership_pct = min(int(touched / total_files * 100), 100)

    state.candidates = sorted_candidates

    # LLM ranking for natural-language explanations (optional — graceful fallback)
    if not sorted_candidates:
        return state

    try:
        from langchain_core.messages import HumanMessage  # type: ignore

        candidate_summary = "\n".join(
            f"- @{c.username}: score={c.score}, reasons={c.reasons[:3]}" for c in sorted_candidates
        )
        rules_context = ""
        if state.matched_rules:
            rules_lines = [f"  - {r['description']} (severity: {r['severity']})" for r in state.matched_rules[:5]]
            rules_context = "\nMatched Watchflow rules:\n" + "\n".join(rules_lines) + "\n"

        prompt = (
            f"You are a code review assistant. A pull request in `{state.repo_full_name}` "
            f"changes {len(state.pr_files)} files with risk level `{state.risk_level}`.\n"
            f"{rules_context}\n"
            f"Candidate reviewers and their expertise signals:\n{candidate_summary}\n\n"
            "Rank them from best to worst fit and give a short one-sentence reason for each. "
            "Also write a one-line summary of the overall recommendation."
        )
        structured_llm = llm.with_structured_output(LLMReviewerRanking)  # type: ignore[union-attr]
        ranking: LLMReviewerRanking = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        state.llm_ranking = ranking
    except Exception as e:
        logger.warning("reviewer_llm_ranking_failed", error=str(e))
        # Fallback: build ranking from scored candidates without LLM
        state.llm_ranking = LLMReviewerRanking(
            ranked_reviewers=[
                RankedReviewer(username=c.username, reason="; ".join(c.reasons[:2]) or "top contributor")
                for c in sorted_candidates
            ],
            summary=f"Recommended {len(sorted_candidates)} reviewer(s) based on code ownership and commit history.",
        )

    return state
