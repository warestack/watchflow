from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.agents.repository_analysis_agent.models import RuleRecommendation


def test_build_rules_yaml_renders_rules():
    agent = RepositoryAnalysisAgent()
    recs = [
        RuleRecommendation(
            yaml_content="""description: "Rule A"
enabled: true
event_types: ["pull_request"]
parameters:
  foo: bar
""",
            confidence=0.9,
            reasoning="test",
            source_patterns=[],
            category="quality",
            estimated_impact="high",
        )
    ]

    rendered = agent._build_rules_yaml(recs)

    assert rendered.startswith("rules:")
    assert "description: \"Rule A\"" in rendered
    # Ensure indentation under rules:
    assert "\n  description" in rendered


def test_build_pr_template_includes_repo_and_rules():
    agent = RepositoryAnalysisAgent()
    recs = [
        RuleRecommendation(
            yaml_content="""description: "Rule A"
enabled: true
event_types: ["pull_request"]
parameters: {}
""",
            confidence=0.9,
            reasoning="test",
            source_patterns=[],
            category="quality",
            estimated_impact="high",
        )
    ]

    pr_body = agent._build_pr_template("owner/repo", recs)

    assert "owner/repo" in pr_body
    assert "Rule A" in pr_body
    assert "Install the Watchflow GitHub App" in pr_body

