import structlog

from src.core.models import EventType, WebhookEvent, WebhookResponse
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = structlog.get_logger()


class DeploymentStatusEventHandler(EventHandler):
    """Handler for GitHub deployment_status events."""

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type == EventType.DEPLOYMENT_STATUS

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """Handle deployment_status events."""
        payload = event.payload
        repo_full_name = event.repo_full_name
        installation_id = payload.get("installation", {}).get("id")

        if not installation_id:
            logger.error("no_installation_id_found_in_deploymentstatus", repo_full_name=repo_full_name)
            return WebhookResponse(status="error", detail="Missing installation ID")

        # Extract status—fragile if GitHub changes payload structure.
        deployment_status = payload.get("deployment_status", {})
        deployment = payload.get("deployment", {})
        state = deployment_status.get("state", "")

        logger.info("enqueuing_deployment_status_event_for", repo_full_name=repo_full_name)
        logger.info("state", state=state)
        logger.info(f"   Environment: {deployment.get('environment', 'unknown')}")

        from src.event_processors.deployment_status import DeploymentStatusProcessor

        # ... existing code ...
        task_id = await task_queue.enqueue(
            DeploymentStatusProcessor().process,
            event_type="deployment_status",
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            payload=payload,
        )

        logger.info("deployment_status_event_enqueued_with_task", task_id=task_id)

        return WebhookResponse(
            status="ok",
            detail=f"Deployment status event for {repo_full_name} enqueued successfully",
            event_type=EventType.DEPLOYMENT_STATUS,
        )
