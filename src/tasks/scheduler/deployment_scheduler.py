import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from src.agents.engine_agent.agent import RuleEngineAgent
from src.integrations.github_api import github_client

logger = logging.getLogger(__name__)


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
            logger.warning("Deployment scheduler is already running")
            return

        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("🕒 Deployment scheduler started - checking every 15 minutes")

    async def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Deployment scheduler stopped")

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

            logger.info(f"⏰ Adding deployment {deployment_data['deployment_id']} to scheduler")
            logger.info(f"    Repo: {deployment_data['repo']}")
            logger.info(f"    Installation: {deployment_data['installation_id']}")
            logger.info(f"    Time-based violations: {len(deployment_data.get('time_based_violations', []))}")

            self.pending_deployments.append(deployment_data)
        except Exception as e:
            logger.error(f"Error adding deployment to scheduler: {e}")

    async def _scheduler_loop(self):
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

    async def _check_pending_deployments(self):
        """Check and re-evaluate pending deployments."""
        if not self.pending_deployments:
            return

        current_time = datetime.utcnow()
        logger.info(
            f"🔍 Checking {len(self.pending_deployments)} pending deployments at {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        deployments_to_remove = []

        for i, deployment in enumerate(self.pending_deployments):
            try:
                # Check if deployment is too old (remove after 7 days)
                created_at = deployment.get("created_at")
                if created_at:
                    if isinstance(created_at, int | float):
                        # Convert timestamp to datetime
                        created_at = datetime.fromtimestamp(created_at)
                    age = current_time - created_at
                    if age > timedelta(days=7):
                        logger.info(
                            f"⏰ Removing expired deployment for {deployment.get('repo')} (age: {age.days} days)"
                        )
                        deployments_to_remove.append(i)
                        continue
                else:
                    # If no created_at timestamp, remove the deployment as it's invalid
                    logger.warning(f"⏰ Removing deployment for {deployment.get('repo')} with no created_at timestamp")
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
                    logger.info(f"⏳ Deployment for {deployment.get('repo')} still blocked by time-based rules")

            except Exception as e:
                logger.error(f"Error re-evaluating deployment {deployment.get('repo', 'unknown')}: {e}")

        # Remove processed deployments (in reverse order to maintain indices)
        for i in reversed(deployments_to_remove):
            removed = self.pending_deployments.pop(i)
            logger.info(f"✅ Removed deployment for {removed.get('repo')} from scheduler")

        if self.pending_deployments:
            logger.info(f"📋 {len(self.pending_deployments)} deployments still pending")

    async def _re_evaluate_deployment(self, deployment: dict[str, Any]) -> bool:
        """Re-evaluate a deployment against current time-based rules."""
        try:
            # Validate required fields
            required_fields = ["repo", "environment", "installation_id", "event_data", "rules"]
            missing_fields = [field for field in required_fields if not deployment.get(field)]
            if missing_fields:
                logger.error(f"Missing required fields for deployment re-evaluation: {missing_fields}")
                return False

            logger.info(
                f"🔄 Re-evaluating deployment for {deployment.get('repo')} environment {deployment.get('environment')}"
            )

            # Refresh the GitHub token (it might have expired)
            try:
                fresh_token = await github_client.get_installation_access_token(deployment["installation_id"])
                if not fresh_token:
                    logger.error(f"Failed to get fresh GitHub token for installation {deployment['installation_id']}")
                    return False
                deployment["github_token"] = fresh_token
            except Exception as e:
                logger.error(f"Failed to refresh GitHub token: {e}")
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
                logger.info("✅ No violations found - deployment can be approved")
                return True

            # Check if any violations are still time-based
            time_based_violations = []
            other_violations = []

            for violation in violations:
                rule_name = violation.get("rule", "").lower()
                message = violation.get("message", "").lower()

                # Check if this is a time-based violation
                if any(
                    keyword in rule_name + message
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
                logger.info(f"❌ Deployment still has non-time-based violations: {len(other_violations)}")
                # Remove from scheduler since these won't resolve automatically
                return False

            if time_based_violations:
                logger.info(f"⏰ Deployment still blocked by {len(time_based_violations)} time-based violations")
                return False

            # No violations left
            logger.info("✅ All violations resolved - deployment can be approved")
            return True

        except Exception as e:
            logger.error(f"Error re-evaluating deployment: {e}")
            return False

    async def _approve_deployment(self, deployment: dict[str, Any]):
        """Approve a previously rejected deployment."""
        try:
            callback_url = deployment.get("callback_url")
            installation_id = deployment.get("installation_id")
            repo = deployment.get("repo", "unknown")
            environment = deployment.get("environment", "unknown")

            if not callback_url:
                logger.error(f"No callback URL found for deployment {repo}")
                return

            if not installation_id:
                logger.error(f"No installation ID found for deployment {repo}")
                return

            comment = (
                "✅ **Deployment Automatically Approved**\n\n"
                "Time-based restrictions have been lifted. The deployment can now proceed.\n\n"
                f"**Environment:** {environment}\n"
                f"**Approved at:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
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

            logger.info(f"✅ Deployment {deployment.get('deployment_id')} automatically approved for {repo}")

        except Exception as e:
            logger.error(f"Error approving deployment {deployment.get('deployment_id')}: {e}")

    def get_status(self) -> dict[str, Any]:
        """Get current scheduler status."""
        try:
            return {
                "running": self.running,
                "pending_count": len(self.pending_deployments),
                "pending_deployments": [
                    {
                        "repo": d.get("repo"),
                        "environment": d.get("environment"),
                        "deployment_id": d.get("deployment_id"),
                        "created_at": datetime.fromtimestamp(d.get("created_at")).isoformat()
                        if d.get("created_at") and isinstance(d.get("created_at"), int | float)
                        else (
                            d.get("created_at").isoformat()
                            if hasattr(d.get("created_at"), "isoformat")
                            else str(d.get("created_at"))
                        ),
                        "last_checked": d.get("last_checked").isoformat() if d.get("last_checked") else None,
                        "violations_count": len(d.get("violations", [])),
                        "time_based_violations_count": len(d.get("time_based_violations", [])),
                    }
                    for d in self.pending_deployments
                ],
            }
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
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
                    "id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "enabled": rule.enabled,
                    "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                    "event_types": [et.value if hasattr(et, "value") else et for et in rule.event_types],
                    "parameters": {},
                }

                # Extract parameters from conditions (flatten them)
                if hasattr(rule, "conditions"):
                    for condition in rule.conditions:
                        if hasattr(condition, "parameters"):
                            rule_dict["parameters"].update(condition.parameters)

                formatted_rules.append(rule_dict)
            except Exception as e:
                logger.error(f"Error converting rule to new format: {e}")
                # Skip this rule if conversion fails
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
