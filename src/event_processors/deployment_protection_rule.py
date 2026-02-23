import logging
import time
from typing import Any

from src.agents import get_agent
from src.core.utils.retry import retry_async
from src.core.utils.timeout import execute_with_timeout
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.scheduler.deployment_scheduler import get_deployment_scheduler
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = 30.0


class DeploymentProtectionRuleProcessor(BaseEventProcessor):
    """Processor for deployment protection rule events using hybrid agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent
        self.engine_agent = get_agent("engine")

    def get_event_type(self) -> str:
        return "deployment_protection_rule"

    @staticmethod
    def _is_valid_callback_url(url: str | None) -> bool:
        return bool(url and isinstance(url, str) and url.strip().startswith("http"))

    @staticmethod
    def _is_valid_environment(env: str | None) -> bool:
        return bool(env and isinstance(env, str) and env.strip())

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()

        try:
            payload = task.payload

            environment = payload.get("environment")
            deployment = payload.get("deployment", {})
            deployment_id = deployment.get("id")
            deployment_callback_url = payload.get("deployment_callback_url")
            installation_id = task.installation_id
            repo_full_name = task.repo_full_name

            can_call_callback = self._is_valid_callback_url(deployment_callback_url) and self._is_valid_environment(
                environment
            )
            if not can_call_callback:
                logger.warning(
                    "deployment_status_skipped",
                    extra={
                        "operation": "deployment_protection_rule",
                        "deployment_id": deployment_id,
                        "environment": environment,
                        "reason": "invalid or missing callback_url or environment",
                    },
                )

            logger.info(
                "deployment_processing_start",
                extra={
                    "operation": "deployment_protection_rule",
                    "deployment_id": deployment_id,
                    "environment": environment,
                    "repo": repo_full_name,
                },
            )

            rules = await self.rule_provider.get_rules(repo_full_name, installation_id)

            if not rules:
                logger.info("No rules found for repository")
                if can_call_callback:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "No rules configured", installation_id
                    )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=1,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            deployment_rules = []
            for r in rules:
                if hasattr(r, "event_types"):
                    event_types = [et.value if hasattr(et, "value") else et for et in r.event_types]
                elif isinstance(r, dict):
                    event_types = r.get("event_types", [])
                else:
                    logger.error("rule_invalid", extra={"rule": str(r), "rule_type": type(r).__name__})
                    continue

                if "deployment" in event_types:
                    deployment_rules.append(r)

            if not deployment_rules:
                logger.info("No deployment rules found")
                if can_call_callback:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "No deployment rules configured", installation_id
                    )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=1,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            logger.info("Found %d applicable rules for deployment", len(deployment_rules))

            formatted_rules = self._convert_rules_to_new_format(deployment_rules)

            event_data = {
                "deployment": deployment,
                "triggering_user": deployment.get("creator", {}),
                "repository": payload.get("repository", {}),
                "organization": payload.get("organization", {}),
                "event_id": payload.get("event_id"),
                "timestamp": payload.get("timestamp"),
                "installation": {"id": task.installation_id},
                "github_client": self.github_client,  # Pass GitHub client for validators
            }

            analysis_result = await execute_with_timeout(
                self.engine_agent.execute(
                    event_type="deployment",
                    event_data=event_data,
                    rules=formatted_rules,
                ),
                timeout=AGENT_TIMEOUT_SECONDS,
                timeout_message=f"Agent execution timed out after {AGENT_TIMEOUT_SECONDS}s",
            )

            violations = []
            if analysis_result.data and "evaluation_result" in analysis_result.data:
                eval_result = analysis_result.data["evaluation_result"]
                if hasattr(eval_result, "violations"):
                    violations = [
                        v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in eval_result.violations
                    ]

            logger.info("Analysis completed: %d violations", len(violations))
            for violation in violations:
                logger.info("Violation: %s", violation.get("message", "Unknown violation"))

            if not violations:
                if can_call_callback:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "All deployment rules passed", installation_id
                    )
                logger.info("All rules passed, deployment approved")
            else:
                time_based_violations = self._check_time_based_violations(violations)
                if time_based_violations and can_call_callback:
                    await get_deployment_scheduler().add_pending_deployment(
                        {
                            "deployment_id": deployment_id,
                            "repo": task.repo_full_name,
                            "installation_id": task.installation_id,
                            "environment": environment or deployment.get("environment"),
                            "event_data": payload,
                            "rules": deployment_rules,
                            "violations": violations,
                            "time_based_violations": time_based_violations,
                            "created_at": time.time(),
                            "callback_url": deployment_callback_url,
                        }
                    )
                    logger.info("Time-based violations detected, added to scheduler for re-evaluation")

                if can_call_callback:
                    await self._reject_deployment(deployment_callback_url, environment, violations, installation_id)
                logger.info("Deployment rejected due to %d violations", len(violations))

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(
                "deployment_processing_complete",
                extra={
                    "operation": "deployment_protection_rule",
                    "deployment_id": deployment_id,
                    "environment": environment,
                    "processing_time_ms": processing_time,
                    "state": "approved" if not violations else "rejected",
                    "violations_count": len(violations),
                },
            )

            return ProcessingResult(
                success=(not violations), violations=violations, api_calls_made=1, processing_time_ms=processing_time
            )

        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            exc_payload = task.payload
            exc_deployment = exc_payload.get("deployment", {})
            exc_deployment_id = exc_deployment.get("id")
            exc_callback_url = exc_payload.get("deployment_callback_url")
            exc_environment = exc_payload.get("environment")
            logger.error(
                "deployment_processing_error",
                extra={
                    "operation": "deployment_protection_rule",
                    "deployment_id": exc_deployment_id,
                    "error": str(e),
                    "processing_time_ms": processing_time,
                },
            )
            if self._is_valid_callback_url(exc_callback_url) and self._is_valid_environment(exc_environment):
                fallback_comment = "Processing failed. Approved as fallback to avoid indefinite blocking."
                await self._approve_deployment(
                    exc_callback_url, exc_environment, fallback_comment, task.installation_id
                )
                logger.info(
                    "deployment_fallback_approval",
                    extra={
                        "operation": "deployment_protection_rule",
                        "deployment_id": exc_deployment_id,
                        "reason": "exception during processing",
                    },
                )
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=0,
                processing_time_ms=processing_time,
                error=str(e),
            )

    @staticmethod
    def _check_time_based_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            v
            for v in violations
            if any(k in v.get("rule_description", "").lower() for k in ["hours", "weekend", "time", "day"])
        ]

    async def _send_deployment_review(
        self,
        callback_url: str,
        environment: str,
        state: str,
        comment: str,
        installation_id: int,
    ) -> None:
        async def _do_send() -> dict[str, Any] | None:
            return await self.github_client.review_deployment_protection_rule(
                callback_url=callback_url,
                environment=environment,
                state=state,
                comment=comment,
                installation_id=installation_id,
            )

        try:
            result = await retry_async(
                _do_send,
                max_retries=3,
                initial_delay=1.0,
                max_delay=30.0,
                exceptions=(Exception,),
            )
            if result is None:
                logger.error(
                    "deployment_review_failed",
                    extra={"operation": state, "environment": environment, "reason": "API returned None"},
                )
            else:
                logger.info("deployment_review_sent", extra={"operation": state, "environment": environment})
        except Exception as e:
            logger.error(
                "deployment_review_error",
                extra={"operation": state, "environment": environment, "error": str(e)},
            )

    async def _approve_deployment(self, callback_url: str, environment: str, comment: str, installation_id: int):
        await self._send_deployment_review(callback_url, environment, "approved", comment, installation_id)

    async def _reject_deployment(
        self, callback_url: str, environment: str, violations: list[dict[str, Any]], installation_id: int
    ):
        comment_text = self._format_violations_comment(violations)
        await self._send_deployment_review(callback_url, environment, "rejected", comment_text, installation_id)

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        formatted_rules = []
        for rule in rules:
            if isinstance(rule, dict):
                rule_dict = {
                    "description": rule.get("description", rule.get("rule_description", "")),
                    "enabled": rule.get("enabled", True),
                    "severity": rule.get("severity", "medium"),
                    "event_types": rule.get("event_types", []),
                    "parameters": rule.get("parameters", {}),
                }
            else:
                rule_dict = {
                    "description": getattr(rule, "description", ""),
                    "enabled": getattr(rule, "enabled", True),
                    "severity": (
                        rule.severity.value if hasattr(rule.severity, "value") else getattr(rule, "severity", "medium")
                    ),
                    "event_types": [
                        et.value if hasattr(et, "value") else et for et in getattr(rule, "event_types", [])
                    ],
                    "parameters": getattr(rule, "parameters", {}) or {},
                }
                if not rule_dict["parameters"] and hasattr(rule, "conditions"):
                    for condition in rule.conditions:
                        rule_dict["parameters"].update(getattr(condition, "parameters", {}))
            formatted_rules.append(rule_dict)
        return formatted_rules

    @staticmethod
    def _format_violations_comment(violations):
        text = "**Deployment Blocked - Rule Violations Detected**\n"
        for v in violations:
            rule_description = v.get("rule_description", v.get("rule", v.get("description", "Unknown")))
            text += f"**{rule_description}**\n"
            text += f"**Severity:** {v.get('severity', 'high').capitalize()}\n"
            text += f"**Issue:** {v.get('message', '')}\n"
            text += f"**Solution:** {v.get('how_to_fix', 'See documentation.')}\n"
        text += "\n---\n*This review was performed automatically by Watchflow.*"
        return text

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        return {}

    def _get_rule_provider(self):
        from src.rules.loaders.github_loader import github_rule_loader

        return github_rule_loader
