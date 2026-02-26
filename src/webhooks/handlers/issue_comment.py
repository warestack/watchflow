import re

import structlog

from src.agents import get_agent
from src.core.models import EventType, WebhookEvent
from src.integrations.github import github_client
from src.rules.utils import _validate_rules_yaml
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler, WebhookResponse

logger = structlog.get_logger()


class IssueCommentEventHandler(EventHandler):
    """Handler for GitHub issue comment events."""

    @property
    def event_type(self) -> EventType:
        return EventType.ISSUE_COMMENT

    async def can_handle(self, event: WebhookEvent) -> bool:
        return event.event_type == EventType.ISSUE_COMMENT

    async def handle(self, event: WebhookEvent) -> WebhookResponse:
        """Handle issue comment events."""
        try:
            comment_body = event.payload.get("comment", {}).get("body", "")
            commenter = event.payload.get("comment", {}).get("user", {}).get("login")
            repo = event.repo_full_name
            installation_id = event.installation_id

            logger.info(f"comment_processed commenter={commenter} body_length={len(comment_body)}")

            # Bot self-reply guard—avoids infinite loop, spam.
            bot_usernames = ["watchflow[bot]", "watchflow-bot", "watchflow", "watchflowbot", "watchflow_bot"]
            if commenter and any(bot_name.lower() in commenter.lower() for bot_name in bot_usernames):
                logger.info("ignoring_comment_from_bot_user", commenter=commenter)
                return WebhookResponse(status="ignored", detail="Bot comment")

            logger.info("processing_comment_from_human_user", commenter=commenter)

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
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return WebhookResponse(status="ok", detail=help_message)

            # Acknowledgment—user wants to mark violation as known/accepted.
            ack_reason = self._extract_acknowledgment_reason(comment_body)
            if ack_reason is not None:
                from src.event_processors.factory import EventProcessorFactory
                from src.tasks.task_queue import Task

                # Create a proper handler for the acknowledgment
                async def process_acknowledgment(acknowledgment_task: Task) -> None:
                    """Handler for processing violation acknowledgments."""
                    processor = EventProcessorFactory.get_processor("violation_acknowledgment")
                    await processor.process(acknowledgment_task)

                # Build the payload with acknowledgment reason included
                ack_payload = {**event.payload, "acknowledgment_reason": ack_reason}

                # Enqueue with correct signature: (func, event_type, payload, *args, **kwargs)
                result = await task_queue.enqueue(
                    process_acknowledgment,
                    "violation_acknowledgment",
                    ack_payload,
                )
                logger.info("acknowledgment_comment_enqueued", result=result)
                return WebhookResponse(
                    status="ok",
                    detail=f"Acknowledgment enqueued with reason: {ack_reason}",
                )

            # Evaluate—user wants feasibility check for rule idea.
            eval_rule = self._extract_evaluate_rule(comment_body)
            if eval_rule is not None:
                agent = get_agent("feasibility")
                # Use a different variable name to avoid mypy confusion with previous 'result' variable
                evaluation_result = await agent.execute(rule_description=eval_rule)
                is_feasible = evaluation_result.data.get("is_feasible", False)
                yaml_content = evaluation_result.data.get("yaml_content", "")
                feedback = evaluation_result.message
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
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return WebhookResponse(status="ok", detail=comment)

            # Validate—user wants rules.yaml sanity check.
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
                        comment=str(validation_result),
                        installation_id=installation_id,
                    )
                    logger.info("posted_validation_result_as_a_comment", pr_number=pr_number)
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("could_not_determine_pr_or_issue")
                    return WebhookResponse(status="ok", detail=str(validation_result))

            else:
                # No match—ignore, avoid noise.
                logger.info("comment_does_not_match_any_known")
                return WebhookResponse(status="ignored", detail="No matching patterns")

        except Exception as e:
            logger.error(f"❌ Error handling issue comment: {str(e)}")
            return WebhookResponse(status="error", detail=str(e))

    def _extract_acknowledgment_reason(self, comment_body: str) -> str | None:
        """Extract the quoted reason from an acknowledgment command, or None if not present."""
        comment_body = comment_body.strip()

        logger.info("extractingacknowledgmentreason")

        # Regex flexibility—users type commands in unpredictable ways.
        patterns = [
            r'@watchflow\s+(acknowledge|ack)\s+"([^"]+)"',  # Double quotes—most common
            r"@watchflow\s+(acknowledge|ack)\s+'([^']+)'",  # Single quotes—fallback
            r"@watchflow\s+(acknowledge|ack)\s+([^\n\r]+)",  # No quotes—last resort
        ]

        for _i, pattern in enumerate(patterns):
            match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
            if match:
                # All patterns: group 2 = reason. Brittle if GitHub changes format.
                reason = match.group(2).strip()
                logger.info("pattern_matched_reason", reason=reason)
                if reason:  # Defensive: skip empty reasons—user typo, bot spam.
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
        # Pythonic: use any() for pattern match—cleaner, faster.
        return any(re.search(pattern, comment_body, re.IGNORECASE) for pattern in patterns)
