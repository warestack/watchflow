from fastapi import APIRouter
from pydantic import BaseModel

from src.agents import get_agent

router = APIRouter()


class RuleEvaluationRequest(BaseModel):
    rule_text: str
    event_data: dict | None = None  # Advanced: pass extra event data for edge cases.


@router.post("/rules/evaluate")
async def evaluate_rule(request: RuleEvaluationRequest):
    # Agent: uses central config—change here affects all rule evals.
    agent = get_agent("feasibility")

    # Async call—agent may throw if rule malformed.
    result = await agent.execute(rule_description=request.rule_text)

    # Output: keep format stable for frontend. Brittle if agent changes keys.
    return {
        "supported": result.data.get("is_feasible", False),
        "snippet": result.data.get("yaml_content", ""),
        "feedback": result.message,
    }
