from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.core.models import EventType


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


class HygieneMetrics(BaseModel):
    """
    Aggregated repository signals for hygiene analysis.

    This model powers the "AI Immune System" by summarizing patterns across recent PRs.
    High unlinked_issue_rate or abnormal average_pr_size triggers defensive rules like:
    - require_linked_issue (force context)
    - max_pr_size (prevent mass changes)
    - first_time_contributor_review (extra scrutiny)

    These metrics are calculated from the last 20-30 merged PRs and inform LLM reasoning.
    """

    unlinked_issue_rate: float = Field(
        ...,
        description="Percentage (0.0-1.0) of PRs without linked issues. High values indicate poor governance.",
    )
    average_pr_size: int = Field(
        ..., description="Mean lines changed per PR. Unusually high values suggest untargeted contributions."
    )
    first_time_contributor_count: int = Field(
        ..., description="Count of unique first-time contributors in recent PRs (risk indicator)."
    )

    # Enhanced Hygiene Signals (AI Immune System - Phase 2)
    issue_diff_mismatch_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs where the linked issue doesn't semantically match the code diff. Detects low-effort contributions claiming to fix unrelated issues.",
    )
    ghost_contributor_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs where the author never responded to review comments. Indicates drive-by contributions with no engagement.",
    )
    test_coverage_delta_avg: float | None = Field(
        default=None,
        description="Average change in test coverage across PRs. Negative values indicate a decline in test quality.",
    )
    codeowner_bypass_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs merged without required CODEOWNERS approval. Indicates governance gaps.",
    )
    ai_generated_rate: float | None = Field(
        default=None,
        description="Percentage (0.0-1.0) of PRs flagged as being substantially AI-generated. Informs rules about AI contribution quality.",
    )


class RuleCondition(BaseModel):
    """Represents a condition that must be met for a rule to be triggered."""

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuleAction(BaseModel):
    """Represents an action to take when a rule is violated."""

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    """Represents a rule that can be evaluated against repository events."""

    description: str = Field(description="Primary identifier and description of the rule")
    enabled: bool = True
    severity: RuleSeverity = RuleSeverity.MEDIUM
    event_types: list[EventType] = Field(default_factory=list)
    conditions: list[RuleCondition] = Field(default_factory=list)
    actions: list[RuleAction] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)  # Store parameters as-is from YAML
