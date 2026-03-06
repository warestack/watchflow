"""
Data models for the Rule Extractor Agent.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractorOutput(BaseModel):
    """Structured output: list of rule-like statements extracted from markdown plus metadata."""

    model_config = ConfigDict(extra="forbid")

    statements: list[str] = Field(
        description="List of distinct rule-like statements extracted from the document. Each item is a single, clear sentence or phrase describing one rule or guideline.",
        default_factory=list,
    )
    decision: str = Field(
        default="extracted",
        description="Outcome of extraction (e.g. 'extracted', 'none', 'partial').",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for the extraction (0.0 to 1.0).",
    )
    reasoning: str = Field(
        default="",
        description="Brief reasoning for the extraction outcome.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Optional recommendations for improving the source or extraction.",
    )
    strategy_used: str = Field(
        default="",
        description="Strategy or approach used for extraction.",
    )

    @field_validator("statements", mode="after")
    @classmethod
    def clean_and_dedupe_statements(cls, v: list[str]) -> list[str]:
        """Strip whitespace, drop empty strings, and deduplicate while preserving order."""
        seen: set[str] = set()
        out: list[str] = []
        for s in v:
            if not isinstance(s, str):
                continue
            t = s.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out
