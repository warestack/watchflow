import logging
from typing import Any

import httpx


# Custom Exceptions for clean error handling in the API layer
class GitHubRateLimitError(Exception):
    pass


class GitHubResourceNotFoundError(Exception):
    pass


logger = logging.getLogger(__name__)


class GitHubService:
    """
    Application Service for interacting with GitHub.
    Abstraction layer over raw API calls or the lower-level GitHubClient.
    """

    BASE_URL = "https://api.github.com"

    def __init__(self):
        # We use a shared client for connection pooling in production,
        # but for now, we instantiate per request for safety.
        pass

    async def get_repo_metadata(self, repo_url: str) -> dict[str, Any]:
        """
        Fetches basic metadata (is_private, stars, etc.)
        Does NOT require a token for public repos.
        """
        owner, repo = self._parse_url(repo_url)
        api_url = f"{self.BASE_URL}/repos/{owner}/{repo}"

        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)

            if response.status_code == 404:
                raise GitHubResourceNotFoundError(f"Repo {owner}/{repo} not found")
            if response.status_code == 403 and "rate limit" in response.text.lower():
                raise GitHubRateLimitError("GitHub API rate limit exceeded")

            response.raise_for_status()
            return response.json()

    async def analyze_repository_rules(self, repo_url: str, token: str | None = None) -> list[dict[str, Any]]:
        """
        The Core Logic: Analyzes the repo and returns rule suggestions.
        This replaces the "Fake Mock Data".
        """
        owner, repo = self._parse_url(repo_url)

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # 1. Check for specific governance files (Real API Check)
        files_to_check = ["CODEOWNERS", "CONTRIBUTING.md", ".github/workflows"]
        found_files = []

        async with httpx.AsyncClient() as client:
            for filepath in files_to_check:
                # Tricky: Public repos can be read without auth, Private need auth
                # We use the 'contents' API
                check_url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{filepath}"
                resp = await client.get(check_url, headers=headers)
                if resp.status_code == 200:
                    found_files.append(filepath)

        # 2. Generate Recommendations based on REAL findings
        recommendations = []

        if "CODEOWNERS" not in found_files:
            recommendations.append(
                {
                    "description": "Enforce CODEOWNERS for critical paths",
                    "severity": "high",
                    "reason": "We detected this repository lacks a CODEOWNERS file, which is critical for defining responsibility.",
                }
            )

        if "CONTRIBUTING.md" not in found_files:
            recommendations.append(
                {
                    "description": "Add Contributing Guidelines",
                    "severity": "medium",
                    "reason": "No CONTRIBUTING.md found. This increases friction for new developers.",
                }
            )

        # Always suggest a default rule to prove the connection works
        recommendations.append(
            {
                "description": "Require Linear History",
                "severity": "low",
                "reason": "Standard practice for cleaner git logs.",
            }
        )

        return recommendations

    def _parse_url(self, url: str) -> tuple[str, str]:
        """
        Extracts owner and repo from https://github.com/owner/repo
        """
        clean_url = str(url).rstrip("/")
        parts = clean_url.split("/")
        if len(parts) < 2:
            raise ValueError("Invalid GitHub URL")
        return parts[-2], parts[-1]
