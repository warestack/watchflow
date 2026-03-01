"""LLM-assisted conditions for semantic rule evaluation.

This module contains conditions that use an LLM to perform evaluations
that cannot be expressed as deterministic checks. These conditions are
opt-in and clearly documented as having LLM latency in the evaluation path.
"""

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = logging.getLogger(__name__)


def _truncate_text(text: str, max_length: int = 2000) -> str:
    """Truncate text to prevent excessively large prompts and potential injection.

    Args:
        text: The text to truncate
        max_length: Maximum length in characters (default: 2000)

    Returns:
        Truncated text with ellipsis if needed
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + "... [truncated]"


class AlignmentVerdict(BaseModel):
    """Structured LLM response for description-diff alignment evaluation.

    This follows the standard agent output schema for consistency across
    LLM-assisted conditions.
    """

    decision: str = Field(description="Whether the description is 'aligned' or 'misaligned'")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0", ge=0.0, le=1.0)
    reasoning: str = Field(description="Brief explanation of the alignment or mismatch")
    recommendations: list[str] | None = Field(
        description="Actionable suggestions for improving the description (only if misaligned)", default=None
    )
    strategy_used: str = Field(description="The strategy used to evaluate the description")


_SYSTEM_PROMPT = """\
You are a senior code reviewer evaluating whether a pull request description \
accurately reflects the actual code changes shown in the diff.

Guidelines:
- A description is "aligned" if it describes the INTENT and SCOPE of the \
changes, even if it does not list every file.
- Minor omissions are acceptable (e.g., not mentioning a test file that \
accompanies a feature). Focus on whether the description would mislead a reviewer.
- Flag clear mismatches: description says "fix login bug" but diff only touches \
billing code; description claims refactoring but diff adds a new feature; \
description is entirely generic ("update code") with no mention of what changed.
- If the description is empty or trivially short (e.g. "fix", "update"), treat \
it as misaligned.
- Respond with structured output only. Do NOT include markdown or extra text."""

_HUMAN_PROMPT_TEMPLATE = """\
## PR title
{title}

## PR description
{description}

## Diff summary (top changed files)
{diff_summary}

## Changed file list
{file_list}

Evaluate whether the PR description aligns with the actual code changes."""


class DescriptionDiffAlignmentCondition(BaseCondition):
    """Validates that the PR description semantically matches the code diff.

    This is the first LLM-backed condition in Watchflow. It uses the configured
    AI provider (OpenAI / Bedrock / Vertex AI) to compare the PR description
    against the diff summary and flag mismatches. Because it calls an LLM, it
    adds latency (~1-3s) compared to deterministic conditions.

    The condition gracefully degrades: if the LLM call fails (provider not
    configured, rate limit, network error), it logs a warning and returns no
    violation rather than blocking the PR.
    """

    name = "description_diff_alignment"
    description = "Validates that the PR description accurately reflects the actual code changes."
    parameter_patterns = ["require_description_diff_alignment"]
    event_types = ["pull_request"]
    examples = [{"require_description_diff_alignment": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate description-diff alignment using an LLM with retries and graceful degradation."""
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        if not parameters.get("require_description_diff_alignment"):
            return []

        pr_details = event.get("pull_request_details", {})
        title = pr_details.get("title", "")
        description_body = pr_details.get("body") or ""
        diff_summary = event.get("diff_summary", "")
        changed_files = event.get("changed_files", [])

        # Nothing to compare against
        if not changed_files:
            return []

        # Truncate inputs to prevent prompt injection and token overflow
        title_sanitized = _truncate_text(title, 200)
        description_sanitized = _truncate_text(description_body, 2000)
        diff_sanitized = _truncate_text(diff_summary, 2000)

        file_list = "\n".join(
            f"- {f.get('filename', '?')} ({f.get('status', '?')}, "
            f"+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in changed_files[:20]
        )

        human_prompt = _HUMAN_PROMPT_TEMPLATE.format(
            title=title_sanitized or "(no title)",
            description=description_sanitized or "(empty)",
            diff_summary=diff_sanitized or "(no diff summary available)",
            file_list=file_list,
        )

        # Retry loop with exponential backoff
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                from langchain_core.messages import HumanMessage, SystemMessage

                from src.integrations.providers import get_chat_model

                llm = get_chat_model(
                    temperature=0.0,
                    max_tokens=512,
                )

                # Check if provider supports structured output
                supports_structured = hasattr(llm, "with_structured_output") and callable(
                    getattr(llm, "with_structured_output")
                )

                if not supports_structured:
                    logger.warning("Provider does not support structured output; skipping alignment check.")
                    return []

                structured_llm = llm.with_structured_output(AlignmentVerdict, method="function_calling")

                messages = [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ]

                start_time = time.time()
                verdict: AlignmentVerdict = await structured_llm.ainvoke(messages)
                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    "LLM alignment check completed",
                    extra={
                        "attempt": attempt,
                        "latency_ms": latency_ms,
                        "decision": getattr(verdict, "decision", "unknown"),
                        "confidence": getattr(verdict, "confidence", 0.0),
                    },
                )

                # Validate response type
                if not isinstance(verdict, AlignmentVerdict):
                    logger.warning("LLM returned unexpected type; skipping.")
                    return []

                # Human-in-the-loop fallback for low confidence
                if verdict.confidence < 0.5:
                    logger.info(f"Low confidence ({verdict.confidence:.2f}); flagging for human review.")
                    return [
                        Violation(
                            rule_description=self.description,
                            severity=Severity.MEDIUM,
                            message=f"LLM confidence is low ({verdict.confidence:.1%}), requiring human review. Reasoning: {verdict.reasoning}",
                            how_to_fix="Manually review the PR description to ensure it aligns with the code changes.",
                        )
                    ]

                # Check alignment decision
                if verdict.decision == "misaligned":
                    recommendation = verdict.recommendations[0] if verdict.recommendations else None
                    return [
                        Violation(
                            rule_description=self.description,
                            severity=Severity.MEDIUM,
                            message=f"PR description does not align with code changes: {verdict.reasoning}",
                            how_to_fix=recommendation
                            or "Update the PR description to accurately summarize the intent and scope of the code changes.",
                        )
                    ]

                # Success: aligned
                return []

            except Exception as e:
                wait_time = 2**attempt  # Exponential backoff: 2s, 4s, 8s
                logger.warning(
                    f"LLM call failed (attempt {attempt}/{max_attempts})",
                    extra={"error": str(e), "retry_in_seconds": wait_time if attempt < max_attempts else None},
                    exc_info=True,
                )

                if attempt < max_attempts:
                    time.sleep(wait_time)
                else:
                    # All attempts failed - gracefully degrade
                    logger.error("All LLM retry attempts exhausted; skipping alignment check.")
                    return []

        return []
