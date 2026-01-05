#!/usr/bin/env python3
"""
Tests for condition logic with AND/OR/NOT operators.

This test suite verifies that:
1. Simple conditions work correctly
2. AND operator works (all conditions must pass)
3. OR operator works (at least one condition must pass)
4. NOT operator works (negates condition)
5. Nested conditions work correctly
6. Edge cases are handled properly

Can be run in two ways:
1. As pytest test: pytest tests/feedback/test_condition_logic.py -v
2. As standalone verification: python3 tests/feedback/test_condition_logic.py
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add project root to path for imports when running directly
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestConditionExpression:
    """Test ConditionExpression model."""

    def test_simple_condition_creation(self):
        """Test creating a simple condition expression."""
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.models import RuleCondition

        condition = RuleCondition(type="author_team_is", parameters={"team": "devops"})
        expr = ConditionExpression(condition=condition)

        assert expr.operator is None
        assert expr.condition == condition
        assert expr.conditions == []

    def test_and_condition_creation(self):
        """Test creating an AND condition expression."""
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.models import RuleCondition

        cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
        cond2 = RuleCondition(type="files_match_pattern", parameters={"pattern": "*.py"})
        expr1 = ConditionExpression(condition=cond1)
        expr2 = ConditionExpression(condition=cond2)

        and_expr = ConditionExpression(operator="AND", conditions=[expr1, expr2])

        assert and_expr.operator == "AND"
        assert len(and_expr.conditions) == 2

    def test_or_condition_creation(self):
        """Test creating an OR condition expression."""
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.models import RuleCondition

        cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
        cond2 = RuleCondition(type="is_weekend", parameters={})
        expr1 = ConditionExpression(condition=cond1)
        expr2 = ConditionExpression(condition=cond2)

        or_expr = ConditionExpression(operator="OR", conditions=[expr1, expr2])

        assert or_expr.operator == "OR"
        assert len(or_expr.conditions) == 2

    def test_not_condition_creation(self):
        """Test creating a NOT condition expression."""
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.models import RuleCondition

        condition = RuleCondition(type="is_weekend", parameters={})
        not_expr = ConditionExpression(operator="NOT", condition=condition)

        assert not_expr.operator == "NOT"
        assert not_expr.condition == condition

    def test_from_dict_simple(self):
        """Test creating expression from dictionary (simple condition)."""
        from src.rules.condition_evaluator import ConditionExpression

        data = {"type": "author_team_is", "parameters": {"team": "devops"}}
        expr = ConditionExpression.from_dict(data)

        assert expr.operator is None
        assert expr.condition.type == "author_team_is"
        assert expr.condition.parameters == {"team": "devops"}

    def test_from_dict_and(self):
        """Test creating expression from dictionary (AND operator)."""
        from src.rules.condition_evaluator import ConditionExpression

        data = {
            "operator": "AND",
            "conditions": [
                {"type": "author_team_is", "parameters": {"team": "devops"}},
                {"type": "files_match_pattern", "parameters": {"pattern": "*.py"}},
            ],
        }
        expr = ConditionExpression.from_dict(data)

        assert expr.operator == "AND"
        assert len(expr.conditions) == 2

    def test_from_dict_nested(self):
        """Test creating nested expression from dictionary."""
        from src.rules.condition_evaluator import ConditionExpression

        data = {
            "operator": "OR",
            "conditions": [
                {
                    "operator": "AND",
                    "conditions": [
                        {"type": "author_team_is", "parameters": {"team": "security"}},
                        {"type": "files_match_pattern", "parameters": {"pattern": "**/auth/**"}},
                    ],
                },
                {
                    "operator": "AND",
                    "conditions": [
                        {"type": "author_team_is", "parameters": {"team": "devops"}},
                        {"type": "is_weekend", "parameters": {}},
                    ],
                },
            ],
        }
        expr = ConditionExpression.from_dict(data)

        assert expr.operator == "OR"
        assert len(expr.conditions) == 2
        assert expr.conditions[0].operator == "AND"
        assert expr.conditions[1].operator == "AND"

    def test_to_dict_simple(self):
        """Test converting simple expression to dictionary."""
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.models import RuleCondition

        condition = RuleCondition(type="author_team_is", parameters={"team": "devops"})
        expr = ConditionExpression(condition=condition)
        data = expr.to_dict()

        assert data["type"] == "author_team_is"
        assert data["parameters"] == {"team": "devops"}


class TestConditionEvaluator:
    """Test ConditionEvaluator functionality."""

    @pytest.mark.asyncio
    async def test_evaluate_simple_condition(self):
        """Test evaluating a simple condition."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validator
        mock_validator = AsyncMock()
        mock_validator.validate = AsyncMock(return_value=True)

        with patch("src.rules.condition_evaluator.VALIDATOR_REGISTRY", {"author_team_is": mock_validator}):
            evaluator = ConditionEvaluator()
            condition = RuleCondition(type="author_team_is", parameters={"team": "devops"})
            expr = ConditionExpression(condition=condition)

            event_data = {"sender": {"login": "devops-user"}}
            result, metadata = await evaluator.evaluate(expr, event_data)

            assert result is True
            assert metadata["condition_type"] == "author_team_is"
            mock_validator.validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_and_condition_all_pass(self):
        """Test AND condition where all conditions pass."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validators
        mock_validator1 = AsyncMock()
        mock_validator1.validate = AsyncMock(return_value=True)
        mock_validator2 = AsyncMock()
        mock_validator2.validate = AsyncMock(return_value=True)

        with patch(
            "src.rules.condition_evaluator.VALIDATOR_REGISTRY",
            {"author_team_is": mock_validator1, "files_match_pattern": mock_validator2},
        ):
            evaluator = ConditionEvaluator()
            cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
            cond2 = RuleCondition(type="files_match_pattern", parameters={"pattern": "*.py"})
            expr1 = ConditionExpression(condition=cond1)
            expr2 = ConditionExpression(condition=cond2)
            and_expr = ConditionExpression(operator="AND", conditions=[expr1, expr2])

            event_data = {}
            result, metadata = await evaluator.evaluate(and_expr, event_data)

            assert result is True
            assert metadata["operator"] == "AND"
            assert all(metadata["results"])

    @pytest.mark.asyncio
    async def test_evaluate_and_condition_one_fails(self):
        """Test AND condition where one condition fails."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validators - one passes, one fails
        mock_validator1 = AsyncMock()
        mock_validator1.validate = AsyncMock(return_value=True)
        mock_validator2 = AsyncMock()
        mock_validator2.validate = AsyncMock(return_value=False)

        with patch(
            "src.rules.condition_evaluator.VALIDATOR_REGISTRY",
            {"author_team_is": mock_validator1, "files_match_pattern": mock_validator2},
        ):
            evaluator = ConditionEvaluator()
            cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
            cond2 = RuleCondition(type="files_match_pattern", parameters={"pattern": "*.py"})
            expr1 = ConditionExpression(condition=cond1)
            expr2 = ConditionExpression(condition=cond2)
            and_expr = ConditionExpression(operator="AND", conditions=[expr1, expr2])

            event_data = {}
            result, metadata = await evaluator.evaluate(and_expr, event_data)

            assert result is False
            assert metadata["operator"] == "AND"
            assert not all(metadata["results"])

    @pytest.mark.asyncio
    async def test_evaluate_or_condition_one_passes(self):
        """Test OR condition where one condition passes."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validators - one passes, one fails
        mock_validator1 = AsyncMock()
        mock_validator1.validate = AsyncMock(return_value=True)
        mock_validator2 = AsyncMock()
        mock_validator2.validate = AsyncMock(return_value=False)

        with patch(
            "src.rules.condition_evaluator.VALIDATOR_REGISTRY",
            {"author_team_is": mock_validator1, "is_weekend": mock_validator2},
        ):
            evaluator = ConditionEvaluator()
            cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
            cond2 = RuleCondition(type="is_weekend", parameters={})
            expr1 = ConditionExpression(condition=cond1)
            expr2 = ConditionExpression(condition=cond2)
            or_expr = ConditionExpression(operator="OR", conditions=[expr1, expr2])

            event_data = {}
            result, metadata = await evaluator.evaluate(or_expr, event_data)

            assert result is True
            assert metadata["operator"] == "OR"
            assert any(metadata["results"])

    @pytest.mark.asyncio
    async def test_evaluate_or_condition_all_fail(self):
        """Test OR condition where all conditions fail."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validators - both fail
        mock_validator1 = AsyncMock()
        mock_validator1.validate = AsyncMock(return_value=False)
        mock_validator2 = AsyncMock()
        mock_validator2.validate = AsyncMock(return_value=False)

        with patch(
            "src.rules.condition_evaluator.VALIDATOR_REGISTRY",
            {"author_team_is": mock_validator1, "is_weekend": mock_validator2},
        ):
            evaluator = ConditionEvaluator()
            cond1 = RuleCondition(type="author_team_is", parameters={"team": "devops"})
            cond2 = RuleCondition(type="is_weekend", parameters={})
            expr1 = ConditionExpression(condition=cond1)
            expr2 = ConditionExpression(condition=cond2)
            or_expr = ConditionExpression(operator="OR", conditions=[expr1, expr2])

            event_data = {}
            result, metadata = await evaluator.evaluate(or_expr, event_data)

            assert result is False
            assert metadata["operator"] == "OR"
            assert not any(metadata["results"])

    @pytest.mark.asyncio
    async def test_evaluate_not_condition(self):
        """Test NOT condition (negation)."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validator returns True
        mock_validator = AsyncMock()
        mock_validator.validate = AsyncMock(return_value=True)

        with patch("src.rules.condition_evaluator.VALIDATOR_REGISTRY", {"is_weekend": mock_validator}):
            evaluator = ConditionEvaluator()
            condition = RuleCondition(type="is_weekend", parameters={})
            not_expr = ConditionExpression(operator="NOT", condition=condition)

            event_data = {}
            result, metadata = await evaluator.evaluate(not_expr, event_data)

            # NOT True = False
            assert result is False
            assert metadata["operator"] == "NOT"
            assert metadata["negated"] is True
            assert metadata["original_result"] is True

    @pytest.mark.asyncio
    async def test_evaluate_nested_conditions(self):
        """Test nested condition expressions."""
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        # Mock validators
        mock_validators = {
            "author_team_is": AsyncMock(),
            "files_match_pattern": AsyncMock(),
            "is_weekend": AsyncMock(),
        }
        mock_validators["author_team_is"].validate = AsyncMock(return_value=True)
        mock_validators["files_match_pattern"].validate = AsyncMock(return_value=True)
        mock_validators["is_weekend"].validate = AsyncMock(return_value=False)

        with patch("src.rules.condition_evaluator.VALIDATOR_REGISTRY", mock_validators):
            evaluator = ConditionEvaluator()

            # (author_team_is AND files_match_pattern) OR is_weekend
            cond1 = RuleCondition(type="author_team_is", parameters={"team": "security"})
            cond2 = RuleCondition(type="files_match_pattern", parameters={"pattern": "**/auth/**"})
            cond3 = RuleCondition(type="is_weekend", parameters={})

            expr1 = ConditionExpression(condition=cond1)
            expr2 = ConditionExpression(condition=cond2)
            expr3 = ConditionExpression(condition=cond3)

            and_expr = ConditionExpression(operator="AND", conditions=[expr1, expr2])
            or_expr = ConditionExpression(operator="OR", conditions=[and_expr, expr3])

            event_data = {}
            result, metadata = await evaluator.evaluate(or_expr, event_data)

            # (True AND True) OR False = True OR False = True
            assert result is True
            assert metadata["operator"] == "OR"

    @pytest.mark.asyncio
    async def test_evaluate_legacy_conditions(self):
        """Test evaluating legacy conditions (list of RuleCondition)."""
        from src.rules.condition_evaluator import ConditionEvaluator
        from src.rules.models import RuleCondition

        # Mock validators
        mock_validator1 = AsyncMock()
        mock_validator1.validate = AsyncMock(return_value=True)
        mock_validator2 = AsyncMock()
        mock_validator2.validate = AsyncMock(return_value=True)

        with patch(
            "src.rules.condition_evaluator.VALIDATOR_REGISTRY",
            {"author_team_is": mock_validator1, "files_match_pattern": mock_validator2},
        ):
            evaluator = ConditionEvaluator()
            conditions = [
                RuleCondition(type="author_team_is", parameters={"team": "devops"}),
                RuleCondition(type="files_match_pattern", parameters={"pattern": "*.py"}),
            ]

            event_data = {}
            result, metadata = await evaluator.evaluate_rule_conditions(conditions, event_data)

            assert result is True
            assert metadata["format"] == "legacy"
            assert len(metadata["results"]) == 2


class TestRuleConditionEvaluation:
    """Test rule condition evaluation integration."""

    @pytest.mark.asyncio
    async def test_evaluate_rule_with_condition_expression(self):
        """Test evaluating a rule with condition expression."""
        from src.core.models import EventType
        from src.rules.condition_evaluator import ConditionExpression
        from src.rules.evaluator import evaluate_rule_conditions
        from src.rules.models import Rule, RuleSeverity

        # Mock validator
        mock_validator = AsyncMock()
        mock_validator.validate = AsyncMock(return_value=True)

        with patch("src.rules.condition_evaluator.VALIDATOR_REGISTRY", {"author_team_is": mock_validator}):
            condition = ConditionExpression.from_dict({"type": "author_team_is", "parameters": {"team": "devops"}})

            rule = Rule(
                description="Test rule",
                enabled=True,
                severity=RuleSeverity.HIGH,
                event_types=[EventType.PULL_REQUEST],
                condition=condition,
            )

            event_data = {"sender": {"login": "devops-user"}}
            result, metadata = await evaluate_rule_conditions(rule, event_data)

            assert result is True
            assert metadata["format"] == "expression"

    @pytest.mark.asyncio
    async def test_evaluate_rule_with_legacy_conditions(self):
        """Test evaluating a rule with legacy conditions."""
        from src.core.models import EventType
        from src.rules.evaluator import evaluate_rule_conditions
        from src.rules.models import Rule, RuleCondition, RuleSeverity

        # Mock validators
        mock_validator = AsyncMock()
        mock_validator.validate = AsyncMock(return_value=True)

        with patch("src.rules.condition_evaluator.VALIDATOR_REGISTRY", {"author_team_is": mock_validator}):
            rule = Rule(
                description="Test rule",
                enabled=True,
                severity=RuleSeverity.HIGH,
                event_types=[EventType.PULL_REQUEST],
                conditions=[
                    RuleCondition(type="author_team_is", parameters={"team": "devops"}),
                ],
            )

            event_data = {"sender": {"login": "devops-user"}}
            result, metadata = await evaluate_rule_conditions(rule, event_data)

            assert result is True
            assert metadata["format"] == "legacy"

    @pytest.mark.asyncio
    async def test_evaluate_rule_without_conditions(self):
        """Test evaluating a rule without conditions."""
        from src.core.models import EventType
        from src.rules.evaluator import evaluate_rule_conditions
        from src.rules.models import Rule, RuleSeverity

        rule = Rule(
            description="Test rule",
            enabled=True,
            severity=RuleSeverity.HIGH,
            event_types=[EventType.PULL_REQUEST],
        )

        event_data = {}
        result, metadata = await evaluate_rule_conditions(rule, event_data)

        assert result is True
        assert metadata["format"] == "none"


def run_standalone_verification():
    """Run verification checks that don't require pytest."""
    print("=" * 60)
    print("Condition Logic Verification")
    print("=" * 60)
    print()

    all_passed = True

    # Test 1: ConditionExpression exists
    print("1. Checking ConditionExpression exists...")
    try:
        from src.rules.condition_evaluator import ConditionEvaluator, ConditionExpression
        from src.rules.models import RuleCondition

        condition = RuleCondition(type="author_team_is", parameters={"team": "devops"})
        expr = ConditionExpression(condition=condition)
        print("   ✅ ConditionExpression created successfully")
    except Exception as e:
        print(f"   ❌ Failed to import ConditionExpression: {e}")
        all_passed = False

    # Test 2: ConditionEvaluator exists
    print()
    print("2. Checking ConditionEvaluator exists...")
    try:
        from src.rules.condition_evaluator import ConditionEvaluator

        _evaluator = ConditionEvaluator()
        print("   ✅ ConditionEvaluator created successfully")
    except Exception as e:
        print(f"   ❌ Failed to import ConditionEvaluator: {e}")
        all_passed = False

    # Test 3: Rule model supports condition
    print()
    print("3. Checking Rule model supports condition field...")
    try:
        from src.rules.models import Rule

        # Check if Rule has condition field
        rule_fields = Rule.model_fields.keys()
        if "condition" in rule_fields:
            print("   ✅ Rule model has 'condition' field")
        else:
            print("   ❌ Rule model missing 'condition' field")
            all_passed = False
    except Exception as e:
        print(f"   ❌ Failed to check Rule model: {e}")
        all_passed = False

    # Test 4: from_dict works
    print()
    print("4. Checking ConditionExpression.from_dict...")
    try:
        from src.rules.condition_evaluator import ConditionExpression

        data = {
            "operator": "AND",
            "conditions": [
                {"type": "author_team_is", "parameters": {"team": "devops"}},
                {"type": "files_match_pattern", "parameters": {"pattern": "*.py"}},
            ],
        }
        expr = ConditionExpression.from_dict(data)
        assert expr.operator == "AND"
        assert len(expr.conditions) == 2
        print("   ✅ from_dict works correctly")
    except Exception as e:
        print(f"   ❌ from_dict test failed: {e}")
        all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("✅ All verification checks passed!")
    else:
        print("❌ Some checks failed")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # Run standalone verification when executed directly
    success = run_standalone_verification()
    sys.exit(0 if success else 1)
