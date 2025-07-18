"""
Data models for the Rule Engine Agent.
"""

from typing import Any

from pydantic import BaseModel, Field


class RuleViolation(BaseModel):
    """Represents a violation of a specific rule."""

    rule_id: str
    rule_name: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    how_to_fix: str | None = None
    docs_url: str | None = None


class RuleEvaluationResult(BaseModel):
    """The result of evaluating all rules against an event."""

    event_type: str
    repo_full_name: str
    violations: list[RuleViolation] = Field(default_factory=list)
    total_rules_evaluated: int = 0
    rules_triggered: int = 0
    total_rules: int = 0
    evaluation_time_ms: float | None = None


class EngineState(BaseModel):
    """State for the rule engine workflow."""

    event_type: str
    event_data: dict[str, Any]
    rules: list[dict[str, Any]]
    violations: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_context: dict[str, Any] = Field(default_factory=dict)
    analysis_steps: list[str] = Field(default_factory=list)
