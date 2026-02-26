import time
from typing import Any

import structlog

from src.agents.engine_agent.agent import RuleEngineAgent
from src.core.utils.event_filter import NULL_SHA
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = structlog.get_logger()


class PushProcessor(BaseEventProcessor):
    """Processor for push events using hybrid agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent
        self.engine_agent = RuleEngineAgent()

    def get_event_type(self) -> str:
        return "push"

    async def process(self, task: Task) -> ProcessingResult:
        """Process a push event using the agentic approach."""
        start_time = time.time()
        payload = task.payload
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])

        logger.info("=" * 80)
        logger.info("🚀 Processing PUSH event for {repo}", repo=task.repo_full_name)
        logger.info("   Ref: {ref}", ref=ref)
        logger.info("   Commits: {num_commits}", num_commits=len(commits))
        logger.info("=" * 80)

        if payload.get("deleted") or not payload.get("after") or payload.get("after") == NULL_SHA:
            logger.info(
                "push_skipped_deleted_or_empty",
                operation="process_push",
                subject_ids={"repo": task.repo_full_name, "ref": ref},
                decision="skip",
                latency_ms=int((time.time() - start_time) * 1000),
            )
            return ProcessingResult(
                success=True,
                violations=[],
                api_calls_made=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Prepare event_data for the agent
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

        # Get rules for the repository
        rules = await self.rule_provider.get_rules(task.repo_full_name, task.installation_id)

        if not rules:
            logger.info("no_rules_found", repo=task.repo_full_name)
            return ProcessingResult(
                success=True, violations=[], api_calls_made=1, processing_time_ms=int((time.time() - start_time) * 1000)
            )

        logger.info("rules_loaded", num_rules=len(rules))

        # Convert rules to the new format expected by the agent
        formatted_rules = self._convert_rules_to_new_format(rules)

        # Run agentic analysis using the instance
        result = await self.engine_agent.execute(event_type="push", event_data=event_data, rules=formatted_rules)

        violations = result.data.get("violations", [])

        processing_time = int((time.time() - start_time) * 1000)

        # Post results to GitHub (create check run)
        api_calls = 1  # Initial rule fetch
        if violations:
            await self._create_check_run(task, violations)
            api_calls += 1

        # Summary
        logger.info("=" * 80)
        logger.info(
            "push_processing_complete",
            operation="process_push",
            subject_ids={"repo": task.repo_full_name, "ref": ref},
            rules_evaluated=len(formatted_rules),
            violations_found=len(violations),
            api_calls=api_calls,
            latency_ms=processing_time,
        )

        if violations:
            for i, violation in enumerate(violations, 1):
                logger.warning(
                    "violation_found",
                    num=i,
                    rule=violation.get("rule", "Unknown"),
                    severity=violation.get("severity", "medium"),
                    message=violation.get("message", ""),
                )
        else:
            logger.info("all_rules_passed", repo=task.repo_full_name)

        logger.info("=" * 80)

        return ProcessingResult(
            success=True, violations=violations, api_calls_made=api_calls, processing_time_ms=processing_time
        )

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

    async def _create_check_run(self, task: Task, violations: list[dict[str, Any]]):
        """Create a check run with violation results."""
        try:
            sha = task.payload.get("after")

            if not sha or sha == NULL_SHA:
                logger.warning(
                    "no_valid_sha",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name},
                    reason="likely branch deletion",
                )
                return

            # Determine check run status
            if violations:
                status = "completed"
                conclusion = "failure"
            else:
                status = "completed"
                conclusion = "success"

            # Format output
            output = self._format_check_run_output(violations)

            result = await self.github_client.create_check_run(
                repo=task.repo_full_name,
                sha=sha,
                name="Watchflow Rules",
                status=status,
                conclusion=conclusion,
                output=output,
                installation_id=task.installation_id,
            )

            if result:
                logger.info(
                    "check_run_created",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name, "sha": sha[:8]},
                    conclusion=conclusion,
                )
            else:
                logger.error(
                    "check_run_failed",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name, "sha": sha[:8]},
                )

        except Exception as e:
            logger.error(
                "check_run_error",
                operation="create_check_run",
                subject_ids={"repo": task.repo_full_name},
                error=str(e),
            )

    def _format_check_run_output(self, violations: list[dict[str, Any]]) -> dict[str, Any]:
        """Format violations for check run output."""
        if not violations:
            return {
                "title": "All rules passed",
                "summary": "✅ No rule violations detected",
                "text": "All configured rules in `.watchflow/rules.yaml` have passed successfully.",
            }

        # Group violations by severity
        severity_groups = {"critical": [], "high": [], "medium": [], "low": []}

        for violation in violations:
            severity = violation.get("severity", "medium")
            severity_groups[severity].append(violation)

        # Build summary
        summary_parts = []
        for severity in ["critical", "high", "medium", "low"]:
            if severity_groups[severity]:
                count = len(severity_groups[severity])
                summary_parts.append(f"{count} {severity}")

        summary = f"🚨 {len(violations)} violations found: {', '.join(summary_parts)}"

        # Build detailed text
        text = "# Watchflow Rule Violations\n\n"

        for severity in ["critical", "high", "medium", "low"]:
            if severity_groups[severity]:
                severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")

                text += f"## {severity_emoji} {severity.title()} Severity\n\n"

                for violation in severity_groups[severity]:
                    text += f"### {violation.get('rule_description', 'Unknown Rule')}\n"
                    text += f"Rule validation failed with severity: **{violation.get('severity', 'medium')}**\n"
                    if violation.get("suggestion"):
                        text += f"*How to fix: {violation.get('suggestion')}*\n"
                    text += "\n"

        text += "---\n"
        text += "*To configure rules, edit the `.watchflow/rules.yaml` file in this repository.*"

        return {"title": f"{len(violations)} rule violations found", "summary": summary, "text": text}
