from fastapi import APIRouter
from pydantic import BaseModel

from src.agents.feasibility_agent.agent import RuleFeasibilityAgent

router = APIRouter()


class RuleEvaluationRequest(BaseModel):
    rule_text: str
    event_data: dict | None = None  # Optional, for advanced use


@router.post("/rules/evaluate")
async def evaluate_rule(request: RuleEvaluationRequest):
    # Create agent instance (uses centralized config)
    agent = RuleFeasibilityAgent()

    # Use the execute method
    result = await agent.execute(rule_description=request.rule_text)

    # Return the result in the expected format
    return {
        "supported": result.data.get("is_feasible", False),
        "snippet": result.data.get("yaml_content", ""),
        "feedback": result.message,
    }
