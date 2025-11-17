import logging
from typing import Any, Dict

from src.agents.repository_analysis_agent.models import (
    AnalysisSource,
    ContributingGuidelinesAnalysis,
    RepositoryAnalysisState,
    RepositoryFeatures,
    RuleRecommendation,
)
from src.agents.repository_analysis_agent.prompts import (
    CONTRIBUTING_GUIDELINES_ANALYSIS_PROMPT,
    REPOSITORY_ANALYSIS_PROMPT,
    RULE_GENERATION_PROMPT,
)
from src.integrations.github.api import github_client

logger = logging.getLogger(__name__)


async def analyze_repository_structure(state: RepositoryAnalysisState) -> Dict[str, Any]:
    """
    Analyze basic repository structure and features.

    Gathers information about workflows, branch protection, contributors, etc.
    """
    try:
        logger.info(f"Analyzing repository structure for {state.repository_full_name}")

        features = RepositoryFeatures()
        contributing_content = await github_client.get_file_content(
            state.repository_full_name, "CONTRIBUTING.md", state.installation_id
        )
        features.has_contributing = contributing_content is not None

        codeowners_content = await github_client.get_file_content(
            state.repository_full_name, ".github/CODEOWNERS", state.installation_id
        )
        features.has_codeowners = codeowners_content is not None

        
        workflow_content = await github_client.get_file_content(
            state.repository_full_name, ".github/workflows/main.yml", state.installation_id
        )
        if workflow_content:
            features.has_workflows = True
            features.workflow_count = 1  

      
        contributors = await github_client.get_repository_contributors(
            state.repository_full_name, state.installation_id
        )
        features.contributor_count = len(contributors) if contributors else 0

        # TODO: Add more repository analysis (PR count, issues, language detection, etc.)

        logger.info(f"Repository analysis complete: {features.model_dump()}")

        state.repository_features = features
        state.analysis_steps.append("repository_structure_analyzed")

        return {"repository_features": features, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error analyzing repository structure: {e}")
        state.errors.append(f"Repository structure analysis failed: {str(e)}")
        return {"errors": state.errors}


async def analyze_contributing_guidelines(state: RepositoryAnalysisState) -> Dict[str, Any]:
    """
    Analyze CONTRIBUTING.md file for patterns and requirements.
    """
    try:
        logger.info(f" Analyzing contributing guidelines for {state.repository_full_name}")

        # Get contributing guidelines content
        content = await github_client.get_file_content(
            state.repository_full_name, "CONTRIBUTING.md", state.installation_id
        )

        if not content:
            logger.info("No CONTRIBUTING.md file found")
            analysis = ContributingGuidelinesAnalysis()
        else:
           
            llm = github_client.llm if hasattr(github_client, 'llm') else None
            if llm:
                try:
                    prompt = CONTRIBUTING_GUIDELINES_ANALYSIS_PROMPT.format(content=content)
                    response = await llm.ainvoke(prompt)

                   
                    # TODO: Parse JSON response and create ContributingGuidelinesAnalysis

                    analysis = ContributingGuidelinesAnalysis(content=content)
                except Exception as e:
                    logger.error(f"LLM analysis failed: {e}")
                    analysis = ContributingGuidelinesAnalysis(content=content)
            else:
                analysis = ContributingGuidelinesAnalysis(content=content)

        state.contributing_analysis = analysis
        state.analysis_steps.append("contributing_guidelines_analyzed")

        logger.info(" Contributing guidelines analysis complete")

        return {"contributing_analysis": analysis, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error analyzing contributing guidelines: {e}")
        state.errors.append(f"Contributing guidelines analysis failed: {str(e)}")
        return {"errors": state.errors}


async def generate_rule_recommendations(state: RepositoryAnalysisState) -> Dict[str, Any]:
    """
    Generate Watchflow rule recommendations based on repository analysis.
    """
    try:
        logger.info(f" Generating rule recommendations for {state.repository_full_name}")

        recommendations = []

        features = state.repository_features
        contributing = state.contributing_analysis

        
        if features.has_workflows:
            recommendations.append(RuleRecommendation(
                yaml_content="""description: "Require CI checks to pass"
enabled: true
severity: "high"
event_types:
  - pull_request
conditions:
  - type: "ci_checks_passed"
    parameters:
      required_checks: []
actions:
  - type: "block_merge"
    parameters:
      message: "All CI checks must pass before merging"
""",
                confidence=0.9,
                reasoning="Repository has CI workflows configured, so requiring checks to pass is a standard practice",
                source_patterns=["has_workflows"],
                category="quality",
                estimated_impact="high"
            ))

        if features.has_codeowners:
            recommendations.append(RuleRecommendation(
                yaml_content="""description: "Require CODEOWNERS approval for changes"
enabled: true
severity: "medium"
event_types:
  - pull_request
conditions:
  - type: "codeowners_approved"
    parameters: {}
actions:
  - type: "require_approval"
    parameters:
      message: "CODEOWNERS must approve changes to owned files"
""",
                confidence=0.8,
                reasoning="CODEOWNERS file exists, indicating ownership requirements for code changes",
                source_patterns=["has_codeowners"],
                category="process",
                estimated_impact="medium"
            ))

        if contributing.requires_tests:
            recommendations.append(RuleRecommendation(
                yaml_content="""description: "Require test coverage for code changes"
enabled: true
severity: "medium"
event_types:
  - pull_request
conditions:
  - type: "test_coverage_threshold"
    parameters:
      minimum_coverage: 80
actions:
  - type: "block_merge"
    parameters:
      message: "Test coverage must be at least 80%"
""",
                confidence=0.7,
                reasoning="Contributing guidelines mention testing requirements",
                source_patterns=["requires_tests"],
                category="quality",
                estimated_impact="medium"
            ))

        if features.contributor_count > 10:
            recommendations.append(RuleRecommendation(
                yaml_content="""description: "Require at least one approval for pull requests"
enabled: true
severity: "medium"
event_types:
  - pull_request
conditions:
  - type: "minimum_approvals"
    parameters:
      count: 1
actions:
  - type: "block_merge"
    parameters:
      message: "Pull requests require at least one approval"
""",
                confidence=0.6,
                reasoning="Repository has multiple contributors, indicating collaborative development",
                source_patterns=["contributor_count"],
                category="process",
                estimated_impact="medium"
            ))

        
        state.recommendations = recommendations
        state.analysis_steps.append("recommendations_generated")

        logger.info(f"Generated {len(recommendations)} rule recommendations")

        return {"recommendations": recommendations, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        state.errors.append(f"Recommendation generation failed: {str(e)}")
        return {"errors": state.errors}


async def validate_recommendations(state: RepositoryAnalysisState) -> Dict[str, Any]:
    """
    Validate that generated recommendations contain valid YAML.
    """
    try:
        logger.info("Validating rule recommendations")

        import yaml

        valid_recommendations = []

        for rec in state.recommendations:
            try:
                # Parse YAML to validate syntax
                parsed = yaml.safe_load(rec.yaml_content)
                if parsed and isinstance(parsed, dict):
                    valid_recommendations.append(rec)
                else:
                    logger.warning(f"Invalid rule structure: {rec.yaml_content[:100]}...")
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML in recommendation: {e}")
                continue

        state.recommendations = valid_recommendations
        state.analysis_steps.append("recommendations_validated")

        logger.info(f"Validated {len(valid_recommendations)} recommendations")

        return {"recommendations": valid_recommendations, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error validating recommendations: {e}")
        state.errors.append(f"Recommendation validation failed: {str(e)}")
        return {"errors": state.errors}


async def summarize_analysis(state: RepositoryAnalysisState) -> Dict[str, Any]:
    """
    Create a summary of the analysis findings.
    """
    try:
        logger.info("Creating analysis summary")

        summary = {
            "repository": state.repository_full_name,
            "features_analyzed": {
                "has_contributing": state.repository_features.has_contributing,
                "has_codeowners": state.repository_features.has_codeowners,
                "has_workflows": state.repository_features.has_workflows,
                "contributor_count": state.repository_features.contributor_count,
            },
            "recommendations_count": len(state.recommendations),
            "recommendations_by_category": {},
            "high_confidence_count": 0,
            "analysis_steps_completed": len(state.analysis_steps),
            "errors_encountered": len(state.errors),
        }

        # Count recommendations by category
        for rec in state.recommendations:
            summary["recommendations_by_category"][rec.category] = (
                summary["recommendations_by_category"].get(rec.category, 0) + 1
            )
            if rec.confidence >= 0.8:
                summary["high_confidence_count"] += 1

        state.analysis_summary = summary
        state.analysis_steps.append("analysis_summarized")

        logger.info("Analysis summary created")

        return {"analysis_summary": summary, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error creating analysis summary: {e}")
        state.errors.append(f"Analysis summary failed: {str(e)}")
        return {"errors": state.errors}
