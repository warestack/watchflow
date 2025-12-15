"""
Workflow nodes for the RepositoryAnalysisAgent.

Each node is a small, testable function that mutates the RepositoryAnalysisState.
The nodes favor static/hybrid strategies first and avoid heavy LLM calls unless
strictly necessary.
"""

from __future__ import annotations

import textwrap
from typing import Any

import yaml

from src.agents.repository_analysis_agent.models import (
    ContributingGuidelinesAnalysis,
    PullRequestPlan,
    PullRequestSample,
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryAnalysisState,
    RepositoryFeatures,
    RuleRecommendation,
)
from src.integrations.github.api import github_client


async def analyze_repository_structure(state: RepositoryAnalysisState) -> None:
    """Collect repository metadata and structure signals."""
    repo = state.repository_full_name
    installation_id = state.installation_id

    repo_data = await github_client.get_repository(repo, installation_id=installation_id)
    workflows = await github_client.list_directory_any_auth(
        repo_full_name=repo, path=".github/workflows", installation_id=installation_id
    )
    contributors = await github_client.get_repository_contributors(repo, installation_id) if installation_id else []

    state.repository_features = RepositoryFeatures(
        has_contributing=False,
        has_codeowners=bool(await github_client.get_file_content(repo, ".github/CODEOWNERS", installation_id)),
        has_workflows=bool(workflows),
        workflow_count=len(workflows or []),
        language=(repo_data or {}).get("language"),
        contributor_count=len(contributors),
        pr_count=0,
    )


async def analyze_pr_history(state: RepositoryAnalysisState, max_prs: int) -> None:
    """Fetch a small sample of recent pull requests for context."""
    repo = state.repository_full_name
    installation_id = state.installation_id
    prs = await github_client.list_pull_requests(repo, installation_id=installation_id, state="all", per_page=max_prs)

    samples: list[PullRequestSample] = []
    for pr in prs or []:
        samples.append(
            PullRequestSample(
                number=pr.get("number", 0),
                title=pr.get("title", ""),
                state=pr.get("state", ""),
                merged=bool(pr.get("merged_at")),
                additions=pr.get("additions"),
                deletions=pr.get("deletions"),
                changed_files=pr.get("changed_files"),
            )
        )

    state.pr_samples = samples
    state.repository_features.pr_count = len(samples)


async def analyze_contributing_guidelines(state: RepositoryAnalysisState) -> None:
    """Fetch and parse CONTRIBUTING guidelines if present."""
    repo = state.repository_full_name
    installation_id = state.installation_id

    content = await github_client.get_file_content(
        repo, "CONTRIBUTING.md", installation_id
    ) or await github_client.get_file_content(repo, ".github/CONTRIBUTING.md", installation_id)

    if not content:
        state.contributing_analysis = ContributingGuidelinesAnalysis(content=None)
        return

    lowered = content.lower()
    state.contributing_analysis = ContributingGuidelinesAnalysis(
        content=content,
        has_pr_template="pr template" in lowered or "pull request template" in lowered,
        has_issue_template="issue template" in lowered,
        requires_tests="test" in lowered or "tests" in lowered,
        requires_docs="docs" in lowered or "documentation" in lowered,
        code_style_requirements=[
            req for req in ["lint", "format", "pep8", "flake8", "eslint", "prettier"] if req in lowered
        ],
        review_requirements=[req for req in ["review", "approval"] if req in lowered],
    )


def _default_recommendations(state: RepositoryAnalysisState) -> list[RuleRecommendation]:
    """Return a minimal, deterministic set of diff-aware rules."""
    recommendations: list[RuleRecommendation] = []

    # Require tests when source code changes.
    recommendations.append(
        RuleRecommendation(
            yaml_rule=textwrap.dedent(
                """
                description: "Require tests when code changes"
                enabled: true
                severity: medium
                event_types:
                  - pull_request
                validators:
                  - type: diff_pattern
                    parameters:
                      file_patterns:
                        - "**/*.py"
                        - "**/*.ts"
                        - "**/*.tsx"
                        - "**/*.js"
                        - "**/*.go"
                  - type: related_tests
                    parameters:
                      search_paths:
                        - "**/tests/**"
                        - "**/*_test.py"
                        - "**/*.spec.ts"
                        - "**/*.test.js"
                actions:
                  - type: warn
                    parameters:
                      message: "Please include or update tests for code changes."
                """
            ).strip(),
            confidence=0.74,
            reasoning="Default guardrail for code changes without tests.",
            strategy_used="static",
        )
    )

    # Require description and linked issue in PR body.
    recommendations.append(
        RuleRecommendation(
            yaml_rule=textwrap.dedent(
                """
                description: "Ensure PRs include context"
                enabled: true
                severity: low
                event_types:
                  - pull_request
                validators:
                  - type: required_field_in_diff
                    parameters:
                      field: "body"
                      pattern: "(?i)(summary|context|issue)"
                actions:
                  - type: warn
                    parameters:
                      message: "Add a short summary and linked issue in the PR body."
                """
            ).strip(),
            confidence=0.68,
            reasoning="Encourage context for reviewers; lightweight default.",
            strategy_used="static",
        )
    )

    # If no CODEOWNERS, suggest one for shared ownership signals.
    if not state.repository_features.has_codeowners:
        recommendations.append(
            RuleRecommendation(
                yaml_rule=textwrap.dedent(
                    """
                    description: "Flag missing CODEOWNERS entries"
                    enabled: true
                    severity: low
                    event_types:
                      - pull_request
                    validators:
                      - type: diff_pattern
                        parameters:
                          file_patterns:
                            - "**/*"
                    actions:
                      - type: warn
                        parameters:
                          message: "Consider adding CODEOWNERS to clarify ownership."
                    """
                ).strip(),
                confidence=0.6,
                reasoning="Repository lacks CODEOWNERS; gentle nudge to add.",
                strategy_used="static",
            )
        )

    return recommendations


def _render_rules_yaml(recommendations: list[RuleRecommendation]) -> str:
    """Combine rule YAML snippets into a single YAML document."""
    yaml_blocks = [rec.yaml_rule.strip() for rec in recommendations]
    return "\n\n---\n\n".join(yaml_blocks)


def _default_pr_plan(state: RepositoryAnalysisState) -> PullRequestPlan:
    """Create a default PR plan."""
    return PullRequestPlan(
        branch_name="watchflow/rules",
        base_branch="main",
        commit_message="chore: add Watchflow rules",
        pr_title="Add Watchflow rules",
        pr_body="This PR adds Watchflow rule recommendations generated by Watchflow.",
    )


def validate_recommendations(state: RepositoryAnalysisState) -> None:
    """Ensure generated YAML is valid."""
    for rec in state.recommendations:
        yaml.safe_load(rec.yaml_rule)


def summarize_analysis(
    state: RepositoryAnalysisState, request: RepositoryAnalysisRequest
) -> RepositoryAnalysisResponse:
    """Build the final response."""
    rules_yaml = _render_rules_yaml(state.recommendations)
    pr_plan = state.pr_plan or _default_pr_plan(state)
    analysis_summary: dict[str, Any] = {
        "repository_features": state.repository_features.model_dump(),
        "contributing": state.contributing_analysis.model_dump(),
        "pr_samples": [pr.model_dump() for pr in state.pr_samples[: request.max_prs]],
    }

    return RepositoryAnalysisResponse(
        repository_full_name=state.repository_full_name,
        rules_yaml=rules_yaml,
        recommendations=state.recommendations,
        pr_plan=pr_plan,
        analysis_summary=analysis_summary,
    )
