
    ContributingGuidelinesAnalysis,
    PullRequestPlan,
    PullRequestSample,
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryAnalysisState,
    RepositoryFeatures,
    RuleRecommendation,
)

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

