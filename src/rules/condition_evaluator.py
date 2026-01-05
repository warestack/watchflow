"""
Condition evaluator for complex boolean logic (AND/OR/NOT).

Supports nested conditions with AND, OR, and NOT operators.
"""

import logging
from typing import Any

from src.rules.models import RuleCondition
from src.rules.validators import VALIDATOR_REGISTRY

logger = logging.getLogger(__name__)


class ConditionExpression:
    """
    Represents a condition expression with logical operators.

    Supports:
    - Simple conditions: single condition evaluation
    - AND: all conditions must be true
    - OR: at least one condition must be true
    - NOT: negates a condition
    - Nested: conditions can be nested arbitrarily
    """

    def __init__(
        self,
        operator: str | None = None,
        condition: RuleCondition | None = None,
        conditions: list["ConditionExpression"] | None = None,
    ):
        """
        Initialize a condition expression.

        Args:
            operator: Logical operator ("AND", "OR", "NOT", or None for simple condition)
            condition: Single condition (for simple conditions or NOT)
            conditions: List of nested conditions (for AND/OR)
        """
        self.operator = operator.upper() if operator else None
        self.condition = condition
        self.conditions = conditions or []

        # Validate structure
        if self.operator == "NOT":
            if not self.condition:
                raise ValueError("NOT operator requires a single condition")
        elif self.operator in ("AND", "OR"):
            if not self.conditions:
                raise ValueError(f"{self.operator} operator requires at least one condition")
        elif self.operator is None:
            if not self.condition:
                raise ValueError("Simple condition requires a condition")
        else:
            raise ValueError(f"Unknown operator: {self.operator}")

    def to_dict(self) -> dict[str, Any]:
        """Convert expression to dictionary format."""
        if self.operator is None:
            # Simple condition
            return {
                "type": self.condition.type,
                "parameters": self.condition.parameters,
            }
        elif self.operator == "NOT":
            return {
                "operator": "NOT",
                "condition": {
                    "type": self.condition.type,
                    "parameters": self.condition.parameters,
                },
            }
        else:
            return {
                "operator": self.operator,
                "conditions": [cond.to_dict() for cond in self.conditions],
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConditionExpression":
        """
        Create ConditionExpression from dictionary.

        Supports formats:
        - Simple: {"type": "author_team_is", "parameters": {"team": "devops"}}
        - NOT: {"operator": "NOT", "condition": {...}}
        - AND/OR: {"operator": "AND", "conditions": [...]}
        """
        if "operator" in data:
            operator = data["operator"].upper()
            if operator == "NOT":
                condition_data = data["condition"]
                condition = RuleCondition(type=condition_data["type"], parameters=condition_data.get("parameters", {}))
                return cls(operator="NOT", condition=condition)
            else:
                # AND or OR
                nested_conditions = [cls.from_dict(cond) for cond in data["conditions"]]
                return cls(operator=operator, conditions=nested_conditions)
        else:
            # Simple condition
            condition = RuleCondition(type=data["type"], parameters=data.get("parameters", {}))
            return cls(condition=condition)


class ConditionEvaluator:
    """
    Evaluates condition expressions against event data.

    Handles:
    - Simple conditions using validators
    - AND/OR/NOT logical operators
    - Nested condition expressions
    """

    def __init__(self):
        """Initialize the condition evaluator."""
        self.validator_registry = VALIDATOR_REGISTRY

    async def evaluate(
        self, expression: ConditionExpression, event_data: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """
        Evaluate a condition expression against event data.

        Args:
            expression: Condition expression to evaluate
            event_data: Event data to evaluate against

        Returns:
            Tuple of (result: bool, metadata: dict) where metadata contains evaluation details
        """
        metadata = {
            "operator": expression.operator,
            "evaluated_at": "condition_evaluator",
        }

        try:
            if expression.operator is None:
                # Simple condition
                result = await self._evaluate_simple_condition(expression.condition, event_data)
                metadata["condition_type"] = expression.condition.type
                metadata["result"] = result
                return result, metadata

            elif expression.operator == "NOT":
                # Negate the condition
                result, sub_metadata = await self.evaluate(
                    ConditionExpression(condition=expression.condition), event_data
                )
                negated_result = not result
                metadata["negated"] = True
                metadata["original_result"] = result
                metadata["sub_condition"] = sub_metadata
                return negated_result, metadata

            elif expression.operator == "AND":
                # All conditions must be true
                results = []
                sub_metadata_list = []
                for sub_expr in expression.conditions:
                    sub_result, sub_metadata = await self.evaluate(sub_expr, event_data)
                    results.append(sub_result)
                    sub_metadata_list.append(sub_metadata)
                    # Short-circuit: if any is False, AND is False
                    if not sub_result:
                        break

                result = all(results)
                metadata["sub_conditions"] = sub_metadata_list
                metadata["results"] = results
                metadata["result"] = result
                return result, metadata

            elif expression.operator == "OR":
                # At least one condition must be true
                results = []
                sub_metadata_list = []
                for sub_expr in expression.conditions:
                    sub_result, sub_metadata = await self.evaluate(sub_expr, event_data)
                    results.append(sub_result)
                    sub_metadata_list.append(sub_metadata)
                    # Short-circuit: if any is True, OR is True
                    if sub_result:
                        break

                result = any(results)
                metadata["sub_conditions"] = sub_metadata_list
                metadata["results"] = results
                metadata["result"] = result
                return result, metadata

            else:
                raise ValueError(f"Unknown operator: {expression.operator}")

        except Exception as e:
            logger.error(f"Error evaluating condition expression: {e}")
            metadata["error"] = str(e)
            # Fail closed: if we can't evaluate, assume violation
            return False, metadata

    async def _evaluate_simple_condition(self, condition: RuleCondition, event_data: dict[str, Any]) -> bool:
        """
        Evaluate a simple condition using a validator.

        Args:
            condition: Rule condition to evaluate
            event_data: Event data to evaluate against

        Returns:
            True if condition is met, False otherwise
        """
        validator = self.validator_registry.get(condition.type)
        if not validator:
            logger.warning(f"Unknown condition type: {condition.type}")
            return False

        try:
            result = await validator.validate(condition.parameters, event_data)
            logger.debug(f"Condition {condition.type} evaluated: {result} (parameters: {condition.parameters})")
            return result
        except Exception as e:
            logger.error(f"Error evaluating condition {condition.type}: {e}")
            return False

    async def evaluate_rule_conditions(
        self,
        conditions: list[ConditionExpression] | list[RuleCondition] | None,
        event_data: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """
        Evaluate rule conditions (backward compatible).

        If conditions is a list of RuleCondition (old format), treats them as AND.
        If conditions is a list of ConditionExpression (new format), evaluates them.

        Args:
            conditions: List of conditions or condition expressions
            event_data: Event data to evaluate against

        Returns:
            Tuple of (result: bool, metadata: dict)
        """
        if not conditions:
            # No conditions = rule passes
            return True, {"message": "No conditions to evaluate"}

        # Check if it's old format (list of RuleCondition)
        if conditions and isinstance(conditions[0], RuleCondition):
            # Old format: treat as AND of all conditions
            logger.debug("Using legacy condition format (treating as AND)")
            results = []
            for condition in conditions:
                result = await self._evaluate_simple_condition(condition, event_data)
                results.append(result)
                if not result:
                    break  # Short-circuit AND

            all_passed = all(results)
            return all_passed, {
                "format": "legacy",
                "results": results,
                "condition_count": len(conditions),
            }

        # New format: list of ConditionExpression
        if len(conditions) == 1:
            # Single condition expression
            return await self.evaluate(conditions[0], event_data)
        else:
            # Multiple condition expressions - treat as AND by default
            logger.debug(f"Evaluating {len(conditions)} condition expressions (default: AND)")
            results = []
            metadata_list = []
            for expr in conditions:
                result, metadata = await self.evaluate(expr, event_data)
                results.append(result)
                metadata_list.append(metadata)
                if not result:
                    break  # Short-circuit AND

            all_passed = all(results)
            return all_passed, {
                "format": "expression",
                "default_operator": "AND",
                "results": results,
                "sub_conditions": metadata_list,
            }
