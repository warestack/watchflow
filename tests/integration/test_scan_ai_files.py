"""
Integration tests for POST /api/v1/rules/scan-ai-files.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app


class TestScanAIFilesEndpoint:
    """Integration tests for scan-ai-files endpoint."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_scan_ai_files_returns_200_and_list_when_mocked(
        self, client: TestClient
    ) -> None:
        """With GitHub mocked, endpoint returns 200 and candidate_files is a list."""
        mock_tree = [
            {"path": "README.md", "type": "blob"},
            {"path": "docs/cursor-guidelines.md", "type": "blob"},
        ]
        mock_repo = {"default_branch": "main", "full_name": "owner/repo"}

        async def mock_get_repository(*args, **kwargs):
            return mock_repo

        async def mock_get_tree(*args, **kwargs):
            return mock_tree

        with (
            patch(
                "src.api.recommendations.github_client.get_repository",
                new_callable=AsyncMock,
                side_effect=mock_get_repository,
            ),
            patch(
                "src.api.recommendations.github_client.get_repository_tree",
                new_callable=AsyncMock,
                side_effect=mock_get_tree,
            ),
        ):
            response = client.post(
                "/api/v1/rules/scan-ai-files",
                json={
                    "repo_url": "https://github.com/owner/repo",
                    "include_content": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "repo_full_name" in data
        assert data["repo_full_name"] == "owner/repo"
        assert "ref" in data
        assert data["ref"] == "main"
        assert "candidate_files" in data
        assert isinstance(data["candidate_files"], list)
        assert "warnings" in data
        # At least the matching path should appear
        paths = [c["path"] for c in data["candidate_files"]]
        assert "docs/cursor-guidelines.md" in paths
        for c in data["candidate_files"]:
            assert "path" in c
            assert "has_keywords" in c
            