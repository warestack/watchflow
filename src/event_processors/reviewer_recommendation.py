import asyncio
import logging
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from os.path import splitext
from typing import Any

import yaml

from src.core.models import EventType
from src.core.utils.caching import AsyncCache
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.event_processors.risk_assessment.signals import generate_risk_assessment
from src.presentation import github_formatter
from src.rules.loaders.github_loader import RulesFileNotFoundError
from src.rules.models import Rule
from src.rules.utils.codeowners import CodeOwnersParser
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)

# Cache for reviewer recommendation results (30-minute TTL)
_reviewer_cache = AsyncCache(maxsize=256, ttl=1800)

# Cache for repo-level review load data (15-minute TTL)
_load_cache = AsyncCache(maxsize=128, ttl=900)

_REVIEWER_COUNT = {"low": 1, "medium": 2, "high": 2, "critical": 3}

_LABEL_COLORS: dict[str, tuple[str, str]] = {
    "watchflow:risk-low": ("0e8a16", "Watchflow: low risk PR"),
    "watchflow:risk-medium": ("fbca04", "Watchflow: medium risk PR"),
    "watchflow:risk-high": ("d93f0b", "Watchflow: high risk PR"),
    "watchflow:risk-critical": ("7b2d8b", "Watchflow: critical risk PR"),
    "watchflow:reviewer-recommendation": ("1d76db", "Watchflow: reviewer recommendation applied"),
}

# Maps risk signal categories (from generate_risk_assessment) to the rule parameter
# keys that produce them.  Used to filter matched_rules down to only those that
# caused a fired signal — keeps reasoning grounded in the actual /risk evaluation.
_SIGNAL_CATEGORY_TO_PARAMS: dict[str, frozenset[str]] = {
    "size-risk": frozenset({"max_lines", "max_file_size_mb"}),
    "critical-path": frozenset({"critical_owners"}),
    "test-coverage": frozenset({"require_tests"}),
    "security-sensitive": frozenset({"security_patterns"}),
}
# Rules without any of these params are "leftover" rules evaluated by evaluate_rule_matches.
_PROCESSED_PARAMS: frozenset[str] = frozenset().union(*_SIGNAL_CATEGORY_TO_PARAMS.values())

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".tf": "terraform",
    ".sql": "sql",
    ".sh": "shell",
}


def _match_rules_to_files(
    rules: list[Rule],
    changed_filenames: list[str],
) -> tuple[list[Rule], dict[str, list[str]]]:
    """Return rules relevant to this PR, plus per-rule matched filenames.

    - Rules with ``file_patterns`` match only when at least one changed file
      satisfies a pattern.
    - Rules without ``file_patterns`` are treated as global and always match —
      this preserves the original behaviour and ensures that repo-wide rules
      (e.g. ``critical_owners`` designations that apply to every PR) are not
      silently dropped from reviewer context.

    Returns:
        matched: list of matched Rule objects
        per_rule_files: dict mapping rule description → list of matched file paths
                        (only populated for rules that have file_patterns)
    """
    import fnmatch

    matched: list[Rule] = []
    per_rule_files: dict[str, list[str]] = {}

    for rule in rules:
        if EventType.PULL_REQUEST not in rule.event_types:
            continue
        if not rule.enabled:
            continue

        file_patterns = rule.parameters.get("file_patterns", [])
        if not file_patterns:
            # Global rule — applies to every PR regardless of changed files
            matched.append(rule)
            continue

        rule_matched: list[str] = []
        for pattern in file_patterns:
            for f in changed_filenames:
                if fnmatch.fnmatch(f, pattern) and f not in rule_matched:
                    rule_matched.append(f)
        if rule_matched:
            matched.append(rule)
            per_rule_files[rule.description] = rule_matched

    return matched, per_rule_files


def _get_rule_path_if_files_match(rule: Rule, changed_filenames: list[str]) -> str | None:
    """Return the rule's file path pattern if any changed files match it, else None.

    Handles both ``file_patterns`` (list) and ``pattern`` + ``condition_type`` (string).
    Returns the pattern string itself (e.g. "app/payments/*") for use in reasoning lines.
    """
    import fnmatch
    import re

    file_patterns = rule.parameters.get("file_patterns") or []
    if file_patterns:
        for pat in file_patterns:
            for f in changed_filenames:
                if fnmatch.fnmatch(f, pat):
                    return pat
        return None

    # FilePatternCondition-style: single pattern + condition_type
    pattern = rule.parameters.get("pattern")
    condition_type = rule.parameters.get("condition_type", "")
    if pattern and condition_type in ("files_match_pattern", "files_not_match_pattern"):
        regex = "^" + pattern.replace(".", "\\.").replace("*", ".*").replace("?", ".") + "$"
        for f in changed_filenames:
            if re.match(regex, f):
                return pattern

    return None


