"""
LangGraph nodes for the Hybrid Rule Engine Agent.
"""

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.core.config import config
from src.rules.validators import VALIDATOR_REGISTRY

from .models import EngineState
from .prompts import create_llm_evaluation_prompt, create_validator_selection_prompt, get_llm_evaluation_system_prompt

logger = logging.getLogger(__name__)


def _generate_specific_how_to_fix_message(validator_name: str, rule: dict[str, Any], event_data: dict[str, Any]) -> str:
    """Generate specific 'How to fix' messages based on validator type and rule parameters."""

    parameters = rule.get("parameters", {})
    rule_name = rule.get("name", "Unknown Rule")

    if validator_name == "required_labels":
        required_labels = parameters.get("required_labels", [])
        if required_labels:
            if len(required_labels) == 1:
                return f'Add the "{required_labels[0]}" label'
            else:
                labels_str = (
                    ", ".join([f'"{label}"' for label in required_labels[:-1]]) + f' and "{required_labels[-1]}"'
                )
                return f"Add the {labels_str} labels"
        else:
            return f"Review and address the requirements for rule '{rule_name}'"

    elif validator_name == "min_approvals":
        min_approvals = parameters.get("min_approvals", 1)
        if min_approvals == 1:
            return "Get approval from a reviewer"
        else:
            return f"Get approval from {min_approvals} reviewers"

    elif validator_name == "title_pattern":
        pattern = parameters.get("pattern", "")
        if pattern:
            return f"Update the PR title to match the pattern: `{pattern}`"
        else:
            return f"Review and address the requirements for rule '{rule_name}'"

    elif validator_name == "min_description_length":
        min_length = parameters.get("min_length", 10)
        return f"Add more details to the PR description (minimum {min_length} characters)"

    elif validator_name == "max_file_size_mb":
        max_size = parameters.get("max_size_mb", 1)
        return f"Reduce file size to under {max_size}MB"

    elif validator_name == "branches":
        allowed_branches = parameters.get("branches", [])
        if allowed_branches:
            if len(allowed_branches) == 1:
                return f'Change the target branch to "{allowed_branches[0]}"'
            else:
                branches_str = (
                    ", ".join([f'"{branch}"' for branch in allowed_branches[:-1]]) + f' or "{allowed_branches[-1]}"'
                )
                return f"Change the target branch to {branches_str}"
        else:
            return f"Review and address the requirements for rule '{rule_name}'"

    elif validator_name == "is_weekend":
        return "Wait until a weekday to merge this PR"

    elif validator_name == "allowed_hours":
        allowed_hours = parameters.get("allowed_hours", [])
        if allowed_hours:
            hours_str = ", ".join([f"{hour}:00" for hour in allowed_hours])
            return f"Wait until one of the allowed hours: {hours_str}"
        else:
            return f"Review and address the requirements for rule '{rule_name}'"

    elif validator_name == "no-secrets":
        return "Remove any secrets, API keys, or sensitive information from the code"

    elif validator_name == "file-size-limit":
        max_size = parameters.get("max_size", 1000000)
        return f"Reduce file size to under {max_size} bytes"

    elif validator_name == "file-type-restrictions":
        allowed_types = parameters.get("allowed_types", [])
        if allowed_types:
            types_str = ", ".join([f"`.{ext}`" for ext in allowed_types])
            return f"Only include files with these extensions: {types_str}"
        else:
            return f"Review and address the requirements for rule '{rule_name}'"

    else:
        # Generic fallback for unknown validators
        return f"Review and address the requirements for rule '{rule_name}'"


