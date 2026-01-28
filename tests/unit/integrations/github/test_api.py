from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.github.api import GitHubClient


@pytest.fixture
def mock_httpx_client():
    with patch("httpx.AsyncClient") as mock:
        client = AsyncMock()
        # Mocking __aenter__ and __aexit__ for context manager usage
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        # Ensure methods return awaitables
        client.get = AsyncMock()
        client.post = AsyncMock()
        client.patch = AsyncMock()
        client.put = AsyncMock()
        client.delete = AsyncMock()

        mock.return_value = client
        yield client


@pytest.fixture
def github_client():
    with (
        patch("src.integrations.github.api.GitHubClient._decode_private_key", return_value="mock_key"),
        patch("src.integrations.github.api.GitHubClient._generate_jwt", return_value="mock_jwt_token"),
    ):
        yield GitHubClient()


@pytest.mark.asyncio
async def test_get_installation_access_token_success(github_client, mock_httpx_client):
    # Setup response
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"token": "access_token"}
    mock_httpx_client.post.return_value = mock_response

    token = await github_client.get_installation_access_token(12345)

    assert token == "access_token"
    assert github_client._token_cache[12345] == "access_token"


@pytest.mark.asyncio
async def test_get_installation_access_token_cached(github_client, mock_httpx_client):
    github_client._token_cache[12345] = "cached_token"

    token = await github_client.get_installation_access_token(12345)

    assert token == "cached_token"
    mock_httpx_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_installation_access_token_failure(github_client, mock_httpx_client):
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    mock_httpx_client.post.return_value = mock_response

    token = await github_client.get_installation_access_token(12345)

    assert token is None


@pytest.mark.asyncio
async def test_get_repository_success(github_client, mock_httpx_client):
    # Initial token mock
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    # Repo response mock
    mock_repo_response = MagicMock()
    mock_repo_response.status_code = 200
    mock_repo_response.json.return_value = {"full_name": "owner/repo"}

    # Side effect for sequential calls (token -> repo)
    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_repo_response

    repo = await github_client.get_repository("owner/repo", installation_id=123)

    assert repo == {"full_name": "owner/repo"}


@pytest.mark.asyncio
async def test_get_repository_failure(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_repo_response = MagicMock()
    mock_repo_response.status_code = 404

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_repo_response

    repo = await github_client.get_repository("owner/repo", installation_id=123)

    assert repo is None


@pytest.mark.asyncio
async def test_list_directory_any_auth_success(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_files_response = MagicMock()
    mock_files_response.status_code = 200
    mock_files_response.json.return_value = [{"name": "file.txt"}]

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_files_response

    files = await github_client.list_directory_any_auth("owner/repo", "path", installation_id=123)

    assert files == [{"name": "file.txt"}]


@pytest.mark.asyncio
async def test_get_file_content_success(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_content_response = MagicMock()
    mock_content_response.status_code = 200
    mock_content_response.text = "content"

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_content_response

    content = await github_client.get_file_content("owner/repo", "file.txt", installation_id=123)

    assert content == "content"


@pytest.mark.asyncio
async def test_get_file_content_not_found(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_not_found_response = MagicMock()
    mock_not_found_response.status_code = 404

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_not_found_response

    content = await github_client.get_file_content("owner/repo", "file.txt", installation_id=123)

    assert content is None


@pytest.mark.asyncio
async def test_create_check_run_success(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_check_response = MagicMock()
    mock_check_response.status_code = 201
    mock_check_response.json.return_value = {"id": 1}

    # Side effect sequence: first call for token, second for check run
    mock_httpx_client.post.side_effect = [mock_token_response, mock_check_response]

    result = await github_client.create_check_run(
        "owner/repo", "sha", "name", "completed", "success", {}, installation_id=123
    )

    assert result == {"id": 1}


@pytest.mark.asyncio
async def test_get_pull_request_success(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_pr_response = MagicMock()
    mock_pr_response.status_code = 200
    mock_pr_response.json.return_value = {"number": 1}

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_pr_response

    pr = await github_client.get_pull_request("owner/repo", 1, installation_id=123)

    assert pr == {"number": 1}


@pytest.mark.asyncio
async def test_list_pull_requests_success(github_client, mock_httpx_client):
    mock_token_response = MagicMock()
    mock_token_response.status_code = 201
    mock_token_response.json.return_value = {"token": "access_token"}

    mock_prs_response = MagicMock()
    mock_prs_response.status_code = 200
    mock_prs_response.json.return_value = [{"number": 1}]

    mock_httpx_client.post.return_value = mock_token_response
    mock_httpx_client.get.return_value = mock_prs_response

    prs = await github_client.list_pull_requests("owner/repo", installation_id=123)

    assert prs == [{"number": 1}]
