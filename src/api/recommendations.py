import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.agents import get_agent
from src.agents.repository_analysis_agent.models import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
)
from src.core.utils.caching import get_cache, set_cache
from src.core.utils.logging import log_structured

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
