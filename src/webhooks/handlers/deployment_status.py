import logging
from typing import Any

from src.core.models import EventType, WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = logging.getLogger(__name__)


class DeploymentStatusEventHandler(EventHandler):
    """Handler for GitHub deployment_status events."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type == EventType.DEPLOYMENT_STATUS

    async def handle(self, event: WebhookEvent) -> dict[str, Any]:
        """Handle deployment_status events."""
        payload = event.payload
        repo_full_name = event.repo_full_name
        installation_id = payload.get("installation", {}).get("id")

        if not installation_id:
            logger.error(f"No installation ID found in deployment_status event for {repo_full_name}")
            return {"status": "error", "message": "Missing installation ID"}

        # Extract deployment status info
        deployment_status = payload.get("deployment_status", {})
        deployment = payload.get("deployment", {})
        state = deployment_status.get("state", "")

        logger.info(f"🔄 Enqueuing deployment status event for {repo_full_name}")
        logger.info(f"   State: {state}")
        logger.info(f"   Environment: {deployment.get('environment', 'unknown')}")

        # Enqueue the task using the global task_queue
        task_id = await task_queue.enqueue(
            event_type="deployment_status",
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            payload=payload,
        )

        logger.info(f"✅ Deployment status event enqueued with task ID: {task_id}")

        return {
            "status": "success",
            "message": f"Deployment status event for {repo_full_name} enqueued successfully",
            "task_id": task_id,
        }
