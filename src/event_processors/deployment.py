import time
from typing import Any

import structlog

from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = structlog.get_logger()


class DeploymentProcessor(BaseEventProcessor):
    """Processor for deployment events - for logging only."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

    def get_event_type(self) -> str:
        return "deployment"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        payload = task.payload
        deployment = payload.get("deployment", {})

        environment = deployment.get("environment", "")
        creator = deployment.get("creator", {}).get("login", "")
        ref = deployment.get("ref", "")
        deployment_id = deployment.get("id")

        logger.info("=" * 80)
        logger.info("processing_deployment_event_for", repo_full_name=task.repo_full_name)
        logger.info("environment", environment=environment)
        logger.info("creator", creator=creator)
        logger.info("ref", ref=ref)
        logger.info("deployment_id", deployment_id=deployment_id)
        logger.info("=" * 80)

        # Just log the deployment creation - no rule evaluation here
        # Rule evaluation will be handled by deployment_protection_rule events
        logger.info("deployment_created_for", deployment_id=deployment_id, environment=environment)
        logger.info("=" * 80)
        logger.info(f"🏁 DEPLOYMENT processing completed in {int((time.time() - start_time) * 1000)}ms")
        logger.info("=" * 80)

        return ProcessingResult(
            success=True, violations=[], api_calls_made=0, processing_time_ms=int((time.time() - start_time) * 1000)
        )

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Extract data available in webhook payload."""
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Fetch data not available in webhook."""
        return {}
