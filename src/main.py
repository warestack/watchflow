import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.rules import router as rules_api_router
from src.api.scheduler import router as scheduler_api_router
from src.core.config import config
from src.core.models import EventType
from src.tasks.scheduler.deployment_scheduler import deployment_scheduler
from src.tasks.task_queue import task_queue
from src.webhooks.dispatcher import dispatcher
from src.webhooks.handlers.check_run import CheckRunEventHandler
from src.webhooks.handlers.deployment import DeploymentEventHandler
from src.webhooks.handlers.deployment_protection_rule import DeploymentProtectionRuleEventHandler
from src.webhooks.handlers.deployment_review import DeploymentReviewEventHandler
from src.webhooks.handlers.deployment_status import DeploymentStatusEventHandler
from src.webhooks.handlers.issue_comment import IssueCommentEventHandler
from src.webhooks.handlers.pull_request import PullRequestEventHandler
from src.webhooks.handlers.push import PushEventHandler
from src.webhooks.router import router as webhook_router

# --- Application Setup ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)8s %(message)s",
)

app = FastAPI(
    title="Watchflow",
    description="Agentic GitHub Guardrails.",
    version="0.1.0",
)

# --- CORS Configuration ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=config.cors.headers,
)

# --- Include Routers ---

app.include_router(webhook_router, prefix="/webhooks", tags=["GitHub Webhooks"])
app.include_router(rules_api_router, prefix="/api/v1", tags=["Public API"])
app.include_router(scheduler_api_router, prefix="/api/v1/scheduler", tags=["Scheduler API"])

# --- Root Endpoint ---


@app.get("/", tags=["Health Check"])
async def read_root():
    """A simple health check endpoint to confirm the service is running."""
    return {"status": "ok", "message": "Watchflow agents are running."}


# --- Application Lifecycle ---


@app.on_event("startup")
async def startup_event():
    """Application startup logic."""
    print("Watchflow application starting up...")

    # Start background task workers
    await task_queue.start_workers(num_workers=5)

    # Start deployment scheduler
    await deployment_scheduler.start()

    # Register event handlers
    pull_request_handler = PullRequestEventHandler()
    push_handler = PushEventHandler()
    check_run_handler = CheckRunEventHandler()
    issue_comment_handler = IssueCommentEventHandler()
    deployment_handler = DeploymentEventHandler()
    deployment_status_handler = DeploymentStatusEventHandler()
    deployment_review_handler = DeploymentReviewEventHandler()
    deployment_protection_rule_handler = DeploymentProtectionRuleEventHandler()

    dispatcher.register_handler(EventType.PULL_REQUEST, pull_request_handler)
    dispatcher.register_handler(EventType.PUSH, push_handler)
    dispatcher.register_handler(EventType.CHECK_RUN, check_run_handler)
    dispatcher.register_handler(EventType.ISSUE_COMMENT, issue_comment_handler)
    dispatcher.register_handler(EventType.DEPLOYMENT, deployment_handler)
    dispatcher.register_handler(EventType.DEPLOYMENT_STATUS, deployment_status_handler)
    dispatcher.register_handler(EventType.DEPLOYMENT_REVIEW, deployment_review_handler)
    dispatcher.register_handler(EventType.DEPLOYMENT_PROTECTION_RULE, deployment_protection_rule_handler)

    print("Event handlers registered, background workers started, and deployment scheduler started.")

    # Start the deployment scheduler
    asyncio.create_task(deployment_scheduler.start_background_scheduler())
    logging.info("🚀 Deployment scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown logic."""
    print("Watchflow application shutting down...")

    # Stop deployment scheduler
    await deployment_scheduler.stop()

    # Stop background workers
    await task_queue.stop_workers()

    print("Background workers and deployment scheduler stopped.")


# --- Health Check Endpoints ---


@app.get("/health/tasks", tags=["Health Check"])
async def health_tasks():
    """Check the status of background tasks."""
    pending_count = len([t for t in task_queue.tasks.values() if t.status.value == "pending"])
    running_count = len([t for t in task_queue.tasks.values() if t.status.value == "running"])
    completed_count = len([t for t in task_queue.tasks.values() if t.status.value == "completed"])
    failed_count = len([t for t in task_queue.tasks.values() if t.status.value == "failed"])

    return {
        "task_queue_status": "running",
        "workers": len(task_queue.workers),
        "tasks": {
            "pending": pending_count,
            "running": running_count,
            "completed": completed_count,
            "failed": failed_count,
            "total": len(task_queue.tasks),
        },
    }


@app.get("/health/scheduler", tags=["Health Check"])
async def health_scheduler():
    """Check the status of the deployment scheduler."""
    return deployment_scheduler.get_status()
