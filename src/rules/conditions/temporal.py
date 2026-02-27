"""Temporal conditions for rule validation.

This module contains conditions that validate time-based aspects
such as weekend restrictions, allowed hours, and day-of-week restrictions.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from src.core.models import Severity, Violation
from src.rules.conditions.base import BaseCondition

logger = structlog.get_logger(__name__)

# TODO: Move to settings in next phase
WEEKEND_DAYS = (5, 6)  # Saturday = 5, Sunday = 6
DEFAULT_TIMEZONE = "UTC"


class WeekendCondition(BaseCondition):
    """Validates if the current time is during a weekend."""

    name = "is_weekend"
    description = "Validates if the current time is during a weekend"
    parameter_patterns = []
    event_types = ["deployment", "pull_request"]
    examples = [{}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate weekend condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if action is during weekend.
        """
        current_time = datetime.now()
        is_weekend = current_time.weekday() in WEEKEND_DAYS

        if is_weekend:
            weekday_name = current_time.strftime("%A")
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"Action attempted during weekend ({weekday_name})",
                    details={"day": weekday_name, "weekday_index": current_time.weekday()},
                    how_to_fix="Wait until a weekday to perform this action.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        current_time = datetime.now()
        is_weekend = current_time.weekday() in WEEKEND_DAYS
        # Return True if NOT weekend (no violation), False if weekend (violation)
        return not is_weekend


