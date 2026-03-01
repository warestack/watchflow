"""Pull request-related conditions for rule validation.

This module contains conditions that validate PR-specific aspects
such as title patterns, description length, and required labels.
"""

import logging
import re
from typing import Any

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = logging.getLogger(__name__)


class TitlePatternCondition(BaseCondition):
    """Validates if the PR title matches a specific pattern."""

    name = "title_pattern"
    description = "Validates if the PR title matches a specific pattern"
    parameter_patterns = ["title_pattern"]
    event_types = ["pull_request"]
    examples = [{"title_pattern": "^feat|^fix|^docs"}, {"title_pattern": "^JIRA-\\d+"}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate title pattern condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if title doesn't match pattern.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        pattern = parameters.get("title_pattern")
        if not pattern:
            return []  # No violation if no pattern specified

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []  # No violation if we can't check

        title = pull_request.get("title", "")
        if not title:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message="PR title is empty",
                    how_to_fix="Provide a descriptive title for the pull request.",
                )
            ]

        try:
            matches = bool(re.match(pattern, title))
            logger.debug(f"TitlePatternCondition: Title '{title}' matches pattern '{pattern}': {matches}")

            if not matches:
                return [
                    Violation(
                        rule_description=self.description,
                        severity=Severity.MEDIUM,
                        message=f"PR title '{title}' does not match required pattern '{pattern}'",
                        details={"title": title, "pattern": pattern},
                        how_to_fix=f"Update the PR title to match the pattern: {pattern}",
                    )
                ]
        except re.error as e:
            logger.error(f"TitlePatternCondition: Invalid regex pattern '{pattern}': {e}")
            return []  # No violation if pattern is invalid

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        pattern = parameters.get("title_pattern")
        if not pattern:
            return True  # No violation if no pattern specified

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        title = pull_request.get("title", "")
        if not title:
            return False  # Violation if no title

        try:
            matches = bool(re.match(pattern, title))
            logger.debug(f"TitlePatternCondition: Title '{title}' matches pattern '{pattern}': {matches}")
            return matches
        except re.error as e:
            logger.error(f"TitlePatternCondition: Invalid regex pattern '{pattern}': {e}")
            return True  # No violation if pattern is invalid


class MinDescriptionLengthCondition(BaseCondition):
    """Validates if the PR description meets minimum length requirements."""

    name = "min_description_length"
    description = "Validates if the PR description meets minimum length requirements"
    parameter_patterns = ["min_description_length"]
    event_types = ["pull_request"]
    examples = [{"min_description_length": 50}, {"min_description_length": 100}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate description length condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if description is too short.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        min_length: int = int(parameters.get("min_description_length", 1))

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []  # No violation if we can't check

        description = pull_request.get("body", "")
        if not description:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message="PR description is empty",
                    how_to_fix=f"Add a description with at least {min_length} characters.",
                )
            ]

        description_length = len(description.strip())
        is_valid = description_length >= min_length

        logger.debug(
            f"MinDescriptionLengthCondition: Description length {description_length}, requires {min_length}: {is_valid}"
        )

        if not is_valid:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"PR description is too short ({description_length} chars, minimum {min_length} required)",
                    details={"current_length": description_length, "min_length": min_length},
                    how_to_fix=f"Expand the description to at least {min_length} characters.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        min_length: int = int(parameters.get("min_description_length", 1))

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


