"""Compliance and security verification conditions for regulated environments."""

import logging
from typing import Any

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = logging.getLogger(__name__)

class SignedCommitsCondition(BaseCondition):
    """Validates that all commits in a PR are cryptographically signed."""

    name = "signed_commits"
    description = "Ensures all commits in a pull request are verified and signed (GPG/SSH/S/MIME)."
    parameter_patterns = ["require_signed_commits"]
    event_types = ["pull_request"]
    examples = [{"require_signed_commits": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        if not parameters.get("require_signed_commits"):
            return []

        # Assuming commits are attached to the event by PullRequestEnricher
        # via GraphQL PRContext which includes commit data.
        # We need to ensure the GraphQL query fetches commit signature status.
        commits = event.get("commits", [])
        if not commits:
            return []

        unsigned_shas = []
        for commit in commits:
            # We will need to update the GraphQL query to fetch verificationStatus
            is_verified = commit.get("is_verified", False) if isinstance(commit, dict) else getattr(commit, "is_verified", False)
            if not is_verified:
                sha = str(commit.get("oid", "unknown")) if isinstance(commit, dict) else str(getattr(commit, "oid", "unknown"))
                unsigned_shas.append(sha[:7])

        if unsigned_shas:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"Found {len(unsigned_shas)} unsigned commit(s): {', '.join(unsigned_shas)}",
                    how_to_fix="Ensure your local git client is configured to sign commits (e.g. `git config commit.gpgsign true`) and rebase to sign existing commits.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        violations = await self.evaluate({"parameters": parameters, "event": event})
        return len(violations) == 0


class ChangelogRequiredCondition(BaseCondition):
    """Validates that a CHANGELOG update is included if source files are modified."""

    name = "changelog_required"
    description = "Ensures PRs that modify source code also include a CHANGELOG or .changeset addition."
    parameter_patterns = ["require_changelog_update"]
    event_types = ["pull_request"]
    examples = [{"require_changelog_update": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        if not parameters.get("require_changelog_update"):
            return []

        changed_files = event.get("changed_files", []) or event.get("files", [])
        if not changed_files:
            return []

        source_changed = False
        changelog_changed = False

        for f in changed_files:
            filename = f.get("filename", "")
            if not filename:
                continue
                
            # Check if it's a changelog file
            if "CHANGELOG" in filename.upper() or filename.startswith(".changeset/"):
                changelog_changed = True
            elif not filename.startswith(("docs/", ".github/", "tests/")):
                source_changed = True

        if source_changed and not changelog_changed:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message="Source code was modified without a corresponding CHANGELOG update.",
                    how_to_fix="Add an entry to CHANGELOG.md or generate a new .changeset file describing your changes.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        violations = await self.evaluate({"parameters": parameters, "event": event})
        return len(violations) == 0
