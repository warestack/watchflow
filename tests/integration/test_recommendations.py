import pytest
import respx
from fastapi import status
from httpx import ASGITransport, AsyncClient, Response

from src.main import app

# Example repo URLs for test cases
github_public_repo = "https://github.com/pallets/flask"
github_private_repo = "https://github.com/example/private-repo"


def mock_openai_response():
    """Mock OpenAI API response for rule recommendations using structured outputs"""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"repo_full_name": "test/repo", "is_public": true, "file_tree": [], "recommendations": [{"key": "require_pr_reviews", "name": "Require Pull Request Reviews", "description": "Ensure all PRs are reviewed before merging", "severity": "high", "category": "quality", "reasoning": "Based on repository analysis"}]}',
                    "refusal": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.mark.asyncio
@respx.mock
async def test_anonymous_access_public_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Mock GitHub API calls
        respx.get("https://api.github.com/repos/pallets/flask").mock(
            return_value=Response(200, json={"private": False})
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/").mock(
            return_value=Response(
                200,
                json=[
                    {"name": "README.md", "type": "file"},
                    {"name": "pyproject.toml", "type": "file"},
                    {"name": ".github", "type": "dir"},
                ],
            )
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/README.md").mock(
            return_value=Response(200, json={"content": "VGVzdCBjb250ZW50"})  # base64 "Test content"
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/CODEOWNERS").mock(return_value=Response(404))
        respx.get("https://api.github.com/repos/pallets/flask/contents/.github/CODEOWNERS").mock(
            return_value=Response(404)
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/docs/CODEOWNERS").mock(
            return_value=Response(404)
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/.github/workflows").mock(
            return_value=Response(200, json=[])
        )

        # Mock OpenAI API call
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(200, json=mock_openai_response())
        )

        payload = {"repo_url": github_public_repo, "force_refresh": False}
        response = await ac.post("/api/v1/rules/recommend", json=payload)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "rules_yaml" in data and "pr_plan" in data and "analysis_summary" in data
        assert isinstance(data["rules_yaml"], str)
        assert isinstance(data["pr_plan"], str)


@pytest.mark.asyncio
@respx.mock
async def test_anonymous_access_private_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Mock GitHub API - repo not found (404) indicates private or non-existent
        respx.get("https://api.github.com/repos/example/private-repo").mock(return_value=Response(404))
        respx.get("https://api.github.com/repos/example/private-repo/contents/").mock(return_value=Response(404))

        # Mock OpenAI API call (in case the agent tries to proceed despite GitHub 404)
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(200, json=mock_openai_response())
        )

        payload = {"repo_url": github_private_repo, "force_refresh": False}
        response = await ac.post("/api/v1/rules/recommend", json=payload)

        # When GitHub returns 404, the agent returns success with fallback recommendation
        # This is the current behavior - it doesn't fail hard on GitHub 404
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "rules_yaml" in data and "pr_plan" in data and "analysis_summary" in data


@pytest.mark.asyncio
@respx.mock
async def test_authenticated_access_private_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Mock GitHub API calls for private repo with auth
        respx.get("https://api.github.com/repos/example/private-repo").mock(
            return_value=Response(200, json={"private": True})
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/").mock(
            return_value=Response(
                200, json=[{"name": "README.md", "type": "file"}, {"name": "package.json", "type": "file"}]
            )
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/README.md").mock(
            return_value=Response(200, json={"content": "UHJpdmF0ZSByZXBv"})  # base64 "Private repo"
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/CODEOWNERS").mock(
            return_value=Response(404)
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/.github/CODEOWNERS").mock(
            return_value=Response(404)
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/docs/CODEOWNERS").mock(
            return_value=Response(404)
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/.github/workflows").mock(
            return_value=Response(200, json=[])
        )

        # Mock OpenAI API call
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(200, json=mock_openai_response())
        )

        payload = {"repo_url": github_private_repo, "force_refresh": False}
        headers = {"Authorization": "Bearer testtoken"}
        response = await ac.post("/api/v1/rules/recommend", json=payload, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "rules_yaml" in data and "pr_plan" in data and "analysis_summary" in data
        assert isinstance(data["rules_yaml"], str)
        assert isinstance(data["pr_plan"], str)
