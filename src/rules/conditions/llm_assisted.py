"""LLM-assisted conditions for semantic rule evaluation.

This module contains conditions that use an LLM to perform evaluations
that cannot be expressed as deterministic checks. These conditions are
opt-in and clearly documented as having LLM latency in the evaluation path.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = logging.getLogger(__name__)


class AlignmentVerdict(BaseModel):
    """Structured LLM response for description-diff alignment evaluation."""

    is_aligned: bool = Field(description="Whether the PR description accurately reflects the code changes")
    reason: str = Field(description="Brief explanation of the alignment or mismatch")
    how_to_fix: str | None = Field(
        description="Actionable suggestion for improving the description (only if misaligned)", default=None
    )


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
        """Evaluate description-diff alignment using an LLM."""
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

        file_list = "\n".join(
            f"- {f.get('filename', '?')} ({f.get('status', '?')}, "
            f"+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in changed_files[:20]
        )

        human_prompt = _HUMAN_PROMPT_TEMPLATE.format(
            title=title or "(no title)",
            description=description_body or "(empty)",
            diff_summary=diff_summary or "(no diff summary available)",
            file_list=file_list,
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from src.integrations.providers import get_chat_model

            llm = get_chat_model(
                temperature=0.0,
                max_tokens=512,
            )
            structured_llm = llm.with_structured_output(AlignmentVerdict, method="function_calling")

            messages = [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=human_prompt),
            ]

            verdict: AlignmentVerdict = await structured_llm.ainvoke(messages)

            if not verdict.is_aligned:
                return [
                    Violation(
                        rule_description=self.description,
                        severity=Severity.MEDIUM,
                        message=f"PR description does not align with code changes: {verdict.reason}",
                        how_to_fix=verdict.how_to_fix
                        or "Update the PR description to accurately summarize the intent and scope of the code changes.",
                    )
                ]

        except Exception:
            logger.warning(
                "LLM call failed for description-diff alignment check; skipping.",
                exc_info=True,
            )

        return []
