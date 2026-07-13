import asyncio
import hashlib
import time
from typing import Any

import structlog
import yaml

from src.agents import get_agent
from src.api.recommendations import get_suggested_rules_from_repo
from src.core.config import config
from src.core.models import Violation
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.event_processors.pull_request.enricher import PullRequestEnricher
from src.integrations.github.check_runs import CheckRunManager
from src.presentation import github_formatter
from src.rules.ai_rules_scan import is_relevant_pr
from src.rules.loaders.github_loader import GitHubRuleLoader, RulesFileNotFoundError
from src.tasks.task_queue import Task

logger = structlog.get_logger()


class PullRequestProcessor(BaseEventProcessor):
    """Processor for pull request events using agentic rule evaluation."""

    def __init__(self) -> None:
        super().__init__()
        self.engine_agent = get_agent("engine")
        self.enricher = PullRequestEnricher(self.github_client)
        self.check_run_manager = CheckRunManager(self.github_client)
        self._setup_awareness_locks: dict[tuple[str, int], tuple[asyncio.Lock, int]] = {}

    def get_event_type(self) -> str:
        return "pull_request"

    async def process(self, task: Task) -> ProcessingResult:
        """Process a pull request event using the agentic approach."""
        start_time = time.time()
        api_calls = 0

        # Extract common data for check runs
        repo_full_name = task.repo_full_name
        installation_id = task.installation_id
        pr_data = task.payload.get("pull_request", {})
        pr_number = pr_data.get("number")
        sha = pr_data.get("head", {}).get("sha")

        if not installation_id:
            logger.error("No installation ID found in task")
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error="No installation ID found",
            )

        if pr_data.get("state") == "closed" or pr_data.get("merged") or pr_data.get("draft"):
            logger.info(
                "pr_skipped_invalid_state",
                extra={
                    "state": pr_data.get("state"),
                    "merged": pr_data.get("merged"),
                    "draft": pr_data.get("draft"),
                },
            )
            return ProcessingResult(
                success=True,
                violations=[],
                api_calls_made=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info("=" * 80)
            logger.info(f"🚀 Processing PR event for {repo_full_name}")
            logger.info(f"   Action: {task.payload.get('action')}")
            logger.info(f"   PR Number: {pr_number}")
            logger.info("=" * 80)

            github_token_optional = await self.github_client.get_installation_access_token(installation_id)
            if not github_token_optional:
                raise ValueError("Failed to get installation access token")
            github_token = github_token_optional

            # Agentic: scan repo only when relevant (PR targets default branch)
            # Use the PR head ref so we scan the branch being proposed, not main.
            suggested_rules_yaml: str | None = None
            suggested_rules_translated = 0
            suggested_rules_ambiguous: list[Any] = []
            if is_relevant_pr(task.payload):
                scan_start = time.time()
                try:
                    pr_head_ref = pr_data.get("head", {}).get("ref")  # branch name, e.g. feature-x
                    rules_yaml, rules_count, ambiguous, rule_sources = await get_suggested_rules_from_repo(
                        repo_full_name, installation_id, github_token, ref=pr_head_ref
                    )
                    latency_ms = int((time.time() - scan_start) * 1000)
                    from_mapping = sum(1 for s in rule_sources if s == "mapping") if rule_sources else 0
                    from_agent = sum(1 for s in rule_sources if s == "agent") if rule_sources else 0
                    logger.info(
                        "suggested_rules_scan",
                        extra={
                            "operation": "suggested_rules_scan",
                            "subject_ids": [repo_full_name, f"pr#{pr_number}"],
                            "decision": "found" if rules_count > 0 else "none",
                            "latency_ms": latency_ms,
                            "rules_count": rules_count,
                            "ambiguous_count": len(ambiguous),
                            "from_mapping": from_mapping,
                            "from_agent": from_agent,
                        },
                    )
                    suggested_rules_translated = rules_count
                    suggested_rules_ambiguous = list(ambiguous) if ambiguous else []
                    if rules_count > 0:
                        suggested_rules_yaml = rules_yaml
                except Exception:
                    latency_ms = int((time.time() - scan_start) * 1000)
                    logger.exception(
                        "Suggested rules scan failed",
                        extra={
                            "operation": "suggested_rules_scan",
                            "subject_ids": [repo_full_name, f"pr#{pr_number}"],
                            "decision": "failure",
                            "latency_ms": latency_ms,
                        },
                    )
            else:
                logger.info(
                    "suggested_rules_scan",
                    extra={
                        "operation": "suggested_rules_scan",
                        "subject_ids": [repo_full_name, f"pr#{pr_number}"],
                        "decision": "skip",
                        "reason": "PR not relevant (base ref)",
                    },
                )

            # 1. Enrich event data
            event_data = await self.enricher.enrich_event_data(task, github_token)
            api_calls += 1

            # 2. Fetch rules and merge in dynamically translated rules (pre-merge enforcement)
            try:
                rules_optional = await self.rule_provider.get_rules(repo_full_name, installation_id)
                rules = rules_optional if rules_optional is not None else []
                api_calls += 1
            except RulesFileNotFoundError as e:
                logger.warning(f"Rules file not found: {e}")
                if sha:
                    await self.check_run_manager.create_check_run(
                        repo=repo_full_name,
                        sha=sha,
                        installation_id=installation_id,
                        violations=[],
                        conclusion="neutral",
                        error="Rules not configured. Please create `.watchflow/rules.yaml` in your repository.",
                    )
                await self._post_rules_not_configured_comment(task, pr_number, installation_id)
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Rules not configured",
                )

            # Append dynamically translated rules so they are enforced as pre-merge checks
            if suggested_rules_yaml:
                try:
                    parsed = yaml.safe_load(suggested_rules_yaml)
                    if isinstance(parsed, dict) and "rules" in parsed and isinstance(parsed["rules"], list):
                        suggested_count = 0
                        for rule_data in parsed["rules"]:
                            if isinstance(rule_data, dict):
                                try:
                                    rule = GitHubRuleLoader._parse_rule(rule_data)
                                    rules.append(rule)
                                    suggested_count += 1
                                except Exception as parse_err:
                                    logger.warning("Failed to parse suggested rule: %s", parse_err)
                        if suggested_count > 0:
                            logger.info(
                                "Enforcing %d rules total (%d from repo, %d suggested from AI rule files)",
                                len(rules),
                                len(rules) - suggested_count,
                                suggested_count,
                            )
                except yaml.YAMLError as e:
                    logger.warning("Failed to parse suggested rules YAML: %s", e)

            # Surface translation summary to the user (parity with push-event PR body)
            # Post when we have any scan result: translated and/or ambiguous, so users see X enforced and Y not translated
            if pr_number and (suggested_rules_translated > 0 or suggested_rules_ambiguous):
                try:
                    comment_body = github_formatter.format_suggested_rules_ambiguous_comment(
                        rules_translated=suggested_rules_translated,
                        ambiguous=suggested_rules_ambiguous,
                    )
                    await self.github_client.create_pull_request_comment(
                        repo_full_name, pr_number, comment_body, installation_id
                    )
                except Exception as comment_err:
                    logger.warning("Could not post suggested-rules translation summary comment: %s", comment_err)

            # 3. Check for existing acknowledgments
            previous_acknowledgments = {}
            comments_snapshot: list[dict[str, Any]] | None = None
            if pr_number:
                comments_snapshot = await self.github_client.get_issue_comments(
                    repo_full_name, pr_number, installation_id
                )
                if comments_snapshot:
                    previous_acknowledgments = self.enricher.parse_acknowledgments(comments_snapshot)
                if previous_acknowledgments:
                    logger.info(f"📋 Found {len(previous_acknowledgments)} previous acknowledgments")

            # 4. Run engine-based rule evaluation (pass Rule objects so .conditions are preserved).
            # No conversion to flat schema: a previous _convert_rules_to_new_format helper had issues and was removed.
            result = await self.engine_agent.execute(event_type="pull_request", event_data=event_data, rules=rules)

            # 5. Extract and filter violations
            violations: list[Violation] = []
            if result.data and "evaluation_result" in result.data:
                eval_result = result.data["evaluation_result"]
                if hasattr(eval_result, "violations"):
                    violations = [Violation.model_validate(v) for v in eval_result.violations]

            original_violations = violations.copy()
            acknowledgable_violations = []
            require_acknowledgment_violations = []

            for violation in violations:
                # Match by rule_id so acknowledgment lookup matches parsed comments
                ack_key = violation.rule_id or violation.rule_description
                if ack_key in previous_acknowledgments:
                    acknowledgable_violations.append(violation)
                else:
                    require_acknowledgment_violations.append(violation)

            logger.info(
                f"📊 Violation breakdown: {len(acknowledgable_violations)} acknowledged, {len(require_acknowledgment_violations)} requiring fixes"
            )

            violations = require_acknowledgment_violations

            # 6. Report results to GitHub
            if sha:
                if previous_acknowledgments and original_violations:
                    await self.check_run_manager.create_acknowledgment_check_run(
                        repo=repo_full_name,
                        sha=sha,
                        installation_id=installation_id,
                        acknowledgable_violations=acknowledgable_violations,
                        violations=violations,
                        acknowledgments=previous_acknowledgments,
                    )
                else:
                    await self.check_run_manager.create_check_run(
                        repo=repo_full_name,
                        sha=sha,
                        installation_id=installation_id,
                        violations=violations,
                    )

            if violations:
                logger.info(f"🚨 Found {len(violations)} violations, posting to PR...")
                await self._post_violations_to_github(task, violations, existing_comments=comments_snapshot)
                api_calls += 1

            processing_time = int((time.time() - start_time) * 1000)
            logger.info("=" * 80)
            logger.info(f"🏁 PR processing completed in {processing_time}ms")
            logger.info("=" * 80)

            return ProcessingResult(
                success=(not violations),
                violations=violations,
                api_calls_made=api_calls,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"❌ Error processing PR event: {e}")
            if sha:
                await self.check_run_manager.create_check_run(
                    repo=repo_full_name,
                    sha=sha,
                    installation_id=installation_id,
                    violations=[],
                    conclusion="failure",
                    error=str(e),
                )
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def _post_violations_to_github(
        self, task: Task, violations: list[Violation], existing_comments: list[dict[str, Any]] | None = None
    ) -> None:
        """Post violations as comments on the pull request.

        Implements comment-level deduplication by checking existing PR comments
        and skipping if an identical Watchflow violations comment already exists.
        """
        try:
            pr_number = task.payload.get("pull_request", {}).get("number")
            if not pr_number or not task.installation_id:
                return

            # Compute content hash for deduplication
            violations_signature = self._compute_violations_hash(violations)

            # Check if identical comment already exists
            if await self._has_duplicate_comment(
                task.repo_full_name,
                pr_number,
                violations_signature,
                task.installation_id,
                existing_comments=existing_comments,
            ):
                logger.info(
                    "Skipping duplicate violations comment",
                    extra={
                        "pr_number": pr_number,
                        "repo": task.repo_full_name,
                        "violations_hash": violations_signature,
                    },
                )
                return

            # Post new comment with hash marker
            comment_body = github_formatter.format_violations_comment(violations, content_hash=violations_signature)
            await self.github_client.create_pull_request_comment(
                task.repo_full_name, pr_number, comment_body, task.installation_id
            )
            logger.info(
                "Posted violations comment",
                extra={
                    "pr_number": pr_number,
                    "repo": task.repo_full_name,
                    "violations_count": len(violations),
                    "violations_hash": violations_signature,
                },
            )
        except Exception as e:
            logger.error(f"Error posting violations to GitHub: {e}")

    async def _post_rules_not_configured_comment(self, task: Task, pr_number: int | None, installation_id: int) -> None:
        """Post one setup-awareness comment for an initially opened PR.

        Missing rules are surfaced in the neutral check run on every relevant
        event. The timeline comment is onboarding-only, so it must never be
        repeated after the initial ``pull_request.opened`` delivery.
        """
        if not pr_number:
            return

        if task.payload.get("action") != "opened":
            logger.info(
                "setup_awareness_skipped_non_opened",
                pr_number=pr_number,
                repo=task.repo_full_name,
                action=task.payload.get("action"),
            )
            return

        lock_key = (task.repo_full_name, pr_number)
        lock_entry = self._setup_awareness_locks.get(lock_key)
        if lock_entry is None:
            lock, waiting_tasks = asyncio.Lock(), 0
        else:
            lock, waiting_tasks = lock_entry
        self._setup_awareness_locks[lock_key] = (lock, waiting_tasks + 1)
        try:
            async with lock:
                existing_comments = await self.github_client.get_issue_comments(
                    task.repo_full_name, pr_number, installation_id
                )
                if existing_comments is None:
                    logger.warning(
                        "setup_awareness_skipped_lookup_error", pr_number=pr_number, repo=task.repo_full_name
                    )
                    return
                if self._has_setup_awareness_comment(existing_comments):
                    logger.info("setup_awareness_skipped_existing", pr_number=pr_number, repo=task.repo_full_name)
                    return

                welcome_comment = github_formatter.format_rules_not_configured_comment(
                    repo_full_name=task.repo_full_name,
                    installation_id=installation_id,
                )
                result = await self.github_client.create_pull_request_comment(
                    task.repo_full_name, pr_number, welcome_comment, installation_id
                )
                if result:
                    logger.info("setup_awareness_posted", pr_number=pr_number, repo=task.repo_full_name)
                else:
                    logger.warning("setup_awareness_post_failed", pr_number=pr_number, repo=task.repo_full_name)
        except Exception as comment_err:
            logger.warning(
                "setup_awareness_post_failed",
                pr_number=pr_number,
                repo=task.repo_full_name,
                error=str(comment_err),
            )
        finally:
            current_lock, waiting_tasks = self._setup_awareness_locks.get(lock_key, (lock, 1))
            if current_lock is lock:
                if waiting_tasks == 1:
                    self._setup_awareness_locks.pop(lock_key, None)
                else:
                    self._setup_awareness_locks[lock_key] = (lock, waiting_tasks - 1)

    def _compute_violations_hash(self, violations: list[Violation]) -> str:
        """Compute a stable hash of violations for deduplication.

        Uses rule_description + message + severity to create a fingerprint.
        This allows detecting identical violation sets regardless of delivery_id.
        """
        # Sort violations to ensure consistent ordering
        sorted_violations = sorted(
            violations,
            key=lambda v: (v.rule_description or "", v.message, v.severity.value if v.severity else ""),
        )

        # Build signature from key fields
        signature_parts = []
        for v in sorted_violations:
            signature_parts.append(f"{v.rule_description}|{v.message}|{v.severity.value if v.severity else ''}")

        signature_string = "::".join(signature_parts)
        return hashlib.sha256(signature_string.encode()).hexdigest()[:12]  # Use first 12 chars for readability

    async def _has_duplicate_comment(
        self,
        repo: str,
        pr_number: int,
        violations_hash: str,
        installation_id: int,
        existing_comments: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Check if a comment with the same violations hash already exists.

        Looks for the hidden HTML marker in existing comments to detect duplicates.
        """
        marker = f"<!-- watchflow-violations-hash:{violations_hash} -->"
        if existing_comments is not None:
            return self._has_managed_comment_marker_in_comments(existing_comments, marker)

        duplicate = await self._has_managed_comment_marker(repo, pr_number, marker, installation_id)
        if duplicate is None:
            logger.warning("Error checking for duplicate comments. Proceeding with post.")
            # Fail open for violation reporting so an API-read failure does not
            # hide enforcement feedback.
            return False
        return duplicate

    async def _has_managed_comment_marker(
        self, repo: str, pr_number: int, marker: str, installation_id: int
    ) -> bool | None:
        """Return whether Watchflow already posted ``marker`` on this PR.

        ``None`` means the GitHub lookup failed. Callers choose whether that
        failure should fail open (violations) or fail closed (onboarding).
        """
        try:
            existing_comments = await self.github_client.get_issue_comments(repo, pr_number, installation_id)
            if existing_comments is None:
                return None
            return self._has_managed_comment_marker_in_comments(existing_comments, marker)
        except Exception as e:
            logger.warning(f"Error checking for managed comment marker: {e}")
            return None

    @staticmethod
    def _is_watchflow_comment(comment: dict[str, Any]) -> bool:
        expected_author = f"{config.github.app_name}[bot]"
        return (comment.get("user") or {}).get("login", "").lower() == expected_author.lower()

    def _has_managed_comment_marker_in_comments(self, comments: list[dict[str, Any]], marker: str) -> bool:
        return any(
            marker in str(comment.get("body") or "") and self._is_watchflow_comment(comment) for comment in comments
        )

    def _has_setup_awareness_comment(self, comments: list[dict[str, Any]]) -> bool:
        """Recognize marked comments and the legacy setup message emitted before markers existed."""
        legacy_heading = "watchflow rules not configured"
        return any(
            self._is_watchflow_comment(comment)
            and (
                github_formatter.RULES_NOT_CONFIGURED_COMMENT_MARKER in str(comment.get("body") or "")
                or legacy_heading in str(comment.get("body") or "").lower()
            )
            for comment in comments
        )

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Extract data available in webhook payload."""
        return self.enricher.prepare_webhook_data(task)

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Fetch data not available in webhook."""
        pr_number = task.payload.get("pull_request", {}).get("number")
        if not pr_number or not task.installation_id:
            return {}
        return await self.enricher.fetch_api_data(task.repo_full_name, pr_number, task.installation_id)
