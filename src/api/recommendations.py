import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.agents import get_agent
from src.agents.repository_analysis_agent.models import (
    ProceedWithPullRequestRequest,
    ProceedWithPullRequestResponse,
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
)
from src.core.utils.caching import get_cache, set_cache
from src.core.utils.logging import log_structured
from src.integrations.github.api import github_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/v1/rules/recommend",
    response_model=RepositoryAnalysisResponse,
    summary="Analyze repository and recommend rules",
    description="Analyzes a GitHub repository and generates personalized Watchflow rule recommendations",
)
async def recommend_rules(
    request: RepositoryAnalysisRequest,
    req: Request,
) -> RepositoryAnalysisResponse:
    """
    Analyze a repository and generate Watchflow rule recommendations.

    This endpoint analyzes the repository structure, contributing guidelines,
    and patterns to recommend appropriate governance rules.

    Args:
        request: Repository analysis request with repository identifier
        req: FastAPI request object for logging

    Returns:
        Repository analysis response with recommendations

    Raises:
        HTTPException: If analysis fails or repository is invalid
    """
    try:
        if not request.repository_full_name or "/" not in request.repository_full_name:
            raise HTTPException(status_code=400, detail="Invalid repository name format. Expected 'owner/repo'")

        cache_key = f"repo_analysis:{request.repository_full_name}"
        cached_result = await get_cache(cache_key)

        if cached_result:
            log_structured(
                logger,
                "cache_hit",
                operation="repository_analysis",
                subject_ids=[request.repository_full_name],
                cached=True,
            )
            return RepositoryAnalysisResponse(**cached_result)

        agent = get_agent("repository_analysis")

        log_structured(
            logger,
            "analysis_started",
            operation="repository_analysis",
            subject_ids=[request.repository_full_name],
            installation_id=request.installation_id,
        )

        result = await agent.execute(
            repository_full_name=request.repository_full_name,
            installation_id=request.installation_id,
        )

        if not result.success:
            log_structured(
                logger,
                "analysis_failed",
                operation="repository_analysis",
                subject_ids=[request.repository_full_name],
                decision="failed",
                error=result.message,
            )
            raise HTTPException(status_code=500, detail=result.message)

        analysis_response = result.data.get("analysis_response")
        if not analysis_response:
            raise HTTPException(status_code=500, detail="No analysis response generated")

        await set_cache(cache_key, analysis_response.model_dump(), ttl=3600)

        log_structured(
            logger,
            "analysis_completed",
            operation="repository_analysis",
            subject_ids=[request.repository_full_name],
            decision="success",
            recommendations_count=len(analysis_response.recommendations),
            latency_ms=result.metadata.get("execution_time_ms", 0),
        )

        return analysis_response

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in recommend_rules endpoint: {e}")
        log_structured(
            logger,
            "analysis_error",
            operation="repository_analysis",
            subject_ids=[request.repository_full_name] if request else [],
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e


@router.post(
    "/v1/rules/recommend/proceed-with-pr",
    response_model=ProceedWithPullRequestResponse,
    summary="Create a PR with generated Watchflow rules",
    description="Creates a branch, commits rules.yaml, and opens a PR using either installation or user token.",
)
async def proceed_with_pr(request: ProceedWithPullRequestRequest) -> ProceedWithPullRequestResponse:
    if not request.repository_full_name:
        raise HTTPException(status_code=400, detail="repository_full_name or repository_url is required")
    if not request.installation_id and not request.user_token:
        raise HTTPException(status_code=400, detail="installation_id or user_token is required")

    repo = request.repository_full_name
    auth_ctx = {"installation_id": request.installation_id, "user_token": request.user_token}

    repo_data = await github_client.get_repository(repo, **auth_ctx)
    base_branch = request.base_branch or (repo_data or {}).get("default_branch", "main")

    base_sha = await github_client.get_git_ref_sha(repo, base_branch, **auth_ctx)
    if not base_sha:
        log_structured(
            logger,
            "base_branch_resolution_failed",
            operation="proceed_with_pr",
            subject_ids=[repo],
            base_branch=base_branch,
            error="Unable to resolve base branch SHA",
        )
        raise HTTPException(status_code=400, detail=f"Unable to resolve base branch '{base_branch}'")

    # Check if branch already exists
    existing_branch_sha = await github_client.get_git_ref_sha(repo, request.branch_name, **auth_ctx)
    if existing_branch_sha:
        # Branch exists - use it
        log_structured(
            logger,
            "branch_already_exists",
            operation="proceed_with_pr",
            subject_ids=[repo],
            branch=request.branch_name,
            existing_sha=existing_branch_sha,
        )
    else:
        # Create new branch
        created_ref = await github_client.create_git_ref(repo, request.branch_name, base_sha, **auth_ctx)
        if not created_ref:
            log_structured(
                logger,
                "branch_creation_failed",
                operation="proceed_with_pr",
                subject_ids=[repo],
                branch=request.branch_name,
                base_sha=base_sha,
                error="Failed to create branch",
            )
            raise HTTPException(
                status_code=400, detail=f"Failed to create branch '{request.branch_name}'. It may already exist."
            )

    file_result = await github_client.create_or_update_file(
        repo_full_name=repo,
        path=request.file_path,
        content=request.rules_yaml,
        message=request.commit_message,
        branch=request.branch_name,
        **auth_ctx,
    )
    if not file_result:
        log_structured(
            logger,
            "file_creation_failed",
            operation="proceed_with_pr",
            subject_ids=[repo],
            branch=request.branch_name,
            file_path=request.file_path,
            error="Failed to create or update file",
        )
        raise HTTPException(status_code=400, detail="Failed to create or update rules file")

    pr = await github_client.create_pull_request(
        repo_full_name=repo,
        title=request.pr_title,
        head=request.branch_name,
        base=base_branch,
        body=request.pr_body,
        **auth_ctx,
    )
    if not pr:
        log_structured(
            logger,
            "pr_creation_failed",
            operation="proceed_with_pr",
            subject_ids=[repo],
            branch=request.branch_name,
            base_branch=base_branch,
            error="Failed to create pull request",
        )
        raise HTTPException(status_code=400, detail="Failed to create pull request")

    pr_url = pr.get("html_url", "")
    if not pr_url:
        log_structured(
            logger,
            "pr_url_missing",
            operation="proceed_with_pr",
            subject_ids=[repo],
            pr_data=pr,
            error="PR created but html_url is missing",
        )
        raise HTTPException(status_code=500, detail="PR was created but URL is missing")

    log_structured(
        logger,
        "proceed_with_pr_completed",
        operation="proceed_with_pr",
        subject_ids=[repo],
        decision="success",
        branch=request.branch_name,
        pr_number=pr.get("number"),
    )

    return ProceedWithPullRequestResponse(
        pull_request_url=pr.get("html_url", ""),
        branch_name=request.branch_name,
        base_branch=base_branch,
        file_path=request.file_path,
        commit_sha=(file_result.get("commit") or {}).get("sha"),
    )


@router.get("/v1/rules/recommend/{repository_full_name}")
async def get_cached_recommendations(repository_full_name: str) -> JSONResponse:
    """
    Get cached recommendations for a repository.

    Args:
        repository_full_name: Full repository name (owner/repo)

    Returns:
        Cached analysis results or 404 if not found
    """
    cache_key = f"repo_analysis:{repository_full_name}"
    cached_result = await get_cache(cache_key)

    if not cached_result:
        raise HTTPException(status_code=404, detail="No cached analysis found for repository")

    return JSONResponse(content=cached_result)
