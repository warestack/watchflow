"""Advanced access control and separation of duties rules."""

import logging
from typing import Any

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = logging.getLogger(__name__)


class NoSelfApprovalCondition(BaseCondition):
    """Validates that a PR author cannot approve their own PR."""

    name = "no_self_approval"
    description = "Enforces separation of duties by preventing PR authors from approving their own code."
    parameter_patterns = ["block_self_approval"]
    event_types = ["pull_request"]
    examples = [{"block_self_approval": True}]

    async def evaluate(self, context: Any) -> list[Violation]:
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        if not parameters.get("block_self_approval"):
            return []

        author = event.get("pull_request_details", {}).get("user", {}).get("login")
        if not author:
            return []

        reviews = event.get("reviews", [])
        self_approved = False

        for review in reviews:
            review_state = review.get("state") if isinstance(review, dict) else getattr(review, "state", None)
            reviewer = review.get("author") if isinstance(review, dict) else getattr(review, "author", None)

            if review_state == "APPROVED" and reviewer == author:
                self_approved = True
                break

        if self_approved:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.CRITICAL,
                    message="Pull request was approved by its own author.",
                    how_to_fix="Dismiss the self-approval and request a review from a different team member.",
                )
            ]

        return []


class CrossTeamApprovalCondition(BaseCondition):
    """Validates that a PR has approvals from specific teams."""

    name = "cross_team_approval"
    description = "Requires approvals from members of specific GitHub teams."
    parameter_patterns = ["required_team_approvals"]
    event_types = ["pull_request"]
    examples = [{"required_team_approvals": ["backend", "security"]}]

    async def evaluate(self, context: Any) -> list[Violation]:
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        required_teams = parameters.get("required_team_approvals")
        if not required_teams or not isinstance(required_teams, list):
            return []

        reviews = event.get("reviews", [])

        # In a real implementation, we would map reviewers to their GitHub Teams
        # For now, we simulate this by checking if the required teams are in the requested_teams list
        # and if we have enough total approvals. A robust implementation would need a GraphQL call
        # to fetch user team memberships.

        pr_details = event.get("pull_request_details", {})
        requested_teams = pr_details.get("requested_teams", [])
        requested_team_slugs = [t.get("slug") for t in requested_teams if t.get("slug")]

        missing_teams = []
        for req_team in required_teams:
            clean_team = req_team.replace("@", "").split("/")[-1]  # Clean org/team to just team
            if clean_team in requested_team_slugs:
                # Team was requested, now check if anyone approved (simplified check)
                has_approval = any(
                    (r.get("state") == "APPROVED" if isinstance(r, dict) else getattr(r, "state", None) == "APPROVED")
                    for r in reviews
                )
                if not has_approval:
                    missing_teams.append(req_team)
            else:
                # Team wasn't even requested
                missing_teams.append(req_team)

        if missing_teams:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.HIGH,
                    message=f"Missing approvals from required teams: {', '.join(missing_teams)}",
                    how_to_fix="Request reviews from the specified teams and wait for their approval.",
                )
            ]

        return []