async def _fetch_review_load(
    github_client: Any,
    repo: str,
    installation_id: int,
    sem: asyncio.Semaphore,
) -> dict[str, int]:
    """Fetch pending review counts per user from open PRs (1 API call, cached).

    Returns a dict mapping login -> number of open PRs where they are a requested reviewer.
    """
    cache_key = f"load:{repo}"
    cached = _load_cache.get(cache_key)
    if cached is not None:
        return cached

    async with sem:
        open_prs = await github_client.list_pull_requests(repo, installation_id, state="open", per_page=100)

    load: Counter[str] = Counter()
    for pr in open_prs:
        for reviewer in pr.get("requested_reviewers", []):
            login = reviewer.get("login")
            if login:
                load[login] += 1

    result = dict(load)
    _load_cache.set(cache_key, result)
    return result


def _compute_load_penalty(
    candidate_scores: dict[str, float],
    review_load: dict[str, int],
) -> dict[str, float]:
    """Compute load penalties based on median pending review count.

    Candidates with pending reviews > median + 2 get penalized up to 5 points.
    """
    candidate_loads = {u: review_load.get(u, 0) for u in candidate_scores if u in review_load}
    if len(candidate_loads) < 2:
        return {}

    sorted_counts = sorted(candidate_loads.values())
    mid = len(sorted_counts) // 2
    median = (sorted_counts[mid - 1] + sorted_counts[mid]) / 2 if len(sorted_counts) % 2 == 0 else sorted_counts[mid]

    threshold = median + 2
    penalties: dict[str, float] = {}
    for user, pending in candidate_loads.items():
        if pending > threshold:
            penalties[user] = min(pending - threshold, 5)
    return penalties


def _reviewer_count_for_risk(risk_level: str) -> int:
    """Return the number of reviewers to suggest based on risk level."""
    return _REVIEWER_COUNT.get(risk_level, 2)


async def _load_expertise_profiles(
    github_client: Any,
    repo: str,
    installation_id: int,
) -> dict[str, Any]:
    """Read .watchflow/expertise.yaml and return its contributors dict (or {} on any error)."""
    try:
        content = await github_client.get_file_content(repo, ".watchflow/expertise.yaml", installation_id)
        if not content:
            return {}
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data.get("contributors", {}) or {}
    except Exception:
        logger.debug("Could not load expertise profiles (file may not exist yet)")
    return {}


async def _save_expertise_profiles(
    github_client: Any,
    repo: str,
    installation_id: int,
    profiles: dict[str, Any],
    base_branch: str,
) -> None:
    """Write updated expertise profiles to .watchflow/expertise.yaml (fire-and-forget)."""
    try:
        # Re-read to merge with any concurrent updates
        existing = await _load_expertise_profiles(github_client, repo, installation_id)
        merged: dict[str, Any] = {**existing}
        for login, data in profiles.items():
            if login not in merged:
                merged[login] = data
            else:
                existing_langs = set(merged[login].get("languages", []))
                new_langs = set(data.get("languages", []))
                merged[login]["languages"] = sorted(existing_langs | new_langs)

                merged[login]["commit_count"] = merged[login].get("commit_count", 0) + data.get("commit_count", 0)
                existing_path_counts = _normalize_path_commit_counts(merged[login].get("path_commit_counts", {}))
                new_path_counts = _normalize_path_commit_counts(data.get("path_commit_counts", {}))
                for path, count in new_path_counts.items():
                    existing_path_counts[path] = existing_path_counts.get(path, 0) + count
                merged[login]["path_commit_counts"] = existing_path_counts
                # Keep the most recent last_active
                existing_active = merged[login].get("last_active", "")
                new_active = data.get("last_active", "")
                if new_active > existing_active:
                    merged[login]["last_active"] = new_active

        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "contributors": merged,
        }
        content = yaml.dump(payload, default_flow_style=False, sort_keys=True)
        await github_client.create_or_update_file(
            repo_full_name=repo,
            path=".watchflow/expertise.yaml",
            content=content,
            message="chore: update reviewer expertise profiles [watchflow] [skip ci]",
            branch=base_branch,
            installation_id=installation_id,
        )
        logger.info(f"Expertise profiles saved for {repo}")
    except Exception as e:
        logger.warning(f"Could not save expertise profiles for {repo}: {e}")


