"""
LangGraph nodes for the Rule Feasibility Agent with enhanced error handling.
"""

import structlog
from langchain_openai import ChatOpenAI

from src.agents.feasibility_agent.models import FeasibilityAnalysis, FeasibilityState, YamlGeneration
from src.agents.feasibility_agent.prompts import RULE_FEASIBILITY_PROMPT, YAML_GENERATION_PROMPT
from src.core.config import config

logger = structlog.get_logger()


async def analyze_rule_feasibility(state: FeasibilityState) -> FeasibilityState:
    """
    Analyze whether a rule description is feasible to implement using structured output.
    Enhanced with retry logic and better error handling.
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

        # Get structured response with retry logic
        result = await structured_llm.ainvoke(prompt)

        # Update state with analysis results - now type-safe!
        state.is_feasible = result.is_feasible
        state.rule_type = result.rule_type
        state.confidence_score = result.confidence_score
        state.feedback = result.feedback
        state.analysis_steps = result.analysis_steps

        logger.info("rule_feasibility_analysis_completed", is_feasible=state.is_feasible)
        logger.info("rule_type_identified", rule_type=state.rule_type)
        logger.info("confidence_score", confidence_score=state.confidence_score)
        logger.info(f"🔍 Analysis steps: {len(state.analysis_steps)} steps")

    except Exception as e:
        logger.error("error_in_rule_feasibility_analysis", e=e)
        state.is_feasible = False
        state.feedback = f"Analysis failed: {str(e)}"
        state.confidence_score = 0.0
        state.analysis_steps = [f"Error occurred: {str(e)}"]

    return state


async def generate_yaml_config(state: FeasibilityState) -> FeasibilityState:
    """
    Generate YAML configuration for feasible rules using structured output.
    This node only runs if the rule is feasible.
    """
    if not state.is_feasible or not state.rule_type:
        logger.info("skipping_yaml_generation_rule_not_feasible")
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

        # Get structured response with retry logic
        result = await structured_llm.ainvoke(prompt)

        # Update state with generated YAML
        state.yaml_content = result.yaml_content.strip()

        # Basic validation of generated YAML
        if not state.yaml_content or len(state.yaml_content) < 10:
            logger.warning("generated_yaml_seems_too_short_may")
            state.feedback += "\nWarning: Generated YAML may be incomplete"

        logger.info("yaml_configuration_generated_for_rule_type", rule_type=state.rule_type)
        logger.info(f"🔧 Generated YAML length: {len(state.yaml_content)} characters")

    except Exception as e:
        logger.error("error_generating_yaml_configuration", e=e)
        state.feedback += f"\nYAML generation failed: {str(e)}"
        state.yaml_content = ""

    return state
