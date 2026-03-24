import logging
import re

from src.agents import get_agent
from src.core.models import EventType, WebhookEvent
from src.integrations.github import github_client
from src.rules.utils import _validate_rules_yaml
from src.tasks.task_queue import task_queue
from src.webhooks.handlers.base import EventHandler, WebhookResponse

logger = logging.getLogger(__name__)


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
                logger.info(f"🤖 Ignoring comment from bot user: {commenter}")
                return WebhookResponse(status="ignored", detail="Bot comment")

            logger.info(f"👤 Processing comment from human user: {commenter}")

            # Help command—user likely lost/confused.
            if self._is_help_comment(comment_body):
                help_message = (
                    "Here are the available Watchflow commands:\n"
                    '- @watchflow acknowledge "reason" — Acknowledge a rule violation.\n'
                    '- @watchflow ack "reason" — Short form for acknowledge.\n'
                    '- @watchflow evaluate "rule description" — Evaluate the feasibility of a rule.\n'
                    "- @watchflow validate — Validate the .watchflow/rules.yaml file.\n"
                    "- /risk — Show risk assessment.\n"
                    "- /reviewers — Recommend the best reviewers for this PR.\n"
                    "- /reviewers --force — Re-run reviewer recommendation (bypass cache).\n"
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
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("Could not determine PR or issue number to post help message.")
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
                logger.info(f"✅ Acknowledgment comment enqueued: {result}")
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
                    logger.info(f"📝 Posted feasibility evaluation result as a comment to PR/issue #{pr_number}.")
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("Could not determine PR or issue number to post feasibility evaluation result.")
                    return WebhookResponse(status="ok", detail=comment)

            # Reviewers—user wants reviewer recommendations.
            reviewers_match = self._extract_reviewers_command(comment_body)
            if reviewers_match is not None:
                logger.info("🔍 Processing reviewers command.")
                from src.event_processors.factory import EventProcessorFactory
                from src.tasks.task_queue import Task

                force = reviewers_match.get("force", False)

                async def process_reviewer_recommendation(rec_task: Task) -> None:
                    processor = EventProcessorFactory.get_processor("reviewer_recommendation")
                    await processor.process(rec_task)

                rec_payload = {**event.payload, "reviewers_force": force}
                result = await task_queue.enqueue(
                    process_reviewer_recommendation,
                    "reviewer_recommendation",
                    rec_payload,
                )
                logger.info(f"✅ Reviewer recommendation enqueued: {result}")
                return WebhookResponse(
                    status="ok",
                    detail="Reviewer recommendation enqueued",
                )

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
                        comment=str(validation_result),
                        installation_id=installation_id,
                    )
                    logger.info(f"✅ Posted validation result as a comment to PR/issue #{pr_number}.")
                    return WebhookResponse(status="ok")
                else:
                    logger.warning("Could not determine PR or issue number to post validation result.")
                    return WebhookResponse(status="ok", detail=str(validation_result))

            # Risk assessment—user wants a risk assessment with risk level and reason.
            if self._is_risk_comment(comment_body):
                from src.event_processors.factory import EventProcessorFactory
                from src.tasks.task_queue import Task

                async def process_risk_assessment(risk_task: Task) -> None:
                    processor = EventProcessorFactory.get_processor("risk_assessment")
                    await processor.process(risk_task)

                task = task_queue.build_task(
                    "risk_assessment",
                    event.payload,
                    process_risk_assessment,
                )
                risk_result = await task_queue.enqueue(
                    process_risk_assessment,
                    "risk_assessment",
                    event.payload,
                    task,
                )
                logger.info(f"⚡ Risk assessment enqueued: {risk_result}")
                return WebhookResponse(status="ok", detail="Risk assessment enqueued")

            else:
                # No match—ignore, avoid noise.
                logger.info("📋 Comment does not match any known patterns - ignoring")
                return WebhookResponse(status="ignored", detail="No matching patterns")

        except Exception as e:
            logger.error(f"❌ Error handling issue comment: {str(e)}")
            return WebhookResponse(status="error", detail=str(e))

    def _extract_acknowledgment_reason(self, comment_body: str) -> str | None:
        """Extract the quoted reason from an acknowledgment command, or None if not present."""
        comment_body = comment_body.strip()

        logger.info("extracting_acknowledgment_reason")

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

    def _extract_reviewers_command(self, comment_body: str) -> dict[str, bool] | None:
        """Detect /reviewers or @watchflow reviewers command. Returns dict with force flag, or None."""
        comment_body = comment_body.strip()
        patterns = [
            r"(?:@watchflow\s+reviewers|/reviewers)(\s+--force)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, comment_body, re.IGNORECASE)
            if match:
                force = bool(match.group(1) and "--force" in match.group(1))
                return {"force": force}
        return None

    def _is_help_comment(self, comment_body: str) -> bool:
        patterns = [
            r"@watchflow\s+help",
        ]
        # Pythonic: use any() for pattern match—cleaner, faster.
        return any(re.search(pattern, comment_body, re.IGNORECASE) for pattern in patterns)

    def _is_risk_comment(self, comment_body: str) -> bool:
        return bool(re.search(r"^/risk\s*$", comment_body.strip(), re.IGNORECASE))
