"""
Data models for the Rule Extractor Agent.
"""

from pydantic import BaseModel, Field


class ExtractorOutput(BaseModel):
    """Structured output: list of rule-like statements extracted from markdown."""

    statements: list[str] = Field(
        description="List of distinct rule-like statements extracted from the document. Each item is a single, clear sentence or phrase describing one rule or guideline.",
        default_factory=list,
    )
