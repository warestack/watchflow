from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from src.core.models import EventType

if TYPE_CHECKING:
    from src.rules.condition_evaluator import ConditionExpression


class RuleSeverity(str, Enum):
    """Enumerates the severity levels of a rule violation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    ERROR = "error"  # Added for backward compatibility
    WARNING = "warning"  # Added for backward compatibility


class RuleCondition(BaseModel):
    """Represents a condition that must be met for a rule to be triggered."""

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuleAction(BaseModel):
    """Represents an action to take when a rule is violated."""

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class Rule(BaseModel):
    """
    Represents a rule that can be evaluated against repository events.

    Supports both legacy conditions (list of RuleCondition) and new condition expressions
    (ConditionExpression with AND/OR/NOT operators).
    """

    model_config = {"arbitrary_types_allowed": True}

    description: str = Field(description="Primary identifier and description of the rule")
    enabled: bool = True
    severity: RuleSeverity = RuleSeverity.MEDIUM
    event_types: list[EventType] = Field(default_factory=list)
    conditions: list[RuleCondition] = Field(default_factory=list, description="Legacy conditions (treated as AND)")
    condition: "ConditionExpression | None" = Field(
        default=None, description="New condition expression with AND/OR/NOT support"
    )
    actions: list[RuleAction] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict, description="Store parameters as-is from YAML")


def _rebuild_rule_model() -> None:
    """Rebuild Rule model to resolve forward references."""
    from src.rules.condition_evaluator import ConditionExpression  # noqa: F401

    Rule.model_rebuild()


_rebuild_rule_model()
