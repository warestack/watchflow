from collections.abc import Callable
from typing import Any, TypedDict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from giturlparse import parse  # type: ignore
from pydantic import BaseModel, Field, HttpUrl

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent
from src.api.dependencies import get_current_user_optional
from src.api.rate_limit import rate_limiter

# Internal: User model, auth assumed present—see core/api for details.
from src.core.models import User
from src.integrations.github.api import github_client

# 
from src.rules.ai_rules_scan import (
    scan_repo_for_ai_rule_files,
    translate_ai_rule_files_to_yaml,
)
import yaml

logger = structlog.get_logger()

router = APIRouter(prefix="/rules", tags=["Recommendations"])

# --- Models ---  # API schema—keep in sync with frontend expectations.


class AnalyzeRepoRequest(BaseModel):
    """
    Payload for repository analysis.

    Attributes:
        repo_url (HttpUrl): Full URL of the GitHub repository (e.g., https://github.com/pallets/flask).
        force_refresh (bool): Bypass cache if true (Not yet implemented).
        github_token (str, optional): GitHub Personal Access Token for authenticated requests (higher rate limits).
        installation_id (int, optional): GitHub App installation ID for context in generated PR links.
    """

    repo_url: HttpUrl = Field(
        ..., description="Full URL of the GitHub repository (e.g., https://github.com/pallets/flask)"
    )
    force_refresh: bool = Field(False, description="Bypass cache if true (Not yet implemented)")
    github_token: str | None = Field(
        None, description="Optional GitHub Personal Access Token for authenticated requests (higher rate limits)"
    )
    installation_id: int | None = Field(
        None, description="GitHub App installation ID (optional, used for landing page links in PR body)"
    )


class AnalysisResponse(BaseModel):
    """
    Standardized response for the frontend.

    Attributes:
        rules_yaml (str): Generated rules in YAML format.
        pr_plan (dict | str): Structured PR plan data (dict) or markdown string (for backward compatibility).
        analysis_summary (dict): Hygiene metrics and analysis insights.
        analysis_report (str): Agentic markdown report of repository analysis.
        rule_reasonings (dict): Map of rule descriptions to their reasoning/justifications.
        warnings (list[str]): List of warnings about incomplete data or rate limits.
    """

    rules_yaml: str
    pr_plan: dict[str, Any] | str  # Can be dict (new) or str (backward compat)
    analysis_summary: dict[str, Any]
    analysis_report: str | None = None
    rule_reasonings: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, description="Warnings about incomplete data or rate limits")


class ProceedWithPRRequest(BaseModel):
    """
    Request payload for creating a PR with recommended rules.

    Note: Authentication can be provided via:
    - Authorization header (Bearer token) - recommended for users creating PRs before app installation
    - installation_id in payload - for GitHub App installations
    - github_token in payload - alternative to Authorization header

    Attributes:
        repository_full_name (str): Repository in 'owner/repo' format.
        rules_yaml (str): YAML content for the rules file.
        installation_id (int, optional): GitHub App installation ID for authentication (not required if user token provided).
        github_token (str, optional): GitHub Personal Access Token (alternative to Authorization header).
        branch_name (str, optional): Branch name to create (default: "watchflow/rules").
        base_branch (str, optional): Base branch for PR (default: fetched from repo).
        file_path (str, optional): Path for rules file (default: ".watchflow/rules.yaml").
        commit_message (str, optional): Commit message (default: auto-generated).
        pr_title (str, optional): PR title (default: auto-generated).
        pr_body (str, optional): PR body (default: auto-generated).
    """

    repository_full_name: str = Field(..., description="Repository in 'owner/repo' format")
    rules_yaml: str = Field(..., description="YAML content for the rules file")
    installation_id: int | None = Field(
        None,
        description="GitHub App installation ID (optional if user token provided via header or github_token field)",
    )
    github_token: str | None = Field(
        None, description="GitHub Personal Access Token (optional if provided via Authorization header)"
    )
    branch_name: str = Field("watchflow/rules", description="Branch name to create")
    base_branch: str | None = Field(None, description="Base branch for PR (default: repository default branch)")
    file_path: str = Field(".watchflow/rules.yaml", description="Path for rules file")
    commit_message: str | None = Field(None, description="Commit message (default: auto-generated)")
    pr_title: str | None = Field(None, description="PR title (default: auto-generated)")
    pr_body: str | None = Field(None, description="PR body (default: auto-generated)")


class ProceedWithPRResponse(BaseModel):
    """
    Response from PR creation endpoint.

    Attributes:
        pull_request_url (str): URL of the created pull request.
        pull_request_number (int): PR number.
        branch_name (str): Branch name that was created.
        base_branch (str): Base branch for the PR.
        file_path (str): Path of the rules file.
        commit_sha (str, optional): SHA of the commit that added the rules file.
    """

    pull_request_url: str = Field(..., description="URL of the created pull request")
    pull_request_number: int = Field(..., description="PR number")
    branch_name: str = Field(..., description="Branch name that was created")
    base_branch: str = Field(..., description="Base branch for the PR")
    file_path: str = Field(..., description="Path of the rules file")
    commit_sha: str | None = Field(None, description="SHA of the commit that added the rules file")


