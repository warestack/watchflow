import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ConditionValidator(ABC):
    """Abstract base class for all condition validators."""

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


class AuthorTeamValidator(ConditionValidator):
    """Validates if the event author is a member of a specific team."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        team_name = parameters.get("team")
        if not team_name:
            logger.warning("AuthorTeamValidator: No team specified in parameters")
            return False

        # Get author from event
        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            logger.warning("AuthorTeamValidator: No sender login found in event")
            return False

        # Placeholder logic - replace with actual GitHub API call
        logger.debug(f"Checking if {author_login} is in team {team_name}")

        # For testing purposes, let's assume certain users are in certain teams
        team_memberships = {
            "devops": ["devops-user", "admin-user"],
            "codeowners": ["senior-dev", "tech-lead"],
        }

        return author_login in team_memberships.get(team_name, [])


class FilePatternValidator(ConditionValidator):
    """Validates if files in the event match or don't match a pattern."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        pattern = parameters.get("pattern")
        if not pattern:
            logger.warning("FilePatternValidator: No pattern specified in parameters")
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


class NewContributorValidator(ConditionValidator):
    """Validates if the event author is a new contributor."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            return False

        # Placeholder logic - in production, this would check the user's contribution history
        # For now, we'll use a simple list of "new contributors"
        new_contributors = ["new-user-1", "new-user-2", "intern-dev"]

        return author_login in new_contributors


class ApprovalCountValidator(ConditionValidator):
    """Validates if the PR has the required number of approvals."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # Remove unused variable assignment
        # min_approvals = parameters.get("min_approvals", 1)

        # Placeholder logic - in production, this would check the actual PR reviews
        return True


