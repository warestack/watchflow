import logging
import re
from typing import Any

from src.core.models import EventType, WebhookEvent
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = logging.getLogger(__name__)


class IssueCommentEventHandler(EventHandler):
    """Handler for GitHub issue comment events."""

    @property
    def event_type(self) -> EventType:
        return EventType.ISSUE_COMMENT

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type == EventType.ISSUE_COMMENT

    async def handle(self, event: WebhookEvent) -> dict[str, Any]:
        """Handle issue comment events."""
        try:
            comment_body = event.payload.get("comment", {}).get("body", "")
            commenter = event.payload.get("comment", {}).get("user", {}).get("login")
            repo = event.repo_full_name
            installation_id = event.installation_id

            logger.info(f"🔄 Processing comment from {commenter}: {comment_body[:50]}...")

            # Ignore comments from the bot itself to prevent infinite loops
            bot_usernames = ["watchflow[bot]", "watchflow-bot", "watchflow", "watchflowbot", "watchflow_bot"]
            if commenter and any(bot_name.lower() in commenter.lower() for bot_name in bot_usernames):
                logger.info(f"🤖 Ignoring comment from bot user: {commenter}")
                return {"status": "ignored", "reason": "Bot comment"}

            logger.info(f"👤 Processing comment from human user: {commenter}")

            # Check if this is an acknowledgment comment
            if self._is_acknowledgment_comment(comment_body):
                # ✅ Use the correct enqueue method signature
                task_id = await task_queue.enqueue(
                    event_type="violation_acknowledgment",
                    repo_full_name=repo,
                    installation_id=installation_id,
                    payload=event.payload,
                )

                logger.info(f"✅ Acknowledgment comment enqueued with task ID: {task_id}")
                return {"status": "acknowledgment_queued", "task_id": task_id}

            # Handle other comment types (rule creation, etc.)
            elif self._is_rule_creation_comment(comment_body):
                # ✅ Use the correct enqueue method signature
                task_id = await task_queue.enqueue(
                    event_type="rule_creation",
                    repo_full_name=repo,
                    installation_id=installation_id,
                    payload=event.payload,
                )

                logger.info(f"✅ Rule creation comment enqueued with task ID: {task_id}")
                return {"status": "rule_creation_queued", "task_id": task_id}

            else:
                logger.info("📋 Comment does not match any known patterns - ignoring")
                return {"status": "ignored", "reason": "No matching patterns"}

        except Exception as e:
            logger.error(f"❌ Error handling issue comment: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _is_acknowledgment_comment(self, comment_body: str) -> bool:
        """Check if comment is an acknowledgment comment."""
        patterns = [
            r"@watchflow\s+acknowledge",
            r"@watchflow\s+override",
            r"@watchflow\s+bypass",
            r"/acknowledge",
            r"/override",
            r"/bypass",
        ]

        for pattern in patterns:
            if re.search(pattern, comment_body, re.IGNORECASE):
                return True

        return False

    def _is_rule_creation_comment(self, comment_body: str) -> bool:
        """Check if comment is a rule creation comment."""
        patterns = [r"@watchflow\s+create\s+rule", r"@watchflow\s+add\s+rule", r"/create-rule", r"/add-rule"]

        for pattern in patterns:
            if re.search(pattern, comment_body, re.IGNORECASE):
                return True

        return False