# --- Main evaluation logic ---
async def smart_rule_evaluation(state: EngineState) -> EngineState:
    import asyncio

    start_time = time.time()
    violations = []
    analysis_steps = []

    try:
        logger.info(f"🔧 Smart evaluation starting for {len(state.rules)} rules against {state.event_type} event")

        # --- Step 0: Pre-filter rules by event type ---
        applicable_rules = []
        for rule in state.rules:
            rule_event_types = rule.get("event_types", [])
            if state.event_type in rule_event_types:
                applicable_rules.append(rule)
                logger.info(f"🔧 Rule '{rule.get('name')}' is applicable to {state.event_type} events")
            else:
                logger.info(
                    f"🔧 Rule '{rule.get('name')}' is NOT applicable to {state.event_type} events (expects: {rule_event_types})"
                )

        logger.info(f"🔧 Found {len(applicable_rules)} applicable rules out of {len(state.rules)} total rules")

        if not applicable_rules:
            logger.info("🔧 No applicable rules found for this event type")
            state.violations = []
            state.analysis_steps = ["No applicable rules found for this event type"]
            state.evaluation_context = {
                "total_rules": len(state.rules),
                "applicable_rules": 0,
                "rules_evaluated": 0,
                "violations_found": 0,
                "evaluation_strategy": "none",
                "evaluation_time_ms": (time.time() - start_time) * 1000,
            }
            return state

        llm = ChatOpenAI(api_key=config.ai.api_key, model=config.ai.model, max_tokens=2000, temperature=0.1)

        # --- Step 1: Ask LLM to select validator for applicable rules only ---
        validator_list = list(VALIDATOR_REGISTRY.keys())
        selection_prompt = create_validator_selection_prompt(applicable_rules, state.event_type, validator_list)
        messages = [
            SystemMessage(content=selection_prompt),
            HumanMessage(content="Select the best validator for each applicable rule."),
        ]
        logger.info("🔧 Using LLM to select validators for applicable rules...")
        llm_response = await llm.ainvoke(messages)
        try:
            content = llm_response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            validator_selections = json.loads(content.strip())
        except Exception as e:
            logger.error(f"🔧 Failed to parse validator selection: {e}")
            # fallback: all applicable rules use llm_reasoning
            validator_selections = [
                {"rule_id": rule.get("id"), "validator_name": "llm_reasoning"} for rule in applicable_rules
            ]

        # --- Step 2: Evaluate applicable rules using selected validators ---
        validator_tasks = []
        llm_tasks = []
        for sel in validator_selections:
            rule_id = sel["rule_id"]
            validator_name = sel["validator_name"]
            rule = next((r for r in applicable_rules if r.get("id") == rule_id), None)
            if not rule:
                logger.warning(f"🔧 Rule {rule_id} not found in applicable rules, skipping")
                continue

            if validator_name in VALIDATOR_REGISTRY:
                validator_tasks.append(
                    _evaluate_with_validator(rule, validator_name, state.event_data, violations, analysis_steps)
                )
            else:
                llm_tasks.append(
                    _evaluate_with_llm(rule, state.event_data, state.event_type, violations, analysis_steps, llm)
                )

        # --- Step 3: Run all validator tasks in parallel ---
        if validator_tasks:
            logger.info(f"🔧 Running {len(validator_tasks)} validator evaluations in parallel")
            await asyncio.gather(*validator_tasks, return_exceptions=True)

        # --- Step 4: Run all LLM tasks in parallel (batch) ---
        if llm_tasks:
            logger.info(f"🔧 Running {len(llm_tasks)} LLM evaluations in parallel")
            await asyncio.gather(*llm_tasks, return_exceptions=True)

        # --- Step 5: Finalize state ---
        state.violations = violations
        state.analysis_steps = analysis_steps
        state.evaluation_context = {
            "total_rules": len(state.rules),
            "applicable_rules": len(applicable_rules),
            "rules_evaluated": len(validator_selections),
            "violations_found": len(violations),
            "evaluation_strategy": "llm+validator",
            "evaluation_time_ms": (time.time() - start_time) * 1000,
        }

        logger.info(
            f"🔧 Smart evaluation completed: {len(violations)} violations found in {state.evaluation_context['evaluation_time_ms']:.2f}ms"
        )

        return state

    except Exception as e:
        logger.error(f"🔧 Error in smart rule evaluation: {e}")
        state.violations = []
        state.analysis_steps = [f"Error: {str(e)}"]
        state.evaluation_context = {"error": str(e), "evaluation_time_ms": (time.time() - start_time) * 1000}
        return state


