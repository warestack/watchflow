"""Background expertise refresh — runs on a schedule to keep .watchflow/expertise.yaml current.

Called via POST /api/v1/scheduler/refresh-expertise, which requires a GitHub Actions OIDC JWT
(``Authorization: Bearer <token>``).  The token is minted automatically by the workflow — no
user-configured secrets are needed.  The ``repository`` claim in the token is cross-checked
against the ``repo`` field in the request body to prevent cross-repo abuse.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from os.path import splitext
from typing import Any

import yaml

from src.integrations.github import github_client as _github_client
from src.rules.utils.codeowners import CodeOwnersParser

logger = logging.getLogger(__name__)

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

# Limit concurrent API calls per refresh run
_SEM = asyncio.Semaphore(5)

# How far back to scan on a full (fresh) build
_FULL_SCAN_LOOKBACK_DAYS = 365
# Max commits to page through on a full build (safety ceiling)
_FULL_SCAN_MAX_COMMITS = 2000
# Paths to sample per-path commit history on a full build
_FULL_SCAN_PATH_SAMPLE = 30
# Repos with at least this many merged PRs skip the incremental commit scan
_MERGED_PR_THRESHOLD = 20


def _empty_reviews() -> dict[str, int]:
    return {"total": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}


def _normalize_reviews(raw: Any) -> dict[str, int]:
    """Normalize risk-bucket review counts into a safe dict."""
    normalized = _empty_reviews()
    if not isinstance(raw, Mapping):
        return normalized
    for risk in normalized:
        try:
            value = int(raw.get(risk, 0))
        except (TypeError, ValueError):
            value = 0
        normalized[risk] = max(value, 0)
    return normalized


def _extract_profile_reviews(profile: dict[str, Any]) -> dict[str, int]:
    """Return normalized review buckets from profile."""
    return _normalize_reviews(profile.get("reviews", {}))


async def refresh_expertise_by_repo_name(repo_full_name: str) -> None:
    """Refresh expertise.yaml for a single repo, resolving installation from the repo name."""
    owner, _, repo = repo_full_name.partition("/")
    if not owner or not repo:
        msg = f"Invalid repo name: {repo_full_name!r}"
        logger.warning(msg)
        raise ValueError(msg)

    installation = await _github_client.get_repo_installation(owner, repo)
    if not installation:
        msg = f"No installation found for {repo_full_name}"
        logger.warning(msg)
        raise RuntimeError(msg)

    installation_id = installation.get("id")
    if not installation_id:
        msg = f"Installation record for {repo_full_name} has no id"
        logger.warning(msg)
        raise RuntimeError(msg)

    await refresh_expertise_for_repo(repo_full_name, installation_id)
    logger.info(f"Expertise refreshed for {repo_full_name}")


async def refresh_expertise_for_repo(repo: str, installation_id: int) -> None:
    """Refresh .watchflow/expertise.yaml for a single repo.

    Strategy (layered):
    1. CODEOWNERS base layer — parse CODEOWNERS for ownership patterns.
    2. Recent commits layer — scan repo-wide commits + sampled file paths
       (runs when fewer than 20 merged PRs exist).
    3. Merged PR layer — fetch changed files from PRs, commit history per path, reviews.
    4. Merge all layers and write back.
    """
    existing_profiles = await _load_profiles(repo, installation_id)
    now = datetime.now(UTC)

    # --- Layer 1: CODEOWNERS ---
    codeowners_profiles: dict[str, Any] = {}
    codeowners_content = await _fetch_codeowners_content(repo, installation_id)
    if codeowners_content:
        codeowners_profiles = _build_profiles_from_codeowners(codeowners_content)
        logger.debug(f"CODEOWNERS: found {len(codeowners_profiles)} individual owner(s) for {repo}")

    # Fetch recently merged PRs.
    # Page through closed PRs until we have collected _MERGED_PR_THRESHOLD merged ones
    # (or exhaust the history).  This gives an accurate "is this a PR-active repo?"
    # signal regardless of how many closed-but-unmerged PRs exist.
    is_fresh = not bool(existing_profiles)
    all_merged_prs = await _fetch_merged_prs(repo, installation_id, threshold=_MERGED_PR_THRESHOLD)
    # Fresh build: use all collected merged PRs for maximum coverage.
    # Incremental: cap to 10 — we only need to pick up recent activity on top of existing profiles.
    merged_prs = all_merged_prs if is_fresh else all_merged_prs[:10]

    # --- Layer 2: Commit scan ---
    # Fresh build (no existing profiles): scan full history up to 1 year back.
    # Incremental update on a low-PR-activity repo: scan recent commits only.
    commit_profiles: dict[str, Any] = {}
    if is_fresh:
        since_dt = now - timedelta(days=_FULL_SCAN_LOOKBACK_DAYS)
        commit_profiles = await _build_profiles_from_all_commits(repo, installation_id, since=since_dt)
        logger.debug(f"Full commit scan: found {len(commit_profiles)} contributor(s) for {repo}")
    elif len(all_merged_prs) < _MERGED_PR_THRESHOLD:
        commit_profiles = await _build_profiles_from_recent_commits(repo, installation_id)
        logger.debug(f"Commit scan: found {len(commit_profiles)} contributor(s) for {repo}")

    # --- Layer 3: Merged PRs ---
    pr_profiles: dict[str, Any] = {}
    if merged_prs:
        pr_profiles = await _build_profiles_from_merged_prs(repo, installation_id, merged_prs, existing_profiles)

    # --- Merge layers: existing → CODEOWNERS → commits → PRs (highest priority) ---
    merged = dict(existing_profiles)
    for layer in [codeowners_profiles, commit_profiles, pr_profiles]:
        merged = _merge_profile_layer(merged, layer)

    # Determine base branch
    if merged_prs:
        base_branch = merged_prs[0].get("base", {}).get("ref", "main")
    else:
        async with _SEM:
            repo_data, _ = await _github_client.get_repository(repo, installation_id=installation_id)
        base_branch = (repo_data or {}).get("default_branch", "main")

    # Prune stale concrete file paths using the current repository tree.
    # Keep CODEOWNERS-style wildcard patterns (e.g., "src/*.py") as-is.
    valid_paths = await _fetch_valid_repo_paths(repo, installation_id, base_branch)
    merged = _prune_stale_profile_paths(merged, valid_paths)

    # Write updated profiles
    payload = {
        "updated_at": now.isoformat(),
        "contributors": merged,
    }
    content = yaml.dump(payload, default_flow_style=False, sort_keys=True)
    await _github_client.create_or_update_file(
        repo_full_name=repo,
        path=".watchflow/expertise.yaml",
        content=content,
        message="chore: refresh reviewer expertise profiles [watchflow] [skip ci]",
        branch=base_branch,
        installation_id=installation_id,
    )


async def _fetch_valid_repo_paths(repo: str, installation_id: int, ref: str) -> set[str]:
    """Return all current blob paths for the given ref."""
    try:
        async with _SEM:
            tree = await _github_client.get_repository_tree(
                repo, ref=ref, installation_id=installation_id, recursive=True
            )
        return {item.get("path", "") for item in tree if item.get("type") == "blob" and item.get("path")}
    except Exception:
        logger.warning(f"Could not fetch repository tree for stale-path pruning in {repo}@{ref}")
        return set()


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------


async def _fetch_merged_prs(
    repo: str,
    installation_id: int,
    threshold: int,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """Page through closed PRs until *threshold* merged ones are collected or history is exhausted.

    per_page=100 was chosen because repos increasingly contain high volumes of AI-generated
    ("slop") PRs that are closed without merging, which means a smaller page size would
    frequently fail to find enough merged PRs in one pass.  We scan up to max_pages pages
    but exit as soon as the merged threshold is reached, so well-maintained repos pay no
    extra cost.
    """
    merged: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        async with _SEM:
            batch = await _github_client.list_pull_requests(
                repo, installation_id, state="closed", per_page=per_page, page=page
            )
        if not batch:
            break
        merged.extend(pr for pr in batch if pr.get("merged_at"))
        if len(merged) >= threshold:
            break
        if len(batch) < per_page:
            break  # last page
    return merged


async def _fetch_codeowners_content(repo: str, installation_id: int) -> str | None:
    """Try standard CODEOWNERS locations; return raw content or None."""
    for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        try:
            async with _SEM:
                content = await _github_client.get_file_content(repo, path, installation_id)
            if content:
                return content
        except Exception:
            continue
    return None


def _build_profiles_from_codeowners(codeowners_content: str) -> dict[str, Any]:
    """Extract individual owner profiles from CODEOWNERS. Team/org entries are skipped."""
    parser = CodeOwnersParser(codeowners_content)
    profiles: dict[str, Any] = {}

    for pattern, owners in parser.owners_map:
        ext = ""
        if "*." in pattern:
            ext = "." + pattern.rsplit("*.", 1)[-1].split("/")[0].split("*")[0]
        language = _EXT_TO_LANGUAGE.get(ext.lower()) if ext else None

        for owner in owners:
            if "/" in owner:
                continue
            if owner not in profiles:
                profiles[owner] = {
                    "languages": set(),
                    "commit_count": 0,
                    "last_active": "",
                    "reviews": _empty_reviews(),
                    "path_commit_counts": {},
                }
            if language:
                profiles[owner]["languages"].add(language)

    return profiles


async def _build_profiles_from_recent_commits(repo: str, installation_id: int) -> dict[str, Any]:
    """Build expertise profiles from recent repo-wide commits.

    1. Fetch up to 30 recent commits to identify active authors.
    2. Fetch the repo file tree, sample up to 10 source-code paths.
    3. Fetch commit history per sampled path.
    4. Build profiles from author/file/date data.
    """
    async with _SEM:
        recent_commits = await _github_client.get_commits(repo, installation_id, per_page=30)

    if not recent_commits:
        return {}

    profiles: dict[str, Any] = {}
    for commit_data in recent_commits:
        _ingest_commit(profiles, commit_data)

    # Fetch repo tree to sample file paths
    async with _SEM:
        repo_data, _ = await _github_client.get_repository(repo, installation_id=installation_id)
    default_branch = (repo_data or {}).get("default_branch", "main")

    async with _SEM:
        tree = await _github_client.get_repository_tree(
            repo, ref=default_branch, installation_id=installation_id, recursive=True
        )

    source_paths = [
        item["path"]
        for item in tree
        if item.get("type") == "blob" and splitext(item.get("path", ""))[1].lower() in _EXT_TO_LANGUAGE
    ]
    sampled = _sample_diverse_paths(source_paths, max_count=10)

    # Fetch commit history per sampled path
    commit_tasks = [_github_client.get_commits(repo, installation_id, path=path, per_page=20) for path in sampled]
    commit_results: list[Any] = await asyncio.gather(*commit_tasks, return_exceptions=True)

    for idx, result in enumerate(commit_results):
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        path = sampled[idx]
        for commit_data in result:
            _ingest_commit(profiles, commit_data, path=path)

    return profiles


async def _build_profiles_from_all_commits(
    repo: str,
    installation_id: int,
    since: datetime,
) -> dict[str, Any]:
    """Full-history commit scan used for fresh expertise.yaml builds.

    1. Paginate repo-wide commits from *since* (ISO cutoff) until exhausted or the
       safety ceiling (_FULL_SCAN_MAX_COMMITS) is reached — captures all contributors.
    2. Fetch the repo file tree, sample up to _FULL_SCAN_PATH_SAMPLE source-code paths.
    3. Fetch per-path commit history since the same cutoff.
    4. Build profiles from author / file / date data.
    """
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    profiles: dict[str, Any] = {}

    # --- Step 1: paginate all repo-wide commits since cutoff ---
    page = 1
    total_fetched = 0
    per_page = 100
    while total_fetched < _FULL_SCAN_MAX_COMMITS:
        async with _SEM:
            batch = await _github_client.get_commits(
                repo, installation_id, per_page=per_page, page=page, since=since_iso
            )
        if not batch:
            break
        for commit_data in batch:
            _ingest_commit(profiles, commit_data)
        total_fetched += len(batch)
        if len(batch) < per_page:
            break  # last page
        page += 1

    if not profiles:
        return {}

    # --- Step 2: sample source-code paths from repo tree ---
    async with _SEM:
        repo_data, _ = await _github_client.get_repository(repo, installation_id=installation_id)
    default_branch = (repo_data or {}).get("default_branch", "main")

    async with _SEM:
        tree = await _github_client.get_repository_tree(
            repo, ref=default_branch, installation_id=installation_id, recursive=True
        )

    source_paths = [
        item["path"]
        for item in tree
        if item.get("type") == "blob" and splitext(item.get("path", ""))[1].lower() in _EXT_TO_LANGUAGE
    ]
    sampled = _sample_diverse_paths(source_paths, max_count=_FULL_SCAN_PATH_SAMPLE)

    # --- Step 3: per-path commit history since cutoff ---
    commit_tasks = [
        _github_client.get_commits(repo, installation_id, path=path, per_page=100, since=since_iso) for path in sampled
    ]
    commit_results: list[Any] = await asyncio.gather(*commit_tasks, return_exceptions=True)

    for idx, result in enumerate(commit_results):
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        path = sampled[idx]
        for commit_data in result:
            _ingest_commit(profiles, commit_data, path=path)

    return profiles


async def _build_profiles_from_merged_prs(
    repo: str,
    installation_id: int,
    merged_prs: list[dict[str, Any]],
    existing_profiles: dict[str, Any],
) -> dict[str, Any]:
    """Build expertise profiles from merged PR data (file changes, commits, reviews)."""
    # Collect changed files across PRs
    file_tasks = [_github_client.get_pull_request_files(repo, pr["number"], installation_id) for pr in merged_prs]
    files_per_pr: list[Any] = await asyncio.gather(*file_tasks, return_exceptions=True)

    all_filenames: list[str] = []
    for result in files_per_pr:
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        all_filenames.extend(f.get("filename", "") for f in result if f.get("filename"))

    unique_paths = list(dict.fromkeys(all_filenames))[:10]

    # Fetch commit history per sampled path
    commit_tasks = [_github_client.get_commits(repo, installation_id, path=path, per_page=20) for path in unique_paths]
    commit_results: list[Any] = await asyncio.gather(*commit_tasks, return_exceptions=True)

    profiles: dict[str, Any] = {}
    for idx, result in enumerate(commit_results):
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        path = unique_paths[idx] if idx < len(unique_paths) else ""
        for commit_data in result:
            author_login = (commit_data.get("author") or {}).get("login")
            if not author_login:
                continue
            if author_login not in profiles:
                profiles[author_login] = {
                    "languages": set(),
                    "commit_count": 0,
                    "last_active": "",
                    "reviews": _extract_profile_reviews(existing_profiles.get(author_login, {})),
                    "path_commit_counts": {},
                }
            _ingest_commit(profiles, commit_data, path=path)

    # Fetch reviews from merged PRs
    review_tasks = [_github_client.get_pull_request_reviews(repo, pr["number"], installation_id) for pr in merged_prs]
    reviews_per_pr: list[Any] = await asyncio.gather(*review_tasks, return_exceptions=True)

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
            if not reviewer or review.get("state") not in ("APPROVED", "CHANGES_REQUESTED"):
                continue
            if reviewer not in profiles:
                profiles[reviewer] = {
                    "languages": set(),
                    "commit_count": 0,
                    "last_active": "",
                    "reviews": _extract_profile_reviews(existing_profiles.get(reviewer, {})),
                    "path_commit_counts": {},
                }
            buckets = _extract_profile_reviews(profiles[reviewer])
            buckets["total"] = buckets.get("total", 0) + 1
            if pr_risk:
                buckets[pr_risk] = buckets.get(pr_risk, 0) + 1
            profiles[reviewer]["reviews"] = buckets

    return profiles


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _ingest_commit(
    profiles: dict[str, Any],
    commit_data: dict[str, Any],
    path: str | None = None,
) -> None:
    """Update *profiles* in place from a single commit object."""
    author_login = (commit_data.get("author") or {}).get("login")
    if not author_login:
        return

    date_str = commit_data.get("commit", {}).get("author", {}).get("date", "")
    last_active = ""
    if date_str:
        try:
            commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            last_active = commit_date.date().isoformat()
        except (ValueError, TypeError):
            pass

    if author_login not in profiles:
        profiles[author_login] = {
            "languages": set(),
            "commit_count": 0,
            "last_active": last_active,
            "reviews": _empty_reviews(),
            "path_commit_counts": {},
        }

    profiles[author_login]["commit_count"] += 1
    if last_active > profiles[author_login]["last_active"]:
        profiles[author_login]["last_active"] = last_active

    if path:
        path_counts = profiles[author_login].setdefault("path_commit_counts", {})
        path_counts[path] = path_counts.get(path, 0) + 1
        ext = splitext(path)[1].lower()
        language = _EXT_TO_LANGUAGE.get(ext)
        if language:
            profiles[author_login]["languages"].add(language)


def _merge_profile_layer(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge overlay profiles into base.

    Numeric counts (commit_count, reviews buckets) use max() rather
    than addition.  Each scheduler run fetches the same recent window of commits and
    PRs, so summing across runs inflates counts beyond what git history actually
    contains.  Taking the maximum preserves the best observed estimate without
    accumulating duplicates across refreshes.

    ``languages`` is unioned — deduplicated by nature and safe to accumulate.
    ``path_commit_counts`` keys serve as the file path index; no separate
    ``file_paths`` field is stored.
    """
    merged = dict(base)
    for login, data in overlay.items():
        languages = data.get("languages", [])
        path_commit_counts = _normalize_path_commit_counts(data.get("path_commit_counts", {}))
        if isinstance(languages, set):
            languages = sorted(languages)

        if login not in merged:
            merged[login] = {
                "languages": languages,
                "commit_count": data.get("commit_count", 0),
                "last_active": data.get("last_active", ""),
                "reviews": _extract_profile_reviews(data),
                "path_commit_counts": path_commit_counts,
            }
        else:
            existing = merged[login]
            existing["languages"] = sorted(set(existing.get("languages", [])) | set(languages))
            existing["commit_count"] = max(existing.get("commit_count", 0), data.get("commit_count", 0))
            existing_reviews = _extract_profile_reviews(existing)
            incoming_reviews = _extract_profile_reviews(data)
            existing["reviews"] = {
                risk: max(existing_reviews.get(risk, 0), incoming_reviews.get(risk, 0))
                for risk in ("total", "low", "medium", "high", "critical")
            }
            existing_counts = _normalize_path_commit_counts(existing.get("path_commit_counts", {}))
            merged_counts = dict(existing_counts)
            for path, count in path_commit_counts.items():
                merged_counts[path] = max(merged_counts.get(path, 0), count)
            existing["path_commit_counts"] = merged_counts
            if data.get("last_active", "") > existing.get("last_active", ""):
                existing["last_active"] = data["last_active"]

    return merged


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


