"""
LangGraph nodes for the Rule Engine Agent with hybrid validation strategy.
"""

import asyncio
import json
import logging
import time
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.engine_agent.models import (
    EngineState,
    LLMEvaluationResponse,
    RuleDescription,
    StrategySelectionResponse,
    ValidationStrategy,
)
from src.agents.engine_agent.prompts import (
    create_llm_evaluation_prompt,
    create_validation_strategy_prompt,
    get_llm_evaluation_system_prompt,
)
from src.integrations.providers import get_chat_model
from src.rules.when_evaluator import should_apply_rule

logger = logging.getLogger(__name__)


async def analyze_rule_descriptions(state: EngineState) -> dict[str, Any]:
    """
    Analyze rule descriptions and parameters to understand rule requirements.
    """
    start_time = time.time()

    try:
        logger.info(f"🔍 Analyzing {len(state.rule_descriptions)} rule descriptions")

        # Filter rules applicable to this event type, then apply optional `when:` predicates.
        applicable_rules = []
        for rule_desc in state.rule_descriptions:
            if state.event_type not in rule_desc.event_types:
                logger.info(
                    f"🔍 Rule '{rule_desc.description[:50]}...' is NOT applicable (expects: {rule_desc.event_types})"
                )
                continue

            applies, reason = should_apply_rule(rule_desc.when, state.event_data)
            if not applies:
                logger.debug(
                    f"🔍 Rule '{rule_desc.description[:50]}...' skipped: {reason}",
                )
                state.analysis_steps.append(f"Skipped: {rule_desc.description[:50]}... — {reason}")
                continue

            applicable_rules.append(rule_desc)
            logger.info(f"🔍 Rule '{rule_desc.description[:50]}...' is applicable to {state.event_type}")

        state.rule_descriptions = applicable_rules
        state.analysis_steps.append(f"Found {len(applicable_rules)} applicable rules out of {len(state.rules)} total")

        analysis_time = (time.time() - start_time) * 1000
        logger.info(f"🔍 Rule analysis completed in {analysis_time:.2f}ms")

    except Exception as e:
        logger.error(f"❌ Error in rule analysis: {e}")
        state.analysis_steps.append(f"Error in rule analysis: {str(e)}")

    return state.model_dump()


async def select_validation_strategy(state: EngineState) -> dict[str, Any]:
    """
    Use LLM to select the best validation strategy for each rule based on available validators.
    Prioritizes rules with attached executable conditions (Fast path).
    """
    start_time = time.time()

    try:
        logger.info(f"🎯 Selecting validation strategies for {len(state.rule_descriptions)} rules")

        # Use LLM to analyze rules and select validation strategies
        llm = get_chat_model(agent="engine_agent")

        # Identify rules that require LLM selection vs those with conditions
        llm_rules = []

        for rule_desc in state.rule_descriptions:
            # Check for attached condition objects (Fast path)
            if rule_desc.conditions:
                rule_desc.validation_strategy = ValidationStrategy.VALIDATOR
                rule_desc.validator_name = "Condition Objects"
                logger.info(f"🎯 Rule '{rule_desc.description[:50]}...' using attached conditions (Fast)")
                continue

            llm_rules.append(rule_desc)

        if not llm_rules:
            logger.info("🎯 All rules mapped to validators/conditions. Skipping LLM strategy selection.")
            return state.model_dump()

        logger.info(f"🎯 using LLM to select strategy for {len(llm_rules)} remaining rules")

        for rule_desc in llm_rules:
            # Create prompt for strategy selection
            strategy_prompt = create_validation_strategy_prompt(rule_desc, state.available_validators)
            messages = [
                SystemMessage(content=strategy_prompt),
                HumanMessage(content="Select the best validation strategy for this rule."),
            ]

            try:
                # Use structured output for reliable parsing
                structured_llm = llm.with_structured_output(StrategySelectionResponse)
                strategy_result = await structured_llm.ainvoke(messages)

                # Handle both structured response and BaseMessage cases
                if hasattr(strategy_result, "strategy"):
                    # It's a structured response
                    rule_desc.validation_strategy = strategy_result.strategy
                    rule_desc.validator_name = strategy_result.validator_name
                else:
                    # It's a BaseMessage, try to parse the content
                    import json

                    try:
                        content = json.loads(strategy_result.content)
                        rule_desc.validation_strategy = ValidationStrategy(content.get("strategy", "hybrid"))
                        rule_desc.validator_name = content.get("validator_name")
                    except (json.JSONDecodeError, ValueError):
                        # Fallback to default values
                        rule_desc.validation_strategy = ValidationStrategy.HYBRID
                        rule_desc.validator_name = None

                logger.info(f"🎯 Rule '{rule_desc.description[:50]}...' using {rule_desc.validation_strategy} strategy")
                if rule_desc.validator_name:
                    logger.info(f"🎯 Selected validator: {rule_desc.validator_name}")

            except Exception as e:
                logger.warning(f"⚠️ LLM strategy selection failed for rule '{rule_desc.description[:50]}...': {e}")
                rule_desc.validation_strategy = ValidationStrategy.HYBRID
                rule_desc.validator_name = None

        strategy_time = (time.time() - start_time) * 1000
        logger.info(f"🎯 Strategy selection completed in {strategy_time:.2f}ms")

    except Exception as e:
        logger.error(f"❌ Error in validation strategy selection: {e}")
        state.analysis_steps.append(f"Error in strategy selection: {str(e)}")

    return state.model_dump()


