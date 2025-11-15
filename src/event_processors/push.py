import logging
import time
from typing import Any

from src.agents import get_agent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)


class PushProcessor(BaseEventProcessor):
    """Processor for push events using hybrid agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent
        self.engine_agent = get_agent("engine")

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
            logger.info("No rules found for this repository")
            return ProcessingResult(
                success=True, violations=[], api_calls_made=1, processing_time_ms=int((time.time() - start_time) * 1000)
            )

        logger.info(f"📋 Loaded {len(rules)} rules for evaluation")

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
        logger.info(f"🏁 PUSH processing completed in {processing_time}ms")
        logger.info(f"   Rules evaluated: {len(formatted_rules)}")
        logger.info(f"   Violations found: {len(violations)}")
        logger.info(f"   API calls made: {api_calls}")

        if violations:
            logger.warning("🚨 VIOLATION SUMMARY:")
            for i, violation in enumerate(violations, 1):
                logger.warning(f"   {i}. {violation.get('rule', 'Unknown')} ({violation.get('severity', 'medium')})")
                logger.warning(f"      {violation.get('message', '')}")
        else:
            logger.info("✅ All rules passed - no violations detected!")

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
            # head_commit = task.payload.get("head_commit")
            sha = task.payload.get("after")  # Use 'after' SHA instead of head_commit.id

            if not sha or sha == "0000000000000000000000000000000000000000":
                logger.warning("No valid commit SHA found (likely branch deletion), skipping check run creation")
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
                logger.info(f"✅ Successfully created check run for commit {sha[:8]} with conclusion: {conclusion}")
            else:
                logger.error(f"❌ Failed to create check run for commit {sha[:8]}")

        except Exception as e:
            logger.error(f"Error creating check run: {e}")

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
