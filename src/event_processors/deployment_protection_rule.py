import asyncio
import time
from typing import Any

import structlog

from src.agents.engine_agent.agent import RuleEngineAgent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.scheduler.deployment_scheduler import get_deployment_scheduler
from src.tasks.task_queue import Task

logger = structlog.get_logger()


AGENT_TIMEOUT_SECONDS = 30


class DeploymentProtectionRuleProcessor(BaseEventProcessor):
    """Processor for deployment protection rule events using hybrid agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent
        self.engine_agent = RuleEngineAgent()

    def get_event_type(self) -> str:
        return "deployment_protection_rule"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        repo_full_name = task.repo_full_name

        try:
            payload = task.payload

            environment = payload.get("environment")
            deployment = payload.get("deployment", {})
            deployment_id = deployment.get("id")
            deployment_callback_url = payload.get("deployment_callback_url")
            installation_id = task.installation_id
            repo_full_name = task.repo_full_name

            logger.info("=" * 80)
            logger.info(
                "processing_deployment_protection_rule",
                operation="process",
                subject_ids={"repo": repo_full_name, "deployment_id": deployment_id},
                environment=environment,
            )
            logger.info("=" * 80)

            rules = await self.rule_provider.get_rules(repo_full_name, installation_id)

            if not rules:
                logger.info("no_rules_found", repo=repo_full_name)
                if deployment_callback_url and environment:
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
                    logger.error(
                        "invalid_rule_type",
                        operation="process",
                        rule_type=str(type(r)),
                    )
                    continue

                if "deployment" in event_types:
                    deployment_rules.append(r)

            if not deployment_rules:
                logger.info("no_deployment_rules_found", repo=repo_full_name)
                if deployment_callback_url and environment:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "No deployment rules configured", installation_id
                    )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=1,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            logger.info("deployment_rules_found", num_rules=len(deployment_rules))

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

            try:
                analysis_result = await asyncio.wait_for(
                    self.engine_agent.execute(
                        event_type="deployment",
                        event_data=event_data,
                        rules=formatted_rules,
                    ),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "agent_execution_timeout",
                    operation="process",
                    subject_ids={"repo": repo_full_name, "deployment_id": deployment_id},
                    timeout_seconds=AGENT_TIMEOUT_SECONDS,
                )
                if deployment_callback_url and environment:
                    await self._approve_deployment(
                        deployment_callback_url, 
                        environment, 
                        "Deployment approved due to evaluation timeout. Review rules for performance issues.", 
                        installation_id
                    )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=1,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            # Extract violations from AgentResult - same pattern as acknowledgment processor
            violations = []
            if analysis_result.data and "evaluation_result" in analysis_result.data:
                eval_result = analysis_result.data["evaluation_result"]
                if hasattr(eval_result, "violations"):
                    # Convert RuleViolation objects to dictionaries with defensive access
                    for violation in eval_result.violations:
                        violation_dict = {
                            "rule_description": getattr(violation, "rule_description", None),
                            "severity": getattr(violation, "severity", "medium"),
                            "message": getattr(violation, "message", ""),
                            "details": getattr(violation, "details", None),
                            "how_to_fix": getattr(violation, "how_to_fix", None),
                            "docs_url": getattr(violation, "docs_url", None),
                            "validation_strategy": getattr(violation, "validation_strategy", None),
                            "execution_time_ms": getattr(violation, "execution_time_ms", None),
                        }
                        if violation_dict["validation_strategy"] and hasattr(
                            violation_dict["validation_strategy"], "value"
                        ):
                            violation_dict["validation_strategy"] = violation_dict["validation_strategy"].value
                        violations.append(violation_dict)

            logger.info(
                "analysis_completed",
                operation="process",
                subject_ids={"repo": repo_full_name},
                violations_found=len(violations),
            )
            for violation in violations:
                logger.info("violation_found", message=violation.get("message", "Unknown violation"))

            if not violations:
                if deployment_callback_url and environment:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "All deployment rules passed", installation_id
                    )
                logger.info("all_rules_passed", repo=repo_full_name)
            else:
                time_based_violations = self._check_time_based_violations(violations)
                if time_based_violations:
                    await get_deployment_scheduler().add_pending_deployment(
                        {
                            "deployment_id": deployment_id,
                            "repo": task.repo_full_name,
                            "installation_id": task.installation_id,
                            "environment": deployment.get("environment"),
                            "event_data": payload,
                            "rules": deployment_rules,
                            "violations": violations,
                            "time_based_violations": time_based_violations,
                            "created_at": time.time(),
                            "callback_url": deployment_callback_url,
                        }
                    )
                    logger.info("time_based_violations_added_to_scheduler", num_violations=len(time_based_violations))

                if deployment_callback_url and environment:
                    await self._reject_deployment(deployment_callback_url, environment, violations, installation_id)
                logger.info("deployment_rejected", num_violations=len(violations))

            processing_time = int((time.time() - start_time) * 1000)
            logger.info("=" * 80)
            logger.info(
                "deployment_protection_complete",
                operation="process",
                subject_ids={"repo": repo_full_name, "deployment_id": deployment_id},
                state="approved" if not violations else "rejected",
                violations=len(violations),
                latency_ms=processing_time,
            )
            logger.info("=" * 80)

            return ProcessingResult(
                success=(not violations), violations=violations, api_calls_made=1, processing_time_ms=processing_time
            )

        except Exception as e:
            logger.error(
                "deployment_protection_error",
                operation="process",
                subject_ids={"repo": repo_full_name if "repo_full_name" in locals() else "unknown"},
                error=str(e),
            )
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    @staticmethod
    def _check_time_based_violations(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            v
            for v in violations
            if any(k in v.get("rule_description", "").lower() for k in ["hours", "weekend", "time", "day"])
        ]

    async def _approve_deployment(self, callback_url: str, environment: str, comment: str, installation_id: int):
        try:
            result = await self.github_client.review_deployment_protection_rule(
                callback_url=callback_url,
                environment=environment,
                state="approved",
                comment=f"✅ {comment}",
                installation_id=installation_id,
            )
            if result is None:
                logger.error(
                    "approve_deployment_failed",
                    operation="approve_deployment",
                    environment=environment,
                    reason="api_returned_none",
                )
            else:
                logger.info(
                    "deployment_approved",
                    operation="approve_deployment",
                    environment=environment,
                )
        except Exception as e:
            logger.error(
                "approve_deployment_error",
                operation="approve_deployment",
                environment=environment,
                error=str(e),
            )

    async def _reject_deployment(
        self, callback_url: str, environment: str, violations: list[dict[str, Any]], installation_id: int
    ):
        try:
            comment_text = self._format_violations_comment(violations)
            result = await self.github_client.review_deployment_protection_rule(
                callback_url=callback_url,
                environment=environment,
                state="rejected",
                comment=comment_text,
                installation_id=installation_id,
            )
            if result is None:
                logger.error(
                    "reject_deployment_failed",
                    operation="reject_deployment",
                    environment=environment,
                    num_violations=len(violations),
                    reason="api_returned_none",
                )
            else:
                logger.info(
                    "deployment_rejected",
                    operation="reject_deployment",
                    environment=environment,
                    num_violations=len(violations),
                )
        except Exception as e:
            logger.error(
                "reject_deployment_error",
                operation="reject_deployment",
                environment=environment,
                error=str(e),
            )

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
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

    @staticmethod
    def _format_violations_comment(violations):
        text = "🚫 **Deployment Blocked - Rule Violations Detected**\n"
        for v in violations:
            emoji = "❌" if v.get("severity", "high") in ("critical", "high") else "⚠️"
            rule_description = v.get("rule_description", v.get("rule", v.get("description", "Unknown")))
            text += f"{emoji} **{rule_description}**\n"
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
        from src.rules.github_provider import github_rule_loader

        return github_rule_loader