# --- Helpers ---  # Utility—URL parsing brittle if GitHub changes format.


class MetricConfig(TypedDict):
    name: str
    key: str
    category: str
    thresholds: dict[str, float]
    explanation: Callable[[float | int], str]

class ScanAIFilesRequest(BaseModel):
    """
    Payload for scanning a repo for AI assistant rule files (Cursor, Claude, Copilot, etc.).
    """

    repo_url: HttpUrl = Field(
        ..., description="Full URL of the GitHub repository (e.g., https://github.com/owner/repo)"
    )
    github_token: str | None = Field(
        None, description="Optional GitHub Personal Access Token (higher rate limits / private repos)"
    )
    installation_id: int | None = Field(
        None, description="GitHub App installation ID (optional; used to get installation token)"
    )
    include_content: bool = Field(
        False, description="If True, include file content in response (for translation pipeline)"
    )


class ScanAIFilesCandidate(BaseModel):
    """A single candidate AI rule file."""

    path: str = Field(..., description="Repository-relative file path")
    has_keywords: bool = Field(..., description="True if content contains known AI-instruction keywords")
    content: str | None = Field(None, description="File content; only set when include_content was True")


class ScanAIFilesResponse(BaseModel):
    """Response from the scan-ai-files endpoint."""

    repo_full_name: str = Field(..., description="Repository in owner/repo form")
    ref: str = Field(..., description="Branch or ref that was scanned (e.g. main)")
    candidate_files: list[ScanAIFilesCandidate] = Field(
        default_factory=list, description="Candidate AI rule files matching path patterns"
    )
    warnings: list[str] = Field(default_factory=list, description="Warnings (e.g. rate limit, partial results)")

class TranslateAIFilesRequest(BaseModel):
    """Request for translating AI rule files into .watchflow rules YAML."""

    repo_url: HttpUrl = Field(..., description="Full URL of the GitHub repository")
    github_token: str | None = Field(None, description="Optional GitHub PAT")
    installation_id: int | None = Field(None, description="Optional GitHub App installation ID")


class TranslateAIFilesResponse(BaseModel):
    """Response from translate-ai-files endpoint."""

    repo_full_name: str = Field(..., description="Repository in owner/repo form")
    ref: str = Field(..., description="Branch scanned (e.g. main)")
    rules_yaml: str = Field(..., description="Merged rules YAML (rules: [...])")
    rules_count: int = Field(..., description="Number of rules in rules_yaml")
    ambiguous: list[dict[str, Any]] = Field(default_factory=list, description="Statements that could not be translated")
    warnings: list[str] = Field(default_factory=list)



def _get_severity_label(value: float, thresholds: dict[str, float]) -> tuple[str, str]:
    """
    Determine severity label and color based on value and thresholds.

    Returns:
        Tuple of (severity_label, color) where color is 'red', 'yellow', or 'green'
    """
    if value >= thresholds.get("high", 0.5):
        return ("High", "red")
    elif value >= thresholds.get("medium", 0.2):
        return ("Medium", "yellow")
    else:
        return ("Low", "green")


def _format_metric_value(metric_name: str, value: float | int) -> str:
    """Format metric value for display (percentage, count, etc.)."""
    if "rate" in metric_name.lower() or "coverage" in metric_name.lower():
        return f"{value:.0%}"
    return str(value)


