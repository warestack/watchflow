from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.core.models import EventType  # noqa: TCH001, TCH002, TC001
from src.rules.conditions.base import BaseCondition  # noqa: TCH001, TCH002, TC001


class RuleSeverity(str, Enum):
    """Enumerates the severity levels of a rule violation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    ERROR = "error"  # Added for backward compatibility
    WARNING = "warning"  # Added for backward compatibility


class RuleCategory(str, Enum):
    """Enumerates rule categories for organizational and filtering purposes."""

    SECURITY = "security"  # Authentication, secrets, CVE scanning
    QUALITY = "quality"  # Code review, testing, documentation standards
    COMPLIANCE = "compliance"  # Legal, licensing, audit requirements
    VELOCITY = "velocity"  # CI/CD optimization, automation
    HYGIENE = "hygiene"  # AI spam detection, contribution governance (AI Immune System)


class RuleWhen(BaseModel):
    """
    Structured predicate block controlling whether a rule is applied to an event.

    When all predicates evaluate true, the rule runs; otherwise it is skipped.
    An absent or empty block means the rule always runs.
    """

    contributor: str | None = Field(
        default=None,
        description="Contributor predicate: 'first_time' (no prior merged PRs) or 'trusted' (has merged PRs).",
    )
    pr_count_below: int | None = Field(
        default=None,
        description="Rule applies only when the author has fewer than N prior merged PRs.",
    )
    files_match: str | list[str] | None = Field(
        default=None,
        description="Glob pattern(s); rule applies only when at least one changed file matches.",
    )


class RuleCondition(BaseModel):
    """
    Represents a condition that must be met for a rule to be triggered.
    Deprecated: Used for legacy JSON/YAML parsing, but runtime now uses BaseCondition objects.
    """

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuleAction(BaseModel):
    """Represents an action to take when a rule is violated."""

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    """Represents a rule that can be evaluated against repository events."""

    description: str = Field(description="Primary identifier and description of the rule")
    rule_id: str | None = Field(
        default=None, description="Stable rule ID for acknowledgment matching (e.g. require-linked-issue)"
    )
    enabled: bool = True
    severity: RuleSeverity = RuleSeverity.MEDIUM
    event_types: list["EventType"] = Field(default_factory=list)  # noqa: UP037
    conditions: list["BaseCondition"] = Field(default_factory=list)  # noqa: UP037
    actions: list[RuleAction] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)  # Store parameters as-is from YAML
    when: RuleWhen | None = Field(
        default=None,
        description="Optional predicate block. Rule is skipped when predicates do not match the event.",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Update forward references
Rule.model_rebuild()
