"""
Data models for the Intelligent Acknowledgment Agent.
"""

from typing import Any

from pydantic import BaseModel, Field


class AcknowledgedViolation(BaseModel):
    """Represents a violation that can be acknowledged."""

    rule_id: str
    rule_name: str
    reason: str
    risk_level: str = Field(description="Risk level: low, medium, high")
    conditions: str | None = None


class RequiredFix(BaseModel):
    """Represents a violation that requires fixes."""

    rule_id: str
    rule_name: str
    reason: str
    priority: str = Field(description="Priority: high, medium, low")


class AcknowledgmentEvaluation(BaseModel):
    """The result of evaluating an acknowledgment request."""

    is_valid: bool
    reasoning: str
    acknowledgable_violations: list[AcknowledgedViolation] = Field(default_factory=list)
    require_fixes: list[RequiredFix] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    recommendations: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class AcknowledgmentContext(BaseModel):
    """Context information for acknowledgment evaluation in LangGraph workflow."""

    acknowledgment_reason: str
    commenter: str
    pr_data: dict[str, Any]
    violations: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    result: dict[str, Any] | None = None
    error: str | None = None