def _is_pattern_path(path: str) -> bool:
    """Return True for CODEOWNERS-like wildcard patterns."""
    return any(ch in path for ch in ("*", "?", "[", "]"))


def _prune_stale_profile_paths(profiles: dict[str, Any], valid_paths: set[str]) -> dict[str, Any]:
    """Drop deleted concrete file paths from path_commit_counts."""
    if not valid_paths:
        return profiles

    pruned: dict[str, Any] = {}
    for login, profile in profiles.items():
        if not isinstance(profile, dict):
            pruned[login] = profile
            continue
        path_counts = _normalize_path_commit_counts(profile.get("path_commit_counts", {}))
        updated = dict(profile)
        updated["path_commit_counts"] = {p: c for p, c in path_counts.items() if p in valid_paths}
        pruned[login] = updated

    return pruned


def _sample_diverse_paths(paths: list[str], max_count: int = 10) -> list[str]:
    """Sample paths spread across different top-level directories for diversity."""
    if len(paths) <= max_count:
        return paths

    buckets: dict[str, list[str]] = {}
    for p in paths:
        top_dir = p.split("/")[0] if "/" in p else "."
        buckets.setdefault(top_dir, []).append(p)

    sampled: list[str] = []
    bucket_iters = {k: iter(v) for k, v in buckets.items()}
    while len(sampled) < max_count and bucket_iters:
        exhausted = []
        for key, it in bucket_iters.items():
            if len(sampled) >= max_count:
                break
            try:
                sampled.append(next(it))
            except StopIteration:
                exhausted.append(key)
        for key in exhausted:
            del bucket_iters[key]

    return sampled


async def _load_profiles(repo: str, installation_id: int) -> dict[str, Any]:
    """Read existing .watchflow/expertise.yaml contributors dict, or {} if absent."""
    try:
        content = await _github_client.get_file_content(repo, ".watchflow/expertise.yaml", installation_id)
        if content:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data.get("contributors", {}) or {}
    except Exception:
        pass
    return {}