def generate_analysis_report(hygiene_summary: dict[str, Any]) -> str:
    """
    Generate a professional markdown report of repository analysis findings.

    Creates a concise table with metrics, values, severity indicators, categories, and explanations.
    """
    if not hygiene_summary:
        return "## Repository Analysis\n\nNo analysis data available."

    report_lines = [
        "## Repository Analysis",
        "",
        "Analysis of repository health, risks, and trends based on recent PR history:",
        "",
        "| Metric | Value | Severity | Category | Explanation |",
        "|--------|-------|----------|----------|-------------|",
    ]

    # Define metric configurations
    metrics_config: list[MetricConfig] = [
        {
            "name": "Unlinked PR Rate",
            "key": "unlinked_issue_rate",
            "category": "Quality",
            "thresholds": {"high": 0.5, "medium": 0.2},
            "explanation": lambda v: (
                "Most PRs lack issue references, leading to governance gaps and reduced traceability."
                if v >= 0.5
                else "Some PRs lack issue references. Consider enforcing issue links for better traceability."
                if v >= 0.2
                else "Good traceability with most PRs linked to issues."
            ),
        },
        {
            "name": "Average PR Size",
            "key": "average_pr_size",
            "category": "Efficiency",
            "thresholds": {"high": 50, "medium": 20},
            "explanation": lambda v: (
                f"Very large PRs ({v} files changed) are difficult to review. Consider breaking into smaller changes."
                if v >= 50
                else f"Large PRs ({v} files changed) may benefit from splitting."
                if v >= 20
                else f"Small, digestible PRs ({v} files changed). Keep up the good work."
            ),
        },
        {
            "name": "First-Time Contributor Count",
            "key": "first_time_contributor_count",
            "category": "Community",
            "thresholds": {"high": 5, "medium": 2},
            "explanation": lambda v: (
                f"{v} new contributors in recent PRs. Great community growth!"
                if v >= 5
                else f"{v} new contributors observed. Consider outreach to grow the community."
                if v >= 2
                else "No new contributors have been observed. May indicate a lack of growth or outreach."
            ),
        },
        {
            "name": "CI Skip Rate",
            "key": "ci_skip_rate",
            "category": "Quality",
            "thresholds": {"high": 0.1, "medium": 0.05},
            "explanation": lambda v: (
                f"High rate of CI skips ({v:.0%}) bypasses quality checks. This is risky."
                if v >= 0.1
                else f"Some CI skips detected ({v:.0%}). Consider enforcing CI requirements."
                if v >= 0.05
                else "CI checks are consistently enforced. Good practice."
            ),
        },
        {
            "name": "CODEOWNERS Bypass Rate",
            "key": "codeowner_bypass_rate",
            "category": "Compliance",
            "thresholds": {"high": 0.3, "medium": 0.15},
            "explanation": lambda v: (
                f"High bypass rate ({v:.0%}) means critical code paths lack required approvals."
                if v >= 0.3
                else f"Some CODEOWNERS bypasses ({v:.0%}). Enforce approval requirements."
                if v >= 0.15
                else "CODEOWNERS requirements are well-enforced."
            ),
        },
        {
            "name": "New Code Test Coverage",
            "key": "new_code_test_coverage",
            "category": "Quality",
            "thresholds": {"high": 0.8, "medium": 0.5},
            "explanation": lambda v: (
                f"Excellent test coverage ({v:.0%}) for new code changes."
                if v >= 0.8
                else f"Moderate test coverage ({v:.0%}). Consider increasing test coverage."
                if v >= 0.5
                else f"Low test coverage ({v:.0%}). New code changes lack adequate tests."
            ),
        },
        {
            "name": "Issue Diff Mismatch Rate",
            "key": "issue_diff_mismatch_rate",
            "category": "Quality",
            "thresholds": {"high": 0.2, "medium": 0.1},
            "explanation": lambda v: (
                f"High mismatch rate ({v:.0%}) suggests PRs don't align with their linked issues."
                if v >= 0.2
                else f"Some mismatches ({v:.0%}) between issues and code changes."
                if v >= 0.1
                else "Good alignment between issues and code changes."
            ),
        },
        {
            "name": "Ghost Contributor Rate",
            "key": "ghost_contributor_rate",
            "category": "Community",
            "thresholds": {"high": 0.3, "medium": 0.15},
            "explanation": lambda v: (
                f"High ghost rate ({v:.0%}) indicates contributors not engaging with reviews."
                if v >= 0.3
                else f"Some contributors ({v:.0%}) don't respond to review feedback."
                if v >= 0.15
                else "Good contributor engagement with review processes."
            ),
        },
        {
            "name": "AI Generated Rate",
            "key": "ai_generated_rate",
            "category": "Quality",
            "thresholds": {"high": 0.2, "medium": 0.1},
            "explanation": lambda v: (
                f"High AI-generated content ({v:.0%}) may indicate low-effort contributions."
                if v >= 0.2
                else f"Some AI-generated content detected ({v:.0%}). Consider review processes."
                if v >= 0.1
                else "Low AI-generated content rate. Contributions appear human-authored."
            )
            if v is not None
            else "AI detection not available.",
        },
    ]

    for metric in metrics_config:
        value = hygiene_summary.get(metric["key"])
        if value is None:
            continue

        severity, color = _get_severity_label(value, metric["thresholds"])
        formatted_value = _format_metric_value(str(metric["name"]), value)
        explanation = metric["explanation"](value)

        report_lines.append(
            f"| {metric['name']} | {formatted_value} | {severity} | {metric['category']} | {explanation} |"
        )

    return "\n".join(report_lines)


