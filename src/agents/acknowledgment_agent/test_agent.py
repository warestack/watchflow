"""
Test script for the Intelligent Acknowledgment Agent.
"""

import asyncio
import logging

import pytest
import structlog

from src.agents.acknowledgment_agent.agent import AcknowledgmentAgent

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


@pytest.mark.asyncio
async def test_acknowledgment_agent() -> None:
    """Test the intelligent acknowledgment agent with sample data."""

    # Create agent
    agent = AcknowledgmentAgent()

    # Sample data
    acknowledgment_reason = "Minor README update - fixing typo"
    commenter = "testuser"

    # Sample PR data
    pr_data = {
        "title": "Fix typo in README",
        "body": "Fixed a small typo in the documentation",
        "additions": 1,
        "deletions": 1,
        "files": [{"filename": "README.md", "status": "modified"}],
    }

    # Sample violations
    violations = [
        {
            "rule_id": "min-pr-approvals",
            "rule_name": "Minimum PR Approvals Required",
            "severity": "medium",
            "message": "PR requires at least 1 approval",
            "how_to_fix": "Get approval from a team member",
            "details": {"required_approvals": 1, "current_approvals": 0},
        },
        {
            "rule_id": "no-weekend-merges",
            "rule_name": "No PR Merges on Weekends",
            "severity": "high",
            "message": "PR cannot be merged on weekends",
            "how_to_fix": "Wait until Monday to merge",
            "details": {"current_day": "saturday"},
        },
    ]

    # Sample rules
    rules = [
        {
            "id": "min-pr-approvals",
            "name": "Minimum PR Approvals Required",
            "description": "Requires at least one approval before merging",
            "severity": "medium",
            "parameters": {"min_approvals": 1},
        },
        {
            "id": "no-weekend-merges",
            "name": "No PR Merges on Weekends",
            "description": "Prevents merging PRs on weekends for safety",
            "severity": "high",
            "parameters": {},
        },
    ]

    logger.info("testing_intelligent_acknowledgment_agent")

    try:
        # Test evaluation
        result = await agent.evaluate_acknowledgment(
            acknowledgment_reason=acknowledgment_reason,
            violations=violations,
            pr_data=pr_data,
            commenter=commenter,
            rules=rules,
        )

        if result.success:
            logger.info("acknowledgment_evaluation_completed_successfully")
            logger.info(f"   Valid: {result.data.get('is_valid', False)}")
            logger.info(f"   Reasoning: {result.data.get('reasoning', 'No reasoning')}")
            logger.info(f"   Acknowledged violations: {len(result.data.get('acknowledgable_violations', []))}")
            logger.info(f"   Require fixes: {len(result.data.get('require_fixes', []))}")
            logger.info(f"   Confidence: {result.data.get('confidence', 0.0)}")

            # Print detailed results
            if result.data.get("acknowledgable_violations"):
                logger.info("n_acknowledged_violations")
                for violation in result.data["acknowledgable_violations"]:
                    logger.info(f"   • {violation.get('rule_name')} - {violation.get('reason')}")

            if result.data.get("require_fixes"):
                logger.info("n_violations_requiring_fixes")
                for violation in result.data["require_fixes"]:
                    logger.info(f"   • {violation.get('rule_name')} - {violation.get('reason')}")

            if result.data.get("recommendations"):
                logger.info("n_recommendations")
                for rec in result.data["recommendations"]:
                    logger.info("event", rec=rec)

        else:
            logger.error("acknowledgment_evaluation_failed", message=result.message)

    except Exception as e:
        logger.error("test_failed_with_error", e=e)


if __name__ == "__main__":
    asyncio.run(test_acknowledgment_agent())
