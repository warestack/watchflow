"""Tests for LLM-assisted conditions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rules.conditions.llm_assisted import (
    AlignmentVerdict,
    DescriptionDiffAlignmentCondition,
    _truncate_text,
)


@pytest.fixture
def condition():
    return DescriptionDiffAlignmentCondition()


def _make_context(
    description="Fix login bug by correcting session validation",
    title="fix: resolve login session timeout",
    diff_summary="- src/auth/session.py (modified, +10/-3)\n    +validate_session()",
    changed_files=None,
    require=True,
):
    if changed_files is None:
        changed_files = [
            {"filename": "src/auth/session.py", "status": "modified", "additions": 10, "deletions": 3, "patch": ""},
        ]
    return {
        "parameters": {"require_description_diff_alignment": require},
        "event": {
            "pull_request_details": {"title": title, "body": description},
            "diff_summary": diff_summary,
            "changed_files": changed_files,
        },
    }


class TestTruncateText:
    """Tests for _truncate_text helper function."""

    def test_no_truncation_when_under_limit(self):
        text = "Short text"
        assert _truncate_text(text, 100) == "Short text"

    def test_truncation_when_over_limit(self):
        text = "a" * 2500
        result = _truncate_text(text, 2000)
        assert len(result) <= 2000 + len("... [truncated]")
        assert result.endswith("... [truncated]")
        assert result.startswith("a" * 100)

    def test_default_max_length(self):
        text = "b" * 3000
        result = _truncate_text(text)
        assert result.endswith("... [truncated]")
        assert len(result) <= 2000 + len("... [truncated]")


class TestDescriptionDiffAlignmentCondition:
    """Tests for DescriptionDiffAlignmentCondition."""

    def test_class_attributes(self, condition):
        assert condition.name == "description_diff_alignment"
        assert "require_description_diff_alignment" in condition.parameter_patterns
        assert "pull_request" in condition.event_types

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, condition):
        context = _make_context(require=False)
        violations = await condition.evaluate(context)
        assert violations == []

    @pytest.mark.asyncio
    async def test_skips_when_no_changed_files(self, condition):
        context = _make_context(changed_files=[])
        violations = await condition.evaluate(context)
        assert violations == []

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_no_violation_when_aligned(self, mock_get_chat_model, condition):
        """LLM says description is aligned -> no violation."""
        verdict = AlignmentVerdict(
            decision="aligned",
            confidence=0.9,
            reasoning="Description matches diff.",
            recommendations=None,
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context()
        violations = await condition.evaluate(context)

        assert violations == []
        mock_get_chat_model.assert_called_once_with(temperature=0.0, max_tokens=512)
        mock_structured.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_violation_when_misaligned(self, mock_get_chat_model, condition):
        """LLM says description is misaligned -> violation with reason."""
        verdict = AlignmentVerdict(
            decision="misaligned",
            confidence=0.9,
            reasoning="Description says 'fix login' but diff only touches billing code.",
            recommendations=["Update the description to mention billing changes."],
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context(
            description="Fix login bug",
            changed_files=[
                {"filename": "src/billing/invoice.py", "status": "modified", "additions": 50, "deletions": 10},
            ],
        )
        violations = await condition.evaluate(context)

        assert len(violations) == 1
        assert "does not align with code changes" in violations[0].message
        assert "billing" in violations[0].message
        assert violations[0].how_to_fix == "Update the description to mention billing changes."
        assert violations[0].severity.value == "medium"

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_violation_uses_default_how_to_fix(self, mock_get_chat_model, condition):
        """When LLM returns no recommendations, a sensible default is used."""
        verdict = AlignmentVerdict(
            decision="misaligned",
            confidence=0.8,
            reasoning="Generic description.",
            recommendations=None,
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context(description="update code")
        violations = await condition.evaluate(context)

        assert len(violations) == 1
        assert "accurately summarize" in violations[0].how_to_fix

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_human_in_the_loop_for_low_confidence(self, mock_get_chat_model, condition):
        """When confidence < 0.5, requires human review."""
        verdict = AlignmentVerdict(
            decision="aligned",
            confidence=0.4,
            reasoning="Uncertain about alignment due to vague description.",
            recommendations=None,
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context()
        violations = await condition.evaluate(context)

        assert len(violations) == 1
        assert "human review" in violations[0].message.lower()
        assert "40.0%" in violations[0].message or "0.4" in violations[0].message

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_graceful_degradation_on_llm_failure(self, mock_get_chat_model, condition):
        """When LLM call fails, condition returns no violation (fail-open)."""
        mock_get_chat_model.side_effect = Exception("Provider not configured")

        context = _make_context()
        violations = await condition.evaluate(context)

        assert violations == []

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)  # Mock async sleep to speed up test
    @patch("src.integrations.providers.get_chat_model")
    async def test_retry_logic_with_exponential_backoff(self, mock_get_chat_model, mock_sleep, condition):
        """When structured invoke fails, retries with exponential backoff."""
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(side_effect=RuntimeError("Rate limited"))
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context()
        violations = await condition.evaluate(context)

        assert violations == []
        # Should have retried 3 times total
        assert mock_structured.ainvoke.await_count == 3
        # Should have slept twice (2s, 4s)
        assert mock_sleep.await_count == 2

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_graceful_degradation_on_malformed_output(self, mock_get_chat_model, condition):
        """When structured.ainvoke returns unexpected type, no violation."""
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value={"decision": "aligned"})
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context()
        violations = await condition.evaluate(context)

        assert violations == []

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_skips_when_no_structured_output_support(self, mock_get_chat_model, condition):
        """When provider doesn't support structured output, gracefully skip."""
        mock_llm = MagicMock()
        # Remove with_structured_output method to simulate unsupported provider
        delattr(mock_llm, "with_structured_output")
        mock_get_chat_model.return_value = mock_llm

        context = _make_context()
        violations = await condition.evaluate(context)

        assert violations == []

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_empty_description_sent_to_llm(self, mock_get_chat_model, condition):
        """Empty description is forwarded as '(empty)' so the LLM can flag it."""
        verdict = AlignmentVerdict(
            decision="misaligned",
            confidence=0.9,
            reasoning="PR description is empty.",
            recommendations=["Add a description."],
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        context = _make_context(description="")
        violations = await condition.evaluate(context)

        assert len(violations) == 1
        # Verify "(empty)" was in the prompt
        call_messages = mock_structured.ainvoke.call_args[0][0]
        human_msg = call_messages[1].content
        assert "(empty)" in human_msg

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_file_list_truncated_to_20(self, mock_get_chat_model, condition):
        """File list sent to LLM is capped at 20 entries."""
        verdict = AlignmentVerdict(
            decision="aligned",
            confidence=0.9,
            reasoning="OK",
            recommendations=None,
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        files = [
            {"filename": f"src/file_{i}.py", "status": "modified", "additions": 1, "deletions": 0} for i in range(50)
        ]
        context = _make_context(changed_files=files)
        await condition.evaluate(context)

        call_messages = mock_structured.ainvoke.call_args[0][0]
        human_msg = call_messages[1].content
        assert "file_19.py" in human_msg
        assert "file_20.py" not in human_msg

    @pytest.mark.asyncio
    @patch("src.integrations.providers.get_chat_model")
    async def test_text_truncation_applied(self, mock_get_chat_model, condition):
        """Very long description/title/diff are truncated before sending to LLM."""
        verdict = AlignmentVerdict(
            decision="aligned",
            confidence=0.9,
            reasoning="OK",
            recommendations=None,
            strategy_used="semantic_comparison",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=verdict)
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_chat_model.return_value = mock_llm

        # Create excessively long inputs
        long_description = "x" * 3000
        long_title = "y" * 500
        long_diff = "z" * 3000

        context = _make_context(description=long_description, title=long_title, diff_summary=long_diff)
        await condition.evaluate(context)

        call_messages = mock_structured.ainvoke.call_args[0][0]
        human_msg = call_messages[1].content
        # Should contain truncation markers
        assert "[truncated]" in human_msg