def generate_pr_body(
    repo_full_name: str,
    recommendations: list[Any],
    hygiene_summary: dict[str, Any],
    rules_yaml: str,
    installation_id: int | None = None,
    analysis_report: str | None = None,
    rule_reasonings: dict[str, str] | None = None,
) -> str:
    """
    Generate a professional, concise PR body that helps maintainers understand and approve.

    Follows Matas' patterns: evidence-based, data-driven, professional tone, no emojis.
    """
    body_lines = [
        "## Add Watchflow Governance Rules",
        "",
        f"This PR adds automated governance rules for {repo_full_name} based on repository analysis of recent PR history and codebase patterns.",
        "",
        analysis_report or generate_analysis_report(hygiene_summary),
        "",
        "## Recommended Rules",
        "",
    ]

    # Add each recommendation concisely
    # Use agentic reasonings if available
    reasonings = rule_reasonings or {}

    for rec in recommendations:
        severity = rec.get("severity", "medium").title()
        description = rec.get("description", "")
        reasoning = reasonings.get(description, "")

        body_lines.extend(
            [
                f"### {description} - {severity}",
            ]
        )
        if reasoning:
            body_lines.extend(
                [
                    "",
                    f"**Rationale:** {reasoning}",
                ]
            )
        body_lines.append("")

    body_lines.extend(
        [
            "## Changes",
            "",
            "- Adds `.watchflow/rules.yaml` with the recommended governance rules",
            "",
            "## Next Steps",
            "",
            "1. Review the rules in `.watchflow/rules.yaml`",
            "2. Adjust parameters if needed",
            "3. Install the [Watchflow GitHub App](https://github.com/apps/watchflow) to enable automated enforcement",
            "4. Merge this PR to activate the rules",
            "",
            "---",
            "",
            "Generated by Watchflow repository analysis.",
        ]
    )

    return "\n".join(body_lines)


def generate_pr_title(recommendations: list[Any]) -> str:
    """
    Generate a professional, concise PR title based on recommendations.
    """
    if not recommendations:
        return "Add Watchflow governance rules"

    total_count = len(recommendations)
    high_count = sum(1 for r in recommendations if r.get("severity", "").lower() == "high")

    if high_count > 0:
        return f"Add Watchflow governance rules ({total_count} rules, {high_count} high-priority)"
    else:
        return f"Add Watchflow governance rules ({total_count} rules)"


def parse_repo_from_url(url: str) -> str:
    """
    Extracts 'owner/repo' from a full GitHub URL using giturlparse.

    Args:
        url: The full URL string (e.g., https://github.com/owner/repo.git)

    Returns:
        str: 'owner/repo'

    Raises:
        ValueError: If the URL is not a valid GitHub repository URL.
    """
    p = parse(str(url))
    if not p.valid or not p.owner or not p.repo or p.host not in {"github.com", "www.github.com"}:
        raise ValueError("Invalid GitHub repository URL. Must be in format 'https://github.com/owner/repo'.")
    return f"{p.owner}/{p.repo}"


def _ref_to_branch(ref: str | None) -> str | None:
    """Convert a full ref (e.g. refs/heads/feature-x) to branch name for use with GitHub API."""
    if not ref or not ref.strip():
        return None
    ref = ref.strip()
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :].strip() or None
    return ref


async def get_suggested_rules_from_repo(
    repo_full_name: str,
    installation_id: int | None,
    github_token: str | None,
    *,
    ref: str | None = None,
) -> tuple[str, int, list[dict[str, Any]], list[str]]:
    """
    Run agentic scan+translate for a repo (rules.md, etc. -> Watchflow YAML).
    Safe to call from event processors; returns empty result on any failure.
    Returns (rules_yaml, rules_count, ambiguous_list, rule_sources).
    When ref is provided (e.g. from push or PR head), scans that branch; otherwise uses default branch.
    """
    try:
        repo_data, repo_error = await github_client.get_repository(
            repo_full_name, installation_id=installation_id, user_token=github_token
        )
        if repo_error or not repo_data:
            return ("rules: []\n", 0, [], [])
        default_branch = repo_data.get("default_branch") or "main"
        scan_ref = _ref_to_branch(ref) if ref else default_branch
        if not scan_ref:
            scan_ref = default_branch

        tree_entries = await github_client.get_repository_tree(
            repo_full_name,
            ref=scan_ref,
            installation_id=installation_id,
            user_token=github_token,
            recursive=True,
        )
        if not tree_entries:
            return ("rules: []\n", 0, [], [])

        async def get_content(path: str):
            return await github_client.get_file_content(
                repo_full_name, path, installation_id, github_token, ref=scan_ref
            )

        raw_candidates = await scan_repo_for_ai_rule_files(
            tree_entries, fetch_content=True, get_file_content=get_content
        )
        candidates_with_content = [c for c in raw_candidates if c.get("content")]
        if not candidates_with_content:
            return ("rules: []\n", 0, [], [])

        rules_yaml, ambiguous, rule_sources = await translate_ai_rule_files_to_yaml(candidates_with_content)
        rules_count = 0
        try:
            parsed = yaml.safe_load(rules_yaml)
            rules_count = len(parsed.get("rules", [])) if isinstance(parsed, dict) else 0
        except Exception:
            pass
        return (rules_yaml, rules_count, ambiguous, rule_sources)
    except Exception as e:
        logger.warning("get_suggested_rules_from_repo_failed", repo=repo_full_name, error=str(e))
        return ("rules: []\n", 0, [], [])


