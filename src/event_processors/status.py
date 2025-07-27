import logging
import time
from typing import Any

from src.agents.engine_agent.agent import RuleEngineAgent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)


class StatusProcessor(BaseEventProcessor):
    """Processor for status events using hybrid agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent
        self.engine_agent = RuleEngineAgent()

    def get_event_type(self) -> str:
        return "status"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        payload = task.payload
        status = payload.get("status", {})

        # Ignore successful statuses for performance unless specifically configured
        state = status.get("state", "")
        if state == "success":
            logger.info(f"Status '{status.get('context', 'unknown')}' succeeded - no rule evaluation needed")
            return ProcessingResult(
                success=True, violations=[], api_calls_made=0, processing_time_ms=int((time.time() - start_time) * 1000)
            )

        logger.info("=" * 80)
        logger.info(f"🚀 Processing STATUS event for {task.repo_full_name}")
        logger.info(f"   Context: {status.get('context')}")
        logger.info(f"   State: {state}")
        logger.info(f"   Description: {status.get('description', '')}")
        logger.info("=" * 80)

        # Prepare event_data for the agent
        event_data = {
            "status": status,
            "repository": payload.get("repository", {}),
            "organization": payload.get("organization", {}),
            "commit": payload.get("commit", {}),
            "branches": payload.get("branches", []),
            "event_id": payload.get("event_id"),
            "timestamp": payload.get("timestamp"),
        }

        # Fetch rules
        rules = await self.rule_provider.get_rules(task.repo_full_name, task.installation_id)

        # Convert rules to the new format expected by the agent
        formatted_rules = self._convert_rules_to_new_format(rules)

        # Filter rules that apply to status events
        status_rules = [rule for rule in formatted_rules if "status" in rule.get("event_types", [])]

        if not status_rules:
            logger.info("No rules configured for status events")
            return ProcessingResult(
                success=True, violations=[], api_calls_made=1, processing_time_ms=int((time.time() - start_time) * 1000)
            )

        # Run agentic analysis using the instance
        result = await self.engine_agent.execute(
            event_type="status",
            event_data=event_data,
            rules=status_rules,
        )

        violations = result.data.get("violations", [])

        logger.info("=" * 80)
        logger.info(f"🏁 STATUS processing completed in {int((time.time() - start_time) * 1000)}ms")
        logger.info(f"   Violations: {len(violations)}")
        if violations:
            logger.warning("🚨 VIOLATION SUMMARY:")
            for i, violation in enumerate(violations, 1):
                logger.warning(
                    f"   {i}. {violation.get('rule_name', 'Unknown')} ({violation.get('severity', 'medium')})"
                )
                logger.warning(f"      {violation.get('message', '')}")
        logger.info("=" * 80)

        return ProcessingResult(
            success=(not violations),
            violations=violations,
            api_calls_made=1,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        """Convert Rule objects to the new flat schema format."""
        formatted_rules = []

        for rule in rules:
            # Convert Rule object to dict format
            rule_dict = {
                "id": rule.id,
                "name": rule.name,
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
        status = task.payload.get("status", {})
        return {
            "event_type": "status",
            "repo_full_name": task.repo_full_name,
            "status": {
                "id": status.get("id"),
                "context": status.get("context"),
                "state": status.get("state"),
                "description": status.get("description"),
                "target_url": status.get("target_url"),
                "created_at": status.get("created_at"),
                "updated_at": status.get("updated_at"),
            },
            "commit": task.payload.get("commit", {}),
            "branches": task.payload.get("branches", []),
        }

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from GitHub API calls."""
        return {}