def _update_expertise_from_commits(
    existing: dict[str, Any],
    commit_results: list[Any],
    sampled_paths: list[str],
    now: datetime,
) -> dict[str, Any]:
    """Build updated expertise profiles from commit data, merging with existing."""
    updates: dict[str, Any] = {}

    for idx, result in enumerate(commit_results):
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        path = sampled_paths[idx] if idx < len(sampled_paths) else ""
        ext = splitext(path)[1].lower()
        language = _EXT_TO_LANGUAGE.get(ext)

        for commit_data in result:
            author_login = (commit_data.get("author") or {}).get("login")
            if not author_login:
                continue

            date_str = commit_data.get("commit", {}).get("author", {}).get("date", "")
            last_active = ""
            if date_str:
                try:
                    commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    last_active = commit_date.date().isoformat()
                except (ValueError, TypeError):
                    pass

            if author_login not in updates:
                updates[author_login] = {
                    "languages": set(),
                    "commit_count": 0,
                    "last_active": last_active,
                    "path_commit_counts": {},
                }
            path_counts = updates[author_login].setdefault("path_commit_counts", {})
            path_counts[path] = path_counts.get(path, 0) + 1
            if language:
                updates[author_login]["languages"].add(language)
            updates[author_login]["commit_count"] += 1
            if last_active > updates[author_login].get("last_active", ""):
                updates[author_login]["last_active"] = last_active

    # Convert sets to sorted lists and merge with existing
    result_profiles: dict[str, Any] = {}
    for login, data in updates.items():
        existing_profile = existing.get(login, {})
        result_profiles[login] = {
            "languages": sorted(data["languages"]),
            "commit_count": data["commit_count"],
            "last_active": data["last_active"],
            "reviews": _extract_profile_reviews(existing_profile),
            "path_commit_counts": _normalize_path_commit_counts(data.get("path_commit_counts", {})),
        }

    return result_profiles


def _empty_reviews() -> dict[str, int]:
    return {"total": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}


def _normalize_reviews(raw: Any) -> dict[str, int]:
    """Normalize review risk-bucket counts from the reviews object."""
    normalized = _empty_reviews()
    if isinstance(raw, Mapping):
        for risk in normalized:
            try:
                value = int(raw.get(risk, 0))
            except (TypeError, ValueError):
                value = 0
            normalized[risk] = max(value, 0)
    return normalized


def _extract_profile_reviews(profile: dict[str, Any]) -> dict[str, int]:
    """Get normalized review buckets from profile."""
    return _normalize_reviews(profile.get("reviews", {}))


