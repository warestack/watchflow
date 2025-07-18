import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph

from src.agents.base import AgentResult, BaseAgent
from src.core.config import config

from .models import AcknowledgedViolation, AcknowledgmentEvaluation, RequiredFix
from .prompts import create_evaluation_prompt, get_system_prompt

logger = logging.getLogger(__name__)


class AcknowledgmentAgent(BaseAgent):
    """
    Intelligent agent that evaluates acknowledgment requests based on rule descriptions and context.

    Instead of relying on hardcoded rule names, this agent:
    1. Analyzes rule descriptions to understand what each rule does
    2. Evaluates the acknowledgment reason against the rule's purpose
    3. Makes intelligent decisions about which violations can be acknowledged
    4. Provides detailed reasoning for its decisions
    """

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Override the LLM with acknowledgment-specific settings
        self.llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=2000,  # Different from base class
            temperature=0.1,  # Different from base class
        )
        logger.info(f"🧠 Acknowledgment agent initialized with model: {config.ai.model}")

    def _build_graph(self) -> StateGraph:
        """
        Build a simple LangGraph workflow for acknowledgment evaluation.
        Since this agent is primarily LLM-based, we create a minimal graph.
        """
        from .models import AcknowledgmentContext

        # Create a simple state graph
        workflow = StateGraph(AcknowledgmentContext)

        # Add a single node that does the evaluation
        workflow.add_node("evaluate_acknowledgment", self._evaluate_node)

        # Simple linear flow
        workflow.set_entry_point("evaluate_acknowledgment")
        workflow.set_finish_point("evaluate_acknowledgment")

        return workflow.compile()

    async def _evaluate_node(self, state):
        """Node function for LangGraph workflow."""
        try:
            result = await self.evaluate_acknowledgment(
                acknowledgment_reason=state.acknowledgment_reason,
                violations=state.violations,
                pr_data=state.pr_data,
                commenter=state.commenter,
                rules=state.rules,
            )
            return result
        except Exception as e:
            logger.error(f"🧠 Error in evaluation node: {e}")
            return AgentResult(success=False, message=f"Evaluation failed: {str(e)}", data={"error": str(e)})

    @staticmethod
    def _find_violation_by_rule_name(rule_name: str, violations: list[dict[str, Any]]) -> dict[str, Any]:
        """Find a violation by rule name (fallback when LLM returns rule name instead of rule_id)."""
        for violation in violations:
            if violation.get("rule_name") == rule_name:
                return violation
        return {}

    async def evaluate_acknowledgment(
        self,
        acknowledgment_reason: str,
        violations: list[dict[str, Any]],
        pr_data: dict[str, Any],
        commenter: str,
        rules: list[dict[str, Any]],
    ) -> AgentResult:
        """
        Intelligently evaluate an acknowledgment request based on rule descriptions and context.
        """
        try:
            logger.info(f"🧠 Evaluating acknowledgment request from {commenter}")
            logger.info(f"🧠 Reason: {acknowledgment_reason}")
            logger.info(f"🧠 Violations to evaluate: {len(violations)}")

            # Validate inputs
            if not acknowledgment_reason or not violations:
                return AgentResult(
                    success=False,
                    message="Invalid acknowledgment request: missing reason or violations",
                    data={"error": "Missing required parameters"},
                )

            # Create comprehensive evaluation prompt using the prompts module
            evaluation_prompt = create_evaluation_prompt(acknowledgment_reason, violations, pr_data, commenter, rules)

            # Get LLM evaluation
            messages = [SystemMessage(content=get_system_prompt()), HumanMessage(content=evaluation_prompt)]

            logger.info("🧠 Requesting LLM evaluation...")
            llm_response = await self.llm.ainvoke(messages)

            if not llm_response or not llm_response.content:
                logger.error("🧠 Empty LLM response received")
                return AgentResult(
                    success=False, message="Empty response from LLM", data={"error": "LLM returned empty response"}
                )

            # Parse the response
            try:
                # Clean the response - remove markdown code blocks if present
                content = llm_response.content.strip()
                if content.startswith("```json"):
                    content = content[7:]  # Remove ```json
                if content.startswith("```"):
                    content = content[3:]  # Remove ```
                if content.endswith("```"):
                    content = content[:-3]  # Remove trailing ```

                evaluation_result = json.loads(content.strip())
                logger.info("🧠 Successfully parsed LLM evaluation result")
            except json.JSONDecodeError as e:
                logger.error(f"🧠 Failed to parse LLM response: {e}")
                logger.error(f"🧠 Raw response: {llm_response.content}")
                return AgentResult(
                    success=False,
                    message="Failed to parse acknowledgment evaluation",
                    data={"error": f"LLM response parsing failed: {str(e)}"},
                )

            # Validate the response structure
            if not self._validate_evaluation_result(evaluation_result):
                logger.error("🧠 Invalid evaluation result structure")
                return AgentResult(
                    success=False,
                    message="Invalid acknowledgment evaluation result",
                    data={"error": "Invalid response structure"},
                )

            # Convert to structured data using models
            structured_result = self._convert_to_structured_result(evaluation_result)

            if structured_result is None:
                logger.error("🧠 Structured result is None")
                return AgentResult(
                    success=False,
                    message="Failed to convert evaluation result",
                    data={"error": "Structured result conversion failed"},
                )

            logger.info("🧠 Acknowledgment evaluation completed successfully")
            logger.info(f"🧠 Valid: {structured_result.is_valid}")
            logger.info(f"🧠 Acknowledged violations: {len(structured_result.acknowledgable_violations)}")
            logger.info(f"🧠 Require fixes: {len(structured_result.require_fixes)}")
            logger.info(f"🧠 Confidence: {structured_result.confidence}")

            # Map LLM decisions back to original violations using rule_id or rule_name
            acknowledgable_violations = []
            require_fixes = []

            # Create a mapping of rule_id to original violation
            violation_map = {v.get("rule_id"): v for v in violations}

            # Process acknowledgable violations
            for llm_violation in structured_result.acknowledgable_violations:
                rule_id = llm_violation.rule_id
                original_violation = None

                # Try to find by rule_id first
                if rule_id in violation_map:
                    original_violation = violation_map[rule_id]
                else:
                    # Fallback: try to find by rule_name
                    original_violation = self._find_violation_by_rule_name(rule_id, violations)
                    if original_violation:
                        logger.info(f"🧠 Found violation by rule name: '{rule_id}'")
                    else:
                        logger.warning(f"🧠 LLM returned rule_id '{rule_id}' not found in original violations")

                if original_violation:
                    violation_copy = original_violation.copy()
                    # Add acknowledgment-specific fields
                    violation_copy.update(
                        {
                            "acknowledgment_reason": llm_violation.reason,
                            "risk_level": llm_violation.risk_level,
                            "conditions": llm_violation.conditions,
                        }
                    )
                    acknowledgable_violations.append(violation_copy)

            # Process violations requiring fixes
            for llm_violation in structured_result.require_fixes:
                rule_id = llm_violation.rule_id
                original_violation = None

                # Try to find by rule_id first
                if rule_id in violation_map:
                    original_violation = violation_map[rule_id]
                else:
                    # Fallback: try to find by rule_name
                    original_violation = self._find_violation_by_rule_name(rule_id, violations)
                    if original_violation:
                        logger.info(f"🧠 Found violation by rule name: '{rule_id}'")
                    else:
                        logger.warning(f"🧠 LLM returned rule_id '{rule_id}' not found in original violations")

                if original_violation:
                    violation_copy = original_violation.copy()
                    # Add fix-specific fields
                    violation_copy.update({"fix_reason": llm_violation.reason, "priority": llm_violation.priority})
                    require_fixes.append(violation_copy)

            logger.info("🧠 Intelligent evaluation completed:")
            logger.info(f"    Valid: {structured_result.is_valid}")
            logger.info(f"    Reasoning: {structured_result.reasoning}")
            logger.info(f"    Acknowledged violations: {len(acknowledgable_violations)}")
            logger.info(f"    Require fixes: {len(require_fixes)}")
            logger.info(f"    Confidence: {structured_result.confidence}")

            return AgentResult(
                success=True,
                message=f"Acknowledgment evaluation completed: {structured_result.reasoning}",
                data={
                    "is_valid": structured_result.is_valid,
                    "reasoning": structured_result.reasoning,
                    "acknowledgable_violations": acknowledgable_violations,  # Original violations with acknowledgment context
                    "require_fixes": require_fixes,  # Original violations with fix context
                    "confidence": structured_result.confidence,
                    "recommendations": structured_result.recommendations,
                    "details": structured_result.details,
                },
            )

        except Exception as e:
            logger.error(f"🧠 Error in acknowledgment evaluation: {e}")
            import traceback

            logger.error(f"🧠 Traceback: {traceback.format_exc()}")
            return AgentResult(
                success=False, message=f"Acknowledgment evaluation failed: {str(e)}", data={"error": str(e)}
            )

    def _validate_evaluation_result(self, result: dict[str, Any]) -> bool:
        """Validate that the evaluation result has the required structure."""
        required_fields = ["is_valid", "reasoning", "acknowledgable_violations", "require_fixes"]

        for field in required_fields:
            if field not in result:
                logger.error(f"🧠 Missing required field: {field}")
                return False

        # Validate data types
        if not isinstance(result["is_valid"], bool):
            logger.error("🧠 is_valid must be a boolean")
            return False

        if not isinstance(result["acknowledgable_violations"], list):
            logger.error("🧠 acknowledgable_violations must be a list")
            return False

        if not isinstance(result["require_fixes"], list):
            logger.error("🧠 require_fixes must be a list")
            return False

        return True

    def _convert_to_structured_result(self, raw_result: dict[str, Any]) -> AcknowledgmentEvaluation:
        """Convert raw LLM result to structured data using models."""

        # Add safety checks for None values
        if raw_result is None:
            logger.error("🧠 Raw result is None, creating default evaluation")
            return AcknowledgmentEvaluation(
                is_valid=False,
                reasoning="Failed to parse acknowledgment evaluation",
                acknowledgable_violations=[],
                require_fixes=[],
                confidence=0.0,
            )

        # Convert acknowledgable violations with safety checks
        acknowledgable_violations = []
        for violation in raw_result.get("acknowledgable_violations", []):
            if violation is not None:  # Add None check
                acknowledgable_violations.append(
                    AcknowledgedViolation(
                        rule_id=violation.get("rule_id", "unknown"),
                        rule_name=violation.get("rule_name", "Unknown Rule"),
                        reason=violation.get("reason", "No reason provided"),
                        risk_level=violation.get("risk_level", "medium"),
                        conditions=violation.get("conditions"),
                    )
                )

        # Convert required fixes with safety checks
        require_fixes = []
        for violation in raw_result.get("require_fixes", []):
            if violation is not None:  # Add None check
                require_fixes.append(
                    RequiredFix(
                        rule_id=violation.get("rule_id", "unknown"),
                        rule_name=violation.get("rule_name", "Unknown Rule"),
                        reason=violation.get("reason", "No reason provided"),
                        priority=violation.get("priority", "medium"),
                    )
                )

        return AcknowledgmentEvaluation(
            is_valid=raw_result.get("is_valid", False),
            reasoning=raw_result.get("reasoning", "No reasoning provided"),
            acknowledgable_violations=acknowledgable_violations,
            require_fixes=require_fixes,
            confidence=raw_result.get("confidence", 0.5),
            recommendations=raw_result.get("recommendations", []),
            details=raw_result.get("details", {}),
        )

    async def execute(self, event_type: str, event_data: dict[str, Any], rules: list[dict[str, Any]]) -> AgentResult:
        """
        Legacy method for compatibility - not used for acknowledgment evaluation.
        """
        logger.warning("🧠 execute() method called on AcknowledgmentAgent - this should not happen")
        return AgentResult(success=False, message="AcknowledgmentAgent does not support execute() method", data={})
