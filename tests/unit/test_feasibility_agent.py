"""
Unit tests for the Rule Feasibility Agent with structured output.
These tests mock external dependencies (OpenAI API) for fast, isolated testing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.feasibility_agent.agent import RuleFeasibilityAgent
from src.agents.feasibility_agent.models import FeasibilityAnalysis, YamlGeneration


class TestRuleFeasibilityAgent:
    """Test suite for RuleFeasibilityAgent with structured output."""

    @pytest.fixture
    def agent(self):
        """Create agent instance for testing."""
        # Mock both config validation and LLM client creation to avoid requiring API key
        with (
            patch("src.agents.base.BaseAgent._validate_config"),
            patch("src.agents.base.BaseAgent._create_llm_client", return_value=MagicMock()),
        ):
            return RuleFeasibilityAgent()

    @pytest.fixture
    def mock_feasible_analysis(self):
        """Mock successful feasibility analysis."""
        return FeasibilityAnalysis(
            is_feasible=True,
            rule_type="time_restriction",
            confidence_score=0.95,
            feedback="This rule can be implemented using Watchflow's time restriction feature.",
            analysis_steps=[
                "Identified rule as time-based restriction",
                "Confirmed Watchflow supports time restrictions",
                "Mapped to deployment event with weekend exclusion",
            ],
        )

    @pytest.fixture
    def mock_unfeasible_analysis(self):
        """Mock unsuccessful feasibility analysis."""
        return FeasibilityAnalysis(
            is_feasible=False,
            rule_type="undefined",
            confidence_score=1.0,
            feedback="This rule cannot be implemented as it lacks actionable criteria.",
            analysis_steps=[
                "Analyzed rule description",
                "Found no actionable conditions",
                "Determined rule is not implementable",
            ],
        )

    @pytest.fixture
    def mock_yaml_generation(self):
        """Mock YAML generation result."""
        return YamlGeneration(
            yaml_content="""- id: "no-deployments-weekends"
  name: "No Weekend Deployments"
  description: "Prevent deployments on weekends"
  enabled: true
  severity: "high"
  event_types: ["deployment"]
  parameters:
    days: ["saturday", "sunday"]"""
        )

    @pytest.mark.asyncio
    async def test_feasible_rule_execution(self, agent, mock_feasible_analysis, mock_yaml_generation):
        """Test successful execution of a feasible rule."""
        with patch("src.agents.feasibility_agent.nodes.ChatOpenAI") as mock_openai:
            # Mock the structured LLM calls
            mock_analysis_llm = AsyncMock()
            mock_analysis_llm.ainvoke.return_value = mock_feasible_analysis

            mock_yaml_llm = AsyncMock()
            mock_yaml_llm.ainvoke.return_value = mock_yaml_generation

            mock_openai.return_value.with_structured_output.side_effect = [
                mock_analysis_llm,  # First call for analysis
                mock_yaml_llm,  # Second call for YAML
            ]

            # Execute the agent
            result = await agent.execute("No deployments on weekends")

            # Assertions
            assert result.success is True
            assert result.data["is_feasible"] is True
            assert result.data["rule_type"] == "time_restriction"
            assert result.data["confidence_score"] == 0.95
            assert "weekend" in result.data["yaml_content"].lower()
            assert len(result.data["analysis_steps"]) == 3

            # Verify both LLM calls were made (analysis + YAML)
            assert mock_analysis_llm.ainvoke.call_count == 1
            assert mock_yaml_llm.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_unfeasible_rule_execution(self, agent, mock_unfeasible_analysis):
        """Test execution of an unfeasible rule (should skip YAML generation)."""
        with patch("src.agents.feasibility_agent.nodes.ChatOpenAI") as mock_openai:
            # Mock only the analysis LLM call
            mock_analysis_llm = AsyncMock()
            mock_analysis_llm.ainvoke.return_value = mock_unfeasible_analysis

            mock_openai.return_value.with_structured_output.return_value = mock_analysis_llm

            # Execute the agent
            result = await agent.execute("This is impossible to implement")

            # Assertions
            assert result.success is False  # Success should be False for unfeasible rules
            assert result.data["is_feasible"] is False
            assert result.data["rule_type"] == "undefined"
            assert result.data["confidence_score"] == 1.0
            assert result.data["yaml_content"] == ""  # No YAML should be generated

            # Verify only analysis LLM call was made (no YAML generation)
            assert mock_analysis_llm.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_error_handling_in_analysis(self, agent):
        """Test error handling when analysis fails."""
        with patch("src.agents.feasibility_agent.nodes.ChatOpenAI") as mock_openai:
            # Mock LLM to raise an exception
            mock_analysis_llm = AsyncMock()
            mock_analysis_llm.ainvoke.side_effect = Exception("OpenAI API error")

            mock_openai.return_value.with_structured_output.return_value = mock_analysis_llm

            # Execute the agent
            result = await agent.execute("Test rule")

            # Assertions
            assert result.success is False
            assert "Analysis failed" in result.message
            assert result.data["is_feasible"] is False
            assert result.data["confidence_score"] == 0.0

    @pytest.mark.asyncio
    async def test_error_handling_in_yaml_generation(self, agent, mock_feasible_analysis):
        """Test error handling when YAML generation fails."""
        with patch("src.agents.feasibility_agent.nodes.ChatOpenAI") as mock_openai:
            # Mock analysis to succeed, YAML generation to fail
            mock_analysis_llm = AsyncMock()
            mock_analysis_llm.ainvoke.return_value = mock_feasible_analysis

            mock_yaml_llm = AsyncMock()
            mock_yaml_llm.ainvoke.side_effect = Exception("YAML generation failed")

            mock_openai.return_value.with_structured_output.side_effect = [mock_analysis_llm, mock_yaml_llm]

            # Execute the agent
            result = await agent.execute("No deployments on weekends")

            # Assertions
            assert result.success is True  # Analysis succeeded
            assert result.data["is_feasible"] is True
            assert "YAML generation failed" in result.message  # Error should be in feedback

    def test_agent_initialization(self, agent):
        """Test that the agent initializes correctly."""
        assert agent is not None
        assert agent.graph is not None
        assert agent.llm is not None

    @pytest.mark.asyncio
    async def test_various_rule_types(self, agent):
        """Test different types of rules to ensure proper classification."""
        test_cases = [
            {"rule": "All PRs need 2 approvals", "expected_type": "approval_requirement", "should_be_feasible": True},
            {"rule": "PR titles must start with JIRA-", "expected_type": "title_pattern", "should_be_feasible": True},
            {"rule": "Files over 10MB not allowed", "expected_type": "file_size", "should_be_feasible": True},
        ]

        for case in test_cases:
            with patch("src.agents.feasibility_agent.nodes.ChatOpenAI") as mock_openai:
                # Mock analysis response
                mock_analysis = FeasibilityAnalysis(
                    is_feasible=case["should_be_feasible"],
                    rule_type=case["expected_type"],
                    confidence_score=0.9,
                    feedback=f"Rule can be implemented as {case['expected_type']}",
                    analysis_steps=["Analysis step"],
                )

                mock_yaml = YamlGeneration(yaml_content="mock yaml content")

                mock_analysis_llm = AsyncMock()
                mock_analysis_llm.ainvoke.return_value = mock_analysis

                mock_yaml_llm = AsyncMock()
                mock_yaml_llm.ainvoke.return_value = mock_yaml

                mock_openai.return_value.with_structured_output.side_effect = [mock_analysis_llm, mock_yaml_llm]

                # Execute
                result = await agent.execute(case["rule"])

                # Verify
                assert result.data["rule_type"] == case["expected_type"]
                assert result.data["is_feasible"] == case["should_be_feasible"]


class TestFeasibilityModels:
    """Test the Pydantic models for structured output."""

    def test_feasibility_analysis_model(self):
        """Test FeasibilityAnalysis model validation."""
        # Valid model
        analysis = FeasibilityAnalysis(
            is_feasible=True,
            rule_type="time_restriction",
            confidence_score=0.95,
            feedback="Test feedback",
            analysis_steps=["step1", "step2"],
        )

        assert analysis.is_feasible is True
        assert analysis.rule_type == "time_restriction"
        assert analysis.confidence_score == 0.95

    def test_feasibility_analysis_validation(self):
        """Test FeasibilityAnalysis model validation constraints."""
        # Test confidence score validation
        with pytest.raises(ValueError):
            FeasibilityAnalysis(
                is_feasible=True,
                rule_type="test",
                confidence_score=1.5,  # Invalid: > 1.0
                feedback="test",
            )

        with pytest.raises(ValueError):
            FeasibilityAnalysis(
                is_feasible=True,
                rule_type="test",
                confidence_score=-0.1,  # Invalid: < 0.0
                feedback="test",
            )

    def test_yaml_generation_model(self):
        """Test YamlGeneration model."""
        yaml_gen = YamlGeneration(yaml_content="test: yaml")
        assert yaml_gen.yaml_content == "test: yaml"