# --- Endpoints ---  # Main API surface—keep stable for clients.


@router.post(
    "/recommend",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Repository for Governance Rules",
    description="Analyzes a public or private repository using AI agents. Public repos allow anonymous access.",
    dependencies=[Depends(rate_limiter)],
)
async def recommend_rules(
    request: Request, payload: AnalyzeRepoRequest, user: User | None = Depends(get_current_user_optional)
) -> AnalysisResponse:
    """
    Executes the Repository Analysis Agent to generate governance rules.

    This endpoint orchestrates the analysis flow:
    1. Validates the GitHub repository URL.
    2. Instantiates the `RepositoryAnalysisAgent`.
    3. Runs the agent to fetch metadata, analyze PR history, and generate rules.
    4. Returns a standardized response with YAML rules and a remediation plan.

    Args:
        request: The incoming HTTP request (used for IP logging).
        payload: The request body containing the repository URL.
        user: The authenticated user (optional).

    Returns:
        AnalysisResponse: The generated rules, PR plan, and analysis summary.

    Raises:
        HTTPException: 404 if repo not found, 429 if rate limited, 500 for internal errors.
    """
    repo_url_str = str(payload.repo_url)
    client_ip = request.client.host if request.client else "unknown"
    user_id = user.email if user else "Anonymous"

    logger.info("analysis_requested", repo_url=repo_url_str, user_id=user_id, ip=client_ip)

    # Step 1: Parse URL—fail fast if invalid.
    try:
        repo_full_name = parse_repo_from_url(repo_url_str)
    except ValueError as e:
        logger.warning("invalid_url_provided", ip=client_ip, url=repo_url_str, error=str(e))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    # Step 2: Rate limiting—in-memory for open-source version (no external dependencies).

    # Step 3: Extract GitHub token (User/body > installation_id > none)
    github_token = None
    if user and user.github_token:
        # Extract from SecretStr if present
        try:
            github_token = user.github_token.get_secret_value()
        except (AttributeError, TypeError):
            # Fallback if it's already a string
            github_token = str(user.github_token) if user.github_token else None
    elif payload.github_token:
        # Allow token to be passed directly in request body (alternative to Authorization header)
        github_token = payload.github_token
    elif payload.installation_id:
        # When installation_id is in URL (e.g. from welcome comment), use installation token so PAT is not required
        installation_token = await github_client.get_installation_access_token(payload.installation_id)
        if installation_token:
            github_token = installation_token
        # If installation token fails, proceed with None (public repo / low rate limits)

    # Step 4: Agent execution—public flow only. Private repo: expect 404/403, handled below.
    try:
        agent = RepositoryAnalysisAgent()
        result = await agent.execute(repo_full_name=repo_full_name, is_public=True, user_token=github_token)

    except Exception as e:
        logger.exception("agent_execution_failed", repo=repo_full_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal analysis engine error."
        ) from e

    # Step 5: Agent failures—distinguish not found, rate limit, internal error. Pass through agent messages if possible.
    if not result.success:
        error_msg = result.message.lower()

        if "not found" in error_msg or "404" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_full_name}' not found. It may be private or invalid.",
            )
        elif "rate limit" in error_msg or "429" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="System is currently rate-limited by GitHub. Please try again later.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Analysis failed: {result.message}"
            )

    # Step 6: Success—map agent state to the API response model.
    final_state = result.data  # The agent's execute method returns the final state

    # Generate rules_yaml from recommendations
    # RuleRecommendation now includes all required fields directly
    import yaml

    # Extract YAML fields from recommendations
    rules_list = []
    for rec in final_state.get("recommendations", []):
        rec_dict = rec.model_dump(exclude_none=True) if hasattr(rec, "model_dump") else rec
        rule_dict = {
            "description": rec_dict.get("description", ""),
            "enabled": rec_dict.get("enabled", True),
            "severity": rec_dict.get("severity", "medium"),
            "event_types": rec_dict.get("event_types", ["pull_request"]),
            "parameters": rec_dict.get("parameters", {}),
        }
        rules_list.append(rule_dict)

    rules_output = {"rules": rules_list}
    rules_yaml = yaml.dump(rules_output, indent=2, sort_keys=False)

    # Populate the analysis summary from hygiene metrics
    hygiene_summary = final_state.get("hygiene_summary")
    analysis_summary = (
        hygiene_summary.model_dump()
        if hygiene_summary and hasattr(hygiene_summary, "model_dump")
        else hygiene_summary or {}
    )

    # Get agentic outputs
    analysis_report = final_state.get("analysis_report")
    rule_reasonings = final_state.get("rule_reasonings", {})

    # Generate structured PR plan data (for frontend) and markdown (for backward compatibility)
    recommendations_list = final_state.get("recommendations", [])
    recommendations_dict = [
        rec.model_dump(exclude_none=True) if hasattr(rec, "model_dump") else rec for rec in recommendations_list
    ]

    # Generate markdown plan for backward compatibility
    pr_plan_lines = ["### Watchflow: Automated Governance Plan\n"]
    for rec in recommendations_list:
        rec_dict = rec.model_dump(exclude_none=True) if hasattr(rec, "model_dump") else rec
        description = rec_dict.get("description", "Unknown Rule")
        pr_plan_lines.append(f"- **Rule:** {description}")
    pr_plan_markdown = "\n".join(pr_plan_lines)

    # Generate PR body and title for proceed-with-pr endpoint
    # Use installation_id from request if provided (for landing page links)
    installation_id_from_request = getattr(payload, "installation_id", None)
    pr_title = generate_pr_title(recommendations_dict)
    pr_body = generate_pr_body(
        repo_full_name=repo_full_name,
        recommendations=recommendations_dict,
        hygiene_summary=analysis_summary,
        rules_yaml=rules_yaml,
        installation_id=installation_id_from_request,
        analysis_report=analysis_report,
        rule_reasonings=rule_reasonings,
    )

    # Create structured pr_plan object (frontend expects this)
    pr_plan = {
        "title": pr_title,
        "body": pr_body,
        "branch_name": "watchflow/rules",
        "base_branch": "main",  # Will be fetched from repo metadata
        "file_path": ".watchflow/rules.yaml",
        "commit_message": f"chore: add Watchflow governance rules ({len(recommendations_list)} rules)",
        "markdown": pr_plan_markdown,  # Keep markdown for backward compatibility
    }

    # Extract warnings from agent state
    warnings = final_state.get("warnings", [])

    return AnalysisResponse(
        rules_yaml=rules_yaml,
        pr_plan=pr_plan,
        analysis_summary=analysis_summary,
        analysis_report=analysis_report,
        rule_reasonings=rule_reasonings,
        warnings=warnings,
    )


