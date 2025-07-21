"""
LangGraph nodes for the Rule Feasibility Agent.
"""

import logging

from langchain_openai import ChatOpenAI

from src.core.config import config

from .models import FeasibilityAnalysis, FeasibilityState, YamlGeneration
from .prompts import RULE_FEASIBILITY_PROMPT, YAML_GENERATION_PROMPT

logger = logging.getLogger(__name__)


async def analyze_rule_feasibility(state: FeasibilityState) -> FeasibilityState:
    """
    Analyze whether a rule description is feasible to implement using structured output.
    """
    try:
        # Create LLM client with structured output
        llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )

        # Use structured output instead of manual JSON parsing
        structured_llm = llm.with_structured_output(FeasibilityAnalysis)

        # Analyze rule feasibility
        prompt = RULE_FEASIBILITY_PROMPT.format(rule_description=state.rule_description)

        # Get structured response - no more JSON parsing needed!
        result = await structured_llm.ainvoke(prompt)

        # Update state with analysis results - now type-safe!
        state.is_feasible = result.is_feasible
        state.rule_type = result.rule_type
        state.confidence_score = result.confidence_score
        state.feedback = result.feedback
        state.analysis_steps = result.analysis_steps

        logger.info(f"🔍 Rule feasibility analysis completed: {state.is_feasible}")
        logger.info(f"🔍 Rule type identified: {state.rule_type}")
        logger.info(f"🔍 Confidence score: {state.confidence_score}")

    except Exception as e:
        logger.error(f"❌ Error in rule feasibility analysis: {e}")
        state.is_feasible = False
        state.feedback = f"Analysis failed: {str(e)}"
        state.confidence_score = 0.0

    return state


async def generate_yaml_config(state: FeasibilityState) -> FeasibilityState:
    """
    Generate YAML configuration for feasible rules using structured output.
    This node only runs if the rule is feasible.
    """
    if not state.is_feasible or not state.rule_type:
        logger.info("🔧 Skipping YAML generation - rule not feasible or no rule type")
        return state

    try:
        # Create LLM client with structured output
        llm = ChatOpenAI(
            api_key=config.ai.api_key,
            model=config.ai.model,
            max_tokens=config.ai.max_tokens,
            temperature=config.ai.temperature,
        )

        # Use structured output for YAML generation
        structured_llm = llm.with_structured_output(YamlGeneration)

        prompt = YAML_GENERATION_PROMPT.format(rule_type=state.rule_type, rule_description=state.rule_description)

        # Get structured response
        result = await structured_llm.ainvoke(prompt)

        # Update state with generated YAML
        state.yaml_content = result.yaml_content.strip()

        logger.info(f"🔧 YAML configuration generated for rule type: {state.rule_type}")
        logger.info(f"🔧 Generated YAML length: {len(state.yaml_content)} characters")

    except Exception as e:
        logger.error(f"❌ Error generating YAML configuration: {e}")
        state.feedback += f"\nYAML generation failed: {str(e)}"

    return state
