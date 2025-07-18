import logging
import re
import time
from typing import Any

from src.agents.acknowledgment_agent.agent import AcknowledgmentAgent
from src.agents.engine_agent.agent import RuleEngineAgent
from src.core.models import EventType
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.tasks.task_queue import Task

logger = logging.getLogger(__name__)

# Add at the top
acknowledged_prs = set()


class ViolationAcknowledgmentProcessor(BaseEventProcessor):
    """Processor for violation acknowledgment events using intelligent agentic evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of hybrid RuleEngineAgent for rule evaluation
        self.engine_agent = RuleEngineAgent()
        # Create instance of intelligent AcknowledgmentAgent for acknowledgment evaluation
        self.acknowledgment_agent = AcknowledgmentAgent()

    def get_event_type(self) -> str:
        return "violation_acknowledgment"

    async def process(self, task: Task) -> ProcessingResult:
        """Process violation acknowledgment with intelligent validation."""
        start_time = time.time()
        api_calls = 0

        try:
            event_data = task.payload
            repo = event_data.get("repository", {}).get("full_name")
            installation_id = event_data.get("installation", {}).get("id")

            # Extract PR information from the comment
            issue = event_data.get("issue", {})
            pr_number = issue.get("number")
            comment_body = event_data.get("comment", {}).get("body", "")
            commenter = event_data.get("comment", {}).get("user", {}).get("login")

            logger.info("=" * 80)
            logger.info(f"🔍 Processing VIOLATION ACKNOWLEDGMENT for {repo}#{pr_number}")
            logger.info(f"    Commenter: {commenter}")
            logger.info(f"    Comment: {comment_body[:100]}...")
            logger.info("=" * 80)

            # Extract acknowledgment reason from comment
            acknowledgment_reason = self._extract_acknowledgment_reason(comment_body)

            if not acknowledgment_reason:
                logger.info("❌ No valid acknowledgment reason found in comment")
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            # Get installation token
            github_token = await self.github_client.get_installation_access_token(installation_id)
            api_calls += 1

            if not github_token:
                logger.error(f"❌ Failed to get installation token for {installation_id}")
                return ProcessingResult(
                    success=False,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Failed to get installation token",
                )

            # Get current PR data and violations
            pr_data = await self.github_client.get_pull_request(repo, pr_number, installation_id)
            api_calls += 1

            # Get PR files for better analysis
            pr_files = await self.github_client.get_pull_request_files(repo, pr_number, installation_id)
            api_calls += 1

            # Get PR reviews for approval analysis
            pr_reviews = await self.github_client.get_pull_request_reviews(repo, pr_number, installation_id)
            api_calls += 1

            # Get current violations for this PR
            rules = await self.rule_provider.get_rules(repo, installation_id)

            # Filter pull request rules
            pr_rules = []
            for rule in rules:
                if EventType.PULL_REQUEST in rule.event_types:
                    pr_rules.append(rule)

            logger.info(f"📋 Found {len(pr_rules)} pull request rules out of {len(rules)} total rules")

            # ✅ Use the same format as PullRequestProcessor
            formatted_rules = self._convert_rules_to_new_format(pr_rules)

            # ✅ Prepare event data in the format expected by the agentic analysis
            enriched_event_data = {
                "pull_request_details": pr_data,
                "files": pr_files,
                "reviews": pr_reviews,
                "repository": {"full_name": repo},
                "installation": {"id": installation_id},
            }

            # Run rule analysis to get ALL violations (not just current ones)
            analysis_result = await self.engine_agent.execute(
                event_type="pull_request",  # ✅ Use pull_request since we're evaluating PR rules
                event_data=enriched_event_data,
                rules=formatted_rules,
            )

            # Extract violations from AgentResult
            all_violations = []
            if analysis_result.data and "evaluation_result" in analysis_result.data:
                eval_result = analysis_result.data["evaluation_result"]
                if hasattr(eval_result, "violations"):
                    all_violations = [v.__dict__ for v in eval_result.violations]

            logger.info(f"Found {len(all_violations)} total violations")
            for violation in all_violations:
                logger.info(f"    • {violation.get('message', 'Unknown violation')}")

            if not all_violations:
                logger.info("✅ No violations found - acknowledgment not needed")
                await self._post_comment(
                    repo, pr_number, installation_id, "✅ No rule violations detected. Acknowledgment not needed."
                )
                api_calls += 1

                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            # Evaluate acknowledgment against ALL violations
            evaluation_result = await self._evaluate_acknowledgment(
                acknowledgment_reason=acknowledgment_reason,
                pr_data=pr_data,
                violations=all_violations,  # Use ALL violations, not just current ones
                commenter=commenter,
                rules=formatted_rules,  # Pass the formatted rules
            )

            if evaluation_result["valid"]:
                # Acknowledgment is valid - selectively approve violations and provide guidance
                await self._approve_violations_selectively(
                    repo=repo,
                    pr_number=pr_number,
                    acknowledgable_violations=evaluation_result["acknowledgable_violations"],
                    require_fixes=evaluation_result["require_fixes"],
                    reason=acknowledgment_reason,
                    commenter=commenter,
                    installation_id=installation_id,
                )
                api_calls += 1

                # Update check run to reflect post-acknowledgment state
                await self._update_check_run(
                    repo=repo,
                    pr_number=pr_number,
                    acknowledgable_violations=evaluation_result["acknowledgable_violations"],
                    require_fixes=evaluation_result["require_fixes"],
                    installation_id=installation_id,
                )
                api_calls += 1

                logger.info(f"✅ Acknowledgment accepted: {evaluation_result['reason']}")
            else:
                # Acknowledgment is invalid - reject it
                await self._reject_acknowledgment(
                    repo=repo,
                    pr_number=pr_number,
                    reason=evaluation_result["reason"],
                    commenter=commenter,
                    require_fixes=evaluation_result["require_fixes"],
                    installation_id=installation_id,
                )
                api_calls += 1

                logger.info(f"❌ Acknowledgment rejected: {evaluation_result['reason']}")

            processing_time = int((time.time() - start_time) * 1000)
            logger.info("=" * 80)
            logger.info(f"🏁 VIOLATION ACKNOWLEDGMENT processing completed in {processing_time}ms")
            logger.info(f"    Status: {'accepted' if evaluation_result['valid'] else 'rejected'}")
            logger.info("=" * 80)

            return ProcessingResult(
                success=True,
                violations=evaluation_result["require_fixes"] if not evaluation_result["valid"] else [],
                api_calls_made=api_calls,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"❌ Error processing violation acknowledgment: {str(e)}")
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        """Convert Rule objects to the new flat schema format - same as PullRequestProcessor."""
        formatted_rules = []

        for rule in rules:
            # Convert Rule object to dict format
            rule_dict = {
                "id": rule.id,
                "name": rule.name,
                "description": rule.description,
                "enabled": rule.enabled,
                "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                "event_types": [et.value if hasattr(et, "value") else et for et in rule.event_types],
                "parameters": {},
            }

            # ✅ Extract parameters from conditions (flatten them) - this is the key difference!
            for condition in rule.conditions:
                rule_dict["parameters"].update(condition.parameters)

            formatted_rules.append(rule_dict)

        return formatted_rules

    def _extract_acknowledgment_reason(self, comment_body: str) -> str:
        """Extract acknowledgment reason from comment."""
        # Look for acknowledgment patterns
        patterns = [
            r"@watchflow\s+acknowledge\s+(.+)",
            r"@watchflow\s+override\s+(.+)",
            r"@watchflow\s+bypass\s+(.+)",
            r"/acknowledge\s+(.+)",
            r"/override\s+(.+)",
            r"/bypass\s+(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()

        return ""

    async def _evaluate_acknowledgment(
        self,
        acknowledgment_reason: str,
        pr_data: dict[str, Any],
        violations: list[dict[str, Any]],
        commenter: str,
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Use intelligent LLM-based evaluation to determine which violations can be acknowledged vs. require fixes.
        """
        try:
            logger.info("🧠 Using intelligent acknowledgment agent for evaluation")

            # Use the rules parameter that was passed in (already formatted)
            # Don't fetch rules again - use the ones passed from the calling method

            # Use the intelligent acknowledgment agent
            agent_result = await self.acknowledgment_agent.evaluate_acknowledgment(
                acknowledgment_reason=acknowledgment_reason,
                violations=violations,
                pr_data=pr_data,
                commenter=commenter,
                rules=rules,
            )

            if not agent_result.success:
                logger.error(f"🧠 Acknowledgment agent failed: {agent_result.message}")
                return {
                    "valid": False,
                    "acknowledgable_violations": [],
                    "require_fixes": violations,  # All violations require fixes if agent fails
                    "reason": f"Acknowledgment evaluation failed: {agent_result.message}",
                    "confidence": 0.0,
                    "details": {"error": agent_result.data.get("error", "Unknown error")},
                }

            # Extract results from agent response
            evaluation_data = agent_result.data
            is_valid = evaluation_data.get("is_valid", False)
            reasoning = evaluation_data.get("reasoning", "No reasoning provided")
            acknowledgable_violations = evaluation_data.get("acknowledgable_violations", [])
            require_fixes = evaluation_data.get("require_fixes", [])
            confidence = evaluation_data.get("confidence", 0.5)
            recommendations = evaluation_data.get("recommendations", [])

            logger.info("🧠 Intelligent evaluation completed:")
            logger.info(f"    Valid: {is_valid}")
            logger.info(f"    Reasoning: {reasoning}")
            logger.info(f"    Acknowledged violations: {len(acknowledgable_violations)}")
            logger.info(f"    Require fixes: {len(require_fixes)}")
            logger.info(f"    Confidence: {confidence}")

            return {
                "valid": is_valid,
                "acknowledgable_violations": acknowledgable_violations,
                "require_fixes": require_fixes,
                "reason": reasoning,
                "confidence": confidence,
                "details": {
                    "recommendations": recommendations,
                    "evaluation_method": "intelligent_llm",
                    "acknowledgable_count": len(acknowledgable_violations),
                    "require_fixes_count": len(require_fixes),
                },
            }

        except Exception as e:
            logger.error(f"🧠 Error in intelligent acknowledgment evaluation: {e}")
            return {
                "valid": False,
                "acknowledgable_violations": [],
                "require_fixes": violations,  # All violations require fixes on error
                "reason": f"Intelligent evaluation failed: {str(e)}",
                "confidence": 0.0,
                "details": {"error": str(e)},
            }

    async def _approve_violations_selectively(
        self,
        repo: str,
        pr_number: int,
        acknowledgable_violations: list[dict[str, Any]],
        require_fixes: list[dict[str, Any]],
        reason: str,
        commenter: str,
        installation_id: int,
    ):
        """Selectively approve violations and provide guidance for those that require fixes."""
        comment_parts = []

        # Add acknowledgment section
        if acknowledgable_violations:
            comment_parts.append("✅ **Violations Acknowledged**")
            comment_parts.append(f"**Reason:** {reason}")
            comment_parts.append(f"**Acknowledged by:** {commenter}")
            comment_parts.append("")
            comment_parts.append("The following violations have been overridden:")

            for violation in acknowledgable_violations:
                if isinstance(violation, dict):
                    # For acknowledged violations, show the actual violation message
                    message = (
                        violation.get("message")
                        or violation.get("rule_message")
                        or f"Rule '{violation.get('rule_name', 'Unknown Rule')}' validation failed"
                    )
                    comment_parts.append(f"• {message}")
                else:
                    # Handle dataclass-like objects
                    message = getattr(violation, "message", "Rule violation detected")
                    comment_parts.append(f"• {message}")

            comment_parts.append("")

        # Add violations requiring fixes section
        if require_fixes:
            if acknowledgable_violations:
                comment_parts.append("---")
                comment_parts.append("")

            comment_parts.append("⚠️ **Violations Requiring Fixes**")
            comment_parts.append("The following violations cannot be acknowledged and must be addressed:")
            comment_parts.append("")

            for violation in require_fixes:
                if isinstance(violation, dict):
                    rule_name = violation.get("rule_name", "Unknown Rule")
                    message = violation.get("message", "Rule violation detected")
                    how_to_fix = violation.get("how_to_fix", "")

                    comment_parts.append(f"**{rule_name}**")
                    comment_parts.append(f"• {message}")
                    if how_to_fix:
                        comment_parts.append(f"• **How to fix:** {how_to_fix}")
                    comment_parts.append("")
                else:
                    # Handle dataclass-like objects
                    rule_name = getattr(violation, "rule_name", "Unknown Rule")
                    message = getattr(violation, "message", "Rule violation detected")
                    how_to_fix = getattr(violation, "how_to_fix", "")

                    comment_parts.append(f"**{rule_name}**")
                    comment_parts.append(f"• {message}")
                    if how_to_fix:
                        comment_parts.append(f"• **How to fix:** {how_to_fix}")
                    comment_parts.append("")

        comment_parts.append("*This acknowledgment was validated using intelligent analysis.*")

        # Post the comment
        await self._post_comment(
            repo=repo, pr_number=pr_number, installation_id=installation_id, comment="\n".join(comment_parts)
        )

    async def _reject_acknowledgment(
        self,
        repo: str,
        pr_number: int,
        reason: str,
        commenter: str,
        require_fixes: list[dict[str, Any]],
        installation_id: int,
    ):
        """Reject acknowledgment and explain why, showing violations that still need resolution."""
        comment_parts = []

        # Add rejection section
        comment_parts.append("❌ **Acknowledgment Rejected**")
        comment_parts.append(f"**Reason:** {reason}")
        comment_parts.append(f"**Attempted by:** {commenter}")
        comment_parts.append("")
        comment_parts.append(
            "The acknowledgment request was not valid. Please provide a more specific and justified reason for overriding these rule violations."
        )
        comment_parts.append("")

        # Add violations requiring fixes section (same format as _approve_violations_selectively)
        if require_fixes:
            comment_parts.append("---")
            comment_parts.append("")
            comment_parts.append("⚠️ **Violations Requiring Fixes**")
            comment_parts.append("Since the acknowledgment was rejected, all rule violations must be addressed:")
            comment_parts.append("")

            for violation in require_fixes:
                if isinstance(violation, dict):
                    rule_name = violation.get("rule_name", "Unknown Rule")
                    message = violation.get("message", "Rule violation detected")
                    how_to_fix = violation.get("how_to_fix", "")

                    comment_parts.append(f"**{rule_name}**")
                    comment_parts.append(f"• {message}")
                    if how_to_fix:
                        comment_parts.append(f"• **How to fix:** {how_to_fix}")
                    comment_parts.append("")
                else:
                    # Handle dataclass-like objects
                    rule_name = getattr(violation, "rule_name", "Unknown Rule")
                    message = getattr(violation, "message", "Rule violation detected")
                    how_to_fix = getattr(violation, "how_to_fix", "")

                    comment_parts.append(f"**{rule_name}**")
                    comment_parts.append(f"• {message}")
                    if how_to_fix:
                        comment_parts.append(f"• **How to fix:** {how_to_fix}")
                    comment_parts.append("")

        comment_parts.append("*This acknowledgment was validated using intelligent analysis.*")

        # Post the comment
        await self._post_comment(
            repo=repo, pr_number=pr_number, installation_id=installation_id, comment="\n".join(comment_parts)
        )

    async def _post_comment(self, repo: str, pr_number: int, installation_id: int, comment: str):
        """Post a comment on the PR."""
        await self.github_client.create_issue_comment(
            repo=repo, issue_number=pr_number, comment=comment, installation_id=installation_id
        )

    async def _update_check_run(
        self,
        repo: str,
        pr_number: int,
        acknowledgable_violations: list[dict[str, Any]],
        require_fixes: list[dict[str, Any]],
        installation_id: int,
    ):
        """Update the check run to reflect the post-acknowledgment state."""
        try:
            # Get the PR to find the commit SHA
            pr_data = await self.github_client.get_pull_request(repo, pr_number, installation_id)
            sha = pr_data.get("head", {}).get("sha")

            if not sha:
                logger.warning("No commit SHA found, skipping check run update")
                return

            # Determine check run status based on remaining violations
            if require_fixes:
                status = "completed"
                conclusion = "failure"
            else:
                status = "completed"
                conclusion = "success"

            # Format output
            output = self._format_check_run_output(acknowledgable_violations, require_fixes)

            # Update the check run
            result = await self.github_client.create_check_run(
                repo=repo,
                sha=sha,
                name="Watchflow Rules",
                status=status,
                conclusion=conclusion,
                output=output,
                installation_id=installation_id,
            )

            if result:
                logger.info(f"✅ Successfully updated check run for commit {sha[:8]} with conclusion: {conclusion}")
            else:
                logger.error(f"❌ Failed to update check run for commit {sha[:8]}")

        except Exception as e:
            logger.error(f"Error updating check run: {e}")

    def _format_check_run_output(
        self, acknowledgable_violations: list[dict[str, Any]], require_fixes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Format violations for check run output after acknowledgment."""
        if not require_fixes:
            return {
                "title": "All violations resolved",
                "summary": "✅ All rule violations have been acknowledged or resolved",
                "text": "All configured rules in `.watchflow/rules.yaml` have been satisfied through acknowledgment or fixes.",
            }

        # Build summary
        summary = f"⚠️ {len(require_fixes)} violations require fixes"

        # Build detailed text
        text = "# Watchflow Rule Violations - Post Acknowledgment\n\n"

        if acknowledgable_violations:
            text += "## ✅ Acknowledged Violations\n\n"
            for violation in acknowledgable_violations:
                # Handle both old format (dict) and new format (dataclass-like dict)
                if isinstance(violation, dict):
                    rule_name = violation.get("rule_name", "Unknown Rule")
                    validator = violation.get("validator", "unknown")
                    text += f"• Rule '{rule_name}' was violated (validator: {validator})\n"
                else:
                    # Handle dataclass-like objects
                    rule_name = getattr(violation, "rule_name", "Unknown Rule")
                    text += f"• Rule '{rule_name}' was violated\n"
            text += "\n"
            text += "---\n\n"

        text += "## ⚠️ Violations Requiring Fixes\n\n"

        for violation in require_fixes:
            # Handle both old format (dict) and new format (dataclass-like dict)
            if isinstance(violation, dict):
                rule_name = violation.get("rule_name", "Unknown Rule")
                validator = violation.get("validator", "unknown")
                text += f"• Rule '{rule_name}' was violated (validator: {validator})\n"
            else:
                # Handle dataclass-like objects
                rule_name = getattr(violation, "rule_name", "Unknown Rule")
                text += f"• Rule '{rule_name}' was violated\n"
            text += "\n"

        text += "---\n"
        text += "*This check run was updated after violation acknowledgment.*\n"
        text += "*To configure rules, edit the `.watchflow/rules.yaml` file in this repository.*"

        return {"title": f"{len(require_fixes)} violations require fixes", "summary": summary, "text": text}

    # Required abstract methods
    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from webhook payload."""
        return task.payload

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Prepare data from GitHub API calls."""
        # For acknowledgment, we don't need additional API data
        return {}

    def _get_rule_provider(self):
        """Get the rule provider for this processor."""
        from src.rules.github_provider import github_rule_loader

        return github_rule_loader