@router.post(
    "/recommend/proceed-with-pr",
    response_model=ProceedWithPRResponse,
    status_code=status.HTTP_200_OK,
    summary="Create PR with Recommended Rules",
    description="Creates a pull request with the recommended Watchflow rules in the target repository.",
)
async def proceed_with_pr(
    payload: ProceedWithPRRequest, user: User | None = Depends(get_current_user_optional)
) -> ProceedWithPRResponse:
    """
    Endpoint to create a PR with recommended rules.

    Implementation:
    1. Validates required fields and authentication
    2. Fetches repository metadata (default branch)
    3. Gets base branch SHA
    4. Creates a new branch
    5. Commits the rules YAML file
    6. Creates a pull request with compelling body and title
    """
    from src.integrations.github.api import github_client

    # Extract authentication (priority: user token from header > github_token in payload > installation_id)
    installation_id = payload.installation_id
    user_token = None

    # Priority 1: User token from Authorization header
    if user and user.github_token:
        try:
            user_token = user.github_token.get_secret_value()
        except (AttributeError, TypeError):
            user_token = str(user.github_token) if user.github_token else None

    # Priority 2: GitHub token from request body (if not in header)
    if not user_token and payload.github_token:
        user_token = payload.github_token

    # Require at least one form of authentication
    if not installation_id and not user_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required. Provide either:\n"
                "1. Authorization header with Bearer token (GitHub Personal Access Token), or\n"
                "2. github_token in request body, or\n"
                "3. installation_id for GitHub App installations"
            ),
        )

    # Extract PR metadata from payload (with fallbacks)
    repo_full_name = payload.repository_full_name
    rules_yaml = payload.rules_yaml
    branch_name = payload.branch_name
    file_path = payload.file_path
    commit_message = payload.commit_message or "chore: add Watchflow governance rules"

    # Generate PR body with installation_id context if not provided
    if payload.pr_body:
        pr_body = payload.pr_body
    else:
        # Re-generate PR body with installation_id for landing page link
        # This requires parsing recommendations from rules_yaml or getting them from analysis
        # For now, use a simple fallback that includes the landing page link
        landing_url = "https://watchflow.dev"
        if installation_id:
            landing_url = f"https://watchflow.dev/analyze?installation_id={installation_id}&repo={repo_full_name}"
        elif repo_full_name:
            landing_url = f"https://watchflow.dev/analyze?repo={repo_full_name}"
        pr_body = f"Adds Watchflow rule recommendations based on repository analysis.\n\n**Need to update rules later?** [Analyze your repository again]({landing_url}) to get updated recommendations."

    pr_title = payload.pr_title or "Add Watchflow governance rules"

    try:
        # Step 1: Get repository metadata to find default branch
        repo_data, repo_error = await github_client.get_repository(
            repo_full_name=repo_full_name,
            installation_id=installation_id,
            user_token=user_token,
        )

        if repo_error:
            err_status = repo_error["status"]
            status_code = status.HTTP_429_TOO_MANY_REQUESTS if err_status == 403 else err_status
            if status_code not in (401, 403, 404, 429):
                status_code = status.HTTP_502_BAD_GATEWAY
            raise HTTPException(status_code=status_code, detail=repo_error["message"])

        base_branch = payload.base_branch or repo_data.get("default_branch", "main")

        # Step 2: Get base branch SHA
        base_sha = await github_client.get_git_ref_sha(
            repo_full_name=repo_full_name,
            ref=base_branch,
            installation_id=installation_id,
            user_token=user_token,
        )

        if not base_sha:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Base branch '{base_branch}' not found in repository.",
            )

        # Step 3: Create new branch (or use existing if it already exists)
        branch_result = await github_client.create_git_ref(
            repo_full_name=repo_full_name,
            ref=branch_name,
            sha=base_sha,
            installation_id=installation_id,
            user_token=user_token,
        )

        # If branch creation failed, check if branch already exists and use it
        if not branch_result:
            existing_branch_sha = await github_client.get_git_ref_sha(
                repo_full_name=repo_full_name,
                ref=branch_name,
                installation_id=installation_id,
                user_token=user_token,
            )
            if existing_branch_sha:
                logger.info(f"Branch '{branch_name}' already exists, will update file on existing branch")
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create branch '{branch_name}' and branch does not exist.",
                )

        # Step 4: Create/update file on the new branch
        file_result = await github_client.create_or_update_file(
            repo_full_name=repo_full_name,
            path=file_path,
            content=rules_yaml,
            message=commit_message,
            branch=branch_name,
            installation_id=installation_id,
            user_token=user_token,
        )

        if not file_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create file '{file_path}' on branch '{branch_name}'.",
            )

        # Step 5: Create pull request
        pr_result = await github_client.create_pull_request(
            repo_full_name=repo_full_name,
            title=pr_title,
            head=branch_name,
            base=base_branch,
            body=pr_body,
            installation_id=installation_id,
            user_token=user_token,
        )

        if not pr_result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create pull request from '{branch_name}' to '{base_branch}'.",
            )

        pr_url = pr_result.get("html_url", "")
        pr_number = pr_result.get("number", 0)

        logger.info(
            "pr_created_successfully",
            repo=repo_full_name,
            pr_number=pr_number,
            pr_url=pr_url,
            branch=branch_name,
        )

        return ProceedWithPRResponse(
            pull_request_url=pr_url,
            pull_request_number=pr_number,
            branch_name=branch_name,
            base_branch=base_branch,
            file_path=file_path,
            commit_sha=file_result.get("commit", {}).get("sha"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("pr_creation_failed", repo=repo_full_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create pull request. Please try again.",
        ) from e

@router.post(
    "/scan-ai-files",
    response_model=ScanAIFilesResponse,
    status_code=status.HTTP_200_OK,
    summary="Scan repository for AI rule files",
    description=(
        "Lists files matching *rules*.md, *guidelines*.md, *prompt*.md, .cursor/rules/*.mdc. "
        "Optionally fetches content and flags files that contain AI-instruction keywords."
    ),
    dependencies=[Depends(rate_limiter)],
)
async def scan_ai_rule_files(
    request: Request,
    payload: ScanAIFilesRequest,
    user: User | None = Depends(get_current_user_optional),
    ) -> ScanAIFilesResponse:
    """
    Scan a repository for AI assistant rule files (Cursor, Claude, Copilot, etc.).
    """
    repo_url_str = str(payload.repo_url)
    client_ip = request.client.host if request.client else "unknown"
    logger.info("scan_ai_files_requested", repo_url=repo_url_str, ip=client_ip)

    try:
        repo_full_name = parse_repo_from_url(repo_url_str)
    except ValueError as e:
        logger.warning("invalid_url_provided", url=repo_url_str, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    # Resolve token (same as recommend_rules)
    github_token = None
    if user and user.github_token:
        try:
            github_token = user.github_token.get_secret_value()
        except (AttributeError, TypeError):
            github_token = str(user.github_token) if user.github_token else None
    elif payload.github_token:
        github_token = payload.github_token
    elif payload.installation_id:
        installation_token = await github_client.get_installation_access_token(payload.installation_id)
        if installation_token:
            github_token = installation_token

    installation_id = payload.installation_id

    # Default branch
    repo_data, repo_error = await github_client.get_repository(
        repo_full_name, installation_id=installation_id, user_token=github_token
    )
    if repo_error:
        err_status = repo_error["status"]
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if err_status == 403 else err_status
        if status_code not in (401, 403, 404, 429):
            status_code = status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=status_code, detail=repo_error["message"])
    default_branch = repo_data.get("default_branch") or "main"
    ref = default_branch

    # Full tree
    tree_entries = await github_client.get_repository_tree(
        repo_full_name,
        ref=ref,
        installation_id=installation_id,
        user_token=github_token,
        recursive=True,
    )
    if not tree_entries:
        return ScanAIFilesResponse(
            repo_full_name=repo_full_name,
            ref=ref,
            candidate_files=[],
            warnings=["Could not load repository tree; check access and ref."],
        )

    # Optional content fetcher for keyword scan (and optionally include in response)
    async def get_content(path: str):
        return await github_client.get_file_content(
            repo_full_name, path, installation_id, github_token
        )

    # Always fetch content so has_keywords is set; strip content in response unless include_content
    raw_candidates = await scan_repo_for_ai_rule_files(
        tree_entries,
        fetch_content=True,
        get_file_content=get_content,
    )

    candidates = [
        ScanAIFilesCandidate(
            path=c["path"],
            has_keywords=c["has_keywords"],
            content=c["content"] if payload.include_content else None,
        )
        for c in raw_candidates
    ]

    return ScanAIFilesResponse(
        repo_full_name=repo_full_name,
        ref=ref,
        candidate_files=candidates,
        warnings=[],
    )

@router.post(
    "/translate-ai-files",
    response_model=TranslateAIFilesResponse,
    status_code=status.HTTP_200_OK,
    summary="Translate AI rule files to Watchflow YAML",
    description="Scans repo for AI rule files, extracts statements, maps or translates to .watchflow rules YAML.",
    dependencies=[Depends(rate_limiter)],
)
async def translate_ai_rule_files(
    request: Request,
    payload: TranslateAIFilesRequest,
    user: User | None = Depends(get_current_user_optional),
) -> TranslateAIFilesResponse:
    repo_url_str = str(payload.repo_url)
    logger.info("translate_ai_files_requested", repo_url=repo_url_str)

    try:
        repo_full_name = parse_repo_from_url(repo_url_str)
    except ValueError as e:
        logger.warning("invalid_url_provided", url=repo_url_str, error=str(e))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    github_token = None
    if user and user.github_token:
        try:
            github_token = user.github_token.get_secret_value()
        except (AttributeError, TypeError):
            github_token = str(user.github_token) if user.github_token else None
    elif payload.github_token:
        github_token = payload.github_token
    elif payload.installation_id:
        installation_token = await github_client.get_installation_access_token(payload.installation_id)
        if installation_token:
            github_token = installation_token
    installation_id = payload.installation_id

    repo_data, repo_error = await github_client.get_repository(
        repo_full_name, installation_id=installation_id, user_token=github_token
    )
    if repo_error:
        err_status = repo_error["status"]
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if err_status == 403 else err_status
        if status_code not in (401, 403, 404, 429):
            status_code = status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=status_code, detail=repo_error["message"])
    default_branch = repo_data.get("default_branch") or "main"
    ref = default_branch

    tree_entries = await github_client.get_repository_tree(
        repo_full_name, ref=ref, installation_id=installation_id, user_token=github_token, recursive=True
    )
    if not tree_entries:
        return TranslateAIFilesResponse(
            repo_full_name=repo_full_name,
            ref=ref,
            rules_yaml="rules: []\n",
            rules_count=0,
            ambiguous=[],
            warnings=["Could not load repository tree."],
        )

    async def get_content(path: str):
        return await github_client.get_file_content(repo_full_name, path, installation_id, github_token)

    raw_candidates = await scan_repo_for_ai_rule_files(
        tree_entries, fetch_content=True, get_file_content=get_content
    )
    candidates_with_content = [c for c in raw_candidates if c.get("content")]
    if not candidates_with_content:
        return TranslateAIFilesResponse(
            repo_full_name=repo_full_name,
            ref=ref,
            rules_yaml="rules: []\n",
            rules_count=0,
            ambiguous=[],
            warnings=["No AI rule file content could be loaded."],
        )

    rules_yaml, ambiguous, rule_sources = await translate_ai_rule_files_to_yaml(candidates_with_content)
    rules_count = rules_yaml.count("\n  - ") + (1 if rules_yaml.strip() != "rules: []" and "  - " in rules_yaml else 0)
    try:
        parsed = yaml.safe_load(rules_yaml)
        rules_count = len(parsed.get("rules", [])) if isinstance(parsed, dict) else 0
    except Exception:
        pass

    return TranslateAIFilesResponse(
        repo_full_name=repo_full_name,
        ref=ref,
        rules_yaml=rules_yaml,
        rules_count=rules_count,
        ambiguous=ambiguous,
        warnings=[],
    )