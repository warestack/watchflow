import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from src.agents import get_agent
from src.core.utils.retry import retry_async
from src.core.utils.timeout import execute_with_timeout

if TYPE_CHECKING:
    from src.agents.base import BaseAgent
from src.integrations.github import github_client

logger = structlog.get_logger(__name__)

AGENT_TIMEOUT_SECONDS = 30.0
MAX_CONSECUTIVE_FAILURES = 3


class DeploymentScheduler:
    """Scheduler for re-evaluating time-based deployment rules."""

    def __init__(self) -> None:
        self.running = False
        self.pending_deployments: list[dict[str, Any]] = []
        self.scheduler_task: asyncio.Task[None] | None = None
        # Lazy-load engine agent to avoid API key validation at import time
        self._engine_agent: BaseAgent | None = None

    @property
    def engine_agent(self) -> Any:
        """Lazy-load the engine agent to avoid API key validation at import time."""
        if self._engine_agent is None:
            self._engine_agent = get_agent("engine")
        return self._engine_agent

    async def start(self) -> None:
        """Start the scheduler."""
        if self.running:
            logger.warning("Deployment scheduler is already running")
            return

        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Deployment scheduler started, checking every 15 minutes")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self.running = False
        if self.scheduler_task:
            self.scheduler_task.cancel()
            # SIM105: Use contextlib.suppress instead of try-except-pass
            with contextlib.suppress(asyncio.CancelledError):
                await self.scheduler_task
        logger.info("Deployment scheduler stopped")

    async def add_pending_deployment(self, deployment_data: dict[str, Any]) -> None:
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
        """
        try:
            # Validate required fields
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
            ]
            missing_fields = [field for field in required_fields if not deployment_data.get(field)]
            if missing_fields:
                logger.error(f"Missing required fields for deployment scheduler: {missing_fields}")
                return

            logger.info(
                "deployment_scheduler_add",
                deployment_id=deployment_data["deployment_id"],
                repo=deployment_data["repo"],
                time_based_violations=len(deployment_data.get("time_based_violations", [])),
            )

            self.pending_deployments.append(deployment_data)
        except Exception as e:
            logger.error(f"Error adding deployment to scheduler: {e}")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop - runs every 15 minutes."""
        while self.running:
            try:
                await self._check_pending_deployments()
                # Wait 15 minutes (900 seconds)
                await asyncio.sleep(900)
            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                # Wait 1 minute on error before retrying
                await asyncio.sleep(60)

    async def _check_pending_deployments(self) -> None:
        """Check and re-evaluate pending deployments."""
        if not self.pending_deployments:
            return

        current_time = datetime.now(UTC)
        logger.info(
            "deployment_scheduler_check",
            pending_count=len(self.pending_deployments),
            time_utc=current_time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        deployments_to_remove = []

        for i, deployment in enumerate(self.pending_deployments):
            try:
                # Check if deployment is too old (remove after 7 days)
                created_at = deployment.get("created_at")
                if not created_at:
                    logger.warning(
                        "deployment_scheduler_remove_invalid",
                        repo=deployment.get("repo"),
                        reason="no created_at timestamp",
                    )
                    deployments_to_remove.append(i)
                    continue

                if isinstance(created_at, (int, float)):
                    created_at_dt = datetime.fromtimestamp(created_at, tz=UTC)
                elif hasattr(created_at, "year"):
                    created_at_dt = (
                        created_at if getattr(created_at, "tzinfo", None) else created_at.replace(tzinfo=UTC)
                    )
                else:
                    logger.warning(
                        "deployment_scheduler_remove_invalid",
                        repo=deployment.get("repo"),
                        reason="invalid created_at format",
                    )
                    deployments_to_remove.append(i)
                    continue

                age = current_time - created_at_dt
                if age > timedelta(days=7):
                    logger.info(
                        "deployment_scheduler_remove_expired",
                        repo=deployment.get("repo"),
                        age_days=age.days,
                    )
                    deployments_to_remove.append(i)
                    continue

                # Update last checked time
                deployment["last_checked"] = current_time

                should_approve, should_remove = await self._re_evaluate_deployment(deployment)

                if should_approve:
                    await self._approve_deployment(deployment)
                    deployments_to_remove.append(i)
                elif should_remove:
                    deployments_to_remove.append(i)
                else:
                    logger.info(
                        "deployment_scheduler_still_blocked",
                        repo=deployment.get("repo"),
                        reason="time-based rules",
                    )

            except Exception as e:
                logger.error(f"Error re-evaluating deployment {deployment.get('repo', 'unknown')}: {e}")

        # Remove processed deployments (in reverse order to maintain indices)
        for i in reversed(deployments_to_remove):
            removed = self.pending_deployments.pop(i)
            logger.info("deployment_scheduler_removed", repo=removed.get("repo"))

        if self.pending_deployments:
            logger.info("deployment_scheduler_pending", count=len(self.pending_deployments))

    async def _re_evaluate_deployment(self, deployment: dict[str, Any]) -> tuple[bool, bool]:
        """
        Re-evaluate a deployment against current time-based rules.
        Returns (should_approve, should_remove). When should_remove is True,
        deployment is removed from scheduler without approval (e.g. non-time violations).
        """
        try:
            # Validate required fields
            required_fields = ["repo", "environment", "installation_id", "event_data", "rules"]
            missing_fields = [field for field in required_fields if not deployment.get(field)]
            if missing_fields:
                logger.error(
                    "deployment_scheduler_missing_fields",
                    repo=deployment.get("repo"),
                    missing=missing_fields,
                )
                return False, True

            logger.info(
                "deployment_scheduler_reevaluate",
                repo=deployment.get("repo"),
                environment=deployment.get("environment"),
            )

            # Refresh the GitHub token (it might have expired)
            try:
                fresh_token = await github_client.get_installation_access_token(deployment["installation_id"])
                if not fresh_token:
                    logger.error(
                        "deployment_scheduler_token_failed",
                        installation_id=deployment["installation_id"],
                    )
                    failure_count = deployment.get("failure_count", 0) + 1
                    deployment["failure_count"] = failure_count
                    if failure_count >= MAX_CONSECUTIVE_FAILURES:
                        return False, True
                    return False, False
                deployment["github_token"] = fresh_token
            except Exception as e:
                logger.error("deployment_scheduler_token_error", error=str(e))
                failure_count = deployment.get("failure_count", 0) + 1
                deployment["failure_count"] = failure_count
                if failure_count >= MAX_CONSECUTIVE_FAILURES:
                    return False, True
                return False, False

            # Convert rules to the format expected by the analysis agent
            formatted_rules = DeploymentScheduler._convert_rules_to_new_format(deployment["rules"])

            result = await execute_with_timeout(
                self.engine_agent.execute(
                    event_type="deployment",
                    event_data=deployment["event_data"],
                    rules=formatted_rules,
                ),
                timeout=AGENT_TIMEOUT_SECONDS,
                timeout_message=f"Agent execution timed out after {AGENT_TIMEOUT_SECONDS}s",
            )

            violations = []
            eval_result = result.data.get("evaluation_result") if result.data else None
            if eval_result and hasattr(eval_result, "violations"):
                for v in eval_result.violations:
                    violations.append(
                        {
                            "rule_description": getattr(v, "rule_description", ""),
                            "message": getattr(v, "message", ""),
                        }
                    )

            if not violations:
                deployment["failure_count"] = 0
                logger.info("deployment_scheduler_no_violations", repo=deployment.get("repo"))
                return True, False

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
                deployment["failure_count"] = 0
                logger.info(
                    "deployment_scheduler_non_time_violations",
                    repo=deployment.get("repo"),
                    count=len(other_violations),
                )
                return False, True

            deployment["failure_count"] = 0
            if time_based_violations:
                logger.info(
                    "deployment_scheduler_time_violations",
                    repo=deployment.get("repo"),
                    count=len(time_based_violations),
                )
                return False, False

            logger.info("deployment_scheduler_all_resolved", repo=deployment.get("repo"))
            return True, False

        except Exception as e:
            failure_count = deployment.get("failure_count", 0) + 1
            deployment["failure_count"] = failure_count
            logger.error(
                "deployment_scheduler_reevaluate_error",
                repo=deployment.get("repo"),
                error=str(e),
                failure_count=failure_count,
            )
            if failure_count >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "deployment_scheduler_remove_after_failures",
                    repo=deployment.get("repo"),
                    failure_count=failure_count,
                )
                return False, True
            return False, False

    async def _approve_deployment(self, deployment: dict[str, Any]) -> None:
        """Approve a previously rejected deployment."""
        callback_url = deployment.get("callback_url")
        installation_id = deployment.get("installation_id")
        repo = deployment.get("repo", "unknown")
        environment = deployment.get("environment", "unknown")
        deployment_id = deployment.get("deployment_id")

        if not callback_url:
            logger.error("deployment_approve_skipped", repo=repo, reason="no callback URL")
            return

        if not installation_id:
            logger.error("deployment_approve_skipped", repo=repo, reason="no installation ID")
            return

        comment = (
            "**Deployment Automatically Approved**\n\n"
            "Time-based restrictions have been lifted. The deployment can now proceed.\n\n"
            f"**Environment:** {environment}\n"
            f"**Approved at:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            "The deployment will be automatically approved on GitHub."
        )

        async def _do_approve() -> Any:
            return await github_client.review_deployment_protection_rule(
                callback_url=callback_url,
                environment=environment,
                state="approved",
                comment=comment,
                installation_id=installation_id,
            )

        try:
            await retry_async(
                _do_approve,
                max_retries=3,
                initial_delay=1.0,
                max_delay=30.0,
                exceptions=(Exception,),
            )
            logger.info(
                "deployment_scheduler_approved",
                deployment_id=deployment_id,
                repo=repo,
                environment=environment,
            )
        except Exception as e:
            logger.error(
                "deployment_approve_error",
                deployment_id=deployment_id,
                repo=repo,
                error=str(e),
            )

    def get_status(self) -> dict[str, Any]:
        """Get current scheduler status."""
        try:
            pending_deployments_status = []
            for d in self.pending_deployments:
                created_at = d.get("created_at")
                created_at_iso = None
                if created_at:
                    if isinstance(created_at, (int, float)):
                        created_at_iso = datetime.fromtimestamp(created_at, tz=UTC).isoformat()
                    elif hasattr(created_at, "isoformat"):
                        created_at_iso = created_at.isoformat()
                    else:
                        created_at_iso = str(created_at)

                last_checked = d.get("last_checked")
                last_checked_iso = last_checked.isoformat() if last_checked else None

                pending_deployments_status.append(
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
                "pending_deployments": pending_deployments_status,
            }
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
            return {"running": self.running, "pending_count": len(self.pending_deployments), "error": str(e)}

    async def start_background_scheduler(self) -> None:
        """Start the background scheduler task."""
        if not self.running:
            await self.start()

    async def stop_background_scheduler(self) -> None:
        """Stop the background scheduler task."""
        if self.running:
            await self.stop()

    @staticmethod
    def _convert_rules_to_new_format(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert old rule format to new format if needed.
        This is for backward compatibility.
        """
        if not rules:
            return []

        # Check if conversion is needed by inspecting the first rule
        first_rule = rules[0]
        if "rule_description" in first_rule and "event_types" not in first_rule:
            # This looks like the old format
            logger.info("Converting old rule format to new format")
            converted_rules = []
            for rule in rules:
                converted_rules.append(
                    {
                        "description": rule.get("rule_description", ""),
                        "severity": rule.get("severity", "medium"),
                        "event_types": rule.get("event_types", ["deployment"]),
                        "parameters": rule.get("parameters", {}),
                    }
                )
            return converted_rules

        # Already in new format
        return rules


# Global instance - lazy loaded to avoid API key validation at import time
deployment_scheduler = None


def get_deployment_scheduler() -> DeploymentScheduler:
    """Get the global deployment scheduler instance, creating it if needed."""
    global deployment_scheduler
    if deployment_scheduler is None:
        deployment_scheduler = DeploymentScheduler()
    return deployment_scheduler
