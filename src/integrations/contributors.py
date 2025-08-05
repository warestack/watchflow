"""
Utilities for analyzing repository contributors and determining contribution history.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ContributorAnalyzer:
    """Analyzes repository contributors and their contribution history."""

    def __init__(self, github_client):
        self.github_client = github_client
        self._contributors_cache: dict[str, dict] = {}
        self._cache_ttl = 3600  # 1 hour cache

    async def get_past_contributors(
        self, repo: str, installation_id: int, min_contributions: int = 5, days_back: int = 365
    ) -> set[str]:
        """
        Get a list of past contributors who have made significant contributions.

        Args:
            repo: Repository full name (e.g., "owner/repo")
            installation_id: GitHub installation ID
            min_contributions: Minimum number of contributions to be considered a past contributor
            days_back: Number of days to look back for contributions

        Returns:
            Set of usernames who are past contributors
        """
        cache_key = f"{repo}_{min_contributions}_{days_back}"

        # Check cache first
        if cache_key in self._contributors_cache:
            cached_data = self._contributors_cache[cache_key]
            if datetime.now().timestamp() - cached_data.get("timestamp", 0) < self._cache_ttl:
                logger.debug(f"Using cached past contributors for {repo}")
                return set(cached_data.get("contributors", []))

        try:
            logger.info(f"Fetching past contributors for {repo}")

            # Get contributors from GitHub API
            contributors = await self._fetch_contributors(repo, installation_id)

            # Filter by contribution count and recency
            past_contributors = set()
            cutoff_date = datetime.now() - timedelta(days=days_back)

            for contributor in contributors:
                username = contributor.get("login", "")
                contributions = contributor.get("contributions", 0)

                if contributions >= min_contributions:
                    # Check if they have recent activity
                    if await self._has_recent_activity(repo, username, installation_id, cutoff_date):
                        past_contributors.add(username)

            # Cache the results
            self._contributors_cache[cache_key] = {
                "contributors": list(past_contributors),
                "timestamp": datetime.now().timestamp(),
            }

            logger.info(f"Found {len(past_contributors)} past contributors for {repo}")
            return past_contributors

        except Exception as e:
            logger.error(f"Error fetching past contributors for {repo}: {e}")
            return set()

    async def is_new_contributor(
        self, username: str, repo: str, installation_id: int, min_contributions: int = 5, days_back: int = 365
    ) -> bool:
        """
        Check if a user is a new contributor to the repository.

        Args:
            username: GitHub username to check
            repo: Repository full name
            installation_id: GitHub installation ID
            min_contributions: Minimum contributions to be considered established
            days_back: Number of days to look back

        Returns:
            True if the user is a new contributor, False otherwise
        """
        try:
            # Get past contributors
            past_contributors = await self.get_past_contributors(repo, installation_id, min_contributions, days_back)

            # Check if user is in the past contributors list
            is_new = username not in past_contributors

            logger.debug(f"User {username} is {'new' if is_new else 'established'} contributor in {repo}")
            return is_new

        except Exception as e:
            logger.error(f"Error checking if {username} is new contributor in {repo}: {e}")
            # Default to treating as new contributor on error
            return True

    async def get_user_contribution_stats(self, username: str, repo: str, installation_id: int) -> dict:
        """
        Get detailed contribution statistics for a user.

        Args:
            username: GitHub username
            repo: Repository full name
            installation_id: GitHub installation ID

        Returns:
            Dictionary with contribution statistics
        """
        try:
            # Get user's commits
            commits = await self._fetch_user_commits(repo, username, installation_id)

            # Get user's PRs
            pull_requests = await self._fetch_user_pull_requests(repo, username, installation_id)

            # Get user's issues
            issues = await self._fetch_user_issues(repo, username, installation_id)

            stats = {
                "username": username,
                "total_commits": len(commits),
                "total_pull_requests": len(pull_requests),
                "total_issues": len(issues),
                "first_contribution": None,
                "last_contribution": None,
                "contribution_days": 0,
            }

            # Calculate first and last contribution dates
            all_dates = []

            for commit in commits:
                date_str = commit.get("commit", {}).get("author", {}).get("date")
                if date_str:
                    all_dates.append(datetime.fromisoformat(date_str.replace("Z", "+00:00")))

            for pr in pull_requests:
                date_str = pr.get("created_at")
                if date_str:
                    all_dates.append(datetime.fromisoformat(date_str.replace("Z", "+00:00")))

            for issue in issues:
                date_str = issue.get("created_at")
                if date_str:
                    all_dates.append(datetime.fromisoformat(date_str.replace("Z", "+00:00")))

            if all_dates:
                stats["first_contribution"] = min(all_dates).isoformat()
                stats["last_contribution"] = max(all_dates).isoformat()
                stats["contribution_days"] = (max(all_dates) - min(all_dates)).days

            return stats

        except Exception as e:
            logger.error(f"Error getting contribution stats for {username} in {repo}: {e}")
            return {
                "username": username,
                "total_commits": 0,
                "total_pull_requests": 0,
                "total_issues": 0,
                "first_contribution": None,
                "last_contribution": None,
                "contribution_days": 0,
            }

    async def _fetch_contributors(self, repo: str, installation_id: int) -> list[dict]:
        """Fetch contributors from GitHub API."""
        try:
            # Get repository contributors (this includes contribution counts)
            contributors = await self.github_client.get_repository_contributors(repo, installation_id)
            return contributors or []
        except Exception as e:
            logger.error(f"Error fetching contributors for {repo}: {e}")
            return []

    async def _has_recent_activity(self, repo: str, username: str, installation_id: int, cutoff_date: datetime) -> bool:
        """Check if user has recent activity in the repository."""
        try:
            # Check recent commits
            commits = await self._fetch_user_commits(repo, username, installation_id, limit=10)

            for commit in commits:
                date_str = commit.get("commit", {}).get("author", {}).get("date")
                if date_str:
                    commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if commit_date > cutoff_date:
                        return True

            # Check recent PRs
            pull_requests = await self._fetch_user_pull_requests(repo, username, installation_id, limit=10)

            for pr in pull_requests:
                date_str = pr.get("created_at")
                if date_str:
                    pr_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if pr_date > cutoff_date:
                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking recent activity for {username} in {repo}: {e}")
            return False

    async def _fetch_user_commits(self, repo: str, username: str, installation_id: int, limit: int = 100) -> list[dict]:
        """Fetch commits by a specific user."""
        try:
            return await self.github_client.get_user_commits(repo, username, installation_id, limit)
        except Exception as e:
            logger.error(f"Error fetching commits for {username} in {repo}: {e}")
            return []

    async def _fetch_user_pull_requests(
        self, repo: str, username: str, installation_id: int, limit: int = 100
    ) -> list[dict]:
        """Fetch pull requests by a specific user."""
        try:
            return await self.github_client.get_user_pull_requests(repo, username, installation_id, limit)
        except Exception as e:
            logger.error(f"Error fetching PRs for {username} in {repo}: {e}")
            return []

    async def _fetch_user_issues(self, repo: str, username: str, installation_id: int, limit: int = 100) -> list[dict]:
        """Fetch issues by a specific user."""
        try:
            return await self.github_client.get_user_issues(repo, username, installation_id, limit)
        except Exception as e:
            logger.error(f"Error fetching issues for {username} in {repo}: {e}")
            return []


# Global instance
_contributor_analyzer: ContributorAnalyzer | None = None


def get_contributor_analyzer(github_client) -> ContributorAnalyzer:
    """Get or create the global contributor analyzer instance."""
    global _contributor_analyzer
    if _contributor_analyzer is None:
        _contributor_analyzer = ContributorAnalyzer(github_client)
    return _contributor_analyzer


async def is_new_contributor(username: str, repo: str, github_client, installation_id: int) -> bool:
    """
    Convenience function to check if a user is a new contributor.

    Args:
        username: GitHub username
        repo: Repository full name
        github_client: GitHub API client
        installation_id: GitHub installation ID

    Returns:
        True if the user is a new contributor
    """
    analyzer = get_contributor_analyzer(github_client)
    return await analyzer.is_new_contributor(username, repo, installation_id)


async def get_past_contributors(repo: str, github_client, installation_id: int) -> set[str]:
    """
    Convenience function to get past contributors.

    Args:
        repo: Repository full name
        github_client: GitHub API client
        installation_id: GitHub installation ID

    Returns:
        Set of past contributor usernames
    """
    analyzer = get_contributor_analyzer(github_client)
    return await analyzer.get_past_contributors(repo, installation_id)
