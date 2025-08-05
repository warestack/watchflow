"""
Data models for the Rule Supervisor Agent.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentTask(BaseModel):
    """Represents a task assigned to a specific agent."""

    agent_name: str = Field(description="Name of the agent to execute the task")
    task_type: str = Field(description="Type of task (feasibility, evaluation, acknowledgment, etc.)")
    parameters: dict[str, Any] = Field(description="Parameters for the task", default_factory=dict)
    priority: int = Field(description="Task priority (higher = more important)", default=1)
    timeout: float = Field(description="Timeout in seconds", default=30.0)


class SupervisorAgentResult(BaseModel):
    """Result from an individual agent execution within supervisor context."""

    success: bool = Field(description="Whether the task was successful")
    message: str = Field(description="Result message or error description")
    data: dict[str, Any] = Field(description="The actual result data", default_factory=dict)
    metadata: dict[str, Any] = Field(description="Additional metadata", default_factory=dict)


class CoordinationResult(BaseModel):
    """Result from coordinating multiple agents."""

    overall_success: bool = Field(description="Whether the overall coordination was successful")
    summary: str = Field(description="Summary of the coordination result")
    agent_results: list[SupervisorAgentResult] = Field(description="Results from all agents", default_factory=list)
    conflicts: list[str] = Field(description="Conflicts detected between agents", default_factory=list)
    confidence_score: float = Field(description="Confidence in the final decision", ge=0.0, le=1.0, default=0.0)
    reasoning: list[str] = Field(description="Step-by-step reasoning for the final decision", default_factory=list)


class SupervisorState(BaseModel):
    """State for the supervisor coordination workflow."""

    # Input
    task_description: str = Field(description="Description of the overall task")
    event_type: str = Field(description="Type of GitHub event being processed")
    event_data: dict[str, Any] = Field(description="GitHub event data", default_factory=dict)
    rules: list[dict[str, Any]] = Field(description="Rules to evaluate", default_factory=list)

    # Coordination
    agent_tasks: list[AgentTask] = Field(description="Tasks to be executed by agents", default_factory=list)
    agent_results: list[SupervisorAgentResult] = Field(
        description="Results from agent executions", default_factory=list
    )

    # Output
    coordination_result: CoordinationResult | None = Field(description="Final coordination result", default=None)

    # Metadata
    start_time: datetime | None = Field(description="When coordination started", default=None)
    end_time: datetime | None = Field(description="When coordination ended", default=None)
    errors: list[str] = Field(description="Any errors that occurred", default_factory=list)
