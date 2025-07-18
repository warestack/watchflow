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

    # Use the new method signature
    result = await agent.check_feasibility(rule_description=request.rule_text)

    # Return the result in the expected format
    return {"supported": result.is_feasible, "snippet": result.yaml_content, "feedback": result.feedback}