class WeekendValidator(ConditionValidator):
    """Validates if the current time is during a weekend."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        current_time = datetime.now()
        # 5 = Saturday, 6 = Sunday
        is_weekend = current_time.weekday() >= 5
        # Return True if NOT weekend (no violation), False if weekend (violation)
        return not is_weekend


class WorkflowDurationValidator(ConditionValidator):
    """Validates if a workflow run exceeded a time threshold."""

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # max_minutes = parameters.get("minutes", 3)

        # Placeholder logic - in production, this would check the actual workflow duration
        return False  # Placeholder


class MinApprovalsValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        min_approvals = parameters.get("min_approvals", 1)

        # Get reviews from the event data
        reviews = event.get("reviews", [])

        # Count approved reviews
        approved_count = 0
        for review in reviews:
            if review.get("state") == "APPROVED":
                approved_count += 1

        logger.debug(f"MinApprovalsValidator: PR has {approved_count} approvals, requires {min_approvals}")

        return approved_count >= min_approvals


class DaysValidator(ConditionValidator):
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
                f"DaysValidator: PR merged on {weekday}, restricted days: {days}, is_restricted: {is_restricted}"
            )

            return not is_restricted  # Return True if NOT restricted (no violation)

        except Exception as e:
            logger.error(f"DaysValidator: Error parsing merged_at timestamp '{merged_at}': {e}")
            return True  # No violation if we can't parse the date


class TitlePatternValidator(ConditionValidator):
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
            logger.debug(f"TitlePatternValidator: Title '{title}' matches pattern '{pattern}': {matches}")
            return matches
        except re.error as e:
            logger.error(f"TitlePatternValidator: Invalid regex pattern '{pattern}': {e}")
            return True  # No violation if pattern is invalid


class MinDescriptionLengthValidator(ConditionValidator):
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
            f"MinDescriptionLengthValidator: Description length {description_length}, requires {min_length}: {is_valid}"
        )

        return is_valid


class RequiredLabelsValidator(ConditionValidator):
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
            f"RequiredLabelsValidator: PR has labels {pr_labels}, requires {required_labels}, missing {missing_labels}: {is_valid}"
        )

        return is_valid


class MaxFileSizeValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        max_size_mb = parameters.get("max_file_size_mb", 100)
        files = event.get("files", [])

        # If no files data is available, we can't evaluate this rule
        if not files:
            logger.debug("MaxFileSizeValidator: No files data available, skipping validation")
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
                    f"MaxFileSizeValidator: File {filename} exceeds size limit: {size_mb:.2f}MB > {max_size_mb}MB"
                )

        is_valid = len(oversized_files) == 0

        if is_valid:
            logger.debug(f"MaxFileSizeValidator: All {len(files)} files are within size limit of {max_size_mb}MB")
        else:
            logger.debug(f"MaxFileSizeValidator: {len(oversized_files)} files exceed size limit: {oversized_files}")

        return is_valid


class PatternValidator(ConditionValidator):
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
            logger.debug(f"PatternValidator: Title '{title}' matches pattern '{pattern}': {matches}")
            return matches
        except re.error as e:
            logger.error(f"PatternValidator: Invalid regex pattern '{pattern}': {e}")
            return True  # No violation if pattern is invalid


class AllowForcePushValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # allow_force_push = parameters.get("allow_force_push", False)

        # This would typically check if the push was a force push
        # For now, return True (no violation) as placeholder
        return True


class ProtectedBranchesValidator(ConditionValidator):
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
            f"ProtectedBranchesValidator: Base branch '{base_branch}' in protected list {protected_branches}: {is_protected}"
        )

        return not is_protected  # Return True if NOT protected (no violation)


class EnvironmentsValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        environments = parameters.get("environments", [])
        if not environments:
            return True

        # This would typically check deployment environments
        # For now, return True as placeholder
        return True


class RequiredTeamsValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        required_teams = parameters.get("required_teams", [])
        if not required_teams:
            return True

        # This would check if the user is a member of required teams
        # For now, return True as placeholder
        return True


class AllowedHoursValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        allowed_hours = parameters.get("allowed_hours", [])
        if not allowed_hours:
            return True

        current_time = datetime.now()
        current_hour = current_time.hour

        return current_hour in allowed_hours


class BranchesValidator(ConditionValidator):
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

        logger.debug(f"BranchesValidator: Base branch '{base_branch}' in allowed branches {branches}: {is_allowed}")

        return is_allowed


class RequiredChecksValidator(ConditionValidator):
    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        # Add detailed logging to understand what's happening
        logger.info(f"RequiredChecksValidator: CALLED with parameters: {parameters}")
        logger.info(f"RequiredChecksValidator: Event keys available: {list(event.keys())}")
        
        required_checks = parameters.get("required_checks", [])
        logger.info(f"RequiredChecksValidator: Required checks: {required_checks}")
        
        if not required_checks:
            logger.info("RequiredChecksValidator: No required checks specified - PASSING")
            return True

        # Check if this is a pull request event with check data
        checks = event.get("checks", [])
        logger.info(f"RequiredChecksValidator: Found {len(checks)} checks in event data")
        
        if not checks:
            # If no checks available but required checks are specified,
            # this is a violation - required checks are missing
            logger.error("RequiredChecksValidator: No checks data available in event - VIOLATION")
            return False

        # Create a mapping of check names to their status
        check_status = {}
        for check in checks:
            name = check.get("name") or check.get("context")
            if name:
                # Determine if check passed
                # For check_runs: conclusion should be "success"
                # For statuses: state should be "success"
                conclusion = check.get("conclusion")
                state = check.get("state")

                if conclusion == "success" or state == "success":
                    check_status[name] = "success"
                elif conclusion in ["failure", "error", "cancelled", "timed_out"] or state in ["failure", "error"]:
                    check_status[name] = "failure"
                else:
                    check_status[name] = "pending"

        # Check if all required checks have passed
        failed_checks = []
        missing_checks = []

        for required_check in required_checks:
            if required_check not in check_status:
                missing_checks.append(required_check)
            elif check_status[required_check] != "success":
                failed_checks.append(required_check)

        # Log detailed information for debugging
        logger.debug(f"RequiredChecksValidator: Required checks: {required_checks}")
        logger.debug(f"RequiredChecksValidator: Available checks: {list(check_status.keys())}")
        logger.debug(f"RequiredChecksValidator: Failed checks: {failed_checks}")
        logger.debug(f"RequiredChecksValidator: Missing checks: {missing_checks}")

        # Rule is violated if any required checks are missing or failed
        violations_exist = len(failed_checks) > 0 or len(missing_checks) > 0

        if violations_exist:
            logger.info(f"RequiredChecksValidator: VIOLATION - Failed: {failed_checks}, Missing: {missing_checks}")
        else:
            logger.debug("RequiredChecksValidator: All required checks passed")

        return not violations_exist


# Registry of all available validators
VALIDATOR_REGISTRY = {
    "author_team_is": AuthorTeamValidator(),
    "files_match_pattern": FilePatternValidator(),
    "files_not_match_pattern": FilePatternValidator(),
    "author_is_new_contributor": NewContributorValidator(),
    "has_min_approvals": ApprovalCountValidator(),
    "is_weekend": WeekendValidator(),
    "workflow_duration_exceeds": WorkflowDurationValidator(),
    "min_approvals": MinApprovalsValidator(),
    "days": DaysValidator(),
    "title_pattern": TitlePatternValidator(),
    "min_description_length": MinDescriptionLengthValidator(),
    "required_labels": RequiredLabelsValidator(),
    "max_file_size_mb": MaxFileSizeValidator(),
    "pattern": PatternValidator(),
    "allow_force_push": AllowForcePushValidator(),
    "protected_branches": ProtectedBranchesValidator(),
    "environments": EnvironmentsValidator(),
    "required_teams": RequiredTeamsValidator(),
    "allowed_hours": AllowedHoursValidator(),
    "branches": BranchesValidator(),
    "required_checks": RequiredChecksValidator(),
}