class RequiredLabelsCondition(BaseCondition):
    """Validates if the PR has all required labels."""

    name = "required_labels"
    description = "Validates if the PR has all required labels"
    parameter_patterns = ["required_labels"]
    event_types = ["pull_request"]
    examples = [{"required_labels": ["security", "review"]}, {"required_labels": ["bug", "feature"]}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate required labels condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if required labels are missing.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        required_labels = parameters.get("required_labels", [])
        if not required_labels:
            return []  # No labels required

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []  # No violation if we can't check

        pr_labels = [label.get("name", "") for label in pull_request.get("labels", [])]

        missing_labels = [label for label in required_labels if label not in pr_labels]

        logger.debug(
            f"RequiredLabelsCondition: PR has labels {pr_labels}, requires {required_labels}, missing {missing_labels}"
        )

        if missing_labels:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"Missing required labels: {', '.join(missing_labels)}",
                    details={
                        "required_labels": required_labels,
                        "current_labels": pr_labels,
                        "missing_labels": missing_labels,
                    },
                    how_to_fix=f"Add the following labels to the PR: {', '.join(missing_labels)}",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        required_labels = parameters.get("required_labels", [])
        if not required_labels:
            return True  # No labels required

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True  # No violation if we can't check

        pr_labels = [label.get("name", "") for label in pull_request.get("labels", [])]

        missing_labels = [label for label in required_labels if label not in pr_labels]

        is_valid = len(missing_labels) == 0

        logger.debug(
            f"RequiredLabelsCondition: PR has labels {pr_labels}, requires {required_labels}, missing {missing_labels}: {is_valid}"
        )

        return is_valid


class MinApprovalsCondition(BaseCondition):
    """Validates if the PR has the minimum number of approvals."""

    name = "min_approvals"
    description = "Validates if the PR has the minimum number of approvals"
    parameter_patterns = ["min_approvals"]
    event_types = ["pull_request"]
    examples = [{"min_approvals": 1}, {"min_approvals": 2}]

    async def evaluate(self, context: Any) -> list[Violation]:
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        min_approvals = parameters.get("min_approvals", 1)
        # Logic recovered from old watchflow: check explicit 'APPROVED' state
        reviews = event.get("reviews", [])

        approved_count = 0
        for review in reviews:
            if review.get("state") == "APPROVED":
                approved_count += 1

        if approved_count < min_approvals:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"PR has {approved_count} approvals, requires {min_approvals}",
                    how_to_fix=f"Get at least {min_approvals} approving reviews from eligible reviewers.",
                )
            ]
        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        min_approvals = parameters.get("min_approvals", 1)
        reviews = event.get("reviews", [])

        approved_count = 0
        for review in reviews:
            if review.get("state") == "APPROVED":
                approved_count += 1

        return bool(approved_count >= int(min_approvals))


# Regex to detect issue references in PR body/title: #123, closes #123, fixes #123, etc.
_ISSUE_REF_PATTERN = re.compile(
    r"(?:closes?|fixes?|resolves?|refs?)\s+#\d+|#\d+",
    re.IGNORECASE,
)


