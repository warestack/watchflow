"""
Data models for the Rule Feasibility Agent.
"""

from pydantic import BaseModel, Field


class FeasibilityResult(BaseModel):
    """Result of checking if a rule is feasible."""

    is_feasible: bool
    yaml_content: str
    feedback: str
    confidence_score: float | None = None
    rule_type: str | None = None


class FeasibilityState(BaseModel):
    """State for the feasibility evaluation workflow."""

    rule_description: str
    is_feasible: bool = False
    yaml_content: str = ""
    feedback: str = ""
    confidence_score: float = 0.0
    rule_type: str = ""
    analysis_steps: list[str] = Field(default_factory=list)
