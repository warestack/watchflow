"""
Rule Engine Agent with hybrid validation strategy.

Focuses on rule descriptions and parameters, using fast validators with LLM reasoning as fallback.
"""

import logging
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.agents.engine_agent.models import (
    EngineState,
    RuleDescription,
    RuleEvaluationResult,
    RuleViolation,
    ValidationStrategy,
    ValidatorDescription,
)
from src.agents.engine_agent.nodes import (
    analyze_rule_descriptions,
    execute_llm_fallback,
    execute_validator_evaluation,
    select_validation_strategy,
    validate_violations,
)
from src.rules.validators import get_validator_descriptions

logger = logging.getLogger(__name__)


class RuleEngineAgent(BaseAgent):
    """
    Hybrid rule engine that prioritizes fast validators with LLM reasoning as fallback.

    Strategy:
    1. Analyze rule descriptions and parameters
    2. Use LLM to select appropriate validation strategy based on available validators
    3. Execute fast validators for common rules (PR approvals, title patterns, etc.)
    4. Use LLM reasoning for complex/custom rules or as fallback
    5. This provides 80% speed/cost savings while maintaining 100% flexibility
    """

    def __init__(self, max_retries: int = 3, timeout: float = 60.0):
        super().__init__(max_retries=max_retries)
        self.timeout = timeout

        logger.info("🔧 Rule Engine agent initializing...")
        logger.info(f"🔧 Available validators: {list(get_validator_descriptions())}")
        logger.info("🔧 Validation strategy: Hybrid (validators + LLM fallback)")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for hybrid rule evaluation."""
        workflow = StateGraph(EngineState)

        # Add nodes
        workflow.add_node("analyze_rule_descriptions", analyze_rule_descriptions)
        workflow.add_node("select_validation_strategy", select_validation_strategy)
        workflow.add_node("execute_validator_evaluation", execute_validator_evaluation)
        workflow.add_node("execute_llm_fallback", execute_llm_fallback)
        workflow.add_node("validate_violations", validate_violations)

        # Add edges
        workflow.add_edge(START, "analyze_rule_descriptions")
        workflow.add_edge("analyze_rule_descriptions", "select_validation_strategy")
        workflow.add_edge("select_validation_strategy", "execute_validator_evaluation")
        workflow.add_edge("execute_validator_evaluation", "execute_llm_fallback")
        workflow.add_edge("execute_llm_fallback", "validate_violations")
        workflow.add_edge("validate_violations", END)

        return workflow.compile()

    async def execute(self, event_type: str, event_data: dict[str, Any], rules: list[dict[str, Any]]) -> AgentResult:
        """
        Hybrid rule evaluation focusing on rule descriptions and parameters.
        Prioritizes fast validators with LLM reasoning as fallback.
        """
        start_time = time.time()

        try:
            logger.info(f"🔧 Rule Engine starting evaluation for {event_type} with {len(rules)} rules")

            # Convert rules to rule descriptions (without id/name dependency)
            rule_descriptions = self._convert_rules_to_descriptions(rules)

            # Get validator descriptions from the validators themselves
            available_validators = self._get_validator_descriptions()

            # Prepare initial state
            initial_state = EngineState(
                event_type=event_type,
                event_data=event_data,
                rules=rules,
                rule_descriptions=rule_descriptions,
                available_validators=available_validators,
                violations=[],
                evaluation_context={},
                analysis_steps=[],
                validator_usage={},
                llm_usage=0,
            )

            logger.info("🔧 Rule Engine initial state prepared")

            # Run the hybrid graph with timeout
            result = await self._execute_with_timeout(self.graph.ainvoke(initial_state), timeout=self.timeout)

            execution_time = time.time() - start_time
            logger.info(f"🔧 Rule Engine evaluation completed in {execution_time:.2f}s")

            # Extract violations from result (EngineState)
            violations = []
            if hasattr(result, "violations"):
                violations = result.violations
            elif isinstance(result, dict) and "violations" in result:
                violations = result["violations"]

            logger.info(f"🔧 Rule Engine extracted {len(violations)} violations from state")

            # Convert violations to RuleViolation objects
            rule_violations = []
            for violation in violations:
                rule_violation = RuleViolation(
                    rule_description=violation.get("rule_description", "Unknown rule"),
                    severity=violation.get("severity", "medium"),
                    message=violation.get("message", "Rule violation detected"),
                    details=violation.get("details", {}),
                    how_to_fix=violation.get("how_to_fix", ""),
                    docs_url=violation.get("docs_url", ""),
                    validation_strategy=violation.get("validation_strategy", ValidationStrategy.VALIDATOR),
                    execution_time_ms=violation.get("execution_time_ms", 0.0),
                )
                rule_violations.append(rule_violation)

            # Create evaluation result
            evaluation_result = RuleEvaluationResult(
                event_type=event_type,
                repo_full_name=event_data.get("repository", {}).get("full_name", "unknown"),
                violations=rule_violations,
                total_rules_evaluated=len(rules),
                rules_triggered=len(rule_violations),
                total_rules=len(rules),
                evaluation_time_ms=execution_time * 1000,
                validator_usage=result.validator_usage if hasattr(result, "validator_usage") else {},
                llm_usage=result.llm_usage if hasattr(result, "llm_usage") else 0,
            )

            logger.info("🔧 Rule Engine evaluation completed successfully")
            logger.info(f"🔧 Validator usage: {evaluation_result.validator_usage}")
            logger.info(f"🔧 LLM usage: {evaluation_result.llm_usage} calls")

            return AgentResult(
                success=len(violations) == 0,
                message=f"Hybrid evaluation completed: {len(violations)} violations found",
                data={"evaluation_result": evaluation_result},
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "validator_usage": evaluation_result.validator_usage,
                    "llm_usage": evaluation_result.llm_usage,
                    "validation_strategy": "hybrid",
                },
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"🔧 Error in Rule Engine evaluation: {e}")
            return AgentResult(
                success=False,
                message=f"Rule Engine evaluation failed: {str(e)}",
                data={},
                metadata={"execution_time_ms": execution_time * 1000, "error_type": type(e).__name__},
            )

    def _convert_rules_to_descriptions(self, rules: list[dict[str, Any]]) -> list[RuleDescription]:
        """Convert rule dictionaries to RuleDescription objects without id/name dependency."""
        rule_descriptions = []

        for rule in rules:
            # Extract rule description from various possible fields
            description = (
                rule.get("description") or rule.get("name") or rule.get("rule_description") or "Rule with parameters"
            )

            rule_description = RuleDescription(
                description=description,
                parameters=rule.get("parameters", {}),
                event_types=rule.get("event_types", []),
                severity=rule.get("severity", "medium"),
                validation_strategy=ValidationStrategy.HYBRID,  # Will be determined by LLM
                validator_name=None,  # Will be selected by LLM
                fallback_to_llm=True,
            )

            rule_descriptions.append(rule_description)

        return rule_descriptions

    def _get_validator_descriptions(self) -> list[ValidatorDescription]:
        """Get validator descriptions from the validators themselves."""
        validator_descriptions = []

        # Get descriptions from validators
        raw_descriptions = get_validator_descriptions()

        for desc in raw_descriptions:
            validator_desc = ValidatorDescription(
                name=desc["name"],
                description=desc["description"],
                parameter_patterns=desc["parameter_patterns"],
                event_types=desc["event_types"],
                examples=desc["examples"],
            )
            validator_descriptions.append(validator_desc)

        return validator_descriptions

    async def evaluate(
        self, event_type: str, rules: list[dict[str, Any]], event_data: dict[str, Any], github_token: str = ""
    ) -> dict[str, Any]:
        """
        Legacy method for backwards compatibility.
        """
        result = await self.execute(event_type, event_data, rules)

        if result.success:
            return {"status": "success", "message": result.message, "violations": []}
        else:
            eval_result = result.data.get("evaluation_result")
            violations = [v.__dict__ for v in eval_result.violations] if eval_result else []

            return {
                "status": "violations_found" if violations else "success",
                "message": result.message,
                "violations": violations,
            }

    async def evaluate_pull_request(self, rules: list[Any], event_data: dict[str, Any]) -> dict[str, Any]:
        """Legacy method for backwards compatibility."""
        logger.warning("evaluate_pull_request is deprecated. Use evaluate() with event_type='pull_request'")
        return await self.evaluate("pull_request", rules, event_data, "")
