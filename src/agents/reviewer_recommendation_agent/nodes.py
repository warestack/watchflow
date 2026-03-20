# File: src/agents/reviewer_recommendation_agent/nodes.py

import asyncio
import contextlib
import json
import re
from datetime import UTC, datetime
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

_REVIEWER_COUNT = {"low": 1, "medium": 2, "high": 2, "critical": 3}

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


def _parse_codeowners(content: str, changed_files: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Returns (individual_owners, team_owners) where:
    - individual_owners: file_path -> list of GitHub user logins  (@alice -> "alice")
    - team_owners:       file_path -> list of team slugs          (@org/frontend -> "frontend")

    Separating the two is required because GitHub's reviewer request API uses
    separate fields: `reviewers` for individual users and `team_reviewers` for teams.
    Last matching rule wins (GitHub CODEOWNERS behaviour).
    """
    rules: list[tuple[str, list[str], list[str]]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        individuals: list[str] = []
        teams: list[str] = []
        for o in parts[1:]:
            stripped = o.lstrip("@")
            if "/" in stripped:
                teams.append(stripped.split("/")[-1])  # team slug (e.g. "frontend")
            else:
                individuals.append(stripped)  # user login (e.g. "alice")
        rules.append((pattern, individuals, teams))

    individual_ownership: dict[str, list[str]] = {}
    team_ownership: dict[str, list[str]] = {}
    for file_path in changed_files:
        matched_individuals: list[str] = []
        matched_teams: list[str] = []
        for pattern, ind, tms in rules:
            regex = re.escape(pattern).replace(r"\*", "[^/]*").replace(r"\*\*", ".*")
            if not regex.startswith("/"):
                regex = ".*" + regex
            if re.search(regex, "/" + file_path, re.IGNORECASE):
                matched_individuals = ind
                matched_teams = tms
        if matched_individuals:
            individual_ownership[file_path] = matched_individuals
        if matched_teams:
            team_ownership[file_path] = matched_teams
    return individual_ownership, team_ownership


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
        # Rules without path patterns are process/compliance checks (e.g. linked issue,
        # max lines, title pattern). They do not indicate content-based file-change risk,
        # so they are intentionally excluded from risk scoring here.

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
    state.pr_base_branch = pr_data.get("base", {}).get("ref", "main")

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

    # Persist expertise profiles to .watchflow/expertise.json
    try:
        existing_content = await github_client.get_file_content(repo, ".watchflow/expertise.json", installation_id)
        existing_profiles: dict[str, Any] = {}
        if existing_content:
            with contextlib.suppress(json.JSONDecodeError):
                existing_profiles = json.loads(existing_content)

        contributors_data: dict[str, Any] = existing_profiles.get("contributors", {})
        for fp, authors in file_experts.items():
            for login in authors:
                if login not in contributors_data:
                    contributors_data[login] = {"file_paths": [], "commit_count": 0}
                profile = contributors_data[login]
                if fp not in profile.get("file_paths", []):
                    profile.setdefault("file_paths", []).append(fp)
                profile["commit_count"] = profile.get("commit_count", 0) + 1

        updated_profiles = {
            "updated_at": datetime.now(UTC).isoformat(),
            "contributors": contributors_data,
        }
        # Retry once on 409 Conflict (concurrent write race condition: re-read SHA and retry)
        write_result = await github_client.create_or_update_file(
            repo_full_name=repo,
            path=".watchflow/expertise.json",
            content=json.dumps(updated_profiles, indent=2),
            message="chore: update reviewer expertise profiles [watchflow]",
            branch=state.pr_base_branch,
            installation_id=installation_id,
        )
        if write_result is None:
            # First write failed (e.g. 409 conflict from concurrent PR) — re-read and retry once
            existing_content = await github_client.get_file_content(repo, ".watchflow/expertise.json", installation_id)
            if existing_content:
                with contextlib.suppress(json.JSONDecodeError):
                    merged = json.loads(existing_content)
                    for login, profile in contributors_data.items():
                        if login not in merged.get("contributors", {}):
                            merged.setdefault("contributors", {})[login] = profile
                    updated_profiles = {
                        "updated_at": datetime.now(UTC).isoformat(),
                        "contributors": merged["contributors"],
                    }
            await github_client.create_or_update_file(
                repo_full_name=repo,
                path=".watchflow/expertise.json",
                content=json.dumps(updated_profiles, indent=2),
                message="chore: update reviewer expertise profiles [watchflow]",
                branch=state.pr_base_branch,
                installation_id=installation_id,
            )
        state.expertise_profiles = contributors_data
    except Exception as e:
        logger.warning(
            "expertise_profile_update_failed",
            reason=str(e),
            hint="If branch protection is enabled on the base branch, grant the GitHub App a bypass rule for contents:write.",
        )
        state.expertise_profiles = {}

    # Load balancing + acceptance rate: fetch recent merged PRs and analyse review activity
    try:
        recent_prs = await github_client.fetch_recent_pull_requests(repo, installation_id=installation_id, limit=20)
        reviewer_load: dict[str, int] = {}
        reviewer_approvals: dict[str, int] = {}  # login -> APPROVED count
        reviewer_total: dict[str, int] = {}  # login -> APPROVED + CHANGES_REQUESTED count
        for pr in recent_prs[:15]:
            rpr_number = pr.get("pr_number") or pr.get("number")
            if not rpr_number:
                continue
            reviews = await github_client.get_pull_request_reviews(repo, rpr_number, installation_id)
            for review in reviews:
                reviewer_login = review.get("user", {}).get("login", "")
                review_state = review.get("state", "")
                if not reviewer_login:
                    continue
                reviewer_load[reviewer_login] = reviewer_load.get(reviewer_login, 0) + 1
                if review_state in ("APPROVED", "CHANGES_REQUESTED"):
                    reviewer_total[reviewer_login] = reviewer_total.get(reviewer_login, 0) + 1
                    if review_state == "APPROVED":
                        reviewer_approvals[reviewer_login] = reviewer_approvals.get(reviewer_login, 0) + 1
        state.reviewer_load = reviewer_load
        state.reviewer_acceptance_rates = {
            login: round(reviewer_approvals.get(login, 0) / count, 2)
            for login, count in reviewer_total.items()
            if count > 0
        }
    except Exception as e:
        logger.info("reviewer_load_fetch_failed", reason=str(e))
        state.reviewer_load = {}
        state.reviewer_acceptance_rates = {}

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
        total_rules = len(state.matched_rules)
        shown = state.matched_rules[:5]
        descriptions = [f"`{r['description']}` ({r['severity']})" for r in shown]
        suffix = f" (+{total_rules - 5} more)" if total_rules > 5 else ""
        signals.append(
            RiskSignal(
                label="Watchflow rule matches",
                description=f"{total_rules} rule(s) matched: {', '.join(descriptions)}{suffix}",
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

    # Active experts: set of logins with any recent commits to the changed files
    all_recent_committers: set[str] = {login for authors in state.file_experts.values() for login in authors}

    # CODEOWNERS ownership (with time-decay for stale owners)
    # Individual users and team slugs are scored separately so they can be
    # passed to the correct GitHub API fields when requesting reviewers.
    if state.codeowners_content:
        individual_owners, team_owners = _parse_codeowners(state.codeowners_content, state.pr_files)

        # Collect all team slugs for later use in reviewer assignment
        all_team_slugs: set[str] = {slug for slugs in team_owners.values() for slug in slugs}
        state.codeowners_team_slugs = list(all_team_slugs)

        for file_path, owners in individual_owners.items():
            for owner in owners:
                c = get_or_create(owner)
                if owner in all_recent_committers:
                    c.score += 5
                    reason = f"CODEOWNERS owner of `{file_path}`"
                else:
                    c.score += 2
                    reason = f"CODEOWNERS owner of `{file_path}` (no recent activity)"
                if reason not in c.reasons:
                    c.reasons.append(reason)

        for file_path, slugs in team_owners.items():
            for slug in slugs:
                c = get_or_create(slug)
                c.score += 4  # slightly below individual owner; teams are broad
                reason = f"CODEOWNERS team owner of `{file_path}`"
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

    # Boost candidates with accumulated expertise from .watchflow/expertise.json
    # (cross-PR historical expertise stored on previous runs)
    if state.expertise_profiles:
        for login, profile in state.expertise_profiles.items():
            if login == state.pr_author:
                continue
            stored_paths: list[str] = profile.get("file_paths", [])
            overlap = [fp for fp in state.pr_files if fp in stored_paths]
            if overlap:
                c = get_or_create(login)
                pts = min(len(overlap), 3)  # cap at 3 bonus points
                c.score += pts
                reason = f"Historical expertise in {len(overlap)} changed file(s) (from expertise profiles)"
                if reason not in c.reasons:
                    c.reasons.append(reason)

    # Rule-inferred ownership: when no CODEOWNERS, use matched rule path patterns
    # to identify implicit owners from commit history
    if not state.codeowners_content and state.matched_rules:
        for rule in state.matched_rules:
            severity = rule.get("severity", "medium")
            if severity not in ("critical", "high"):
                continue
            # Find changed files that triggered this rule (via matched path patterns)
            rule_experts: list[str] = []
            for fp in state.pr_files:
                if fp in state.file_experts:
                    for login in state.file_experts[fp]:
                        if login != state.pr_author and login not in rule_experts:
                            rule_experts.append(login)
            for rank, login in enumerate(rule_experts[:3]):
                c = get_or_create(login)
                pts = 4 - rank  # +4, +3, +2 — similar to CODEOWNERS but slightly less
                c.score += pts
                reason = f"Inferred owner for `{rule['description']}` rule path ({severity} severity)"
                if reason not in c.reasons:
                    c.reasons.append(reason)

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

    # --- Acceptance rate boost: reward reviewers with high approval rates ---
    for login, rate in state.reviewer_acceptance_rates.items():
        if login not in candidates:
            continue
        c = candidates[login]
        pct = int(rate * 100)
        if rate >= 0.8:
            c.score += 2
            c.reasons.append(f"High review acceptance rate ({pct}%)")
        elif rate >= 0.6:
            c.score += 1
            c.reasons.append(f"Good review acceptance rate ({pct}%)")

    # Risk-based reviewer count: low→1, medium→2, high/critical→3
    reviewer_count = _REVIEWER_COUNT.get(state.risk_level, 2)
    sorted_candidates = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:reviewer_count]

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
            "Rank them from best to worst fit and write a short one-sentence reason for each. "
            "The reason MUST reference the specific signals listed above (e.g. 'Recent commits to `<file>`', "
            "'CODEOWNERS owner of `<file>`', 'Inferred owner for <rule>'). "
            "Do NOT use generic phrases like 'top contributor' or 'direct commit experience' — "
            "always cite the actual file name or rule from the signals. "
            "Also write a one-line summary of the overall recommendation that mentions commit history "
            "if the primary signal is commit-based."
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
