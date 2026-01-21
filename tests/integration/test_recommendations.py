import pytest
import respx
from fastapi import status
from httpx import AsyncClient

from src.main import app

# Example repo URLs for test cases
github_public_repo = "https://github.com/pallets/flask"
github_private_repo = "https://github.com/example/private-repo"


@pytest.mark.asyncio
@respx.mock
async def test_anonymous_access_public_repo():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        respx.get("https://api.github.com/repos/pallets/flask").mock(
            return_value=respx.Response(200, json={"private": False})
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/CODEOWNERS").mock(
            return_value=respx.Response(404)
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/CONTRIBUTING.md").mock(
            return_value=respx.Response(404)
        )
        respx.get("https://api.github.com/repos/pallets/flask/contents/.github/workflows").mock(
            return_value=respx.Response(200, json=[])
        )
        payload = {"repo_url": github_public_repo, "force_refresh": False}
        response = await ac.post("/v1/rules/recommend", json=payload)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "repository" in data and "recommendations" in data
        assert data["repository"] == "pallets/flask"
        assert isinstance(data["recommendations"], list)


@pytest.mark.asyncio
@respx.mock
async def test_anonymous_access_private_repo():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        respx.get("https://api.github.com/repos/example/private-repo").mock(return_value=respx.Response(404))
        payload = {"repo_url": github_private_repo, "force_refresh": False}
        response = await ac.post("/v1/rules/recommend", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND or response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
@respx.mock
async def test_authenticated_access_private_repo():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        respx.get("https://api.github.com/repos/example/private-repo").mock(
            return_value=respx.Response(200, json={"private": True})
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/CODEOWNERS").mock(
            return_value=respx.Response(404)
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/CONTRIBUTING.md").mock(
            return_value=respx.Response(404)
        )
        respx.get("https://api.github.com/repos/example/private-repo/contents/.github/workflows").mock(
            return_value=respx.Response(200, json=[])
        )
        payload = {"repo_url": github_private_repo, "force_refresh": False}
        headers = {"Authorization": "Bearer testtoken"}
        response = await ac.post("/v1/rules/recommend", json=payload, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "repository" in data and "recommendations" in data
        assert data["repository"] == "example/private-repo"
        assert isinstance(data["recommendations"], list)
