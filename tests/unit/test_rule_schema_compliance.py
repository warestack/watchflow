from src.agents.repository_analysis_agent.models import RuleRecommendation
from src.api.recommendations import AnalysisResponse
from src.core.models import RuleConfig, RuleParameters


def test_rule_config_schema():
    """Verify RuleConfig enforces strict schema."""
    config = RuleConfig(
        description="Test rule",
        enabled=True,
        severity="warning",
        event_types=["pull_request"],
        parameters={"message": "test"},
    )
    assert config.severity == "warning"
    assert config.parameters == {"message": "test"}

    # Verify 'reasoning' is not present in the dumped dict.
    dump = config.model_dump()
    assert "reasoning" not in dump
    assert "rationale" not in dump


def test_rule_recommendation_schema():
    """Verify RuleRecommendation includes reasoning but RuleConfig dump excludes it."""
    rec = RuleRecommendation(
        key="test_rule",
        name="Test Rule",
        description="Test description",
        enabled=True,
        severity="error",
        event_types=["pull_request"],
        parameters=RuleParameters(message="fix it"),
        reasoning="Because I said so",
        category="quality",
    )

    assert rec.reasoning == "Because I said so"

    # Convert to RuleConfig
    config = RuleConfig(
        description=rec.description,
        enabled=rec.enabled,
        severity=rec.severity,
        event_types=rec.event_types,
        parameters=rec.parameters.model_dump(exclude_none=True),
    )

    dump = config.model_dump()
    assert "reasoning" not in dump
    assert "key" not in dump
    assert "name" not in dump
    assert dump["parameters"]["message"] == "fix it"


def test_analysis_response_structure():
    """Verify AnalysisResponse separates rules and reasonings."""
    rules = [RuleConfig(description="d1", severity="info", event_types=["pr"], parameters={})]
    reasonings = {"rule1": "reason1"}

    response = AnalysisResponse(
        rules=rules, rule_reasonings=reasonings, analysis_summary="summary", immune_system_metrics={"score": 0.9}
    )

    assert len(response.rules) == 1
    assert response.rule_reasonings["rule1"] == "reason1"
    assert "reasoning" not in response.rules[0].model_dump()
