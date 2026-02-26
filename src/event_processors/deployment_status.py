import time
from typing import Any

import structlog

from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = structlog.get_logger()


class DeploymentStatusProcessor(BaseEventProcessor):
    """Processor for deployment_status events - for logging and monitoring only."""

    def __init__(self) -> None:
        # Call super class __init__ first
        super().__init__()

    def get_event_type(self) -> str:
        return "deployment_status"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        payload = task.payload
        deployment_status = payload.get("deployment_status", {})
        deployment = payload.get("deployment", {})

        state = deployment_status.get("state", "")
        environment = deployment.get("environment", "")
        creator = deployment.get("creator", {}).get("login", "")

        logger.info("=" * 80)
        logger.info("processing_deploymentstatus_event_for", repo_full_name=task.repo_full_name)
        logger.info("state", state=state)
        logger.info("environment", environment=environment)
        logger.info("creator", creator=creator)
        logger.info("=" * 80)

        # Log different states for monitoring purposes
        if state == "error":
            logger.info("deployment_to_had_an_error", environment=environment)
        elif state == "waiting":
            logger.info("deployment_to_is_waiting_for_protection", environment=environment)
        elif state == "success":
            logger.info("deployment_to_was_successful", environment=environment)
        elif state == "failure":
            logger.info("deployment_to_failed", environment=environment)
        else:
            logger.info("deployment_to_has_state", environment=environment, state=state)

        logger.info("=" * 80)
        logger.info(f"🏁 DEPLOYMENT_STATUS processing completed in {int((time.time() - start_time) * 1000)}ms")
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
