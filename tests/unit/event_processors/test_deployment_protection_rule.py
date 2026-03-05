"""Unit tests for DeploymentProtectionRuleProcessor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import EventType
from src.event_processors.deployment_protection_rule import (
    AGENT_TIMEOUT_SECONDS,
    DeploymentProtectionRuleProcessor,
)
from src.rules.models import Rule, RuleSeverity
from src.tasks.task_queue import Task


def _make_deployment_rule() -> Rule:
    return Rule(
        description="Test deployment rule",
        enabled=True,
        severity=RuleSeverity.MEDIUM,
        event_types=[EventType.DEPLOYMENT],
        parameters={},
    )


@pytest.fixture
def mock_agent():
    return AsyncMock()


@pytest.fixture
def processor(monkeypatch, mock_agent):
    monkeypatch.setattr("src.event_processors.deployment_protection_rule.get_agent", lambda x: mock_agent)
    monkeypatch.setattr(
        "src.event_processors.deployment_protection_rule.get_deployment_scheduler",
        lambda: MagicMock(add_pending_deployment=AsyncMock()),
    )
    proc = DeploymentProtectionRuleProcessor()
    proc.github_client = AsyncMock()
    proc.rule_provider = AsyncMock()
    return proc


@pytest.fixture
def task():
    t = MagicMock(spec=Task)
    t.repo_full_name = "owner/repo"
    t.installation_id = 123
    t.payload = {
        "environment": "production",
        "deployment": {"id": 456, "environment": "production", "creator": {}},
        "deployment_callback_url": "https://api.github.com/repos/owner/repo/deployments/456",
        "repository": {"full_name": "owner/repo"},
        "organization": {},
    }
    return t


@pytest.mark.asyncio
async def test_exception_calls_fallback_approval(processor, mock_agent, task):
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    mock_agent.execute.side_effect = RuntimeError("agent failed")
    processor.github_client.review_deployment_protection_rule.return_value = {"status": "success"}

    result = await processor.process(task)

    assert result.success is False
    assert result.error == "agent failed"
    processor.github_client.review_deployment_protection_rule.assert_called_once()
    call_kwargs = processor.github_client.review_deployment_protection_rule.call_args.kwargs
    assert call_kwargs["state"] == "approved"
    assert "fallback" in call_kwargs["comment"].lower()


@pytest.mark.asyncio
async def test_exception_without_callback_skips_approval(processor, mock_agent):
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 123
    task.payload = {
        "environment": "production",
        "deployment": {"id": 456},
        "deployment_callback_url": None,
        "repository": {},
    }
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    mock_agent.execute.side_effect = RuntimeError("agent failed")

    result = await processor.process(task)

    assert result.success is False
    processor.github_client.review_deployment_protection_rule.assert_not_called()


@pytest.mark.asyncio
async def test_validation_rejects_invalid_callback_url(processor, mock_agent):
    """Invalid callback URL prevents API calls even when rules exist and violations are found."""
    task = MagicMock(spec=Task)
    task.repo_full_name = "owner/repo"
    task.installation_id = 123
    task.payload = {
        "environment": "production",
        "deployment": {"id": 456},
        "deployment_callback_url": "not-a-valid-url",
        "repository": {},
    }
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    mock_agent.execute.return_value = MagicMock(
        data={
            "evaluation_result": MagicMock(
                violations=[
                    {
                        "rule_description": "Deploy only during business hours",
                        "message": "Deployment outside allowed time",
                    }
                ]
            )
        }
    )

    result = await processor.process(task)

    assert result.success is False
    assert len(result.violations) == 1
    processor.github_client.review_deployment_protection_rule.assert_not_called()


def test_is_valid_callback_url():
    assert DeploymentProtectionRuleProcessor._is_valid_callback_url("https://api.github.com/callback") is True
    assert DeploymentProtectionRuleProcessor._is_valid_callback_url("http://localhost/callback") is True
    assert DeploymentProtectionRuleProcessor._is_valid_callback_url("") is False
    assert DeploymentProtectionRuleProcessor._is_valid_callback_url(None) is False
    assert DeploymentProtectionRuleProcessor._is_valid_callback_url("ftp://invalid") is False


def test_is_valid_environment():
    assert DeploymentProtectionRuleProcessor._is_valid_environment("production") is True
    assert DeploymentProtectionRuleProcessor._is_valid_environment("") is False
    assert DeploymentProtectionRuleProcessor._is_valid_environment(None) is False


@pytest.mark.asyncio
async def test_timeout_triggers_fallback_approval(processor, mock_agent, task):
    """When agent exceeds AGENT_TIMEOUT_SECONDS, fallback approval is triggered."""
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    processor.github_client.review_deployment_protection_rule.return_value = {"status": "success"}

    with patch(
        "src.event_processors.deployment_protection_rule.execute_with_timeout",
        side_effect=TimeoutError(f"Agent execution timed out after {AGENT_TIMEOUT_SECONDS}s"),
    ):
        result = await processor.process(task)

    assert result.success is False
    assert "timed out" in result.error.lower()
    processor.github_client.review_deployment_protection_rule.assert_called_once()
    call_kwargs = processor.github_client.review_deployment_protection_rule.call_args.kwargs
    assert call_kwargs["state"] == "approved"
    assert "fallback" in call_kwargs["comment"].lower()


@pytest.mark.asyncio
async def test_retry_exhaustion_returns_failure(processor, mock_agent, task):
    """When review_deployment_protection_rule returns None and retries exhaust, process returns failure."""
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    mock_agent.execute.side_effect = RuntimeError("agent failed")
    processor.github_client.review_deployment_protection_rule.return_value = None

    result = await processor.process(task)

    assert result.success is False
    assert "agent failed" in result.error
    assert "fallback" in result.error.lower()
    assert processor.github_client.review_deployment_protection_rule.call_count >= 1


@pytest.mark.asyncio
async def test_time_based_violations_forwarded_to_scheduler(processor, mock_agent, task):
    """Violations matching time-based keywords are forwarded to the deployment scheduler."""
    mock_scheduler = MagicMock(add_pending_deployment=AsyncMock())
    with patch(
        "src.event_processors.deployment_protection_rule.get_deployment_scheduler",
        return_value=mock_scheduler,
    ):
        processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
        mock_agent.execute.return_value = MagicMock(
            data={
                "evaluation_result": MagicMock(
                    violations=[
                        {"rule_description": "Deploy only during business hours", "message": "Outside allowed time"}
                    ]
                )
            }
        )

        result = await processor.process(task)

    assert result.success is False
    assert len(result.violations) == 1
    mock_scheduler.add_pending_deployment.assert_called_once()
    call_args = mock_scheduler.add_pending_deployment.call_args[0][0]
    assert call_args["deployment_id"] == 456
    assert call_args["repo"] == "owner/repo"
    assert len(call_args["time_based_violations"]) == 1
    assert "business hours" in call_args["time_based_violations"][0]["rule_description"]


@pytest.mark.asyncio
async def test_happy_path_with_violations_rejects(processor, mock_agent, task):
    """When agent returns violations, deployment is rejected via review API."""
    processor.rule_provider.get_rules.return_value = [_make_deployment_rule()]
    mock_agent.execute.return_value = MagicMock(
        data={
            "evaluation_result": MagicMock(
                violations=[{"rule_description": "No deployment on weekends", "message": "Deployment blocked"}]
            )
        }
    )
    processor.github_client.review_deployment_protection_rule.return_value = {"status": "success"}

    result = await processor.process(task)

    assert result.success is False
    assert len(result.violations) == 1
    processor.github_client.review_deployment_protection_rule.assert_called_once()
    call_kwargs = processor.github_client.review_deployment_protection_rule.call_args.kwargs
    assert call_kwargs["state"] == "rejected"
    assert "weekends" in call_kwargs["comment"].lower()
