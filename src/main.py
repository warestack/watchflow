import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.auth import router as auth_api_router
from src.api.recommendations import router as recommendations_api_router
from src.api.repos import router as repos_api_router
from src.api.rules import router as rules_api_router
from src.api.scheduler import router as scheduler_api_router
from src.core.config import config
from src.core.models import EventType
from src.tasks.scheduler.deployment_scheduler import get_deployment_scheduler
from src.tasks.task_queue import task_queue
from src.webhooks.dispatcher import dispatcher
from src.webhooks.handlers.check_run import CheckRunEventHandler
from src.webhooks.handlers.deployment import DeploymentEventHandler
from src.webhooks.handlers.deployment_protection_rule import (
    DeploymentProtectionRuleEventHandler,
)
from src.webhooks.handlers.deployment_review import DeploymentReviewEventHandler
from src.webhooks.handlers.deployment_status import DeploymentStatusEventHandler
from src.webhooks.handlers.issue_comment import IssueCommentEventHandler
from src.webhooks.handlers.pull_request import PullRequestEventHandler
from src.webhooks.handlers.push import PushEventHandler
from src.webhooks.router import router as webhook_router

# --- Application Setup ---

# Configure structlog for JSON logging (Phase 5: Observability)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

# Silence noisy libraries (Phase 5: Production readiness)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# Set root logger to configured level
logging.basicConfig(
    level=getattr(logging, config.logging.level),
    format="%(message)s",  # structlog handles formatting
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan manager for startup and shutdown logic."""
    # Startup logic
    logging.info("Watchflow application starting up...")

    # Start background task workers
    await task_queue.start_workers(num_workers=5)

    # Start deployment scheduler
    await get_deployment_scheduler().start()

    # Register event handlers
    pull_request_handler = PullRequestEventHandler()
    push_handler = PushEventHandler()
    check_run_handler = CheckRunEventHandler()
    issue_comment_handler = IssueCommentEventHandler()
    deployment_handler = DeploymentEventHandler()
    deployment_status_handler = DeploymentStatusEventHandler()
    deployment_review_handler = DeploymentReviewEventHandler()
    deployment_protection_rule_handler = DeploymentProtectionRuleEventHandler()

    dispatcher.register_handler(EventType.PULL_REQUEST, pull_request_handler.handle)
    dispatcher.register_handler(EventType.PUSH, push_handler.handle)
    dispatcher.register_handler(EventType.CHECK_RUN, check_run_handler.handle)
    dispatcher.register_handler(EventType.ISSUE_COMMENT, issue_comment_handler.handle)
    dispatcher.register_handler(EventType.DEPLOYMENT, deployment_handler.handle)
    dispatcher.register_handler(EventType.DEPLOYMENT_STATUS, deployment_status_handler.handle)
    dispatcher.register_handler(EventType.DEPLOYMENT_REVIEW, deployment_review_handler.handle)
    dispatcher.register_handler(EventType.DEPLOYMENT_PROTECTION_RULE, deployment_protection_rule_handler.handle)

    logging.info("Event handlers registered, background workers started, and deployment scheduler started.")

    yield

    # Shutdown logic
    logging.info("Watchflow application shutting down...")

    # Stop deployment scheduler
    await get_deployment_scheduler().stop()

    # Stop background workers
    await task_queue.stop_workers()

    logging.info("Background workers and deployment scheduler stopped.")


app = FastAPI(
    title="Watchflow",
    description="Agentic GitHub Guardrails.",
    version="0.1.0",
    lifespan=lifespan,
)

# We explicitly allow all origins ("*") to prevent the browser from blocking requests
# from your local file system or different localhost ports.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Explicitly allow all for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include Routers ---

app.include_router(webhook_router, prefix="/webhooks", tags=["GitHub Webhooks"])
app.include_router(rules_api_router, prefix="/api/v1", tags=["Public API"])
app.include_router(recommendations_api_router, prefix="/api/v1", tags=["Recommendations API"])
app.include_router(auth_api_router, prefix="/api/v1", tags=["Authentication API"])
app.include_router(repos_api_router, prefix="/api/v1", tags=["Repositories API"])
app.include_router(scheduler_api_router, prefix="/api/v1/scheduler", tags=["Scheduler API"])

# --- Root Endpoint ---


@app.get("/", tags=["Health Check"])
async def read_root():
    """A simple health check endpoint to confirm the service is running."""
    return {"status": "ok", "message": "Watchflow agents are running."}


# --- Health Check Endpoints ---


@app.get("/health/tasks", tags=["Health Check"])
async def health_tasks():
    """Check the status of background tasks."""
    tasks = task_queue.tasks.values()
    pending_count = sum(1 for t in tasks if t.status.value == "pending")
    running_count = sum(1 for t in tasks if t.status.value == "running")
    completed_count = sum(1 for t in tasks if t.status.value == "completed")
    failed_count = sum(1 for t in tasks if t.status.value == "failed")

    return {
        "task_queue_status": "running",
        "workers": len(task_queue.workers),
        "tasks": {
            "pending": pending_count,
            "running": running_count,
            "completed": completed_count,
            "failed": failed_count,
            "total": len(tasks),
        },
    }


@app.get("/health/scheduler", tags=["Health Check"])
async def health_scheduler():
    """Check the status of the deployment scheduler."""
    return get_deployment_scheduler().get_status()