class AllowedHoursCondition(BaseCondition):
    """Validates if the current time is within allowed hours."""

    name = "allowed_hours"
    description = "Validates if the current time is within allowed hours"
    parameter_patterns = ["allowed_hours", "timezone"]
    event_types = ["deployment", "pull_request"]
    examples = [
        {"allowed_hours": [9, 10, 11, 14, 15, 16], "timezone": "Europe/Athens"},
        {"allowed_hours": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17], "timezone": "UTC"},
    ]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate allowed hours condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if action is outside allowed hours.
        """
        parameters = context.get("parameters", {})

        allowed_hours = parameters.get("allowed_hours", [])
        if not allowed_hours:
            return []

        timezone_str = parameters.get("timezone", DEFAULT_TIMEZONE)
        current_time = self._get_current_time(timezone_str)
        current_hour = current_time.hour

        logger.debug(
            "AllowedHoursCondition: Checking hour",
            current_hour=current_hour,
            timezone=timezone_str,
            allowed_hours=allowed_hours,
        )

        if current_hour not in allowed_hours:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"Action attempted outside allowed hours (current: {current_hour}:00, allowed: {allowed_hours})",
                    details={
                        "current_hour": current_hour,
                        "timezone": timezone_str,
                        "allowed_hours": allowed_hours,
                    },
                    how_to_fix=f"Perform this action during allowed hours: {allowed_hours}",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        allowed_hours = parameters.get("allowed_hours", [])
        if not allowed_hours:
            return True

        timezone_str = parameters.get("timezone", DEFAULT_TIMEZONE)
        current_time = self._get_current_time(timezone_str)
        current_hour = current_time.hour

        logger.debug(
            "AllowedHoursCondition: Checking hour",
            current_hour=current_hour,
            timezone=timezone_str,
            allowed_hours=allowed_hours,
        )
        return current_hour in allowed_hours

    def _get_current_time(self, timezone_str: str) -> datetime:
        """Get current time in specified timezone."""
        try:
            import pytz  # type: ignore

            tz = pytz.timezone(timezone_str)
            return datetime.now(tz)
        except ImportError:
            logger.warning("pytz not installed, using local time")
            return datetime.now()
        except Exception as e:
            logger.warning("Invalid timezone, using local time", timezone=timezone_str, error=str(e))
            return datetime.now()


class DaysCondition(BaseCondition):
    """Validates if the PR was merged on restricted days."""

    name = "days"
    description = "Validates if the PR was merged on restricted days"
    parameter_patterns = ["days"]
    event_types = ["pull_request"]
    examples = [{"days": ["Friday", "Saturday"]}, {"days": ["Monday"]}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate days restriction condition.

        Args:
            context: Dict with 'parameters' and 'event' keys.

        Returns:
            List of violations if PR was merged on a restricted day.
        """
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        days = parameters.get("days", [])
        if not days:
            return []

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return []

        merged_at = pull_request.get("merged_at")
        if not merged_at:
            return []

        try:
            dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            weekday = dt.strftime("%A")

            is_restricted = weekday in days

            logger.debug(
                "DaysCondition: Checking merge day",
                merged_day=weekday,
                restricted_days=days,
                is_restricted=is_restricted,
            )

            if is_restricted:
                return [
                    Violation(
                        rule_description=self.description,
                        severity=Severity.MEDIUM,
                        message=f"PR merged on restricted day: {weekday}",
                        details={"merged_day": weekday, "restricted_days": days, "merged_at": merged_at},
                        how_to_fix=f"Avoid merging on restricted days: {', '.join(days)}",
                    )
                ]

        except Exception as e:
            logger.error("DaysCondition: Error parsing merged_at timestamp", merged_at=merged_at, error=str(e))

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface for backward compatibility."""
        days = parameters.get("days", [])
        if not days:
            return True

        pull_request = event.get("pull_request_details", {})
        if not pull_request:
            return True

        merged_at = pull_request.get("merged_at")
        if not merged_at:
            return True

        try:
            dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
            weekday = dt.strftime("%A")

            is_restricted = weekday in days

            logger.debug(
                "DaysCondition: Checking merge day",
                merged_day=weekday,
                restricted_days=days,
                is_restricted=is_restricted,
            )

            return not is_restricted

        except Exception as e:
            logger.error("DaysCondition: Error parsing merged_at timestamp", merged_at=merged_at, error=str(e))
            return True


class CommentResponseTimeCondition(BaseCondition):
    """Validates that PR comments have been addressed within a specified SLA."""

    name = "comment_response_time"
    description = "Enforces an SLA (in hours) for responding to review comments."
    parameter_patterns = ["max_comment_response_time_hours"]
    event_types = ["pull_request"]
    examples = [{"max_comment_response_time_hours": 24}]

    async def evaluate(self, context: Any) -> list[Violation]:
        """Evaluate comment response time SLA."""
        parameters = context.get("parameters", {})
        event = context.get("event", {})

        max_hours = parameters.get("max_comment_response_time_hours")
        if not max_hours:
            return []

        review_threads = event.get("review_threads", [])
        if not review_threads:
            return []

        # Use event timestamp as the "current" time for evaluation
        # to ensure deterministic behavior based on when the event fired
        event_time_str = event.get("timestamp")
        if event_time_str:
            try:
                now = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
            except ValueError:
                now = datetime.now(timezone.utc)
        else:
            now = datetime.now(timezone.utc)

        max_delta = timedelta(hours=float(max_hours))
        sla_violations = 0

        for thread in review_threads:
            # We only care about unresolved threads for SLA checking
            if isinstance(thread, dict):
                is_resolved = thread.get("is_resolved", False)
                comments = thread.get("comments", [])
            else:
                is_resolved = getattr(thread, "is_resolved", False)
                comments = getattr(thread, "comments", [])

            if is_resolved or not comments:
                continue

            # The first comment in the thread starts the SLA clock
            first_comment = comments[0]
            
            if isinstance(first_comment, dict):
                created_at_str = first_comment.get("created_at") or first_comment.get("createdAt")
            else:
                created_at_str = getattr(first_comment, "created_at", None) or getattr(first_comment, "createdAt", None)
                
            if not created_at_str:
                continue

            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                # If the current time minus the comment creation time exceeds the SLA
                if now - created_at > max_delta:
                    sla_violations += 1
            except ValueError:
                continue

        if sla_violations > 0:
            return [
                Violation(
                    rule_description=self.description,
                    severity=Severity.MEDIUM,
                    message=f"{sla_violations} review thread(s) have exceeded the {max_hours}-hour response SLA.",
                    how_to_fix="Respond to or resolve all stale review comments.",
                )
            ]

        return []

    async def validate(self, parameters: dict[str, Any], event: dict[str, Any]) -> bool:
        """Legacy validation interface."""
        violations = await self.evaluate({"parameters": parameters, "event": event})
        return len(violations) == 0
