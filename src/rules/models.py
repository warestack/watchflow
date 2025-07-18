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

    id: str
    name: str
    description: str
    enabled: bool = True
    severity: RuleSeverity = RuleSeverity.MEDIUM
    event_types: list[EventType] = Field(default_factory=list)  # Changed from list[str] to list[EventType]
    conditions: list[RuleCondition] = Field(default_factory=list)
    actions: list[RuleAction] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)  # Store parameters as-is from YAML
