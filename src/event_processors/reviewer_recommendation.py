import asyncio
import logging
import time
from collections import Counter, defaultdict
from typing import Any

from src.core.models import EventType
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.presentation import github_formatter
from src.rules.loaders.github_loader import RulesFileNotFoundError
from src.rules.models import Rule, RuleSeverity
from src.rules.utils.codeowners import CodeOwnersParser
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)


def _estimate_risk_level(
    matched_rules: list[Rule],
    changed_files: list[dict[str, Any]],
    pr_author_commit_count: int,
) -> tuple[str, str]:
    """Estimate risk level from matched rules and PR context.

    Returns (level, reason) tuple.
    """
    severity_order = {
        RuleSeverity.CRITICAL: 4,
        RuleSeverity.HIGH: 3,
        RuleSeverity.MEDIUM: 2,
        RuleSeverity.LOW: 1,
        RuleSeverity.ERROR: 3,
        RuleSeverity.WARNING: 1,
    }

    max_severity = 0
    for rule in matched_rules:
        max_severity = max(max_severity, severity_order.get(rule.severity, 0))

    num_files = len(changed_files)
    reasons: list[str] = []

    if max_severity >= 4:
        level = "critical"
        reasons.append("critical rules matched")
    elif max_severity >= 3:
        level = "high"
        reasons.append("high-severity rules matched")
    elif max_severity >= 2 or num_files > 20:
        level = "medium"
        if max_severity >= 2:
            reasons.append("medium-severity rules matched")
    else:
        level = "low"

    if num_files > 0:
        reasons.append(f"{num_files} files changed")

    if pr_author_commit_count == 0:
        reasons.append("first-time contributor")

    reason = ", ".join(reasons) if reasons else f"{num_files} files changed"
    return level, reason


def _match_rules_to_files(rules: list[Rule], changed_filenames: list[str]) -> list[Rule]:
    """Return rules whose file_patterns parameter matches any changed file."""
    import fnmatch

    matched: list[Rule] = []
    for rule in rules:
        if EventType.PULL_REQUEST not in rule.event_types:
            continue
        if not rule.enabled:
            continue

        file_patterns = rule.parameters.get("file_patterns", [])
        if not file_patterns:
            # Rules without file_patterns apply broadly — include them.
            matched.append(rule)
            continue

        for pattern in file_patterns:
            if any(fnmatch.fnmatch(f, pattern) for f in changed_filenames):
                matched.append(rule)
                break

    return matched


class ReviewerRecommendationProcessor(BaseEventProcessor):
    """Processor that recommends reviewers for a PR based on rules, CODEOWNERS, and commit history."""

    def get_event_type(self) -> str:
        return "reviewer_recommendation"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        api_calls = 0

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

            if not repo or not installation_id or not pr_number:
                return ProcessingResult(
                    success=False,
                    violations=[],
                    api_calls_made=0,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Missing repo, installation_id, or PR number",
                )

            logger.info(f"🔍 Generating reviewer recommendations for {repo}#{pr_number}")

            # 1. Fetch PR files
            changed_files = await self.github_client.get_pull_request_files(repo, pr_number, installation_id)
            api_calls += 1
            changed_filenames = [f.get("filename", "") for f in changed_files if f.get("filename")]

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

            matched_rules = _match_rules_to_files(rules, changed_filenames)

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

            # 4. Build owner map from CODEOWNERS
            codeowner_candidates: dict[str, int] = defaultdict(int)
            if codeowners_content:
                parser = CodeOwnersParser(codeowners_content)
                for filename in changed_filenames:
                    owners = parser.get_owners_for_file(filename)
                    for owner in owners:
                        codeowner_candidates[owner] += 1

            # 5. Build expertise profile from commit history on changed paths
            # Sample up to 10 unique directories to reduce API calls
            directories = list({f.rsplit("/", 1)[0] if "/" in f else "." for f in changed_filenames})
            sampled_paths = changed_filenames[:5] + directories[:5]
            # Deduplicate
            sampled_paths = list(dict.fromkeys(sampled_paths))[:10]

            commit_author_counts: Counter[str] = Counter()
            commit_tasks = [
                self.github_client.get_commits_for_path(repo, path, installation_id, per_page=20)
                for path in sampled_paths
            ]
            commit_results = await asyncio.gather(*commit_tasks, return_exceptions=True)
            api_calls += len(sampled_paths)

            for result in commit_results:
                if isinstance(result, Exception):
                    continue
                for commit_data in result:
                    author_login = (commit_data.get("author") or {}).get("login")
                    if author_login:
                        commit_author_counts[author_login] += 1

            # 6. Determine PR author's commit count (for first-time contributor signal)
            pr_author_commit_count = commit_author_counts.get(pr_author, 0)

            # 7. Estimate risk
            risk_level, risk_reason = _estimate_risk_level(matched_rules, changed_files, pr_author_commit_count)

            # 8. Rank candidates
            # Score: codeowner matches (weight 3) + commit activity (weight 1)
            candidate_scores: dict[str, float] = defaultdict(float)
            candidate_reasons: dict[str, str] = {}

            for user, file_count in codeowner_candidates.items():
                candidate_scores[user] += file_count * 3
                pct = int(file_count / max(len(changed_filenames), 1) * 100)
                candidate_reasons[user] = f"code owner, {pct}% ownership of changed files"

            for user, count in commit_author_counts.items():
                candidate_scores[user] += count
                if user not in candidate_reasons:
                    candidate_reasons[user] = f"{count} recent commits on affected paths"
                else:
                    candidate_reasons[user] += f", {count} recent commits"

            # Remove the PR author from candidates
            candidate_scores.pop(pr_author, None)

            # Sort by score descending
            ranked = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
            top_reviewers = ranked[:5]

            # 9. Build reasoning lines
            reasoning_lines: list[str] = []
            for rule in matched_rules[:5]:
                sev = rule.severity.value if hasattr(rule.severity, "value") else str(rule.severity)
                patterns = rule.parameters.get("file_patterns", [])
                pattern_str = ", ".join(patterns[:3]) if patterns else "all files"
                reasoning_lines.append(f"Rule `{pattern_str}` (severity: {sev}) — {rule.description}")

            for user, _ in top_reviewers[:3]:
                count = commit_author_counts.get(user, 0)
                if count > 0:
                    reasoning_lines.append(f"@{user} has {count} recent commits on affected paths")

            if pr_author_commit_count == 0:
                reasoning_lines.append(
                    f"@{pr_author} is a first-time contributor — additional review scrutiny recommended"
                )

            # 10. Format comment
            comment = github_formatter.format_reviewer_recommendation_comment(
                risk_level=risk_level,
                risk_reason=risk_reason,
                reviewers=[(user, candidate_reasons.get(user, "contributor")) for user, _ in top_reviewers],
                reasoning_lines=reasoning_lines,
            )

            # 11. Post comment
            await self.github_client.create_pull_request_comment(repo, pr_number, comment, installation_id)
            api_calls += 1

            # 12. Apply labels
            risk_label = f"watchflow:risk-{risk_level}"
            labels = ["watchflow:reviewer-recommendation", risk_label]
            await self.github_client.add_labels_to_issue(repo, pr_number, labels, installation_id)
            api_calls += 1

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
