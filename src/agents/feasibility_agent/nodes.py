"""
LangGraph nodes for the Rule Feasibility Agent with enhanced error handling.
"""

import logging

from src.core.ai import get_chat_model

from src.agents.feasibility_agent.models import FeasibilityAnalysis, FeasibilityState, YamlGeneration
from src.agents.feasibility_agent.prompts import RULE_FEASIBILITY_PROMPT, YAML_GENERATION_PROMPT
from src.core.config import config

logger = logging.getLogger(__name__)


async def analyze_rule_feasibility(state: FeasibilityState) -> FeasibilityState:
    """
    Analyze whether a rule description is feasible to implement using structured output.
    Enhanced with retry logic and better error handling.
    """
    try:
        # Create LLM client with structured output
        llm = get_chat_model()

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

        logger.info(f"🔍 Rule feasibility analysis completed: {state.is_feasible}")
        logger.info(f"🔍 Rule type identified: {state.rule_type}")
        logger.info(f"🔍 Confidence score: {state.confidence_score}")
        logger.info(f"🔍 Analysis steps: {len(state.analysis_steps)} steps")

    except Exception as e:
        logger.error(f"❌ Error in rule feasibility analysis: {e}")
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
        logger.info("🔧 Skipping YAML generation - rule not feasible or no rule type")
        return state

    try:
        # Create LLM client with structured output
        llm = get_chat_model()

        # Use structured output for YAML generation
        structured_llm = llm.with_structured_output(YamlGeneration)

        prompt = YAML_GENERATION_PROMPT.format(rule_type=state.rule_type, rule_description=state.rule_description)

        # Get structured response with retry logic
        result = await structured_llm.ainvoke(prompt)

        # Update state with generated YAML
        state.yaml_content = result.yaml_content.strip()

        # Basic validation of generated YAML
        if not state.yaml_content or len(state.yaml_content) < 10:
            logger.warning("⚠️ Generated YAML seems too short, may be invalid")
            state.feedback += "\nWarning: Generated YAML may be incomplete"

        logger.info(f"🔧 YAML configuration generated for rule type: {state.rule_type}")
        logger.info(f"🔧 Generated YAML length: {len(state.yaml_content)} characters")

    except Exception as e:
        logger.error(f"❌ Error generating YAML configuration: {e}")
        state.feedback += f"\nYAML generation failed: {str(e)}"
        state.yaml_content = ""

    return state
