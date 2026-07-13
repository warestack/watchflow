import asyncio
import hashlib
import json
import time
from collections import Counter, defaultdict
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
        self._violation_comment_locks: dict[tuple[str, int], tuple[asyncio.Lock, int]] = {}
        self._violation_states: dict[tuple[str, int], list[dict[str, str]]] = {}
        self._violation_reports: dict[tuple[str, int], bool] = {}

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
            previous_violation_state, has_previous_violation_report = await self._get_previous_violation_state(
                task, sha, installation_id
            )
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

            if pr_number:
                await self._post_violations_to_github(
                    task, violations, previous_violation_state, has_previous_violation_report
                )
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
        self,
        task: Task,
        violations: list[Violation],
        previous_state: list[dict[str, str]] | None = None,
        has_previous_report: bool = False,
    ) -> None:
        """Keep comments immutable: create a snapshot first, then alert only on regressions."""
        pr_number = task.payload.get("pull_request", {}).get("number")
        installation_id = task.installation_id
        if not pr_number or not installation_id:
            return

        lock_key = (task.repo_full_name, pr_number)
        lock_entry = self._violation_comment_locks.get(lock_key)
        if lock_entry is None:
            lock, waiting_tasks = asyncio.Lock(), 0
        else:
            lock, waiting_tasks = lock_entry
        self._violation_comment_locks[lock_key] = (lock, waiting_tasks + 1)

        try:
            async with lock:
                effective_previous_state = self._violation_states.get(lock_key, previous_state)
                effective_has_previous_report = self._violation_reports.get(lock_key, has_previous_report)
                violations_hash = self._compute_violations_hash(violations)
                current_state = github_formatter.build_violations_state(violations)
                if violations and not effective_has_previous_report:
                    snapshot = github_formatter.format_violations_comment(
                        violations, content_hash=violations_hash, current_report=True
                    )
                    created = await self.github_client.create_pull_request_comment(
                        task.repo_full_name, pr_number, snapshot, installation_id
                    )
                    if created:
                        effective_has_previous_report = True
                        logger.info("violations_snapshot_posted", repo=task.repo_full_name, pr_number=pr_number)
                    else:
                        logger.warning("violations_snapshot_post_failed", repo=task.repo_full_name, pr_number=pr_number)
                elif effective_previous_state is not None:
                    added, worsened = self._find_violation_regressions(effective_previous_state, violations)
                    if added or worsened:
                        alert = github_formatter.format_violation_regression_alert(
                            self._describe_violation_trigger(task), added, worsened, violations
                        )
                        alert_created = await self.github_client.create_pull_request_comment(
                            task.repo_full_name, pr_number, alert, installation_id
                        )
                        if alert_created:
                            logger.info(
                                "violations_regression_alert_posted",
                                repo=task.repo_full_name,
                                pr_number=pr_number,
                                added_count=len(added),
                                worsened_count=len(worsened),
                            )
                        else:
                            logger.warning(
                                "violations_regression_alert_failed", repo=task.repo_full_name, pr_number=pr_number
                            )
                    else:
                        logger.info(
                            "violations_comment_skipped_non_regression", repo=task.repo_full_name, pr_number=pr_number
                        )
                self._violation_states[lock_key] = current_state
                self._violation_reports[lock_key] = effective_has_previous_report
        except Exception as error:
            logger.warning(
                "violations_comment_sync_failed", repo=task.repo_full_name, pr_number=pr_number, error=str(error)
            )
        finally:
            current_lock, waiting_tasks = self._violation_comment_locks.get(lock_key, (lock, 1))
            if current_lock is lock:
                if waiting_tasks == 1:
                    self._violation_comment_locks.pop(lock_key, None)
                else:
                    self._violation_comment_locks[lock_key] = (lock, waiting_tasks - 1)

    async def _get_previous_violation_state(
        self, task: Task, sha: str | None, installation_id: int
    ) -> tuple[list[dict[str, str]] | None, bool]:
        """Load the last state from Checks, falling back to Watchflow's immutable comment snapshots."""
        pr_number = task.payload.get("pull_request", {}).get("number")
        if not pr_number:
            return None, False
        lock_key = (task.repo_full_name, pr_number)
        if lock_key in self._violation_states:
            state = self._violation_states[lock_key]
            return state, self._violation_reports.get(lock_key, bool(state))

        reference_sha = sha
        before_sha = task.payload.get("before")
        if task.payload.get("action") == "synchronize" and isinstance(before_sha, str) and before_sha.strip("0"):
            reference_sha = before_sha
        check_state: list[dict[str, str]] | None = None
        if reference_sha:
            try:
                check_runs = await self.github_client.get_check_runs(
                    task.repo_full_name, reference_sha, installation_id
                )
                for check_run in sorted(check_runs or [], key=lambda item: int(item.get("id", 0)), reverse=True):
                    if str(check_run.get("name", "")).lower() not in {"watchflow rules", "watchflow-rules"}:
                        continue
                    output = check_run.get("output") or {}
                    state = github_formatter.parse_violations_state_marker(str(output.get("text") or ""))
                    if state is not None:
                        # A non-empty Check is enough to establish that violations were
                        # already reported. For a passing Check, inspect comments below:
                        # it may precede the first violations report on this PR.
                        if state:
                            return state, True
                        check_state = state
                        break
            except Exception as error:
                logger.warning(
                    "violations_state_check_lookup_failed",
                    repo=task.repo_full_name,
                    pr_number=pr_number,
                    error=str(error),
                )

        try:
            comments = await self.github_client.get_issue_comments(task.repo_full_name, pr_number, installation_id)
            if comments is None:
                return None, True
            for comment in reversed(comments):
                if not self._is_watchflow_comment(comment):
                    continue
                body = str(comment.get("body") or "")
                state = github_formatter.parse_violations_state_marker(body)
                if state is not None:
                    return check_state if check_state is not None else state, True
                if github_formatter.VIOLATIONS_HASH_MARKER_PATTERN.search(body):
                    return check_state, True
        except Exception as error:
            logger.warning(
                "violations_state_comment_lookup_failed",
                repo=task.repo_full_name,
                pr_number=pr_number,
                error=str(error),
            )
            return None, True
        return check_state, False

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)

    @staticmethod
    def _violation_identity(violation: Violation) -> str:
        return violation.rule_id or violation.rule_description

    def _find_violation_regressions(
        self, previous_state: list[dict[str, str]], violations: list[Violation]
    ) -> tuple[list[Violation], list[tuple[Violation, str]]]:
        """Return violations added or raised in severity since the canonical report."""
        previous_by_identity: dict[str, list[str]] = defaultdict(list)
        for item in previous_state:
            previous_by_identity[item["id"]].append(item["severity"])
        current_by_identity: dict[str, list[Violation]] = defaultdict(list)
        for violation in violations:
            current_by_identity[self._violation_identity(violation)].append(violation)

        added: list[Violation] = []
        worsened: list[tuple[Violation, str]] = []
        for identity in set(previous_by_identity) | set(current_by_identity):
            previous = previous_by_identity[identity]
            current = current_by_identity[identity]
            previous_counts = Counter(previous)
            unmatched_current: list[Violation] = []
            for violation in current:
                severity = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
                if previous_counts[severity]:
                    previous_counts[severity] -= 1
                else:
                    unmatched_current.append(violation)
            unmatched_previous = [severity for severity, count in previous_counts.items() for _ in range(count)]
            # Pair the most severe findings first. This avoids treating an
            # improvement of a high finding plus resolution of a low finding
            # as a false increase from low to medium when a rule emits more
            # than one finding with the same identity.
            unmatched_current.sort(
                key=lambda violation: self._severity_rank(
                    violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
                ),
                reverse=True,
            )
            unmatched_previous.sort(key=self._severity_rank, reverse=True)
            for previous_severity, violation in zip(unmatched_previous, unmatched_current, strict=False):
                current_severity = (
                    violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
                )
                if self._severity_rank(current_severity) > self._severity_rank(previous_severity):
                    worsened.append((violation, previous_severity))
            added.extend(unmatched_current[len(unmatched_previous) :])
        return added, worsened

    @staticmethod
    def _describe_violation_trigger(task: Task) -> str:
        event_type = getattr(task, "event_type", "")
        event_type = getattr(event_type, "value", event_type)
        event_type = event_type.lower() if isinstance(event_type, str) else ""
        action = task.payload.get("action", "")
        if event_type == "pull_request_review":
            reviewer = task.payload.get("review", {}).get("user", {}).get("login")
            return f"a review was {action}{f' by @{reviewer}' if reviewer else ''}"
        if event_type == "pull_request_review_thread":
            return f"a review thread was {action}"
        return {
            "synchronize": "new commits were pushed",
            "edited": "the pull request details were edited",
            "opened": "the pull request was opened",
            "reopened": "the pull request was reopened",
            "ready_for_review": "the pull request was marked ready for review",
        }.get(action, "the pull request was re-evaluated")

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

        Uses the rendered violation fields to create a fingerprint.
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
            details = json.dumps(v.details, sort_keys=True, default=str, separators=(",", ":"))
            signature_parts.append(
                f"{v.rule_id or ''}|{v.rule_description}|{v.message}|{v.severity.value if v.severity else ''}|"
                f"{v.how_to_fix or ''}|{details}"
            )

        signature_string = "::".join(signature_parts)
        return hashlib.sha256(signature_string.encode()).hexdigest()[:12]  # Use first 12 chars for readability

    @staticmethod
    def _is_watchflow_comment(comment: dict[str, Any]) -> bool:
        expected_author = f"{config.github.app_name}[bot]"
        return (comment.get("user") or {}).get("login", "").lower() == expected_author.lower()

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
