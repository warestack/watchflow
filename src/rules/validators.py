import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Condition(ABC):
    """Abstract base class for all condition validators."""

    # Class attributes for validator descriptions
    name: str = ""
    description: str = ""
    parameter_patterns: list[str] = []
    event_types: list[str] = []
    examples: list[dict[str, Any]] = []

    @abstractmethod
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """
        Validates a condition against the event data.

        Args:
            parameters: The parameters for this condition type
            event: The webhook event to validate against

        Returns:
            True if the condition is met, False otherwise
        """
        pass

    def get_description(self) -> dict[str, Any]:
        """Get validator description for dynamic strategy selection."""
        return {
            "name": self.name,
            "description": self.description,
            "parameter_patterns": self.parameter_patterns,
            "event_types": self.event_types,
            "examples": self.examples,
        }


class AuthorTeamCondition(Condition):
    """Validates if the event author is a member of a specific team."""

    name = "author_team_is"
    description = "Validates if the event author is a member of a specific team"
    parameter_patterns = ["team"]
    event_types = ["pull_request", "push", "deployment"]
    examples = [{"team": "devops"}, {"team": "codeowners"}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        team_name = parameters.get("team")
        if not team_name:
            logger.warning("AuthorTeamCondition: No team specified in parameters")
            return False

        # Get author from event
        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            logger.warning("AuthorTeamCondition: No sender login found in event")
            return False

        # Placeholder logic - replace with actual GitHub API call
        logger.debug(f"Checking if {author_login} is in team {team_name}")

        # For testing purposes, let's assume certain users are in certain teams
        team_memberships = {
            "devops": ["devops-user", "admin-user"],
            "codeowners": ["senior-dev", "tech-lead"],
        }

        return author_login in team_memberships.get(team_name, [])


class FilePatternCondition(Condition):
    """Validates if files in the event match or don't match a pattern."""

    name = "files_match_pattern"
    description = "Validates if files in the event match or don't match a pattern"
    parameter_patterns = ["pattern", "condition_type"]
    event_types = ["pull_request", "push"]
    examples = [
        {"pattern": "*.py", "condition_type": "files_match_pattern"},
        {"pattern": "*.md", "condition_type": "files_not_match_pattern"},
    ]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        pattern = parameters.get("pattern")
        if not pattern:
            logger.warning("FilePatternCondition: No pattern specified in parameters")
            return False

        # Get the list of changed files from the event
        changed_files = self._get_changed_files(event)

        if not changed_files:
            logger.debug("No files to check against pattern")
            return False

        # Convert glob pattern to regex
        regex_pattern = self._glob_to_regex(pattern)

        # Check if any files match the pattern
        matching_files = [file for file in changed_files if re.match(regex_pattern, file)]

        # For "files_not_match_pattern", we want True if NO files match
        # For "files_match_pattern", we want True if ANY files match
        condition_type = parameters.get("condition_type", "files_match_pattern")

        if condition_type == "files_not_match_pattern":
            return len(matching_files) == 0
        else:
            return len(matching_files) > 0

    def _get_changed_files(self, event: dict[str, Any]) -> list[str]:
        """Extracts the list of changed files from the event."""
        event_type = event.get("event_type", "")
        if event_type == "pull_request":
            # For pull requests, we'd need to get this from the GitHub API
            # For now, return a placeholder
            return []
        elif event_type == "push":
            # For push events, the files are in the commits
            return []
        else:
            return []

    def _glob_to_regex(self, glob_pattern: str) -> str:
        """Converts a glob pattern to a regex pattern."""
        # Simple conversion - in production, you'd want a more robust implementation
        regex = glob_pattern.replace(".", "\\.").replace("*", ".*").replace("?", ".")
        return f"^{regex}$"


class NewContributorCondition(Condition):
    """Validates if the event author is a new contributor."""

    name = "author_is_new_contributor"
    description = "Validates if the event author is a new contributor"
    parameter_patterns = []
    event_types = ["pull_request", "push"]
    examples = [{}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            return False

        # Placeholder logic - in production, this would check the user's contribution history
        # For now, we'll use a simple list of "new contributors"
        new_contributors = ["new-user-1", "new-user-2", "intern-dev"]

        return author_login in new_contributors


class ApprovalCountCondition(Condition):
    """Validates if the PR has the required number of approvals."""

    name = "has_min_approvals"
    description = "Validates if the PR has the required number of approvals"
    parameter_patterns = ["min_approvals"]
    event_types = ["pull_request"]
    examples = [{"min_approvals": 1}, {"min_approvals": 2}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # Remove unused variable assignment
        # min_approvals = parameters.get("min_approvals", 1)

        # Placeholder logic - in production, this would check the actual PR reviews
        return True


class WeekendCondition(Condition):
    """Validates if the current time is during a weekend."""

    name = "is_weekend"
    description = "Validates if the current time is during a weekend"
    parameter_patterns = []
    event_types = ["deployment", "pull_request"]
    examples = [{}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        current_time = datetime.now()
        # 5 = Saturday, 6 = Sunday
        is_weekend = current_time.weekday() >= 5
        # Return True if NOT weekend (no violation), False if weekend (violation)
        return not is_weekend


class WorkflowDurationCondition(Condition):
    """Validates if a workflow run exceeded a time threshold."""

    name = "workflow_duration_exceeds"
    description = "Validates if a workflow run exceeded a time threshold"
    parameter_patterns = ["minutes"]
    event_types = ["workflow_run"]
    examples = [{"minutes": 3}, {"minutes": 5}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # max_minutes = parameters.get("minutes", 3)

        # Placeholder logic - in production, this would check the actual workflow duration
        return False  # Placeholder


class MinApprovalsCondition(Condition):
    """Validates if the PR has the minimum number of approvals."""

    name = "min_approvals"
    description = "Validates if the PR has the minimum number of approvals"
    parameter_patterns = ["min_approvals"]
    event_types = ["pull_request"]
    examples = [{"min_approvals": 1}, {"min_approvals": 2}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        min_approvals = parameters.get("min_approvals", 1)

        # Get reviews from the event data
        reviews = event.get("reviews", [])

        # Count approved reviews
        approved_count = 0
        for review in reviews:
            if review.get("state") == "APPROVED":
                approved_count += 1

        logger.debug(f"MinApprovalsCondition: PR has {approved_count} approvals, requires {min_approvals}")

        return approved_count >= min_approvals


class DaysCondition(Condition):
    """Validates if the PR was merged on restricted days."""

    name = "days"
    description = "Validates if the PR was merged on restricted days"
    parameter_patterns = ["days"]
    event_types = ["pull_request"]
    examples = [{"days": ["Friday", "Saturday"]}, {"days": ["Monday"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        days = parameters.get("days", [])
        if not days:
            return True  # No restrictions

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        # Only check if PR is merged
        merged_at = pull_request.get("merged_at")
        if not merged_at:
            return True  # If not merged, not violated

        try:
            # Parse the merged_at timestamp
            dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            weekday = dt.strftime("%A")

            # Check if merge day is in restricted days
            is_restricted = weekday in days

            logger.debug(
                f"DaysCondition: PR merged on {weekday}, restricted days: {days}, is_restricted: {is_restricted}"
            )

            return not is_restricted  # Return True if NOT restricted (no violation)

        except Exception as e:
            logger.error(f"DaysCondition: Error parsing merged_at timestamp '{merged_at}': {e}")
            return True  # No violation if we can't parse the date


class TitlePatternCondition(Condition):
    """Validates if the PR title matches a specific pattern."""

    name = "title_pattern"
    description = "Validates if the PR title matches a specific pattern"
    parameter_patterns = ["title_pattern"]
    event_types = ["pull_request"]
    examples = [{"title_pattern": "^feat|^fix|^docs"}, {"title_pattern": "^JIRA-\\d+"}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        pattern = parameters.get("title_pattern")
        if not pattern:
            return True  # No violation if no pattern specified

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        title = pull_request.get("title", "")
        if not title:
            return False  # Violation if no title

        # Test the pattern
        try:
            matches = bool(re.match(pattern, title))
            logger.debug(f"TitlePatternCondition: Title '{title}' matches pattern '{pattern}': {matches}")
            return matches
        except re.error as e:
            logger.error(f"TitlePatternCondition: Invalid regex pattern '{pattern}': {e}")
            return True  # No violation if pattern is invalid


class MinDescriptionLengthCondition(Condition):
    """Validates if the PR description meets minimum length requirements."""

    name = "min_description_length"
    description = "Validates if the PR description meets minimum length requirements"
    parameter_patterns = ["min_description_length"]
    event_types = ["pull_request"]
    examples = [{"min_description_length": 50}, {"min_description_length": 100}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        min_length = parameters.get("min_description_length", 1)

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        description = pull_request.get("body", "")
        if not description:
            return False  # Violation if no description

        description_length = len(description.strip())
        is_valid = description_length >= min_length

        logger.debug(
            f"MinDescriptionLengthCondition: Description length {description_length}, requires {min_length}: {is_valid}"
        )

        return is_valid


class RequiredLabelsCondition(Condition):
    """Validates if the PR has all required labels."""

    name = "required_labels"
    description = "Validates if the PR has all required labels"
    parameter_patterns = ["required_labels"]
    event_types = ["pull_request"]
    examples = [{"required_labels": ["security", "review"]}, {"required_labels": ["bug", "feature"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        required_labels = parameters.get("required_labels", [])
        if not required_labels:
            return True  # No labels required

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        pr_labels = [label.get("name", "") for label in pull_request.get("labels", [])]

        # Check if all required labels are present
        missing_labels = [label for label in required_labels if label not in pr_labels]

        is_valid = len(missing_labels) == 0

        logger.debug(
            f"RequiredLabelsCondition: PR has labels {pr_labels}, requires {required_labels}, missing {missing_labels}: {is_valid}"
        )

        return is_valid


class MaxFileSizeCondition(Condition):
    """Validates if files don't exceed maximum size limits."""

    name = "max_file_size_mb"
    description = "Validates if files don't exceed maximum size limits"
    parameter_patterns = ["max_file_size_mb"]
    event_types = ["pull_request", "push"]
    examples = [{"max_file_size_mb": 10}, {"max_file_size_mb": 1}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        max_size_mb = parameters.get("max_file_size_mb", 100)
        files = event.get("files", [])

        # If no files data is available, we can't evaluate this rule
        if not files:
            logger.debug("MaxFileSizeCondition: No files data available, skipping validation")
            return True  # No violation if we can't check

        # Check each file's size
        oversized_files = []
        for file in files:
            size_bytes = file.get("size", 0)
            size_mb = size_bytes / (1024 * 1024)
            if size_mb > max_size_mb:
                filename = file.get("filename", "unknown")
                oversized_files.append(f"{filename} ({size_mb:.2f}MB)")
                logger.debug(
                    f"MaxFileSizeCondition: File {filename} exceeds size limit: {size_mb:.2f}MB > {max_size_mb}MB"
                )

        is_valid = len(oversized_files) == 0

        if is_valid:
            logger.debug(f"MaxFileSizeCondition: All {len(files)} files are within size limit of {max_size_mb}MB")
        else:
            logger.debug(f"MaxFileSizeCondition: {len(oversized_files)} files exceed size limit: {oversized_files}")

        return is_valid


class PatternCondition(Condition):
    """Generic pattern validator for various fields."""

    name = "pattern"
    description = "Generic pattern validator for various fields"
    parameter_patterns = ["pattern"]
    event_types = ["pull_request", "push"]
    examples = [{"pattern": "^feat|^fix"}, {"pattern": "^JIRA-\\d+"}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        pattern = parameters.get("pattern", "")
        if not pattern:
            return True

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        # This is a generic pattern validator - could be used for various fields
        # For now, check against PR title as a common use case
        title = pull_request.get("title", "")

        try:
            matches = bool(re.match(pattern, title))
            logger.debug(f"PatternCondition: Title '{title}' matches pattern '{pattern}': {matches}")
            return matches
        except re.error as e:
            logger.error(f"PatternCondition: Invalid regex pattern '{pattern}': {e}")
            return True  # No violation if pattern is invalid


class AllowForcePushCondition(Condition):
    """Validates if force pushes are allowed."""

    name = "allow_force_push"
    description = "Validates if force pushes are allowed"
    parameter_patterns = ["allow_force_push"]
    event_types = ["push"]
    examples = [{"allow_force_push": False}, {"allow_force_push": True}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # allow_force_push = parameters.get("allow_force_push", False)

        # This would typically check if the push was a force push
        # For now, return True (no violation) as placeholder
        return True


class ProtectedBranchesCondition(Condition):
    """Validates if the PR targets protected branches."""

    name = "protected_branches"
    description = "Validates if the PR targets protected branches"
    parameter_patterns = ["protected_branches"]
    event_types = ["pull_request"]
    examples = [{"protected_branches": ["main", "develop"]}, {"protected_branches": ["master"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        protected_branches = parameters.get("protected_branches", [])
        if not protected_branches:
            return True

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        base_branch = pull_request.get("base", {}).get("ref", "")

        # Check if the base branch is in the protected list
        is_protected = base_branch in protected_branches

        logger.debug(
            f"ProtectedBranchesCondition: Base branch '{base_branch}' in protected list {protected_branches}: {is_protected}"
        )

        return not is_protected  # Return True if NOT protected (no violation)


class EnvironmentsCondition(Condition):
    """Validates deployment environments."""

    name = "environments"
    description = "Validates deployment environments"
    parameter_patterns = ["environments"]
    event_types = ["deployment"]
    examples = [{"environments": ["staging", "production"]}, {"environments": ["dev"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        environments = parameters.get("environments", [])
        if not environments:
            return True

        # This would typically check deployment environments
        # For now, return True as placeholder
        return True


class RequiredTeamsCondition(Condition):
    """Validates if the user is a member of required teams."""

    name = "required_teams"
    description = "Validates if the user is a member of required teams"
    parameter_patterns = ["required_teams"]
    event_types = ["pull_request", "push"]
    examples = [{"required_teams": ["devops", "security"]}, {"required_teams": ["codeowners"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        required_teams = parameters.get("required_teams", [])
        if not required_teams:
            return True

        # This would check if the user is a member of required teams
        # For now, return True as placeholder
        return True


class AllowedHoursCondition(Condition):
    """Validates if the current time is within allowed hours."""

    name = "allowed_hours"
    description = "Validates if the current time is within allowed hours"
    parameter_patterns = ["allowed_hours", "timezone"]
    event_types = ["deployment", "pull_request"]
    examples = [
        {"allowed_hours": [9, 10, 11, 14, 15, 16], "timezone": "Europe/Athens"},
        {"allowed_hours": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17], "timezone": "UTC"},
    ]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        allowed_hours = parameters.get("allowed_hours", [])
        if not allowed_hours:
            return True

        # Get timezone from parameters, default to UTC
        timezone_str = parameters.get("timezone", "UTC")
        try:
            import pytz

            tz = pytz.timezone(timezone_str)
            current_time = datetime.now(tz)
        except (ImportError, pytz.exceptions.UnknownTimeZoneError):
            # Fallback to UTC if pytz is not available or timezone is invalid
            logger.warning(f"Invalid timezone '{timezone_str}', using UTC")
            current_time = datetime.now()

        current_hour = current_time.hour

        logger.debug(
            f"AllowedHoursCondition: Current hour {current_hour} in timezone {timezone_str}, allowed hours: {allowed_hours}"
        )
        return current_hour in allowed_hours


class BranchesCondition(Condition):
    """Validates if the PR targets allowed branches."""

    name = "branches"
    description = "Validates if the PR targets allowed branches"
    parameter_patterns = ["branches"]
    event_types = ["pull_request"]
    examples = [{"branches": ["main", "develop"]}, {"branches": ["master"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        branches = parameters.get("branches", [])
        if not branches:
            return True

        # Get PR data from the correct location
        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        base_branch = pull_request.get("base", {}).get("ref", "")

        is_allowed = base_branch in branches

        logger.debug(f"BranchesCondition: Base branch '{base_branch}' in allowed branches {branches}: {is_allowed}")

        return is_allowed


class RequiredChecksCondition(Condition):
    """Validates if all required checks have passed."""

    name = "required_checks"
    description = "Validates if all required checks have passed"
    parameter_patterns = ["required_checks"]
    event_types = ["pull_request"]
    examples = [{"required_checks": ["ci/cd", "security-scan"]}, {"required_checks": ["lint", "test"]}]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        required_checks = parameters.get("required_checks", [])
        if not required_checks:
            return True

        # This would check if all required checks have passed
        # For now, return True as placeholder
        return True


# Registry of all available validators
VALIDATOR_REGISTRY = {
    "author_team_is": AuthorTeamCondition(),
    "files_match_pattern": FilePatternCondition(),
    "files_not_match_pattern": FilePatternCondition(),
    "author_is_new_contributor": NewContributorCondition(),
    "has_min_approvals": ApprovalCountCondition(),
    "is_weekend": WeekendCondition(),
    "workflow_duration_exceeds": WorkflowDurationCondition(),
    "min_approvals": MinApprovalsCondition(),
    "days": DaysCondition(),
    "title_pattern": TitlePatternCondition(),
    "min_description_length": MinDescriptionLengthCondition(),
    "required_labels": RequiredLabelsCondition(),
    "max_file_size_mb": MaxFileSizeCondition(),
    "pattern": PatternCondition(),
    "allow_force_push": AllowForcePushCondition(),
    "protected_branches": ProtectedBranchesCondition(),
    "environments": EnvironmentsCondition(),
    "required_teams": RequiredTeamsCondition(),
    "allowed_hours": AllowedHoursCondition(),
    "branches": BranchesCondition(),
    "required_checks": RequiredChecksCondition(),
}


def get_validator_descriptions() -> list[dict[str, Any]]:
    """Get descriptions for all available validators."""
    return [validator.get_description() for validator in VALIDATOR_REGISTRY.values()]