# --- 3. Update _evaluate_with_validator to use async validate ---
async def _evaluate_with_validator(
    rule: dict[str, Any],
    validator_name: str,
    event_data: dict[str, Any],
    violations: list[dict[str, Any]],
    analysis_steps: list[str],
) -> dict[str, Any]:
    try:
        validator = VALIDATOR_REGISTRY[validator_name]
        parameters = rule.get("parameters", {})
        is_valid = await validator.validate(parameters, event_data)
        is_violated = not is_valid
        message = (
            f"Rule '{rule.get('name')}' validation failed"
            if is_violated
            else f"Rule '{rule.get('name')}' validation passed"
        )
        details = {
            "validator_used": validator_name,
            "parameters": parameters,
            "validation_result": "failed" if is_violated else "passed",
        }
        if is_violated:
            violation = {
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "severity": rule.get("severity", "medium"),
                "message": message,
                "details": details,
                "how_to_fix": _generate_specific_how_to_fix_message(validator_name, rule, event_data),
                "docs_url": "",
            }
            violations.append(violation)
            analysis_steps.append(f"  - ❌ Rule violated: {rule.get('name')} (validator)")
        else:
            analysis_steps.append(f"  - ✅ Rule passed: {rule.get('name')} (validator)")
        return {"is_violated": is_violated, "message": message, "details": details}
    except Exception as e:
        return {"is_violated": False, "message": f"Validator error: {str(e)}", "details": {"error": str(e)}}


async def _evaluate_with_llm(
    rule: dict[str, Any],
    event_data: dict[str, Any],
    event_type: str,
    violations: list[dict[str, Any]],
    analysis_steps: list[str],
    llm: ChatOpenAI,
) -> dict[str, Any]:
    """Evaluate a rule using LLM reasoning for complex/custom rules."""
    try:
        # Create prompt for LLM evaluation using the prompts module
        evaluation_prompt = create_llm_evaluation_prompt(rule, event_data, event_type)

        messages = [SystemMessage(content=get_llm_evaluation_system_prompt()), HumanMessage(content=evaluation_prompt)]

        logger.info(f"🔧 Using LLM reasoning for rule: {rule.get('name')}")
        llm_response = await llm.ainvoke(messages)

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
            is_violated = evaluation_result.get("is_violated", False)
            message = evaluation_result.get("message", "Rule violation detected")
            details = evaluation_result.get("details", {})
            how_to_fix = evaluation_result.get("how_to_fix", "")

            if is_violated:
                violation = {
                    "rule_id": rule.get("id"),
                    "rule_name": rule.get("name"),
                    "severity": rule.get("severity", "medium"),
                    "message": message,
                    "details": details,
                    "how_to_fix": how_to_fix,
                    "docs_url": "",
                }
                violations.append(violation)
                logger.info(f"🔧 Rule violation detected: {rule.get('name')} (LLM reasoning)")
                analysis_steps.append(f"  - ❌ Rule violated: {rule.get('name')} (LLM reasoning)")
            else:
                logger.info(f"🔧 Rule passed: {rule.get('name')} (LLM reasoning)")
                analysis_steps.append(f"  - ✅ Rule passed: {rule.get('name')} (LLM reasoning)")

            return {"is_violated": is_violated, "message": message, "details": details, "how_to_fix": how_to_fix}

        except json.JSONDecodeError as e:
            logger.error(f"🔧 Failed to parse LLM evaluation response: {e}")
            return {"is_violated": False, "message": f"LLM parsing error: {str(e)}", "details": {"error": str(e)}}

    except Exception as e:
        logger.error(f"🔧 Error in LLM evaluation: {e}")
        return {"is_violated": False, "message": f"LLM evaluation error: {str(e)}", "details": {"error": str(e)}}


async def validate_violations(state: EngineState) -> EngineState:
    """Validate and format violations for output."""
    logger.info(f"🔧 Violations validated: {len(state.violations)} violations")
    return state