class RequireLinkedIssueCondition(BaseCondition):
    """Validates that the PR body or title references at least one linked issue (e.g. #123, closes #123)."""

    name = "require_linked_issue"
    description = "Checks PR description (body) and title for a linked issue reference (e.g. #123, Fixes #123, Closes #456). Use when the rule requires issue refs in either field."
    parameter_patterns = ["require_linked_issue"]
    event_types = ["pull_request"]
    examples = [{"require_linked_issue": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate linked-issue condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if PR does not reference an issue.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        if not parameters.get("require_linked_issue"):
            return []

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []

        body = pull_request.get("body") or ""
        title = pull_request.get("title") or ""
        combined = f"{title}\n{body}"

        if _ISSUE_REF_PATTERN.search(combined):
            logger.debug("RequireLinkedIssueCondition: PR references an issue")
            return []

        return [
            Violation(
                rule_description=self.description,
                severity=Severity.MEDIUM,
                message="PR does not reference a linked issue (e.g. #123 or closes #123 in body/title)",
                how_to_fix="Add an issue reference in the PR title or description (e.g. Fixes #123).",
            )
        ]

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        if not parameters.get("require_linked_issue"):
            return True

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True

        body = pull_request.get("body") or ""
        title = pull_request.get("title") or ""
        combined = f"{title}\n{body}"
        return bool(_ISSUE_REF_PATTERN.search(combined))


class _PatchPatternCondition(BaseCondition):
    """Base class for conditions that match regex patterns against PR diff patches.

    Subclasses configure the parameter key, violation severity, and message format.
    """

    _pattern_param_key: str = ""
    _violation_severity: Severity = Severity.MEDIUM

    def _make_message(self, matched: list[str], filename: str) -> str:
        """Return the violation message. Override for custom wording."""
        return f"Patterns {matched} found in added lines of {filename}"

    def _make_how_to_fix(self) -> str:
        """Return the how_to_fix text. Override for custom wording."""
        return "Remove the matched patterns from your code changes."

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate patch-pattern condition."""
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        patterns = parameters.get(self._pattern_param_key)
        if not patterns or not isinstance(patterns, list):
            return []

        changed_files = event.get("changed_files", [])
        if not changed_files:
            return []

        from src.rules.utils.diff import match_patterns_in_patch

        violations = []
        for file_info in changed_files:
            patch = file_info.get("patch")
            if not patch:
                continue

            matched = match_patterns_in_patch(patch, patterns)
            if matched:
                filename = file_info.get("filename", "unknown")
                violations.append(
                    Violation(
                        rule_description=self.description,
                        severity=self._violation_severity,
                        message=self._make_message(matched, filename),
                        how_to_fix=self._make_how_to_fix(),
                    )
                )

        return violations

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface."""
        patterns = parameters.get(self._pattern_param_key)
        if not patterns or not isinstance(patterns, list):
            return True

        changed_files = event.get("changed_files", [])
        from src.rules.utils.diff import match_patterns_in_patch

        for file_info in changed_files:
            patch = file_info.get("patch")
            if patch and match_patterns_in_patch(patch, patterns):
                return False

        return True


class DiffPatternCondition(_PatchPatternCondition):
    """Validates that a PR diff does not contain specified restricted patterns."""

    name = "diff_pattern"
    description = "Checks if code changes contain restricted patterns or fail to contain required patterns."
    parameter_patterns = ["diff_restricted_patterns"]
    event_types = ["pull_request"]
    examples = [{"diff_restricted_patterns": ["console\\.log", "TODO:"]}]

    _pattern_param_key = "diff_restricted_patterns"
    _violation_severity = Severity.MEDIUM

    def _make_message(self, matched: list[str], filename: str) -> str:
        return f"Restricted patterns {matched} found in added lines of {filename}"

    def _make_how_to_fix(self) -> str:
        return "Remove the restricted patterns from your code changes."


class SecurityPatternCondition(_PatchPatternCondition):
    """Detects security-sensitive patterns (like API keys) in code changes."""

    name = "security_pattern"
    description = "Detects hardcoded secrets, API keys, or sensitive data in PR diffs."
    parameter_patterns = ["security_patterns"]
    event_types = ["pull_request"]
    examples = [{"security_patterns": ["api_key", "secret", "password", "token"]}]

    _pattern_param_key = "security_patterns"
    _violation_severity = Severity.CRITICAL

    def _make_message(self, matched: list[str], filename: str) -> str:
        return f"Security-sensitive patterns {matched} detected in {filename}"

    def _make_how_to_fix(self) -> str:
        return "Remove hardcoded secrets or sensitive patterns from the code."


class UnresolvedCommentsCondition(BaseCondition):
    """Validates that a pull request has no unresolved review comments."""

    name = "unresolved_comments"
    description = "Blocks PR merge if unresolved review comments exist."
    parameter_patterns = ["block_on_unresolved_comments", "require_resolution"]
    event_types = ["pull_request"]
    examples = [{"block_on_unresolved_comments": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate unresolved comments condition."""
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        block = parameters.get("block_on_unresolved_comments") or parameters.get("require_resolution")
        if not block:
            return []

        review_threads = event.get("review_threads", [])
        if not review_threads:
            return []

        unresolved_count = 0
        for thread in review_threads:
            # Depending on how the dict is parsed/stored in the event data
            if hasattr(thread, "is_resolved"):
                is_resolved = thread.is_resolved
                is_outdated = getattr(thread, "is_outdated", False)
            else:
                is_resolved = thread.get("is_resolved", False)
                is_outdated = thread.get("is_outdated", False)

            # If a thread is unresolved and not outdated
            if not is_resolved and not is_outdated:
                unresolved_count += 1

        if unresolved_count > 0:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"PR has {unresolved_count} unresolved review comment thread(s)",
                    how_to_fix="Resolve all review comments before merging.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface."""
        block = parameters.get("block_on_unresolved_comments") or parameters.get("require_resolution")
        if not block:
            return True

        review_threads = event.get("review_threads", [])
        for thread in review_threads:
            if hasattr(thread, "is_resolved"):
                is_resolved = thread.is_resolved
                is_outdated = getattr(thread, "is_outdated", False)
            else:
                is_resolved = thread.get("is_resolved", False)
                is_outdated = thread.get("is_outdated", False)

            if not is_resolved and not is_outdated:
                return False

        return True
