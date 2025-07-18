"""
Hybrid Rule Engine Agent Module.

This module provides a hybrid agent that combines LLM flexibility with validator speed
for intelligent rule evaluation.
"""

from .agent import RuleEngineAgent
from .models import EngineState, RuleEvaluationResult, RuleViolation
from .prompts import (
    create_llm_evaluation_prompt,
    create_rule_filtering_prompt,
    create_validator_selection_prompt,
    get_llm_evaluation_system_prompt,
)

__all__ = [
    "RuleEngineAgent",
    "EngineState",
    "RuleEvaluationResult",
    "RuleViolation",
    "create_rule_filtering_prompt",
    "create_llm_evaluation_prompt",
    "get_llm_evaluation_system_prompt",
    "create_validator_selection_prompt",
]
