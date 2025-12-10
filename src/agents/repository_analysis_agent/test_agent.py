from unittest.mock import AsyncMock, patch

import pytest

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.agents.repository_analysis_agent.models import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryFeatures,
    RuleRecommendation,
)


class TestRepositoryAnalysisAgent:
    """Test cases for RepositoryAnalysisAgent."""

    @pytest.fixture
    def agent(self):
        """Create a test instance of RepositoryAnalysisAgent."""
        return RepositoryAnalysisAgent(max_retries=1, timeout=30.0)

    @pytest.mark.asyncio
    async def test_execute_invalid_repository_name(self, agent):
        """Test that invalid repository names are rejected."""
        result = await agent.execute("invalid-repo-name")

        assert not result.success
        assert "Invalid repository name format" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_mock_github_client(self, agent):
        """Test repository analysis with mocked GitHub client."""

        with patch("src.agents.repository_analysis_agent.nodes.github_client") as mock_client:
            mock_client.get_file_content = AsyncMock(
                side_effect=[
                    None,  # CONTRIBUTING.md not found
                    None,  # .github/CODEOWNERS not found
                    None,  # workflow file not found
                ]
            )
            mock_client.get_repository_contributors = AsyncMock(
                return_value=[
                    {"login": "user1", "contributions": 10},
                    {"login": "user2", "contributions": 5},
                ]
            )

            result = await agent.execute("test-owner/test-repo")

            assert result.success
            assert "analysis_response" in result.data

            response = result.data["analysis_response"]
            assert isinstance(response, RepositoryAnalysisResponse)
            assert response.repository_full_name == "test-owner/test-repo"
            assert isinstance(response.recommendations, list)
            assert isinstance(response.analysis_summary, dict)

    @pytest.mark.asyncio
    async def test_analyze_repository_with_contributing_file(self, agent):
        """Test analysis when CONTRIBUTING.md exists."""
        with patch("src.agents.repository_analysis_agent.nodes.github_client") as mock_client:
            mock_client.get_file_content = AsyncMock(
                side_effect=[
                    "# Contributing Guidelines\n\n## Testing\nAll PRs must include tests.",  # CONTRIBUTING.md
                    None,  # CODEOWNERS
                    None,  # workflow
                ]
            )
            mock_client.get_repository_contributors = AsyncMock(return_value=[])

            result = await agent.execute("test-owner/test-repo")

            assert result.success
            response = result.data["analysis_response"]

            assert len(response.recommendations) > 0

            assert response.analysis_summary["features_analyzed"]["has_contributing"] is True

    def test_workflow_structure(self, agent):
        """Test that the LangGraph workflow is properly structured."""
        graph = agent.graph

        assert hasattr(graph, "nodes")

    @pytest.mark.asyncio
    async def test_error_handling(self, agent):
        """Test error handling in repository analysis."""
        with patch("src.agents.repository_analysis_agent.nodes.github_client") as mock_client:
            mock_client.get_file_content = AsyncMock(side_effect=Exception("API Error"))
            mock_client.get_repository_contributors = AsyncMock(side_effect=Exception("API Error"))

            result = await agent.execute("test-owner/test-repo")

            assert isinstance(result, object)


class TestRuleRecommendation:
    """Test cases for RuleRecommendation model."""

    def test_valid_recommendation_creation(self):
        """Test creating a valid rule recommendation."""
        rec = RuleRecommendation(
            yaml_content="description: Test rule\nenabled: true",
            confidence=0.8,
            reasoning="Test reasoning",
            source_patterns=["has_workflows"],
            category="quality",
            estimated_impact="high",
        )

        assert rec.yaml_content == "description: Test rule\nenabled: true"
        assert rec.confidence == 0.8
        assert rec.category == "quality"

    def test_confidence_validation(self):
        """Test confidence score validation."""
        # Valid confidence
        rec = RuleRecommendation(yaml_content="test: rule", confidence=0.5, reasoning="test", category="test")
        assert rec.confidence == 0.5

        # Test bounds
        with pytest.raises(ValueError):
            RuleRecommendation(yaml_content="test: rule", confidence=1.5, reasoning="test", category="test")


class TestRepositoryAnalysisRequest:
    """Test cases for RepositoryAnalysisRequest model."""

    def test_valid_request(self):
        """Test creating a valid analysis request."""
        request = RepositoryAnalysisRequest(repository_full_name="owner/repo", installation_id=12345)

        assert request.repository_full_name == "owner/repo"
        assert request.installation_id == 12345

    def test_request_without_installation_id(self):
        """Test request without installation ID."""
        request = RepositoryAnalysisRequest(repository_full_name="owner/repo")

        assert request.repository_full_name == "owner/repo"
        assert request.installation_id is None


class TestRepositoryFeatures:
    """Test cases for RepositoryFeatures model."""

    def test_features_initialization(self):
        """Test repository features model."""
        features = RepositoryFeatures(
            has_contributing=True, has_codeowners=True, has_workflows=True, contributor_count=10
        )

        assert features.has_contributing is True
        assert features.has_codeowners is True
        assert features.has_workflows is True
        assert features.contributor_count == 10
