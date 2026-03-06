import logging
import time
from typing import Any

from src.agents import get_agent
from src.api.recommendations import get_suggested_rules_from_repo
from src.core.config import config
from src.core.models import Severity, Violation
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.integrations.github.check_runs import CheckRunManager
from src.rules.ai_rules_scan import is_relevant_push
from src.tasks.task_queue import Task


logger = logging.getLogger(__name__)


class PushProcessor(BaseEventProcessor):
    """Processor for push events using hybrid agentic rule evaluation."""

    def __init__(self) -> None:
        super().__init__()

        self.engine_agent = get_agent("engine")

        self.check_run_manager = CheckRunManager(self.github_client)

    def get_event_type(self) -> str:
        return "push"

    async def process(self, task: Task) -> ProcessingResult:
        """Process a push event using the agentic approach."""
        start_time = time.time()
        payload = task.payload
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])

        logger.info("=" * 80)
        logger.info(f"🚀 Processing PUSH event for {task.repo_full_name}")
        logger.info(f"   Ref: {ref}")
        logger.info(f"   Commits: {len(commits)}")
        logger.info("=" * 80)

        event_data = {
            "push": {
                "ref": ref,
                "commits": commits,
                "head_commit": payload.get("head_commit", {}),
                "before": payload.get("before"),
                "after": payload.get("after"),
            },
            "triggering_user": {"login": payload.get("pusher", {}).get("name")},
            "repository": payload.get("repository", {}),
            "organization": payload.get("organization", {}),
            "event_id": payload.get("event_id"),
            "timestamp": payload.get("timestamp"),
        }

        if not task.installation_id:
            logger.error("No installation ID found in task")
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error="No installation ID found",
            )

        # Agentic: scan repo only when relevant (default branch or touched rule files)
        # Use the branch that was pushed so we scan that branch's file content, not main.
        if is_relevant_push(task.payload):
            scan_start = time.time()
            github_token = await self.github_client.get_installation_access_token(task.installation_id)
            if not github_token:
                latency_ms = int((time.time() - scan_start) * 1000)
                logger.warning(
                    "suggested_rules_scan",
                    operation="suggested_rules_scan",
                    subject_ids={"repo": task.repo_full_name, "installation": task.installation_id},
                    decision="skipped",
                    latency_ms=latency_ms,
                    reason="No installation token",
                )
            else:
                try:
                    push_ref = payload.get("ref")  # e.g. refs/heads/feature-x
                    rules_yaml, rules_count, ambiguous, rule_sources = await get_suggested_rules_from_repo(
                        task.repo_full_name, task.installation_id, github_token, ref=push_ref
                    )
                    latency_ms = int((time.time() - scan_start) * 1000)
                    from_mapping = sum(1 for s in rule_sources if s == "mapping") if rule_sources else 0
                    from_agent = sum(1 for s in rule_sources if s == "agent") if rule_sources else 0
                    preview = (rules_yaml[:200] + "…") if rules_yaml and len(rules_yaml) > 200 else (rules_yaml or "")
                    logger.info(
                        "suggested_rules_scan",
                        operation="suggested_rules_scan",
                        subject_ids={"repo": task.repo_full_name, "ref": push_ref or "default"},
                        decision="found" if rules_count > 0 else "none",
                        latency_ms=latency_ms,
                        rules_count=rules_count,
                        ambiguous_count=len(ambiguous),
                        from_mapping=from_mapping,
                        from_agent=from_agent,
                        preview=preview,
                    )
                    if rules_count > 0:
                        await self._create_pr_with_suggested_rules(
                            task=task,
                            github_token=github_token,
                            rules_yaml=rules_yaml,
                            push_sha=payload.get("after") or payload.get("head_commit", {}).get("sha"),
                        )
                except Exception as e:
                    latency_ms = int((time.time() - scan_start) * 1000)
                    logger.warning(
                        "Suggested rules scan failed",
                        operation="suggested_rules_scan",
                        subject_ids={"repo": task.repo_full_name},
                        decision="failure",
                        latency_ms=latency_ms,
                        error=str(e),
                    )
        else:
            logger.info(
                "suggested_rules_scan",
                operation="suggested_rules_scan",
                subject_ids={"repo": task.repo_full_name, "ref": task.payload.get("ref")},
                decision="skip",
                reason="Push not relevant",
            )

        rules_optional = await self.rule_provider.get_rules(task.repo_full_name, task.installation_id)
        rules = rules_optional if rules_optional is not None else []

        if not rules:
            logger.info("No rules found for this repository")
            return ProcessingResult(
                success=True, violations=[], api_calls_made=1, processing_time_ms=int((time.time() - start_time) * 1000)
            )

        logger.info(f"📋 Loaded {len(rules)} rules for evaluation")

        formatted_rules = self._convert_rules_to_new_format(rules)

        result = await self.engine_agent.execute(event_type="push", event_data=event_data, rules=formatted_rules)

        raw_violations = result.data.get("violations", [])
        violations: list[Violation] = []

        for v in raw_violations:
            try:
                # Map raw fields to Violation model
                severity_str = v.get("severity", "medium").lower()
                try:
                    severity = Severity(severity_str)
                except ValueError:
                    severity = Severity.MEDIUM

                violation = Violation(
                    rule_description=v.get("rule", "Unknown Rule"),
                    rule_id=v.get("rule_id"),
                    severity=severity,
                    message=v.get("message", "No message provided"),
                    how_to_fix=v.get("suggestion"),
                    details=v,
                )
                violations.append(violation)
            except Exception as e:
                logger.error(f"Error converting violation: {e}")

        processing_time = int((time.time() - start_time) * 1000)

        api_calls = 1

        sha = payload.get("after")
        if not sha or sha == "0000000000000000000000000000000000000000":
            logger.warning("No valid commit SHA found, skipping check run")
        else:
            # Ensure installation_id is not None before passing to check_run_manager
            if task.installation_id is None:
                logger.warning("Missing installation_id for push event, cannot create check run")
            else:
                if violations:
                    await self.check_run_manager.create_check_run(
                        repo=task.repo_full_name,
                        sha=sha,
                        installation_id=task.installation_id,
                        violations=violations,
                    )
                    api_calls += 1
                else:
                    # Create passing check run if no violations (optional but good practice)
                    await self.check_run_manager.create_check_run(
                        repo=task.repo_full_name,
                        sha=sha,
                        installation_id=task.installation_id,
                        violations=[],
                        conclusion="success",
                    )
                    api_calls += 1

        logger.info("=" * 80)

        logger.info(f"🏁 PUSH processing completed in {processing_time}ms")
        logger.info(f"   Rules evaluated: {len(formatted_rules)}")
        logger.info(f"   Violations found: {len(violations)}")
        logger.info(f"   API calls made: {api_calls}")
        logger.info("=" * 80)

        return ProcessingResult(
            success=True, violations=violations, api_calls_made=api_calls, processing_time_ms=processing_time
        )

    async def _create_pr_with_suggested_rules(
        self,
        task: Task,
        github_token: str,
        rules_yaml: str,
        push_sha: str | None,
    ) -> None:
        """
        Self-improving loop: create a branch with proposed .watchflow/rules.yaml and open a PR
        against the default branch so the team can review the auto-generated rules.
        """
        repo_full_name = task.repo_full_name
        installation_id = task.installation_id
        if not installation_id or not push_sha or len(push_sha) < 7:
            logger.warning("create_pr_skipped: missing installation_id or push_sha for repo %s", repo_full_name)
            return
        branch_suffix = push_sha[:7]
        branch_name = f"watchflow/update-rules-{branch_suffix}"
        file_path = f"{config.repo_config.base_path}/{config.repo_config.rules_file}"

        try:
            repo_data, repo_error = await self.github_client.get_repository(
                repo_full_name, installation_id=installation_id, user_token=github_token
            )
            if repo_error:
                logger.warning(
                    "create_pr_get_repo_failed: repo=%s status=%s message=%s",
                    repo_full_name,
                    repo_error.get("status"),
                    repo_error.get("message"),
                )
                return
            default_branch = repo_data.get("default_branch") or "main"

            base_sha = await self.github_client.get_git_ref_sha(
                repo_full_name, ref=default_branch, installation_id=installation_id, user_token=github_token
            )
            if not base_sha:
                logger.warning("create_pr_no_base_sha: repo=%s base=%s", repo_full_name, default_branch)
                return

            branch_result = await self.github_client.create_git_ref(
                repo_full_name,
                ref=branch_name,
                sha=base_sha,
                installation_id=installation_id,
                user_token=github_token,
            )
            if not branch_result:
                existing_sha = await self.github_client.get_git_ref_sha(
                    repo_full_name, ref=branch_name, installation_id=installation_id, user_token=github_token
                )
                if not existing_sha:
                    logger.warning("create_pr_branch_failed: repo=%s branch=%s", repo_full_name, branch_name)
                    return
                logger.info("create_pr_branch_exists: repo=%s branch=%s", repo_full_name, branch_name)

            file_result = await self.github_client.create_or_update_file(
                repo_full_name,
                path=file_path,
                content=rules_yaml,
                message="chore: update .watchflow/rules.yaml from AI rule files",
                branch=branch_name,
                installation_id=installation_id,
                user_token=github_token,
            )
            if not file_result:
                logger.warning(
                    "create_pr_file_failed: repo=%s path=%s branch=%s",
                    repo_full_name,
                    file_path,
                    branch_name,
                )
                return

            pr_body = (
                "This PR was auto-generated by Watchflow because AI rule files (e.g. `rules.md`, "
                "`*guidelines*.md`) were updated. It proposes updating `.watchflow/rules.yaml` with "
                "the translated rules so your team can review the auto-generated constraints before merging."
            )
            pr_result = await self.github_client.create_pull_request(
                repo_full_name,
                title="Watchflow: proposed rules from AI rule files",
                head=branch_name,
                base=default_branch,
                body=pr_body,
                installation_id=installation_id,
                user_token=github_token,
            )
            if not pr_result:
                logger.warning(
                    "create_pr_pull_failed: repo=%s head=%s base=%s",
                    repo_full_name,
                    branch_name,
                    default_branch,
                )
                return
            pr_url = pr_result.get("html_url", "")
            pr_number = pr_result.get("number", 0)
            logger.info(
                "create_pr_success: repo=%s pr #%s %s branch=%s base=%s",
                repo_full_name,
                pr_number,
                pr_url,
                branch_name,
                default_branch,
            )
        except Exception as e:
            logger.warning("create_pr_with_suggested_rules_failed: repo=%s error=%s", repo_full_name, e)

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        """Convert Rule objects to the new flat schema format."""
        formatted_rules = []

        for rule in rules:
            # Convert Rule object to dict format
            rule_dict = {
                "description": rule.description,
                "enabled": rule.enabled,
                "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                "event_types": [et.value if hasattr(et, "value") else et for et in rule.event_types],
                "parameters": rule.parameters if hasattr(rule, "parameters") else {},
            }

            # If no parameters field, try to extract from conditions (backward compatibility)
            if not rule_dict["parameters"] and hasattr(rule, "conditions"):
                for condition in rule.conditions:
                    rule_dict["parameters"].update(condition.parameters)

            formatted_rules.append(rule_dict)

        return formatted_rules

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from webhook payload."""
        return {
            "event_type": "push",
            "repo_full_name": task.repo_full_name,
            "ref": task.payload.get("ref"),
            "pusher": task.payload.get("pusher", {}),
            "commits": task.payload.get("commits", []),
            "head_commit": task.payload.get("head_commit", {}),
            "before": task.payload.get("before"),
            "after": task.payload.get("after"),
            "forced": task.payload.get("forced", False),
            "deleted": task.payload.get("deleted", False),
            "created": task.payload.get("created", False),
        }

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from GitHub API calls."""
        return {}
