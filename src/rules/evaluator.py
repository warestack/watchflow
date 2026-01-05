"""
Rule evaluation utilities including condition expression evaluation.
"""

import logging
from typing import Any

from src.rules.condition_evaluator import ConditionEvaluator
from src.rules.models import Rule

logger = logging.getLogger(__name__)


async def evaluate_rule_conditions(rule: Rule, event_data: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate rule conditions (both legacy and new format).

    Args:
        rule: Rule object to evaluate
        event_data: Event data to evaluate against

    Returns:
        Tuple of (condition_passed: bool, metadata: dict)
        - condition_passed: True if all conditions pass, False otherwise
        - metadata: Evaluation details
    """
    evaluator = ConditionEvaluator()

    # Check if rule has new condition expression format
    if rule.condition is not None:
        logger.debug(f"Evaluating condition expression for rule: {rule.description}")
        result, metadata = await evaluator.evaluate(rule.condition, event_data)
        metadata["format"] = "expression"
        return result, metadata

    # Check if rule has legacy conditions
    if rule.conditions:
        logger.debug(f"Evaluating legacy conditions for rule: {rule.description}")
        result, metadata = await evaluator.evaluate_rule_conditions(rule.conditions, event_data)
        metadata["format"] = "legacy"
        return result, metadata

    # No conditions = rule passes (no restrictions)
    logger.debug(f"No conditions for rule: {rule.description}")
    return True, {"message": "No conditions to evaluate", "format": "none"}
