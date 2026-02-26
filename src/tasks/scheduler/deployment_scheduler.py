import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from src.agents.engine_agent.agent import RuleEngineAgent
from src.integrations.github_api import github_client

logger = structlog.get_logger()


class DeploymentScheduler:
    """Scheduler for re-evaluating time-based deployment rules."""

    def __init__(self):
        self.running = False
        self.pending_deployments: list[dict[str, Any]] = []
        self.scheduler_task = None
        # Lazy-load engine agent to avoid API key validation at import time
        self._engine_agent = None

    @property
    def engine_agent(self) -> RuleEngineAgent:
        """Lazy-load the engine agent to avoid API key validation at import time."""
        if self._engine_agent is None:
            self._engine_agent = RuleEngineAgent()
        return self._engine_agent

    async def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("scheduler_already_running")
            return

        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("scheduler_started", check_interval_minutes=15)

    async def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("scheduler_stopped")

    async def add_pending_deployment(self, deployment_data: dict[str, Any]):
        """
        Add a deployment to the pending list for future re-evaluation.

        Args:
            deployment_data: dictionary containing:
                - deployment_id: GitHub deployment ID
                - repo: Repository full name
                - installation_id: GitHub App installation ID
                - environment: Deployment environment
                - event_data: Original event data
                - rules: Rules that were evaluated
                - violations: Current violations
                - time_based_violations: Time-based violations
                - created_at: Timestamp when added
                - callback_url: Deployment callback URL
        """
        try:
            # Validate required fields - add callback_url
            required_fields = [
                "deployment_id",
                "repo",
                "installation_id",
                "environment",
                "event_data",
                "rules",
                "violations",
                "time_based_violations",
                "created_at",
                "callback_url",
            ]
            missing_fields = [field for field in required_fields if deployment_data.get(field) is None]
            if missing_fields:
                logger.error(
                    "missing_required_fields",
                    operation="add_pending_deployment",
                    missing_fields=missing_fields,
                )
                return

            logger.info(
                "adding_deployment_to_scheduler",
                operation="add_pending_deployment",
                subject_ids={"repo": deployment_data["repo"], "deployment_id": deployment_data["deployment_id"]},
                installation_id=deployment_data["installation_id"],
                num_time_based_violations=len(deployment_data.get("time_based_violations", [])),
            )

            self.pending_deployments.append(deployment_data)
        except Exception as e:
            logger.error(
                "add_deployment_error",
                operation="add_pending_deployment",
                error=str(e),
            )

    async def _scheduler_loop(self):
        """Main scheduler loop - runs every 15 minutes."""
        while self.running:
            try:
                await self._check_pending_deployments()
                # Wait 15 minutes (900 seconds)
                await asyncio.sleep(900)
            except asyncio.CancelledError:
                logger.info("scheduler_loop_cancelled")
                break
            except Exception as e:
                logger.error("scheduler_loop_error", error=str(e))
                # Wait 1 minute on error before retrying
                await asyncio.sleep(60)

    async def _check_pending_deployments(self):
        """Check and re-evaluate pending deployments."""
        if not self.pending_deployments:
            return

        current_time = datetime.now(UTC)
        logger.info(
            "checking_pending_deployments",
            operation="_check_pending_deployments",
            num_pending=len(self.pending_deployments),
            current_time=current_time.isoformat(),
        )

        deployments_to_remove = []

        for i, deployment in enumerate(self.pending_deployments):
            try:
                # Check if deployment is too old (remove after 7 days)
                created_at = deployment.get("created_at")
                if created_at is not None:
                    if isinstance(created_at, int | float):
                        # Convert timestamp to datetime with timezone awareness
                        created_at = datetime.fromtimestamp(created_at, tz=UTC)
                    age = current_time - created_at
                    if age > timedelta(days=7):
                        logger.info(
                            "removing_expired_deployment",
                            operation="_check_pending_deployments",
                            subject_ids={"repo": deployment.get("repo")},
                            age_days=age.days,
                        )
                        deployments_to_remove.append(i)
                        continue
                else:
                    # If no created_at timestamp, remove the deployment as it's invalid
                    logger.warning(
                        "removing_deployment_no_timestamp",
                        operation="_check_pending_deployments",
                        subject_ids={"repo": deployment.get("repo")},
                    )
                    deployments_to_remove.append(i)
                    continue

                # Update last checked time
                deployment["last_checked"] = current_time

                # Re-evaluate the deployment
                should_approve = await self._re_evaluate_deployment(deployment)

                if should_approve:
                    # Approve the deployment
                    await self._approve_deployment(deployment)
                    deployments_to_remove.append(i)
                else:
                    logger.info(
                        "deployment_still_blocked",
                        operation="_check_pending_deployments",
                        subject_ids={"repo": deployment.get("repo")},
                    )

            except Exception as e:
                logger.error(
                    "re_evaluate_error",
                    operation="_check_pending_deployments",
                    subject_ids={"repo": deployment.get("repo", "unknown")},
                    error=str(e),
                )

        # Remove processed deployments (in reverse order to maintain indices)
        for i in reversed(deployments_to_remove):
            removed = self.pending_deployments.pop(i)
            logger.info(
                "deployment_removed_from_scheduler",
                operation="_check_pending_deployments",
                subject_ids={"repo": removed.get("repo")},
            )

        if self.pending_deployments:
            logger.info("deployments_still_pending", num_pending=len(self.pending_deployments))

    async def _re_evaluate_deployment(self, deployment: dict[str, Any]) -> bool:
        """Re-evaluate a deployment against current time-based rules."""
        try:
            # Validate required fields
            required_fields = ["repo", "environment", "installation_id", "event_data", "rules"]
            missing_fields = [field for field in required_fields if deployment.get(field) is None]
            if missing_fields:
                logger.error(
                    "missing_required_fields",
                    operation="_re_evaluate_deployment",
                    missing_fields=missing_fields,
                )
                return False

            logger.info(
                "re_evaluating_deployment",
                operation="_re_evaluate_deployment",
                subject_ids={"repo": deployment.get("repo")},
                environment=deployment.get("environment"),
            )

            # Refresh the GitHub token (it might have expired)
            try:
                fresh_token = await github_client.get_installation_access_token(deployment["installation_id"])
                if fresh_token is None:
                    logger.error(
                        "failed_to_get_token",
                        operation="_re_evaluate_deployment",
                        installation_id=deployment["installation_id"],
                    )
                    return False
                deployment["github_token"] = fresh_token
            except Exception as e:
                logger.error(
                    "token_refresh_error",
                    operation="_re_evaluate_deployment",
                    error=str(e),
                )
                return False

            # Convert rules to the format expected by the analysis agent
            formatted_rules = self._convert_rules_to_new_format(deployment["rules"])

            # Re-run rule analysis
            result = await self.engine_agent.execute(
                event_type="deployment",
                event_data=deployment["event_data"],
                rules=formatted_rules,
            )

            violations = result.data.get("violations", [])

            if not violations:
                logger.info(
                    "no_violations_deployment_can_approve",
                    operation="_re_evaluate_deployment",
                    subject_ids={"repo": deployment.get("repo")},
                )
                return True

            # Check if any violations are still time-based
            time_based_violations = []
            other_violations = []

            for violation in violations:
                rule_description = violation.get("rule_description", "").lower()
                message = violation.get("message", "").lower()

                # Check if this is a time-based violation
                if any(
                    keyword in rule_description + message
                    for keyword in [
                        "hour",
                        "day",
                        "weekend",
                        "time",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ]
                ):
                    time_based_violations.append(violation)
                else:
                    other_violations.append(violation)

            if other_violations:
                logger.info(
                    "deployment_has_non_time_violations",
                    operation="_re_evaluate_deployment",
                    subject_ids={"repo": deployment.get("repo")},
                    num_violations=len(other_violations),
                )
                # Remove from scheduler since these won't resolve automatically
                return False

            if time_based_violations:
                logger.info(
                    "deployment_still_blocked_by_time",
                    operation="_re_evaluate_deployment",
                    subject_ids={"repo": deployment.get("repo")},
                    num_violations=len(time_based_violations),
                )
                return False

            # No violations left
            logger.info(
                "all_violations_resolved",
                operation="_re_evaluate_deployment",
                subject_ids={"repo": deployment.get("repo")},
            )
            return True

        except Exception as e:
            logger.error(
                "re_evaluate_error",
                operation="_re_evaluate_deployment",
                error=str(e),
            )
            return False

    async def _approve_deployment(self, deployment: dict[str, Any]):
        """Approve a previously rejected deployment."""
        repo = deployment.get("repo", "unknown")
        try:
            callback_url = deployment.get("callback_url")
            installation_id = deployment.get("installation_id")
            environment = deployment.get("environment", "unknown")

            if callback_url is None:
                logger.error(
                    "no_callback_url",
                    operation="_approve_deployment",
                    subject_ids={"repo": repo},
                )
                return

            if installation_id is None:
                logger.error(
                    "no_installation_id",
                    operation="_approve_deployment",
                    subject_ids={"repo": repo},
                )
                return

            current_time = datetime.now(UTC)
            comment = (
                "✅ **Deployment Automatically Approved**\n\n"
                "Time-based restrictions have been lifted. The deployment can now proceed.\n\n"
                f"**Environment:** {environment}\n"
                f"**Approved at:** {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                "The deployment will be automatically approved on GitHub."
            )

            # Approve the deployment protection rule
            await github_client.review_deployment_protection_rule(
                callback_url=callback_url,
                environment=environment,
                state="approved",
                comment=comment,
                installation_id=installation_id,
            )

            logger.info(
                "deployment_auto_approved",
                operation="_approve_deployment",
                subject_ids={"repo": repo, "deployment_id": deployment.get("deployment_id")},
                environment=environment,
            )

        except Exception as e:
            logger.error(
                "approve_deployment_error",
                operation="_approve_deployment",
                subject_ids={"repo": repo},
                error=str(e),
            )

    def get_status(self) -> dict[str, Any]:
        """Get current scheduler status."""
        try:
            pending_deployments = []
            for d in self.pending_deployments:
                created_at = d.get("created_at")
                created_at_iso = None
                if created_at is not None:
                    if isinstance(created_at, int | float):
                        created_at_iso = datetime.fromtimestamp(created_at, tz=UTC).isoformat()
                    elif hasattr(created_at, "isoformat"):
                        created_at_iso = created_at.isoformat()
                    else:
                        created_at_iso = str(created_at)

                last_checked = d.get("last_checked")
                last_checked_iso = (
                    last_checked.isoformat() if last_checked and hasattr(last_checked, "isoformat") else None
                )

                pending_deployments.append(
                    {
                        "repo": d.get("repo"),
                        "environment": d.get("environment"),
                        "deployment_id": d.get("deployment_id"),
                        "created_at": created_at_iso,
                        "last_checked": last_checked_iso,
                        "violations_count": len(d.get("violations", [])),
                        "time_based_violations_count": len(d.get("time_based_violations", [])),
                    }
                )

            return {
                "running": self.running,
                "pending_count": len(self.pending_deployments),
                "pending_deployments": pending_deployments,
            }
        except Exception as e:
            logger.error("get_status_error", error=str(e))
            return {"running": self.running, "pending_count": len(self.pending_deployments), "error": str(e)}

    async def start_background_scheduler(self):
        """Start the background scheduler task."""
        if not self.running:
            await self.start()

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        """Convert Rule objects to the new flat schema format."""
        formatted_rules = []

        for rule in rules:
            try:
                # Convert Rule object to dict format
                rule_dict = {
                    "description": rule.description,
                    "enabled": rule.enabled,
                    "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                    "event_types": [et.value if hasattr(et, "value") else et for et in rule.event_types],
                    "parameters": rule.parameters if hasattr(rule, "parameters") else {},
                }

                # Extract parameters from conditions (flatten them)
                if hasattr(rule, "conditions"):
                    for condition in rule.conditions:
                        if hasattr(condition, "parameters"):
                            rule_dict["parameters"].update(condition.parameters)

                formatted_rules.append(rule_dict)
            except Exception as e:
                logger.error(
                    "rule_conversion_error",
                    operation="_convert_rules_to_new_format",
                    error=str(e),
                )
                continue

        return formatted_rules

    async def stop_background_scheduler(self):
        """Stop the background scheduler task."""
        if self.running:
            await self.stop()


# Global instance - lazy loaded to avoid API key validation at import time
deployment_scheduler = None


def get_deployment_scheduler() -> DeploymentScheduler:
    """Get the global deployment scheduler instance, creating it if needed."""
    global deployment_scheduler
    if deployment_scheduler is None:
        deployment_scheduler = DeploymentScheduler()
    return deployment_scheduler