def _normalize_path_commit_counts(raw: Any) -> dict[str, int]:
    """Normalize path_commit_counts to {path: non-negative int}."""
    if not isinstance(raw, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for path, value in raw.items():
        if not isinstance(path, str) or not path:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            normalized[path] = count
    return normalized


async def _fetch_review_history(
    github_client: Any,
    repo: str,
    installation_id: int,
    sem: asyncio.Semaphore,
    existing_profiles: dict[str, Any],
) -> dict[str, Any]:
    """Fetch reviews for up to 5 recent merged PRs, update expertise profiles.

    Skips the fetch if profiles were updated within the last 7 days.

    Reviews are bucketed by each past PR's risk label:
    watchflow:risk-low|medium|high|critical.
    """
    # Check freshness — skip if profiles were updated within 7 days
    try:
        content = await github_client.get_file_content(repo, ".watchflow/expertise.yaml", installation_id)
        if content:
            data = yaml.safe_load(content) or {}
            updated_at_str = data.get("updated_at", "")
            if updated_at_str:
                updated_at = datetime.fromisoformat(updated_at_str)
                if (datetime.now(UTC) - updated_at).days < 7:
                    logger.debug("Expertise profiles are fresh (<7d); skipping review history fetch")
                    return existing_profiles
    except Exception:
        pass

    try:
        async with sem:
            recent_prs = await github_client.list_pull_requests(repo, installation_id, state="closed", per_page=10)
        merged_prs = [pr for pr in recent_prs if pr.get("merged_at")][:5]

        review_tasks = [
            github_client.get_pull_request_reviews(repo, pr["number"], installation_id) for pr in merged_prs
        ]
        reviews_per_pr = await asyncio.gather(*review_tasks, return_exceptions=True)

        updated = dict(existing_profiles)
        for pr, reviews in zip(merged_prs, reviews_per_pr, strict=False):
            if isinstance(reviews, Exception) or not isinstance(reviews, list):
                continue
            pr_labels = {label.get("name", "") for label in (pr.get("labels") or [])}
            pr_risk: str | None = None
            for risk in ("critical", "high", "medium", "low"):
                if f"watchflow:risk-{risk}" in pr_labels:
                    pr_risk = risk
                    break
            for review in reviews:
                reviewer = (review.get("user") or {}).get("login")
                if not reviewer:
                    continue
                if review.get("state", "") not in ("APPROVED", "CHANGES_REQUESTED"):
                    continue
                if reviewer not in updated:
                    updated[reviewer] = {
                        "languages": [],
                        "commit_count": 0,
                        "last_active": "",
                        "path_commit_counts": {},
                        "reviews": _empty_reviews(),
                    }
                review_buckets = _extract_profile_reviews(updated[reviewer])
                review_buckets["total"] = review_buckets.get("total", 0) + 1
                if pr_risk:
                    review_buckets[pr_risk] = review_buckets.get(pr_risk, 0) + 1
                updated[reviewer]["reviews"] = review_buckets

        return updated
    except Exception as e:
        logger.warning(f"Could not fetch review history for {repo}: {e}")
        return existing_profiles


def _extract_critical_owners(matched_rules: list[Rule]) -> set[str]:
    """Return the set of usernames listed as critical_owners across all matched rules."""
    owners: set[str] = set()
    for rule in matched_rules:
        for username in rule.parameters.get("critical_owners", []):
            owners.add(username.lstrip("@"))
    return owners


def _build_reviewer_rule_mentions(matched_rules: list[Rule]) -> dict[str, list[str]]:
    """Return a map of login -> list of rule descriptions where they appear as critical_owners."""
    mentions: dict[str, list[str]] = {}
    for rule in matched_rules:
        for username in rule.parameters.get("critical_owners", []):
            login = username.lstrip("@")
            mentions.setdefault(login, []).append(rule.description)
    return mentions


class ReviewerRecommendationProcessor(BaseEventProcessor):
    """Processor that recommends reviewers for a PR based on rules, CODEOWNERS, and commit history."""

    def __init__(self) -> None:
        super().__init__()
        from src.agents import get_agent

        self.reasoning_agent = get_agent("reviewer_reasoning")

    def get_event_type(self) -> str:
        return "reviewer_recommendation"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        api_calls = 0
        # Semaphore to cap concurrent GitHub API calls
        sem = asyncio.Semaphore(5)

        async def _limited(coro):  # type: ignore[no-untyped-def]
            async with sem:
                return await coro

        try:
            payload = task.payload
            repo = payload.get("repository", {}).get("full_name", "")
            installation_id = payload.get("installation", {}).get("id")
            pr_number = payload.get("issue", {}).get("number") or payload.get("pull_request", {}).get("number")
            pr_author = (
                payload.get("issue", {}).get("user", {}).get("login")
                or payload.get("pull_request", {}).get("user", {}).get("login")
                or ""
            )
            force = payload.get("reviewers_force", False)

            if not repo or not installation_id or not pr_number:
                return ProcessingResult(
                    success=False,
                    violations=[],
                    api_calls_made=0,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Missing repo, installation_id, or PR number",
                )

            logger.info(f"🔍 Generating reviewer recommendations for {repo}#{pr_number}")

            # Check cache (unless --force)
            cache_key = f"reviewer:{repo}#{pr_number}"
            if force:
                _reviewer_cache.invalidate(cache_key)
                logger.info(f"🔄 --force: invalidated cache for {cache_key}")
            else:
                cached = _reviewer_cache.get(cache_key)
                if cached is not None:
                    logger.info(f"📋 Returning cached reviewer recommendation for {cache_key}")
                    comment = cached["comment"]
                    labels = cached["labels"]
                    await self.github_client.create_pull_request_comment(repo, pr_number, comment, installation_id)
                    api_calls += 1
                    applied = await self.github_client.add_labels_to_issue(repo, pr_number, labels, installation_id)
                    api_calls += 1
                    if not applied:
                        logger.warning(f"Failed to apply labels {labels} to {repo}#{pr_number}")
                    processing_time = int((time.time() - start_time) * 1000)
                    return ProcessingResult(
                        success=True,
                        violations=[],
                        api_calls_made=api_calls,
                        processing_time_ms=processing_time,
                    )

            # 1. Fetch PR files, PR details, review load, and expertise profiles in parallel
            pr_files_coro = _limited(self.github_client.get_pull_request_files(repo, pr_number, installation_id))
            pr_details_coro = _limited(self.github_client.get_pull_request(repo, pr_number, installation_id))
            load_coro = _fetch_review_load(self.github_client, repo, installation_id, sem)
            expertise_coro = _load_expertise_profiles(self.github_client, repo, installation_id)
            changed_files, pr_data, review_load, expertise_profiles = await asyncio.gather(
                pr_files_coro, pr_details_coro, load_coro, expertise_coro
            )
            api_calls += 3  # files, PR details, load (expertise reads file count separately)

            changed_filenames = [f.get("filename", "") for f in changed_files if f.get("filename")]
            # Prefer PR author from PR details if available
            if pr_data and pr_data.get("user", {}).get("login"):
                pr_author = pr_data["user"]["login"]

            if not changed_filenames:
                await self.github_client.create_pull_request_comment(
                    repo,
                    pr_number,
                    "## Watchflow: Reviewer Recommendation\n\nNo changed files detected — cannot generate recommendations.",
                    installation_id,
                )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            # 2. Load rules and match against changed files
            rules: list[Rule] = []
            try:
                loaded = await self.rule_provider.get_rules(repo, installation_id)
                rules = loaded if loaded else []
                api_calls += 1
            except RulesFileNotFoundError:
                logger.info("No rules.yaml found — proceeding without rule matching")

            matched_rules, per_rule_files = _match_rules_to_files(rules, changed_filenames)
            # Rules with a file path pattern that matches at least one changed file: (rule, pattern)
            path_matched_rules: list[tuple[Rule, str]] = [
                (r, pat) for r in matched_rules if (pat := _get_rule_path_if_files_match(r, changed_filenames))
            ]

            # 3. Fetch CODEOWNERS
            codeowners_content: str | None = None
            codeowners_paths = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"]
            for path in codeowners_paths:
                try:
                    content = await self.github_client.get_file_content(repo, path, installation_id)
                    api_calls += 1
                    if content:
                        codeowners_content = content
                        break
                except Exception:
                    continue

            # 4. Build owner map from CODEOWNERS.
            # Individual owners (@user) feed the scoring pipeline directly.
            # Team owners (@org/team) are expanded to their members (who also enter scoring)
            # and also shown as a team in the comment so the whole team is notified.
            codeowner_candidates: dict[str, int] = defaultdict(int)
            team_codeowner_candidates: dict[str, int] = defaultdict(int)
            if codeowners_content:
                parser = CodeOwnersParser(codeowners_content)
                for filename in changed_filenames:
                    owners = parser.get_owners_for_file(filename)
                    for owner in owners:
                        if "/" in owner:
                            team_codeowner_candidates[owner] += 1
                        else:
                            codeowner_candidates[owner] += 1

            # Resolve team CODEOWNERS to individual members and add them to scoring.
            # Members inherit the same file-count boost as if they were listed directly.
            # Org is parsed from the team string itself (@org/team-slug) so cross-org
            # entries like @other-org/platform resolve correctly.
            if team_codeowner_candidates:
                team_member_tasks = []
                teams_ordered = list(team_codeowner_candidates)
                for team in teams_ordered:
                    slug = team.lstrip("@")
                    org, _, team_slug = slug.partition("/")
                    team_member_tasks.append(self.github_client.get_team_members(org, team_slug, installation_id))
                team_member_results = await asyncio.gather(*team_member_tasks, return_exceptions=True)
                for team, members_result in zip(teams_ordered, team_member_results, strict=False):
                    if isinstance(members_result, Exception) or not isinstance(members_result, list):
                        continue
                    file_count = team_codeowner_candidates[team]
                    for member in members_result:
                        codeowner_candidates[member] += file_count

            # 5. Build expertise profile from commit history with recency weighting
            directories = list({f.rsplit("/", 1)[0] if "/" in f else "." for f in changed_filenames})
            pr_languages = {
                _EXT_TO_LANGUAGE[splitext(f)[1].lower()]
                for f in changed_filenames
                if splitext(f)[1].lower() in _EXT_TO_LANGUAGE
            }
            # Directories with depth >= 2 for meaningful matching (skip bare "src", ".")
            changed_dirs = {f.rsplit("/", 1)[0] for f in changed_filenames if "/" in f and f.count("/") >= 1}
            sampled_paths = changed_filenames[:5] + directories[:5]
            sampled_paths = list(dict.fromkeys(sampled_paths))[:10]

            commit_author_scores: Counter[str] = Counter()
            commit_author_counts: Counter[str] = Counter()

            commit_tasks = [
                _limited(self.github_client.get_commits(repo, installation_id, path=path, per_page=20))
                for path in sampled_paths
            ]
            commit_results = await asyncio.gather(*commit_tasks, return_exceptions=True)
            api_calls += len(sampled_paths)

            now = datetime.now(UTC)
            for _idx, result in enumerate(commit_results):
                if isinstance(result, Exception):
                    continue
                for commit_data in result:
                    author_login = (commit_data.get("author") or {}).get("login")
                    if not author_login:
                        continue
                    commit_author_counts[author_login] += 1

                    # Recency weighting
                    date_str = commit_data.get("commit", {}).get("author", {}).get("date", "")
                    weight = 1
                    if date_str:
                        try:
                            commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                            age_days = (now - commit_date).days
                            weight = 2 if age_days <= 30 else (1 if age_days <= 90 else 0)
                        except (ValueError, TypeError):
                            weight = 1
                    commit_author_scores[author_login] += weight

            # 6. Compute risk signals using canonical evaluators
            risk_result = await generate_risk_assessment(repo, installation_id, pr_data, changed_files)
            risk_level: str = risk_result.level
            risk_descriptions = [s.description for s in risk_result.signals]
            risk_reason = f"{len(risk_result.signals)} signal(s) — max severity: {risk_level}"

            # Fetch review history (may be skipped if fresh)
            expertise_profiles = await _fetch_review_history(
                self.github_client, repo, installation_id, sem, expertise_profiles
            )

            # 7. Rank candidates — 3-tier approach
            candidate_scores: dict[str, float] = defaultdict(float)
            candidate_reasons: dict[str, str] = {}

            # Tier 0: CODEOWNERS (highest base weight)
            for user, file_count in codeowner_candidates.items():
                candidate_scores[user] += file_count * 5
                pct = int(file_count / max(len(changed_filenames), 1) * 100)
                candidate_reasons[user] = f"mentioned in CODEOWNERS ({pct}% of changed files)"

            # Tier 0: Commit history (recency-weighted)
            for user, score in commit_author_scores.items():
                candidate_scores[user] += score
                count = commit_author_counts.get(user, 0)
                if user not in candidate_reasons:
                    candidate_reasons[user] = f"{count} recent commits on changed paths"
                else:
                    candidate_reasons[user] += f", {count} recent commits on changed paths"

            # Tier 1: Expertise from expertise.yaml (file, directory, language, commit_count)
            for login, profile in expertise_profiles.items():
                if login == pr_author:
                    continue
                extras: list[str] = []

                # File overlap — path_commit_counts keys are the profile's known paths
                profile_path_counts = _normalize_path_commit_counts(profile.get("path_commit_counts", {}))
                profile_paths = set(profile_path_counts.keys())
                exact_overlap = sum(1 for fp in changed_filenames if fp in profile_paths)
                if exact_overlap:
                    candidate_scores[login] += min(exact_overlap, 3)
                    extras.append(f"worked on {exact_overlap} of the changed files (expertise.yaml)")

                # Per-path commit strength (distinguishes deep ownership vs one-off touches)
                matched_path_commits = sum(profile_path_counts.get(fp, 0) for fp in changed_filenames)
                if matched_path_commits > 0:
                    strength_bonus = 1 if matched_path_commits <= 2 else (2 if matched_path_commits <= 6 else 3)
                    candidate_scores[login] += strength_bonus
                    extras.append(f"{matched_path_commits} commits on changed files (expertise.yaml)")

                # Directory overlap
                profile_dirs = {fp.rsplit("/", 1)[0] for fp in profile_paths if "/" in fp}
                dir_overlap = changed_dirs & profile_dirs
                dir_score = min(len(dir_overlap), 2)
                if dir_score > 0:
                    candidate_scores[login] += dir_score
                    dir_names = ", ".join(sorted(dir_overlap)[:3])
                    extras.append(f"expertise in {dir_names} (expertise.yaml)")

                # Language overlap
                reviewer_langs = set(profile.get("languages", []))
                lang_overlap = pr_languages & reviewer_langs
                if lang_overlap:
                    candidate_scores[login] += min(len(lang_overlap), 2)
                    extras.append(f"{', '.join(sorted(lang_overlap))} expertise (expertise.yaml)")

                # Stored commit_count tiebreaker
                stored_commits = profile.get("commit_count", 0)
                if stored_commits >= 20:
                    candidate_scores[login] += 1
                    extras.append(f"{stored_commits}+ commits in the repo (expertise.yaml)")

                if extras:
                    extra_str = ", ".join(extras)
                    if login not in candidate_reasons:
                        candidate_reasons[login] = extra_str
                    else:
                        candidate_reasons[login] += f", {extra_str}"

            # Tier 2: Review history expertise (domain reviewer signal)
            for login, profile in expertise_profiles.items():
                if login == pr_author:
                    continue
                extras = []

                review_buckets = _extract_profile_reviews(profile)
                high_risk = review_buckets.get("high", 0) + review_buckets.get("critical", 0)
                if high_risk > 0:
                    candidate_scores[login] += min(high_risk, 3)
                    extras.append(f"reviewed {high_risk} high-risk PRs")

                review_count = int(review_buckets.get("total", 0))
                if review_count >= 5:
                    bonus = min(review_count // 5, 2)
                    candidate_scores[login] += bonus
                    extras.append(f"{review_count} PRs reviewed in this repo")

                if extras:
                    extra_str = ", ".join(extras)
                    if login not in candidate_reasons:
                        candidate_reasons[login] = extra_str
                    else:
                        candidate_reasons[login] += f", {extra_str}"

            # Inactivity penalty (applied to existing candidates only)
            today = now.date()
            for login, profile in expertise_profiles.items():
                if login == pr_author or login not in candidate_scores:
                    continue
                last_active_str = profile.get("last_active", "")
                if not last_active_str:
                    continue
                try:
                    days_inactive = (today - date.fromisoformat(last_active_str)).days
                except (ValueError, TypeError):
                    continue
                if days_inactive > 365:
                    candidate_scores[login] -= 2
                    candidate_reasons[login] = candidate_reasons.get(login, "") + ", last active >1 year ago"
                elif days_inactive > 180:
                    candidate_scores[login] -= 1
                    candidate_reasons[login] = candidate_reasons.get(login, "") + ", last active >6 months ago"

            # Tier 3: Senior reviewer bonus (critical_owners designation)
            reviewer_rule_mentions = _build_reviewer_rule_mentions(matched_rules)
            critical_owners = set(reviewer_rule_mentions.keys())
            senior_boost = {"critical": 6, "high": 4, "medium": 2, "low": 0}.get(risk_level, 0)
            if senior_boost > 0:
                for owner in critical_owners:
                    if owner != pr_author:
                        candidate_scores[owner] = candidate_scores.get(owner, 0) + senior_boost
                        rule_descs = reviewer_rule_mentions.get(owner, [])
                        extra = (
                            f"required reviewer per rule: {'; '.join(rule_descs)}"
                            if rule_descs
                            else "required reviewer (critical_owners)"
                        )
                        if owner not in candidate_reasons:
                            candidate_reasons[owner] = extra
                        else:
                            candidate_reasons[owner] += f", {extra}"

            # Load balancing: penalize overloaded reviewers
            load_penalties = _compute_load_penalty(candidate_scores, review_load)
            for user, penalty in load_penalties.items():
                candidate_scores[user] -= penalty
                pending = review_load.get(user, 0)
                extra = f"{pending} pending reviews"
                if user in candidate_reasons:
                    candidate_reasons[user] += f", {extra}"
                else:
                    candidate_reasons[user] = extra

            # Remove PR author from candidates
            candidate_scores.pop(pr_author, None)

            # Sort by score descending, limit by risk-based reviewer count
            ranked = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
            reviewer_count = _reviewer_count_for_risk(risk_level)
            top_reviewers = ranked[:reviewer_count]

            # 8. LLM reasoning enrichment via agent (graceful degradation)
            from src.agents.reviewer_reasoning_agent.models import ReviewerProfile

            reviewer_profile_models = [
                ReviewerProfile(
                    login=login,
                    mechanical_reason=candidate_reasons.get(login, "contributor"),
                    languages=expertise_profiles.get(login, {}).get("languages", []),
                    commit_count=expertise_profiles.get(login, {}).get("commit_count", 0),
                    reviews=_extract_profile_reviews(expertise_profiles.get(login, {})),
                    last_active=expertise_profiles.get(login, {}).get("last_active", ""),
                    score=score,
                    rule_mentions=reviewer_rule_mentions.get(login, []),
                )
                for login, score in top_reviewers
            ]
            rule_labels: dict[str, str] = {}
            reasoning_result = await self.reasoning_agent.execute(
                risk_level=risk_level,
                changed_files=changed_filenames[:10],
                risk_signals=risk_descriptions,
                reviewers=reviewer_profile_models,
                path_rules=[r.description for r, _ in path_matched_rules],
            )
            if reasoning_result.success:
                for login, sentence in reasoning_result.data.get("explanations", {}).items():
                    if login in candidate_reasons and sentence:
                        candidate_reasons[login] = sentence
                rule_labels = reasoning_result.data.get("rule_labels", {})

            # 10. Build reasoning lines for the comment — mirror exactly what /risks shows.
            reasoning_lines: list[str] = []

            # Explain why top-1 reviewer was ranked first.
            if top_reviewers:
                top_login, top_score = top_reviewers[0]
                top_reason = candidate_reasons.get(top_login, "strongest overall match")
                if len(top_reviewers) > 1:
                    reasoning_lines.append(f"Top-1 reviewer @{top_login} — {top_reason}")
                else:
                    reasoning_lines.append(f"Top-1 reviewer @{top_login} ranked highest — {top_reason}")

            # Build a lookup so risk signals that mention a known path pattern
            # can be rewritten with the rule's actual description and severity.
            path_to_rule: dict[str, tuple[str, str]] = {}
            for rule, path in path_matched_rules:
                severity = rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity)
                label = rule_labels.get(rule.description, rule.description.split(":")[0].strip().lower())
                path_to_rule[path] = (label, severity, rule.description)

            for signal in risk_descriptions:
                matched_path = next((p for p in path_to_rule if p in signal), None)
                if matched_path:
                    label, severity, description = path_to_rule[matched_path]
                    reasoning_lines.append(f"{label} {matched_path} (severity: {severity}) - {description}")
                else:
                    reasoning_lines.append(signal)

            # First-time contributor note (use GitHub author association)
            author_assoc = (pr_data.get("author_association") or "").upper() if pr_data else ""
            if pr_author and author_assoc in {
                "FIRST_TIME_CONTRIBUTOR",
                "FIRST_TIME_CONTRIBUTOR_ON_CREATE",
                "FIRST_TIMER",
                "NONE",
            }:
                reasoning_lines.append(
                    f"@{pr_author} is a first-time contributor — additional review scrutiny recommended"
                )

            # 10. Format comment
            # Collect matched teams sorted by file coverage descending
            matched_teams = sorted(team_codeowner_candidates.items(), key=lambda x: x[1], reverse=True)
            comment = github_formatter.format_reviewer_recommendation_comment(
                risk_level=risk_level,
                risk_reason=risk_reason,
                reviewers=[(user, candidate_reasons.get(user, "contributor")) for user, _ in top_reviewers],
                reasoning_lines=reasoning_lines,
                review_load=review_load,
                team_reviewers=matched_teams,
            )

            # 11. Cache result, post comment, apply labels
            risk_label = f"watchflow:risk-{risk_level}"
            labels = ["watchflow:reviewer-recommendation", risk_label]
            _reviewer_cache.set(cache_key, {"comment": comment, "labels": labels})

            await self.github_client.create_pull_request_comment(repo, pr_number, comment, installation_id)
            api_calls += 1
            for label in labels:
                if label in _LABEL_COLORS:
                    color, description = _LABEL_COLORS[label]
                    await self.github_client.ensure_label(repo, label, color, description, installation_id)
                    api_calls += 1
            applied = await self.github_client.add_labels_to_issue(repo, pr_number, labels, installation_id)
            api_calls += 1
            if not applied:
                logger.warning(f"Failed to apply labels {labels} to {repo}#{pr_number}")

            # Do not mutate expertise.yaml from reviewer evaluations.
            # Expertise refresh is intentionally delegated to the dedicated scheduler endpoint/workflow.

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"✅ Reviewer recommendation posted for {repo}#{pr_number} in {processing_time}ms")

            return ProcessingResult(
                success=True,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"Error generating reviewer recommendations: {e}")
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        return {}
