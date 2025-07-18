import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.rules.validators import VALIDATOR_REGISTRY

from .models import EngineState, RuleEvaluationResult, RuleViolation
from .nodes import smart_rule_evaluation, validate_violations

logger = logging.getLogger(__name__)


class RuleEngineAgent(BaseAgent):
    """
    Hybrid agent that combines LLM flexibility with validator speed.

    Strategy:
    1. Use LLM to understand and filter rules based on event type
    2. For common rules (PR approvals, title patterns, etc.) - use fast validators
    3. For complex/custom rules - use LLM reasoning
    4. This gives 80% speed/cost savings while maintaining 100% flexibility
    """

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        logger.info("🔧 Hybrid Engine agent initializing...")
        logger.info(f"🔧 Available validators: {list(VALIDATOR_REGISTRY.keys())}")
        logger.info(f"🔧 Agent type: {type(self)}")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for hybrid rule evaluation."""
        workflow = StateGraph(EngineState)

        # Add nodes
        workflow.add_node("smart_rule_evaluation", smart_rule_evaluation)
        workflow.add_node("validate_violations", validate_violations)

        # Add edges
        workflow.add_edge(START, "smart_rule_evaluation")
        workflow.add_edge("smart_rule_evaluation", "validate_violations")
        workflow.add_edge("validate_violations", END)

        return workflow.compile()

    async def execute(self, event_type: str, event_data: dict[str, Any], rules: list[dict[str, Any]]) -> AgentResult:
        """
        Hybrid rule evaluation: LLM filtering + validator tools + LLM reasoning.
        """
        try:
            logger.info(f"🔧 Hybrid Engine agent starting evaluation for {event_type} with {len(rules)} rules")

            # Prepare initial state
            initial_state = EngineState(
                event_type=event_type,
                event_data=event_data,
                rules=rules,
                violations=[],
                evaluation_context={},
                analysis_steps=[],
            )

            logger.info("🔧 Hybrid Engine agent initial state prepared")

            # Run the hybrid graph
            logger.info("🔧 Hybrid Engine agent running LangGraph workflow")
            result = await self.graph.ainvoke(initial_state)

            logger.info(
                f"🔧 Hybrid Engine agent LangGraph result: {result}",
            )

            # Extract violations from result
            violations = result.get("violations", []) if hasattr(result, "get") else []

            logger.info(f"🔧 Hybrid Engine agent extracted {len(violations)} violations")

            # Convert violations to RuleViolation objects
            rule_violations = []
            for violation in violations:
                rule_violation = RuleViolation(
                    rule_id=violation.get("rule_id", "unknown"),
                    rule_name=violation.get("rule_name", "Unknown Rule"),
                    severity=violation.get("severity", "medium"),
                    message=violation.get("message", "Rule violation detected"),
                    details=violation.get("details", {}),
                    how_to_fix=violation.get("how_to_fix", ""),
                    docs_url=violation.get("docs_url", ""),
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
                evaluation_time_ms=result.get("evaluation_context", {}).get("evaluation_time_ms", 0),
            )

            logger.info("🔧 Hybrid Engine agent evaluation completed successfully")

            return AgentResult(
                success=len(violations) == 0,
                message=f"Hybrid evaluation completed: {len(violations)} violations found",
                data={"evaluation_result": evaluation_result},
            )
        except Exception as e:
            logger.error(f"🔧 Error in hybrid engine agent rule evaluation: {e}")
            return AgentResult(success=False, message=f"Hybrid rule evaluation failed: {str(e)}", data={})

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
