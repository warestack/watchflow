"""
LangGraph nodes for the Rule Feasibility Agent.
"""

import json
import logging

from langchain_openai import ChatOpenAI

from src.core.config import config

from .models import FeasibilityState
from .prompts import RULE_FEASIBILITY_PROMPT, YAML_GENERATION_PROMPT

logger = logging.getLogger(__name__)


def analyze_rule_feasibility(state: FeasibilityState) -> FeasibilityState:
    """
    Analyze whether a rule description is feasible to implement.
    """
    try:
        # Create LLM client directly using centralized config
        llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )

        # Analyze rule feasibility
        prompt = RULE_FEASIBILITY_PROMPT.format(rule_description=state.rule_description)

        response = llm.invoke(prompt)

        # Log the raw response for debugging
        logger.info(f"Raw LLM response: {response.content}")

        # Check if response is empty
        if not response.content or response.content.strip() == "":
            logger.error("LLM returned empty response")
            state.is_feasible = False
            state.feedback = "Analysis failed: LLM returned empty response"
            return state

        # Try to parse JSON with better error handling
        try:
            result = json.loads(response.content.strip())
        except json.JSONDecodeError as json_error:
            logger.error(f"Failed to parse JSON response: {json_error}")
            logger.error(f"Response content: {response.content}")

            # Try to extract JSON from markdown code blocks if present
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]  # Remove ```json
            elif content.startswith("```"):
                content = content[3:]  # Remove ```
            if content.endswith("```"):
                content = content[:-3]  # Remove trailing ```

            try:
                result = json.loads(content.strip())
                logger.info("Successfully extracted JSON from markdown code blocks")
            except json.JSONDecodeError:
                # If all parsing attempts fail, set default values
                logger.error("All JSON parsing attempts failed")
                state.is_feasible = False
                state.feedback = (
                    f"Analysis failed: Could not parse LLM response as JSON. Raw response: {response.content[:200]}..."
                )
                return state

        # Update state with analysis results
        state.is_feasible = result.get("is_feasible", False)
        state.rule_type = result.get("rule_type", "")
        state.confidence_score = result.get("confidence_score", 0.0)
        state.yaml_content = result.get("yaml_content", "")
        state.feedback = result.get("feedback", "")
        state.analysis_steps = result.get("analysis_steps", [])

        logger.info(f"Rule feasibility analysis completed: {state.is_feasible}")

    except Exception as e:
        logger.error(f"Error in rule feasibility analysis: {e}")
        state.is_feasible = False
        state.feedback = f"Analysis failed: {str(e)}"

    return state


def generate_yaml_config(state: FeasibilityState) -> FeasibilityState:
    """
    Generate YAML configuration for feasible rules.
    """
    if not state.is_feasible or not state.rule_type:
        return state

    try:
        # Create LLM client directly using centralized config
        llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )

        prompt = YAML_GENERATION_PROMPT.format(rule_type=state.rule_type, rule_description=state.rule_description)

        response = llm.invoke(prompt)
        state.yaml_content = response.content.strip()

        logger.info(f"YAML configuration generated for rule type: {state.rule_type}")

    except Exception as e:
        logger.error(f"Error generating YAML configuration: {e}")
        state.feedback += f"\nYAML generation failed: {str(e)}"

    return state
