"""Risk assessment processor — handles RISK_ASSESSMENT tasks."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.agents import get_agent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.event_processors.risk_assessment.signals import generate_risk_assessment
from src.presentation.github_formatter import format_risk_assessment_comment

if TYPE_CHECKING:
    from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)

_RISK_LABELS = [
    "watchflow:risk-low",
    "watchflow:risk-medium",
    "watchflow:risk-high",
    "watchflow:risk-critical",
]

_LABEL_COLORS = {
    "watchflow:risk-low": ("0e8a16", "Watchflow: low risk PR"),
    "watchflow:risk-medium": ("fbca04", "Watchflow: medium risk PR"),
    "watchflow:risk-high": ("d93f0b", "Watchflow: high risk PR"),
    "watchflow:risk-critical": ("b60205", "Watchflow: critical risk PR"),
}


class RiskAssessmentProcessor(BaseEventProcessor):
    """Processor that performs risk assessment."""

    def __init__(self) -> None:
        super().__init__()
        self.engine_agent = get_agent("engine")

    def get_event_type(self) -> str:
        return "risk_assessment"

    async def process(self, task: Task) -> ProcessingResult:
        start_time = time.time()
        api_calls = 0

        event_data = task.payload
        repo = event_data.get("repository", {}).get("full_name")
        installation_id = event_data.get("installation", {}).get("id")
        pr_number = event_data.get("issue", {}).get("number")

        logger.info(f"Risk assessment started for {repo}#{pr_number}")

        try:
            if not repo or not installation_id or not pr_number:
                logger.error("Missing repo, installation_id, or pr_number in risk assessment payload")
                return ProcessingResult(
                    success=False,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Missing required payload fields",
                )

            # Fetch PR data
            pr_data = await self.github_client.get_pull_request(repo, pr_number, installation_id)
            api_calls += 1
            if not pr_data:
                logger.error(f"Failed to fetch PR data for {repo}#{pr_number}")
                return ProcessingResult(
                    success=False,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Failed to fetch PR data",
                )

            pr_files = await self.github_client.get_pull_request_files(repo, pr_number, installation_id)
            api_calls += 1

            risk_assessment_result = await generate_risk_assessment(repo, installation_id, pr_data, pr_files)

            logger.info(
                f"Risk assessment complete for {repo}#{pr_number}: "
                f"{risk_assessment_result.level} ({len(risk_assessment_result.signals)} signals triggered)"
            )

            # Post comment
            comment = format_risk_assessment_comment(risk_assessment_result)
            await self.github_client.create_pull_request_comment(
                repo=repo,
                pr_number=pr_number,
                comment=comment,
                installation_id=installation_id,
            )
            api_calls += 1

            await self.github_client.add_labels_to_issue(
                repo, pr_number, [f"watchflow:risk-{risk_assessment_result.level}"], installation_id
            )
            api_calls += 1

            return ProcessingResult(
                success=True,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.error(f"Error in risk assessment for {repo}#{pr_number}: {e}", exc_info=True)
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    # Required abstract method stubs
    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        return {}
