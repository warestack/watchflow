import asyncio
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.errors import GitHubGraphQLError, RepositoryNotFoundError
from src.integrations.github.schemas import GitHubRepository

logger = structlog.get_logger(__name__)

_PR_HYGIENE_QUERY = """
query PRHygiene($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(last: 20, states: [MERGED, CLOSED]) {
      nodes {
        number
        title
        body
        changedFiles
        comments {
          totalCount
        }
        closingIssuesReferences(first: 1) {
          totalCount
        }
        reviews(first: 1) {
          totalCount
        }
      }
    }
  }
}
"""


class GitHubClient:
    def __init__(self, token: str | None = None, base_url: str = "https://api.github.com"):
        self.token = token
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Accept": "application/vnd.github.v3+json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def get_repo(self, owner: str, repo: str) -> GitHubRepository:
        url = f"{self.base_url}/repos/{owner}/{repo}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                return GitHubRepository.model_validate(response.json())
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise RepositoryNotFoundError(f"Repository {owner}/{repo} not found.") from e
                logger.error("GitHub API error", error=e, response_body=e.response.text)
                raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def execute_graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/graphql"
        payload = {"query": query, "variables": variables}
        start_time = asyncio.get_event_loop().time()
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                json_response = response.json()
                if "errors" in json_response:
                    logger.error(
                        "GitHub GraphQL Error",
                        errors=json_response["errors"],
                        query=query,
                        variables=variables,
                    )
                    raise GitHubGraphQLError(json_response["errors"])
                return json_response
            except httpx.HTTPStatusError as e:
                logger.error(
                    "GitHub GraphQL request failed",
                    status_code=e.response.status_code,
                    response_body=e.response.text,
                    query=query,
                )
                raise
            finally:
                end_time = asyncio.get_event_loop().time()
                logger.info(
                    "GraphQL query executed",
                    query_name="PRHygiene",
                    duration_ms=(end_time - start_time) * 1000,
                )

    async def fetch_pr_hygiene_stats(self, owner: str, repo: str) -> list[dict[str, Any]]:
        variables = {"owner": owner, "repo": repo}
        data = await self.execute_graphql(_PR_HYGIENE_QUERY, variables)
        nodes = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])
        if not nodes:
            logger.warning("GraphQL query returned no PR nodes.", owner=owner, repo=repo)
        return nodes
