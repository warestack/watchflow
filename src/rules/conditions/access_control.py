"""Access control conditions for rule validation.

This module contains conditions that validate security and access control
aspects like team membership, code ownership, and branch protection.
"""

from typing import Any

import structlog

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = structlog.get_logger(__name__)

# TODO: Move to settings in next phase - hardcoded team memberships for demo only
DEFAULT_TEAM_MEMBERSHIPS: dict[str, list[str]] = {
    "devops": ["devops-user", "admin-user"],
    "codeowners": ["senior-dev", "tech-lead"],
}


class AuthorTeamCondition(BaseCondition):
    """Validates if the event author is a member of a specific team."""

    name = "author_team_is"
    description = "Validates if the event author is a member of a specific team"
    parameter_patterns = ["team"]
    event_types = ["pull_request", "push", "deployment"]
    examples = [{"team": "devops"}, {"team": "codeowners"}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate team membership condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if author is not in the required team.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        team_name = parameters.get("team")
        if not team_name:
            logger.warning("AuthorTeamCondition: No team specified in parameters")
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message="No team specified in rule parameters",
                    how_to_fix="Provide a 'team' parameter in the rule configuration.",
                )
            ]

        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            logger.warning("AuthorTeamCondition: No sender login found in event")
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.INFO,
                    message="Unable to determine event author",
                )
            ]

        logger.debug("Checking team membership", author=author_login, team=team_name)

        # TODO: Replace with real GitHub API call—current logic for test/demo only.
        team_memberships = DEFAULT_TEAM_MEMBERSHIPS
        is_member = author_login in team_memberships.get(team_name, [])

        if not is_member:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"Author '{author_login}' is not a member of team '{team_name}'",
                    details={"author": author_login, "required_team": team_name},
                    how_to_fix=f"Request a team member from '{team_name}' to perform this action.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        team_name = parameters.get("team")
        if not team_name:
            logger.warning("AuthorTeamCondition: No team specified in parameters")
            return False

        author_login = event.get("sender", {}).get("login", "")
        if not author_login:
            logger.warning("AuthorTeamCondition: No sender login found in event")
            return False

        logger.debug("Checking team membership", author=author_login, team=team_name)

        team_memberships = DEFAULT_TEAM_MEMBERSHIPS
        return author_login in team_memberships.get(team_name, [])


class CodeOwnersCondition(BaseCondition):
    """Validates if changes to files require review from code owners."""

    name = "code_owners"
    description = "Validates if changes to files require review from code owners"
    parameter_patterns = ["critical_owners"]
    event_types = ["pull_request"]
    examples = [
        {"critical_owners": ["admin", "maintainers"]},
        {"critical_owners": ["security-team", "devops"]},
        {},  # No critical_owners means any file with owners is critical
    ]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate code owners condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if code owner review is required but not present.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        changed_files = self._get_changed_files(event)
        if not changed_files:
            logger.debug("CodeOwnersCondition: No files to check")
            return []

        from src.rules.utils.codeowners import is_critical_file

        critical_owners = parameters.get("critical_owners")

        critical_files = [
            file_path for file_path in changed_files if is_critical_file(file_path, critical_owners=critical_owners)
        ]

        if critical_files:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"Changes to critical files require code owner review: {', '.join(critical_files)}",
                    details={"critical_files": critical_files, "critical_owners": critical_owners},
                    how_to_fix="Request a review from a designated code owner before merging.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        changed_files = self._get_changed_files(event)
        if not changed_files:
            logger.debug("CodeOwnersCondition: No files to check")
            return True

        from src.rules.utils.codeowners import is_critical_file

        critical_owners = parameters.get("critical_owners")

        requires_code_owner_review = any(
            is_critical_file(file_path, critical_owners=critical_owners) for file_path in changed_files
        )

        logger.debug(
            "CodeOwnersCondition: Files checked",
            files=changed_files,
            requires_review=requires_code_owner_review,
        )
        return not requires_code_owner_review

    def _get_changed_files(self, event: dict[str, Any]) -> list[str]:
        """Extract changed files from the event."""
        files = event.get("files", [])
        if files:
            return [file.get("filename", "") for file in files if file.get("filename")]

        pull_request = event.get("pull_request_details", {})
        if pull_request:
            from typing import cast

            return cast("list[str]", pull_request.get("changed_files", []))

        return []


class ProtectedBranchesCondition(BaseCondition):
    """Validates if the PR targets protected branches."""

    name = "protected_branches"
    description = "Validates if the PR targets protected branches"
    parameter_patterns = ["protected_branches"]
    event_types = ["pull_request"]
    examples = [{"protected_branches": ["main", "develop"]}, {"protected_branches": ["master"]}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate protected branches condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if PR targets a protected branch.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        protected_branches = parameters.get("protected_branches", [])
        if not protected_branches:
            return []

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []

        base_branch = pull_request.get("base", {}).get("ref", "")
        is_protected = base_branch in protected_branches

        logger.debug(
            "ProtectedBranchesCondition: Checking branch",
            base_branch=base_branch,
            protected_branches=protected_branches,
            is_protected=is_protected,
        )

        if is_protected:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"PR targets protected branch '{base_branch}'",
                    details={"base_branch": base_branch, "protected_branches": protected_branches},
                    how_to_fix="Ensure additional review requirements are met for protected branches.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        protected_branches = parameters.get("protected_branches", [])
        if not protected_branches:
            return True

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True

        base_branch = pull_request.get("base", {}).get("ref", "")
        is_protected = base_branch in protected_branches

        logger.debug(
            "ProtectedBranchesCondition: Checking branch",
            base_branch=base_branch,
            protected_branches=protected_branches,
            is_protected=is_protected,
        )

        return not is_protected
