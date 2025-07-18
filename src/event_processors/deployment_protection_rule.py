import logging
import time
from typing import Any

from src.agents.engine_agent.agent import RuleEngineAgent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.scheduler.deployment_scheduler import deployment_scheduler
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)


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

        try:
            payload = task.payload

            environment = payload.get("environment")
            deployment = payload.get("deployment", {})
            deployment_id = deployment.get("id")
            deployment_callback_url = payload.get("deployment_callback_url")
            installation_id = task.installation_id
            repo_full_name = task.repo_full_name

            logger.info("=" * 80)
            logger.info(f"🚀 Processing DEPLOYMENT_PROTECTION_RULE event for {repo_full_name}")
            logger.info(f"    Environment: {environment} | Deployment ID: {deployment_id}")
            logger.info("=" * 80)

            rules = await self.rule_provider.get_rules(repo_full_name, installation_id)

            if not rules:
                logger.info("📋 No rules found for repository")
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
                    logger.error(f"Rule is not a dict or object: {r} (type: {type(r)})")
                    continue

                if "deployment" in event_types:
                    deployment_rules.append(r)

            if not deployment_rules:
                logger.info("📋 No deployment rules found")
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

            logger.info(f"📋 Found {len(deployment_rules)} applicable rules for deployment")

            formatted_rules = self._convert_rules_to_new_format(deployment_rules)

            event_data = {
                "deployment": deployment,
                "triggering_user": deployment.get("creator", {}),
                "repository": payload.get("repository", {}),
                "organization": payload.get("organization", {}),
                "event_id": payload.get("event_id"),
                "timestamp": payload.get("timestamp"),
            }

            analysis_result = await self.engine_agent.execute(
                event_type="deployment",
                event_data=event_data,
                rules=formatted_rules,
            )

            violations = analysis_result.data.get("violations", [])
            logger.info("🔍 Analysis completed:")
            logger.info(f"    Violations found: {len(violations)}")
            logger.info(f"    API calls made: {analysis_result.data.get('api_calls', 0)}")

            if not violations:
                if deployment_callback_url and environment:
                    await self._approve_deployment(
                        deployment_callback_url, environment, "All deployment rules passed", installation_id
                    )
                logger.info("✅ All rules passed - deployment approved!")
            else:
                time_based_violations = self._check_time_based_violations(violations)
                if time_based_violations:
                    await deployment_scheduler.add_pending_deployment(
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
                    logger.info("⏰ Time-based violations detected - added to scheduler for re-evaluation")

                if deployment_callback_url and environment:
                    await self._reject_deployment(deployment_callback_url, environment, violations, installation_id)
                logger.info(f"❌ Deployment rejected due to {len(violations)} violations")

            processing_time = int((time.time() - start_time) * 1000)
            logger.info("=" * 80)
            logger.info(f"🏁 DEPLOYMENT_PROTECTION_RULE processing completed in {processing_time}ms")
            logger.info(f"    State: {'approved' if not violations else 'rejected'}")
            logger.info(f"    Violations: {len(violations)}")
            logger.info("=" * 80)

            return ProcessingResult(
                success=(not violations), violations=violations, api_calls_made=1, processing_time_ms=processing_time
            )

        except Exception as e:
            logger.error(f"❌ Error processing deployment protection rule: {str(e)}")
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
            v for v in violations if any(k in v.get("rule_id", "").lower() for k in ["hours", "weekend", "time", "day"])
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
                logger.error("Failed to approve deployment - API call returned None")
            else:
                logger.info("Successfully approved deployment")
        except Exception as e:
            logger.error(f"Error approving deployment: {e}")

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
                logger.error("Failed to reject deployment - API call returned None")
            else:
                logger.info(f"Successfully rejected deployment with {len(violations)} violations")
        except Exception as e:
            logger.error(f"Error rejecting deployment: {e}")
            # Note: We can't create a fallback deployment status here because we don't have the repo name
            # The deployment will remain in "waiting" state, which is better than failing completely

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        formatted_rules = []
        for rule in rules:
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

    @staticmethod
    def _format_violations_comment(violations):
        lines = ["🚫 **Deployment Blocked - Rule Violations Detected**\n"]
        for v in violations:
            emoji = "❌" if v.get("severity", "high") in ("critical", "high") else "⚠️"
            rule_name = v.get("rule_name", v.get("rule", v.get("id", "Unknown")))
            lines.append(
                f"{emoji} **{rule_name}**\n"
                f"**Severity:** {v.get('severity', 'high').capitalize()}\n"
                f"**Issue:** {v.get('message', '')}\n"
                f"**Solution:** {v.get('how_to_fix', 'See documentation.')}\n"
            )
        lines.append("\n---\n*This review was performed automatically by Watchflow.*")
        return "\n".join(lines)

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        return {}

    def _get_rule_provider(self):
        from src.rules.github_provider import github_rule_loader

        return github_rule_loader
