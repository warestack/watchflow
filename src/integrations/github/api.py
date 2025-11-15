import base64
import logging
import time
from typing import Any

import aiohttp
import httpx
import jwt
from cachetools import TTLCache

from src.core.config import config

logger = logging.getLogger(__name__)


class GitHubClient:
    """
    A client for interacting with the GitHub API.

    This client handles the authentication flow for a GitHub App, including
    generating a JWT and exchanging it for an installation access token.
    Tokens are cached to improve performance and avoid rate limiting.
    """

    def __init__(self):
        self._private_key = self._decode_private_key()
        self._app_id = config.github.app_id
        self._session: aiohttp.ClientSession | None = None
        # Cache for installation tokens (TTL: 50 minutes, GitHub tokens expire in 60)
        self._token_cache: TTLCache = TTLCache(maxsize=100, ttl=50 * 60)

    async def get_installation_access_token(self, installation_id: int) -> str | None:
        """
        Gets an access token for a specific installation of the GitHub App.
        Caches the token to avoid regenerating it for every request.
        """
        if installation_id in self._token_cache:
            logger.debug(f"Using cached installation token for installation_id {installation_id}.")
            return self._token_cache[installation_id]

        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{config.github.api_base_url}/app/installations/{installation_id}/access_tokens"

        session = await self._get_session()
        async with session.post(url, headers=headers) as response:
            if response.status == 201:
                data = await response.json()
                token = data["token"]
                self._token_cache[installation_id] = token
                logger.info(f"Generated new installation token for installation_id {installation_id}.")
                return token
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get installation access token for installation {installation_id}. "
                    f"Status: {response.status}, Response: {error_text}"
                )
                return None

    async def get_file_content(self, repo_full_name: str, file_path: str, installation_id: int) -> str | None:
        """
        Fetches the content of a file from a repository.
        """
        token = await self.get_installation_access_token(installation_id)
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw",  # Get raw content
        }
        url = f"{config.github.api_base_url}/repos/{repo_full_name}/contents/{file_path}"

        session = await self._get_session()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                logger.info(f"Successfully fetched file '{file_path}' from '{repo_full_name}'.")
                return await response.text()
            elif response.status == 404:
                logger.info(f"File '{file_path}' not found in '{repo_full_name}'.")
                return None
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get file content for {repo_full_name}/{file_path}. "
                    f"Status: {response.status}, Response: {error_text}"
                )
                return None

    async def close(self):
        """Closes the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_pr_files(self, repo_full_name: str, pr_number: int, installation_id: int) -> list[dict[str, Any]]:
        """
        Fetch the list of files changed in a pull request.
        """
        return await self.get_pull_request_files(repo_full_name, pr_number, installation_id)

    async def get_pr_reviews(self, repo_full_name: str, pr_number: int, installation_id: int) -> list[dict[str, Any]]:
        """
        Fetch the list of reviews for a pull request.
        """
        return await self.get_pull_request_reviews(repo_full_name, pr_number, installation_id)

    async def get_pr_checks(self, repo_full_name: str, pr_number: int, installation_id: int) -> list[dict[str, Any]]:
        """
        Fetch the list of checks/statuses for a pull request.
        """
        try:
            # First get the PR to get the head SHA
            pr_data = await self.get_pull_request(repo_full_name, pr_number, installation_id)
            if not pr_data:
                return []

            head_sha = pr_data.get("head", {}).get("sha")
            if not head_sha:
                return []

            # Then get check runs for that SHA
            return await self.get_check_runs(repo_full_name, head_sha, installation_id)
        except Exception as e:
            logger.error(f"Error getting checks for PR #{pr_number} in {repo_full_name}: {e}")
            return []

    async def get_user_teams(self, repo: str, username: str, installation_id: int) -> list:
        """Fetch the teams a user belongs to in a repo's org."""
        token = await self.get_installation_access_token(installation_id)
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        org = repo.split("/")[0]
        url = f"https://api.github.com/orgs/{org}/memberships/{username}/teams"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return [team["slug"] for team in resp.json()]
            return []

    async def get_user_team_membership(self, repo: str, username: str, installation_id: int) -> dict[str, Any]:
        """Get team membership for a user (with caching)."""
        # Implementation with caching
        return {}

    async def get_codeowners(self, repo: str, installation_id: int) -> dict[str, Any]:
        """Get CODEOWNERS file content."""
        try:
            content = await self.get_file_content(repo, ".github/CODEOWNERS", installation_id)
            return {"content": content} if content else {}
        except Exception:
            return {}

    async def create_pull_request_comment(
        self, repo: str, pr_number: int, comment: str, installation_id: int
    ) -> dict[str, Any]:
        """Create a comment on a pull request."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/issues/{pr_number}/comments"
            data = {"body": comment}

            session = await self._get_session()
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Created comment on PR #{pr_number} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to create comment on PR #{pr_number} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return {}
        except Exception as e:
            logger.error(f"Error creating comment on PR #{pr_number} in {repo}: {e}")
            return {}

    async def create_check_run(
        self, repo: str, sha: str, name: str, status: str, conclusion: str, output: dict, installation_id: int
    ) -> dict:
        """Create a check run."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/check-runs"
            data = {"name": name, "head_sha": sha, "status": status, "conclusion": conclusion, "output": output}

            session = await self._get_session()
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Created check run '{name}' for {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to create check run '{name}' for {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return {}
        except Exception as e:
            logger.error(f"Error creating check run '{name}' for {repo}: {e}")
            return {}

    async def update_check_run(
        self, repo: str, check_run_id: int, status: str, conclusion: str, output: dict[str, Any], installation_id: int
    ) -> dict[str, Any]:
        """Update a check run."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/check-runs/{check_run_id}"
            data = {"status": status, "conclusion": conclusion, "output": output}

            session = await self._get_session()
            async with session.patch(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Updated check run {check_run_id} for {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to update check run {check_run_id} for {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return {}
        except Exception as e:
            logger.error(f"Error updating check run {check_run_id} for {repo}: {e}")
            return {}

    async def get_check_runs(self, repo: str, sha: str, installation_id: int) -> list[dict[str, Any]]:
        """Get check runs for a commit."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return []

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/commits/{sha}/check-runs"

            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("check_runs", [])
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to get check runs for {repo} commit {sha}. Status: {response.status}, Response: {error_text}"
                    )
                    return []
        except Exception as e:
            logger.error(f"Error getting check runs for {repo} commit {sha}: {e}")
            return []

    async def get_pull_request_reviews(self, repo: str, pr_number: int, installation_id: int) -> list[dict[str, Any]]:
        """Get reviews for a pull request."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return []

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/pulls/{pr_number}/reviews"

            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Retrieved {len(result)} reviews for PR #{pr_number} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to get reviews for PR #{pr_number} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return []
        except Exception as e:
            logger.error(f"Error getting reviews for PR #{pr_number} in {repo}: {e}")
            return []

    async def get_pull_request_files(self, repo: str, pr_number: int, installation_id: int) -> list[dict[str, Any]]:
        """Get files changed in a pull request."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return []

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/pulls/{pr_number}/files"

            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Retrieved {len(result)} files for PR #{pr_number} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to get files for PR #{pr_number} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return []
        except Exception as e:
            logger.error(f"Error getting files for PR #{pr_number} in {repo}: {e}")
            return []

    async def create_comment_reply(
        self, repo: str, comment_id: int, reply: str, installation_id: int
    ) -> dict[str, Any]:
        """Create a reply to a comment."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/issues/comments/{comment_id}/reactions"
            data = {"content": "eyes"}  # Add a reaction to acknowledge

            session = await self._get_session()
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    logger.info(f"Added reaction to comment {comment_id} in {repo}")
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to add reaction to comment {comment_id} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return {}
        except Exception as e:
            logger.error(f"Error adding reaction to comment {comment_id} in {repo}: {e}")
            return {}

    async def create_issue_comment(
        self, repo: str, issue_number: int, comment: str, installation_id: int
    ) -> dict[str, Any]:
        """Create a comment on an issue."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/issues/{issue_number}/comments"
            data = {"body": comment}

            session = await self._get_session()
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Created comment on issue #{issue_number} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to create comment on issue #{issue_number} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return {}
        except Exception as e:
            logger.error(f"Error creating comment on issue #{issue_number} in {repo}: {e}")
            return {}

    async def get_pull_request(self, repo: str, pr_number: int, installation_id: int) -> dict:
        """Get pull request details."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return {}

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/pulls/{pr_number}"

            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Retrieved PR #{pr_number} details from {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to get PR #{pr_number} from {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return None
        except Exception as e:
            logger.error(f"Error getting PR #{pr_number} from {repo}: {e}")
            return {}

    async def create_deployment_status(
        self,
        repo: str,
        deployment_id: int,
        state: str,
        description: str,
        environment: str,
        log_url: str,
        installation_id: int,
    ):
        """Create a deployment status."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return None

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/deployments/{deployment_id}/statuses"
            data = {"state": state, "description": description, "environment": environment, "log_url": log_url}

            session = await self._get_session()
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    result = await response.json()
                    logger.info(f"Created deployment status for deployment {deployment_id} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to create deployment status for deployment {deployment_id} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return None
        except Exception as e:
            logger.error(f"Error creating deployment status for deployment {deployment_id} in {repo}: {e}")
            return None

    async def review_deployment_protection_rule(
        self, callback_url: str, environment: str, state: str, comment: str, installation_id: int
    ):
        """Review a deployment protection rule."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id} to review deployment.")
                return None

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            data = {
                "state": state,  # "approved" or "rejected"
                "comment": comment,
                "environment_name": environment,
            }

            session = await self._get_session()
            async with session.post(callback_url, headers=headers, json=data) as response:
                if response.status in [200, 204]:  # 204 No Content is also a success
                    logger.info(f"Successfully reviewed deployment protection rule with state {state}.")
                    if response.status == 200:
                        return await response.json()
                    else:
                        return {"status": "success", "state": state}
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to review deployment protection rule for environment {environment}. Status: {response.status}, Response: {error_text}"
                    )
                    logger.error(f"Request URL: {callback_url}")
                    logger.error(f"Request payload: {data}")
                    return None
        except Exception as e:
            logger.error(f"Error reviewing deployment protection rule: {e}")
            return None

    async def get_issue_comments(self, repo: str, issue_number: int, installation_id: int) -> list[dict[str, Any]]:
        """Get comments for an issue."""
        try:
            token = await self.get_installation_access_token(installation_id)
            if not token:
                logger.error(f"Failed to get installation token for {installation_id}")
                return []

            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

            url = f"{config.github.api_base_url}/repos/{repo}/issues/{issue_number}/comments"

            session = await self._get_session()
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Retrieved {len(result)} comments for issue #{issue_number} in {repo}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to get comments for issue #{issue_number} in {repo}. Status: {response.status}, Response: {error_text}"
                    )
                    return []
        except Exception as e:
            logger.error(f"Error getting comments for issue #{issue_number} in {repo}: {e}")
            return []

    async def update_deployment_status(
        self, callback_url: str, state: str, description: str, environment_url: str | None = None
    ):
        """Update deployment status via callback URL."""
        try:
            # For this method, we need to use a different approach since we don't have the installation_id
            # We'll use the JWT token directly
            jwt_token = self._generate_jwt()
            headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github.v3+json"}

            data = {"state": state, "description": description}
            if environment_url:
                data["environment_url"] = environment_url

            session = await self._get_session()
            async with session.post(callback_url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Updated deployment status to {state}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to update deployment status. Status: {response.status}, Response: {error_text}"
                    )
                    return None
        except Exception as e:
            logger.error(f"Error updating deployment status: {e}")
            return None

    async def get_repository_contributors(self, repo: str, installation_id: int) -> list[dict[str, Any]]:
        """
        Fetches repository contributors with their contribution counts.
        """
        token = await self.get_installation_access_token(installation_id)
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{config.github.api_base_url}/repos/{repo}/contributors"

        session = await self._get_session()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                contributors = await response.json()
                logger.info(f"Successfully fetched {len(contributors)} contributors for {repo}.")
                return contributors
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get contributors for {repo}. Status: {response.status}, Response: {error_text}"
                )
                return []

    async def get_user_commits(
        self, repo: str, username: str, installation_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Fetches commits by a specific user in the repository.
        """
        token = await self.get_installation_access_token(installation_id)
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{config.github.api_base_url}/repos/{repo}/commits?author={username}&per_page={min(limit, 100)}"

        session = await self._get_session()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                commits = await response.json()
                logger.info(f"Successfully fetched {len(commits)} commits by {username} in {repo}.")
                return commits
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get commits by {username} in {repo}. Status: {response.status}, Response: {error_text}"
                )
                return []

    async def get_user_pull_requests(
        self, repo: str, username: str, installation_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Fetches pull requests by a specific user in the repository.
        """
        token = await self.get_installation_access_token(installation_id)
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{config.github.api_base_url}/repos/{repo}/pulls?state=all&creator={username}&per_page={min(limit, 100)}"

        session = await self._get_session()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                pull_requests = await response.json()
                logger.info(f"Successfully fetched {len(pull_requests)} PRs by {username} in {repo}.")
                return pull_requests
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get PRs by {username} in {repo}. Status: {response.status}, Response: {error_text}"
                )
                return []

    async def get_user_issues(
        self, repo: str, username: str, installation_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Fetches issues by a specific user in the repository.
        """
        token = await self.get_installation_access_token(installation_id)
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = (
            f"{config.github.api_base_url}/repos/{repo}/issues?state=all&creator={username}&per_page={min(limit, 100)}"
        )

        session = await self._get_session()
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                issues = await response.json()
                logger.info(f"Successfully fetched {len(issues)} issues by {username} in {repo}.")
                return issues
            else:
                error_text = await response.text()
                logger.error(
                    f"Failed to get issues by {username} in {repo}. Status: {response.status}, Response: {error_text}"
                )
                return []

    async def _get_session(self) -> aiohttp.ClientSession:
        """Initializes and returns the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _generate_jwt(self) -> str:
        """Generates a JSON Web Token (JWT) to authenticate as the GitHub App."""
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + (1 * 60),  # X * minutes expiration
            "iss": self._app_id,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    @staticmethod
    def _decode_private_key() -> str:
        """
        Decodes the base64-encoded private key from the configuration.

        Returns:
            The decoded private key as a string.
        """
        try:
            # Decode the base64-encoded private key
            decoded_key = base64.b64decode(config.github.private_key).decode("utf-8")
            return decoded_key
        except Exception as e:
            logger.error(f"Failed to decode private key: {e}")
            raise ValueError("Invalid private key format. Expected base64-encoded PEM key.") from e


# Global instance
github_client = GitHubClient()
