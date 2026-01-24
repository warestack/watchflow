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
