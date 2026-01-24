import logging
import re
from typing import Any

from src.agents import get_agent
from src.core.models import EventType, WebhookEvent
from src.integrations.github import github_client
from src.rules.utils import _validate_rules_yaml
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

            logger.info("comment_processed", commenter=commenter, body_length=len(comment_body))

            # Bot self-reply guard—avoids infinite loop, spam.
            bot_usernames = ["watchflow[bot]", "watchflow-bot", "watchflow", "watchflowbot", "watchflow_bot"]
            if commenter and any(bot_name.lower() in commenter.lower() for bot_name in bot_usernames):
                logger.info(f"🤖 Ignoring comment from bot user: {commenter}")
                return {"status": "ignored", "reason": "Bot comment"}

            logger.info(f"👤 Processing comment from human user: {commenter}")

            # Help command—user likely lost/confused.
            if self._is_help_comment(comment_body):
                help_message = (
                    "Here are the available Watchflow commands:\n"
                    '- @watchflow acknowledge "reason" — Acknowledge a rule violation.\n'
                    '- @watchflow ack "reason" — Short form for acknowledge.\n'
                    '- @watchflow evaluate "rule description" — Evaluate the feasibility of a rule.\n'
                    "- @watchflow validate — Validate the .watchflow/rules.yaml file.\n"
                    "- @watchflow help — Show this help message.\n"
                )
                logger.info("ℹ️ Responding to help command.")
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
                    logger.info(f"ℹ️ Posted help message as a comment to PR/issue #{pr_number}.")
                    return {"status": "help_posted"}
                else:
                    logger.warning("Could not determine PR or issue number to post help message.")
                    return {"status": "help", "message": help_message}

            # Acknowledgment—user wants to mark violation as known/accepted.
            ack_reason = self._extract_acknowledgment_reason(comment_body)
            if ack_reason is not None:
                task_id = await task_queue.enqueue(
                    event_type="violation_acknowledgment",
                    repo_full_name=repo,
                    installation_id=installation_id,
                    payload={**event.payload, "acknowledgment_reason": ack_reason},
                )
                logger.info(f"✅ Acknowledgment comment enqueued with task ID: {task_id}")
                return {"status": "acknowledgment_queued", "task_id": task_id, "reason": ack_reason}

            # Evaluate—user wants feasibility check for rule idea.
            eval_rule = self._extract_evaluate_rule(comment_body)
            if eval_rule is not None:
                agent = get_agent("feasibility")
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
                    logger.info(f"📝 Posted feasibility evaluation result as a comment to PR/issue #{pr_number}.")
                    return {"status": "feasibility_evaluation_posted"}
                else:
                    logger.warning("Could not determine PR or issue number to post feasibility evaluation result.")
                    return {"status": "feasibility_evaluation", "message": comment}

            # Validate—user wants rules.yaml sanity check.
            if self._is_validate_comment(comment_body):
                logger.info("🔍 Processing validate command.")
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
                    logger.info(f"✅ Posted validation result as a comment to PR/issue #{pr_number}.")
                    return {"status": "validation_posted"}
                else:
                    logger.warning("Could not determine PR or issue number to post validation result.")
                    return {"status": "validation", "message": validation_result}

            else:
                # No match—ignore, avoid noise.
                logger.info("📋 Comment does not match any known patterns - ignoring")
                return {"status": "ignored", "reason": "No matching patterns"}

        except Exception as e:
            logger.error(f"❌ Error handling issue comment: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _extract_acknowledgment_reason(self, comment_body: str) -> str | None:
        """Extract the quoted reason from an acknowledgment command, or None if not present."""
        comment_body = comment_body.strip()

        logger.info("extracting_acknowledgment_reason", body_length=len(comment_body))

        # Regex flexibility—users type commands in unpredictable ways.
        patterns = [
            r'@watchflow\s+(acknowledge|ack)\s+"([^"]+)"',  # Double quotes—most common
            r"@watchflow\s+(acknowledge|ack)\s+'([^']+)'",  # Single quotes—fallback
            r"@watchflow\s+(acknowledge|ack)\s+([^\n\r]+)",  # No quotes—last resort
        ]

        for i, pattern in enumerate(patterns):
            match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
            if match:
                # All patterns: group 2 = reason. Brittle if GitHub changes format.
                reason = match.group(2).strip()
                logger.info(f"✅ Pattern {i + 1} matched! Reason: '{reason}'")
                if reason:  # Defensive: skip empty reasons—user typo, bot spam.
                    return reason
            else:
                logger.info(f"❌ Pattern {i + 1} did not match")

        logger.info("❌ No patterns matched for acknowledgment reason")
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
        # Pythonic: use any() for pattern match—cleaner, faster.
        return any(re.search(pattern, comment_body, re.IGNORECASE) for pattern in patterns)
