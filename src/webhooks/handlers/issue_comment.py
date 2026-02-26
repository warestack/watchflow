import re
from typing import Any

import structlog

from src.agents.feasibility_agent.agent import RuleFeasibilityAgent
from src.core.models import EventType, WebhookEvent
from src.integrations.github_api import github_client
from src.rules.utils import _validate_rules_yaml
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler

logger = structlog.get_logger()


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
                logger.info("ignoring_comment_from_bot_user", commenter=commenter)
                return {"status": "ignored", "reason": "Bot comment"}

            logger.info("processing_comment_from_human_user", commenter=commenter)

            # Check if this is a help command
            if self._is_help_comment(comment_body):
                help_message = (
                    "Here are the available Watchflow commands:\n"
                    '- @watchflow acknowledge "reason" — Acknowledge a rule violation.\n'
                    '- @watchflow ack "reason" — Short form for acknowledge.\n'
                    '- @watchflow evaluate "rule description" — Evaluate the feasibility of a rule.\n'
                    "- @watchflow validate — Validate the .watchflow/rules.yaml file.\n"
                    "- @watchflow help — Show this help message.\n"
                )
                logger.info("responding_to_help_command")
                pr_number = (
                    event.payload.get("issue", {}).get("number")
                    or event.payload.get("pull_request", {}).get("number")
                    or event.payload.get("number")
                )
                if pr_number:
                    await github_client.create_pull_request_comment(
                        repo=repo,
                        pr_number=pr_number,
                        comment=help_message,
                        installation_id=installation_id,
                    )
                    logger.info("posted_help_message_as_a_comment", pr_number=pr_number)
                    return {"status": "help_posted"}
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return {"status": "help", "message": help_message}

            # Check if this is an acknowledgment comment
            ack_reason = self._extract_acknowledgment_reason(comment_body)
            if ack_reason is not None:
                task_id = await task_queue.enqueue(
                    event_type="violation_acknowledgment",
                    repo_full_name=repo,
                    installation_id=installation_id,
                    payload={**event.payload, "acknowledgment_reason": ack_reason},
                )
                logger.info("acknowledgment_comment_enqueued_with_task_id", task_id=task_id)
                return {"status": "acknowledgment_queued", "task_id": task_id, "reason": ack_reason}

            # Check if this is an evaluate command
            eval_rule = self._extract_evaluate_rule(comment_body)
            if eval_rule is not None:
                agent = RuleFeasibilityAgent()
                result = await agent.execute(rule_description=eval_rule)
                is_feasible = result.data.get("is_feasible", False)
                yaml_content = result.data.get("yaml_content", "")
                feedback = result.message
                comment = (
                    f"**Rule Feasibility Evaluation**\n"
                    f"**Rule:** {eval_rule}\n\n"
                    f"**Feasible:** {'✅ Yes' if is_feasible else '❌ No'}\n"
                    f"**Feedback:** {feedback}\n"
                )
                if is_feasible and yaml_content:
                    comment += f"\n**YAML Snippet:**\n```yaml\n{yaml_content}\n```"
                pr_number = (
                    event.payload.get("issue", {}).get("number")
                    or event.payload.get("pull_request", {}).get("number")
                    or event.payload.get("number")
                )
                if pr_number:
                    await github_client.create_pull_request_comment(
                        repo=repo,
                        pr_number=pr_number,
                        comment=comment,
                        installation_id=installation_id,
                    )
                    logger.info("posted_feasibility_evaluation_result_as_a", pr_number=pr_number)
                    return {"status": "feasibility_evaluation_posted"}
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return {"status": "feasibility_evaluation", "message": comment}

            # Check if this is a validate command
            if self._is_validate_comment(comment_body):
                logger.info("processing_validate_command")
                validation_result = await _validate_rules_yaml(repo, installation_id)
                pr_number = (
                    event.payload.get("issue", {}).get("number")
                    or event.payload.get("pull_request", {}).get("number")
                    or event.payload.get("number")
                )
                if pr_number:
                    await github_client.create_pull_request_comment(
                        repo=repo,
                        pr_number=pr_number,
                        comment=validation_result,
                        installation_id=installation_id,
                    )
                    logger.info("posted_validation_result_as_a_comment", pr_number=pr_number)
                    return {"status": "validation_posted"}
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return {"status": "validation", "message": validation_result}

            else:
                logger.info("comment_does_not_match_any_known")
                return {"status": "ignored", "reason": "No matching patterns"}

        except Exception as e:
            logger.error(f"❌ Error handling issue comment: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _extract_acknowledgment_reason(self, comment_body: str) -> str | None:
        """Extract the quoted reason from an acknowledgment command, or None if not present."""
        comment_body = comment_body.strip()

        logger.info("extracting_acknowledgment_reason_from", comment_body=comment_body)

        # Try different patterns for flexibility
        patterns = [
            r'@watchflow\s+(acknowledge|ack)\s+"([^"]+)"',  # Double quotes
            r"@watchflow\s+(acknowledge|ack)\s+'([^']+)'",  # Single quotes
            r"@watchflow\s+(acknowledge|ack)\s+([^\n\r]+)",  # No quotes, until end of line
        ]

        for _i, pattern in enumerate(patterns):
            match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
            if match:
                # For patterns with quotes, group 2 contains the reason
                # For pattern without quotes, group 2 contains the reason
                reason = match.group(2).strip()
                logger.info("pattern_matched_reason", reason=reason)
                if reason:  # Make sure we got a non-empty reason
                    return reason
            else:
                logger.info("pattern_did_not_match")

        logger.info("no_patterns_matched_for_acknowledgment_reason")
        return None

    def _extract_evaluate_rule(self, comment_body: str) -> str | None:
        comment_body = comment_body.strip()
        pattern = r'@watchflow\s+evaluate\s+"([^"]+)"'
        match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _is_validate_comment(self, comment_body: str) -> bool:
        comment_body = comment_body.strip()
        pattern = r"@watchflow\s+validate"
        return re.search(pattern, comment_body, re.IGNORECASE) is not None

    def _is_help_comment(self, comment_body: str) -> bool:
        patterns = [
            r"@watchflow\s+help",
        ]
        for pattern in patterns:
            if re.search(pattern, comment_body, re.IGNORECASE):
                return True
        return False
