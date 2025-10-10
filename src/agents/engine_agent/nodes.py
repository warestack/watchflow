"""
LangGraph nodes for the Rule Engine Agent with hybrid validation strategy.
"""

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.engine_agent.models import (
    EngineState,
    HowToFixResponse,
    LLMEvaluationResponse,
    RuleDescription,
    StrategySelectionResponse,
    ValidationStrategy,
)
from src.agents.engine_agent.prompts import (
    create_how_to_fix_prompt,
    create_llm_evaluation_prompt,
    create_validation_strategy_prompt,
    get_llm_evaluation_system_prompt,
)
from src.core.ai import get_chat_model
from src.rules.validators import VALIDATOR_REGISTRY

logger = logging.getLogger(__name__)


async def analyze_rule_descriptions(state: EngineState) -> EngineState:
    """
    Analyze rule descriptions and parameters to understand rule requirements.
    """
    start_time = time.time()

    try:
        logger.info(f"🔍 Analyzing {len(state.rule_descriptions)} rule descriptions")

        # Filter rules applicable to this event type
        applicable_rules = []
        for rule_desc in state.rule_descriptions:
            if state.event_type in rule_desc.event_types:
                applicable_rules.append(rule_desc)
                logger.info(f"🔍 Rule '{rule_desc.description[:50]}...' is applicable to {state.event_type}")
            else:
                logger.info(
                    f"🔍 Rule '{rule_desc.description[:50]}...' is NOT applicable (expects: {rule_desc.event_types})"
                )

        state.rule_descriptions = applicable_rules
        state.analysis_steps.append(f"Found {len(applicable_rules)} applicable rules out of {len(state.rules)} total")

        analysis_time = (time.time() - start_time) * 1000
        logger.info(f"🔍 Rule analysis completed in {analysis_time:.2f}ms")

    except Exception as e:
        logger.error(f"❌ Error in rule analysis: {e}")
        state.analysis_steps.append(f"Error in rule analysis: {str(e)}")

    return state


async def select_validation_strategy(state: EngineState) -> EngineState:
    """
    Use LLM to select the best validation strategy for each rule based on available validators.
    """
    start_time = time.time()

    try:
        logger.info(f"🎯 Selecting validation strategies for {len(state.rule_descriptions)} rules using LLM")

        # Use LLM to analyze rules and select validation strategies
        llm = get_chat_model(agent="engine_agent")

        for rule_desc in state.rule_descriptions:
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

    return state


async def execute_validator_evaluation(state: EngineState) -> EngineState:
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
            return state

        # Execute validators concurrently
        validator_tasks = []
        for rule_desc in validator_rules:
            if rule_desc.validator_name and rule_desc.validator_name in VALIDATOR_REGISTRY:
                task = _execute_single_validator(rule_desc, state.event_data)
                validator_tasks.append(task)

        if validator_tasks:
            results = await asyncio.gather(*validator_tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Validator failed for rule '{validator_rules[i].description[:50]}...': {result}")
                    # Fallback to LLM if validator fails
                    validator_rules[i].validation_strategy = ValidationStrategy.LLM_REASONING
                else:
                    if result.get("is_violated", False):
                        state.violations.append(result.get("violation", {}))
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

    return state


async def execute_llm_fallback(state: EngineState) -> EngineState:
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
            return state

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
                        if result.get("is_violated", False):
                            violation = result.get("violation", {})
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

    return state


async def _execute_single_validator(rule_desc: RuleDescription, event_data: dict[str, Any]) -> dict[str, Any]:
    """Execute a single validator evaluation."""
    start_time = time.time()

    try:
        validator = VALIDATOR_REGISTRY[rule_desc.validator_name]
        is_valid = await validator.validate(rule_desc.parameters, event_data)
        is_violated = not is_valid

        execution_time = (time.time() - start_time) * 1000

        if is_violated:
            # Generate dynamic "how to fix" message using LLM
            how_to_fix = await _generate_dynamic_how_to_fix(rule_desc, event_data, validator.name)

            violation = {
                "rule_description": rule_desc.description,
                "severity": rule_desc.severity,
                "message": f"Rule validation failed: {rule_desc.description}",
                "details": {
                    "validator_used": rule_desc.validator_name,
                    "parameters": rule_desc.parameters,
                    "validation_result": "failed",
                },
                "how_to_fix": how_to_fix,
                "docs_url": "",
                "validation_strategy": ValidationStrategy.VALIDATOR,
                "execution_time_ms": execution_time,
            }
            return {"is_violated": True, "violation": violation}
        else:
            return {"is_violated": False, "execution_time_ms": execution_time}

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logger.error(f"❌ Validator error for rule '{rule_desc.description[:50]}...': {e}")
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
        structured_llm = llm.with_structured_output(LLMEvaluationResponse)
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
                "severity": rule_desc.severity,
                "message": f"LLM evaluation failed: {str(e)}",
                "details": {"error_type": type(e).__name__, "error_message": str(e)},
                "how_to_fix": "Review the rule configuration and try again",
                "docs_url": "",
                "validation_strategy": ValidationStrategy.LLM_REASONING,
                "execution_time_ms": execution_time,
            },
        }


async def _generate_dynamic_how_to_fix(
    rule_desc: RuleDescription, event_data: dict[str, Any], validator_name: str
) -> str:
    """Generate dynamic 'how to fix' message using LLM."""

    try:
        llm = get_chat_model(agent="engine_agent", max_tokens=1000)

        # Create prompt for how to fix generation
        how_to_fix_prompt = create_how_to_fix_prompt(rule_desc, event_data, validator_name)
        messages = [
            SystemMessage(
                content="You are an expert at providing actionable guidance for fixing GitHub rule violations."
            ),
            HumanMessage(content=how_to_fix_prompt),
        ]

        # Use structured output for reliable parsing
        structured_llm = llm.with_structured_output(HowToFixResponse)
        how_to_fix_result = await structured_llm.ainvoke(messages)

        # Handle both structured response and BaseMessage cases
        if hasattr(how_to_fix_result, "how_to_fix"):
            return how_to_fix_result.how_to_fix
        else:
            # It's a BaseMessage, try to parse the content
            import json

            try:
                content = json.loads(how_to_fix_result.content)
                return content.get(
                    "how_to_fix", f"Review and address the requirements for rule: {rule_desc.description}"
                )
            except (json.JSONDecodeError, ValueError):
                return f"Review and address the requirements for rule: {rule_desc.description}"

    except Exception as e:
        logger.error(f"❌ Error generating how to fix message: {e}")
        # Fallback to generic message
        return f"Review and address the requirements for rule: {rule_desc.description}"


async def validate_violations(state: EngineState) -> EngineState:
    """Validate and format violations for output."""
    logger.info(f"🔧 Violations validated: {len(state.violations)} violations")
    return state
