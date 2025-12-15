import logging

    ContributingGuidelinesAnalysis,
    RepositoryAnalysisState,
    RepositoryFeatures,
    RuleRecommendation,
)
from src.agents.repository_analysis_agent.prompts import (
    CONTRIBUTING_GUIDELINES_ANALYSIS_PROMPT,

)
from src.integrations.github.api import github_client

logger = logging.getLogger(__name__)



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



    """Pull a small PR sample to inform rule recommendations."""
    try:
        logger.info(f"Fetching recent PRs for {state.repository_full_name}")
        prs = await github_client.list_pull_requests(
            state.repository_full_name, state.installation_id or 0, state="closed", per_page=20
        )

        pr_samples: list[dict[str, Any]] = []
        for pr in prs:
            pr_samples.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "merged": pr.get("merged_at") is not None,
                    "changed_files": pr.get("changed_files"),
                    "additions": pr.get("additions"),
                    "deletions": pr.get("deletions"),
                    "user": pr.get("user", {}).get("login"),
                }
            )

        state.pr_samples = pr_samples
        state.analysis_steps.append("pr_history_sampled")
        logger.info(f"Collected {len(pr_samples)} PR samples")
        return {"pr_samples": pr_samples, "analysis_steps": state.analysis_steps}
    except Exception as e:
        logger.error(f"Error analyzing PR history: {e}")
        state.errors.append(f"PR history analysis failed: {str(e)}")
        return {"errors": state.errors}



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



    """
    Generate Watchflow rule recommendations based on repository analysis.
    """
    try:
        logger.info(f" Generating rule recommendations for {state.repository_full_name}")

        recommendations = []

        features = state.repository_features
        contributing = state.contributing_analysis


        # Diff-aware: enforce filter handling in core RAG/query code
        recommendations.append(
            RuleRecommendation(
                yaml_content="""description: "Block merges when PRs change filter validation logic without failing on invalid inputs"
enabled: true
severity: "high"
event_types: ["pull_request"]
parameters:
  file_patterns:
    - "packages/core/src/**/vector-query.ts"
    - "packages/core/src/**/graph-rag.ts"
    - "packages/core/src/**/filters/*.ts"
  require_patterns:
    - "throw\\\\s+new\\\\s+Error"
    - "raise\\\\s+ValueError"
  forbidden_patterns:
    - "return\\\\s+.*filter\\\\s*$"
  how_to_fix: "Ensure invalid filters raise descriptive errors instead of silently returning unfiltered results."
""",
                confidence=0.85,
                reasoning="Filter handling regressions were flagged in historical fixes; enforce throws on invalid input.",
                source_patterns=["pr_history"],
                category="quality",
                estimated_impact="high",
            )
        )

        # Diff-aware: enforce test updates when core code changes
        recommendations.append(
            RuleRecommendation(
                yaml_content="""description: "Require regression tests when modifying tool schema validation or client tool execution"
enabled: true
severity: "medium"
event_types: ["pull_request"]
parameters:
  source_patterns:
    - "packages/core/src/**/tool*.ts"
    - "packages/core/src/agent/**"
    - "packages/client/**"
  test_patterns:
    - "packages/core/tests/**"
    - "tests/**"
  min_test_files: 1
  rationale: "Tool invocation changes have previously caused regressions in clientTools streaming."
""",
                confidence=0.8,
                reasoning="Core tool changes often broke client tools; require at least one related test update.",
                source_patterns=["pr_history"],
                category="quality",
                estimated_impact="medium",
            )
        )

        # Diff-aware: ensure agent descriptions exist
        recommendations.append(
            RuleRecommendation(
                yaml_content="""description: "Ensure every agent exposes a user-facing description for UI profiles"
enabled: true
severity: "low"
event_types: ["pull_request"]
parameters:
  file_patterns:
    - "packages/core/src/agent/**"
  required_text:
    - "description"
  message: "Add or update the agent description so downstream UIs can render capabilities."
""",
                confidence=0.75,
                reasoning="Agent profile UIs require descriptions; ensure new/updated agents include them.",
                source_patterns=["pr_history"],
                category="process",
                estimated_impact="low",
            )
        )

        # Diff-aware: preserve URL handling for supported providers
        recommendations.append(
            RuleRecommendation(
                yaml_content="""description: "Block merges when URL or asset handling changes bypass provider capability checks"
enabled: true
severity: "high"
event_types: ["pull_request"]
parameters:
  file_patterns:
    - "packages/core/src/agent/message-list/**"
    - "packages/core/src/llm/**"
  require_patterns:
    - "isUrlSupportedByModel"
  forbidden_patterns:
    - "downloadAssetsFromMessages\\(messages\\)"
  how_to_fix: "Preserve remote URLs for providers that support them natively; only download assets for unsupported providers."
""",
                confidence=0.8,
                reasoning="Past URL handling bugs; ensure capability checks remain intact.",
                source_patterns=["pr_history"],
                category="quality",
                estimated_impact="high",
            )
        )

        # Legacy structural signals retained for completeness
        if features.has_workflows:

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

        state.recommendations = recommendations
        state.analysis_steps.append("recommendations_generated")

        logger.info(f"Generated {len(recommendations)} rule recommendations")

        return {"recommendations": recommendations, "analysis_steps": state.analysis_steps}

    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        state.errors.append(f"Recommendation generation failed: {str(e)}")
        return {"errors": state.errors}



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