async def execute_validator_evaluation(state: EngineState) -> dict[str, Any]:
    """
    Execute fast validator evaluations for rules that can use validators.
    """
    start_time = time.time()

    try:
        validator_rules = [
            rd for rd in state.rule_descriptions if rd.validation_strategy == ValidationStrategy.VALIDATOR
        ]
        logger.info(f"⚡ Executing {len(validator_rules)} validator evaluations")

        if not validator_rules:
            logger.info("⚡ No validator rules to evaluate")
            return state.model_dump()

        # Execute validators concurrently
        validator_tasks = []
        for rule_desc in validator_rules:
            if rule_desc.conditions:
                # NEW: Use attached conditions
                task = _execute_conditions(rule_desc, state.event_data)
                validator_tasks.append(task)
            else:
                logger.error(
                    f"❌ Rule '{rule_desc.description[:50]}...' set to VALIDATOR strategy but has no conditions attached."
                )
                state.analysis_steps.append(
                    f"❌ Configuration Error: Rule '{rule_desc.description[:30]}...' has VALIDATOR strategy but no conditions."
                )

        if validator_tasks:
            results = await asyncio.gather(*validator_tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Validator failed for rule '{validator_rules[i].description[:50]}...': {result}")
                    # Fallback to LLM if validator fails
                    validator_rules[i].validation_strategy = ValidationStrategy.LLM_REASONING
                else:
                    result_dict = cast("dict[str, Any]", result)
                    if result_dict.get("is_violated", False):
                        if "violations" in result_dict:
                            # From _execute_conditions (returns list of violations)
                            state.violations.extend(result_dict["violations"])
                        elif "violation" in result_dict:
                            # From _execute_single_validator (returns single violation dict)
                            state.violations.append(result_dict["violation"])

                        state.analysis_steps.append(f"⚡ Validator violation: {validator_rules[i].description[:50]}...")
                    else:
                        state.analysis_steps.append(f"⚡ Validator passed: {validator_rules[i].description[:50]}...")

                    # Track validator usage
                    validator_name = validator_rules[i].validator_name
                    if validator_name:
                        state.validator_usage[validator_name] = state.validator_usage.get(validator_name, 0) + 1

        validator_time = (time.time() - start_time) * 1000
        logger.info(f"⚡ Validator evaluation completed in {validator_time:.2f}ms")

    except Exception as e:
        logger.error(f"❌ Error in validator evaluation: {e}")
        state.analysis_steps.append(f"Error in validator evaluation: {str(e)}")

    return state.model_dump()


async def execute_llm_fallback(state: EngineState) -> dict[str, Any]:
    """
    Execute LLM reasoning for complex rules or as fallback for validator failures.
    """
    start_time = time.time()

    try:
        llm_rules = [
            rd
            for rd in state.rule_descriptions
            if rd.validation_strategy in [ValidationStrategy.LLM_REASONING, ValidationStrategy.HYBRID]
        ]
        logger.info(f"🧠 Executing {len(llm_rules)} LLM evaluations")

        if not llm_rules:
            logger.info("🧠 No LLM rules to evaluate")
            return state.model_dump()

        # Execute LLM evaluations concurrently (with rate limiting)
        llm = get_chat_model(agent="engine_agent")

        llm_tasks = []
        for rule_desc in llm_rules:
            task = _execute_single_llm_evaluation(rule_desc, state.event_data, state.event_type, llm)
            llm_tasks.append(task)

        if llm_tasks:
            # Execute in batches to avoid overwhelming the LLM
            batch_size = 3
            for i in range(0, len(llm_tasks), batch_size):
                batch = llm_tasks[i : i + batch_size]
                results = await asyncio.gather(*batch, return_exceptions=True)

                # Process batch results
                for j, result in enumerate(results):
                    rule_desc = llm_rules[i + j]
                    if isinstance(result, Exception):
                        logger.error(f"❌ LLM evaluation failed for rule '{rule_desc.description[:50]}...': {result}")
                        state.analysis_steps.append(f"🧠 LLM failed: {rule_desc.description[:50]}...")
                    else:
                        result_dict = cast("dict[str, Any]", result)
                        if result_dict.get("is_violated", False):
                            violation = result_dict.get("violation", {})
                            state.violations.append(violation)
                            state.analysis_steps.append(f"🧠 LLM violation: {rule_desc.description[:50]}...")
                            logger.info(
                                f"🚨 Violation detected: {rule_desc.description[:50]}... - {violation.get('message', 'No message')[:100]}..."
                            )
                        else:
                            state.analysis_steps.append(f"🧠 LLM passed: {rule_desc.description[:50]}...")

                # Small delay between batches
                if i + batch_size < len(llm_tasks):
                    await asyncio.sleep(0.5)

        # Track LLM usage
        state.llm_usage = len(llm_rules)

        llm_time = (time.time() - start_time) * 1000
        logger.info(f"🧠 LLM evaluation completed in {llm_time:.2f}ms")

    except Exception as e:
        logger.error(f"❌ Error in LLM evaluation: {e}")
        state.analysis_steps.append(f"Error in LLM evaluation: {str(e)}")

    return state.model_dump()


async def _execute_conditions(rule_desc: RuleDescription, event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute attached rule conditions."""
    start_time = time.time()

    try:
        all_violations = []
        for condition in rule_desc.conditions:
            # Condition.evaluate takes a context dict
            context = {"parameters": rule_desc.parameters, "event": event_data}
            violations = await condition.evaluate(context)
            all_violations.extend(violations)

        execution_time = (time.time() - start_time) * 1000

        if all_violations:
            # Convert Violation objects to dicts for EngineState
            violation_dicts = []
            for v in all_violations:
                v_dict = v.model_dump()
                v_dict["rule_id"] = rule_desc.rule_id
                v_dict["validation_strategy"] = ValidationStrategy.VALIDATOR
                v_dict["execution_time_ms"] = execution_time
                violation_dicts.append(v_dict)

            return {"is_violated": True, "violations": violation_dicts}
        else:
            return {"is_violated": False, "execution_time_ms": execution_time}

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logger.error(f"❌ Condition execution error for rule '{rule_desc.description[:50]}...': {e}")
        return {"is_violated": False, "error": str(e), "execution_time_ms": execution_time}


async def _execute_single_llm_evaluation(
    rule_desc: RuleDescription, event_data: dict[str, Any], event_type: str, llm: Any
) -> dict[str, Any]:
    """Execute a single LLM evaluation."""
    start_time = time.time()

    try:
        # Create evaluation prompt
        evaluation_prompt = create_llm_evaluation_prompt(rule_desc, event_data, event_type)
        messages = [SystemMessage(content=get_llm_evaluation_system_prompt()), HumanMessage(content=evaluation_prompt)]

        # Use structured output for reliable parsing
        # Use function_calling method for better OpenAI compatibility
        structured_llm = llm.with_structured_output(LLMEvaluationResponse, method="function_calling")
        evaluation_result = await structured_llm.ainvoke(messages)

        execution_time = (time.time() - start_time) * 1000

        # Handle both structured response and BaseMessage cases
        if hasattr(evaluation_result, "is_violated"):
            # It's a structured response
            is_violated = evaluation_result.is_violated
            message = evaluation_result.message
            details = evaluation_result.details
            how_to_fix = evaluation_result.how_to_fix
        else:
            # It's a BaseMessage, try to parse the content
            try:
                content = json.loads(evaluation_result.content)
                is_violated = content.get("is_violated", False)
                message = content.get("message", "No message provided")
                details = content.get("details", {})
                how_to_fix = content.get("how_to_fix")
            except (json.JSONDecodeError, ValueError) as e:
                # Try to extract violation info from partial JSON
                logger.warning(f"⚠️ Failed to parse LLM response for rule '{rule_desc.description[:30]}...': {e}")

                # Check if we can extract basic violation info from truncated JSON
                content_str = evaluation_result.content
                if '"rule_violation": true' in content_str or '"is_violated": true' in content_str:
                    is_violated = True
                    message = "Rule violation detected (truncated response)"
                    details = {"truncated": True, "raw_content": content_str[:500]}
                    how_to_fix = "Review the rule requirements"
                else:
                    is_violated = False
                    message = "Failed to parse LLM response"
                    details = {}
                    how_to_fix = None

        if is_violated:
            violation = {
                "rule_description": rule_desc.description,
                "severity": rule_desc.severity,
                "message": message,
                "details": details,
                "how_to_fix": how_to_fix or "",
                "docs_url": "",
                "validation_strategy": ValidationStrategy.LLM_REASONING,
                "execution_time_ms": execution_time,
            }
            return {"is_violated": True, "violation": violation}
        else:
            return {"is_violated": False, "execution_time_ms": execution_time}

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logger.error(f"❌ LLM evaluation error for rule '{rule_desc.description[:50]}...': {e}")
        return {
            "is_violated": False,
            "error": str(e),
            "execution_time_ms": execution_time,
            "violation": {
                "rule_description": rule_desc.description,
                "rule_id": rule_desc.rule_id,
                "severity": rule_desc.severity,
                "message": f"LLM evaluation failed: {str(e)}",
                "details": {"error_type": type(e).__name__, "error_message": str(e)},
                "how_to_fix": "Review the rule configuration and try again",
                "docs_url": "",
                "validation_strategy": ValidationStrategy.LLM_REASONING,
                "execution_time_ms": execution_time,
            },
        }


async def validate_violations(state: EngineState) -> dict[str, Any]:
    """Validate and format violations for output."""
    logger.info(f"🔧 Violations validated: {len(state.violations)} violations")
    return state.model_dump()
