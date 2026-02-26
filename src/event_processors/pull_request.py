import re
import time
from typing import Any

import structlog

from src.agents.engine_agent.agent import RuleEngineAgent
from src.event_processors.base import BaseEventProcessor, ProcessingResult
from src.rules.github_provider import RulesFileNotFoundError
from src.tasks.task_queue import Task

logger = structlog.get_logger()


class PullRequestProcessor(BaseEventProcessor):
    """Processor for pull request events using agentic rule evaluation."""

    def __init__(self):
        # Call super class __init__ first
        super().__init__()

        # Create instance of RuleEngineAgent
        self.engine_agent = RuleEngineAgent()

    def get_event_type(self) -> str:
        return "pull_request"

    async def process(self, task: Task) -> ProcessingResult:
        """Process a pull request event using the agentic approach."""
        start_time = time.time()
        api_calls = 0

        try:
            logger.info("=" * 80)
            logger.info(
                "processing_pr_event",
                operation="process_pr",
                subject_ids={
                    "repo": task.repo_full_name,
                    "pr_number": task.payload.get("pull_request", {}).get("number"),
                },
                action=task.payload.get("action"),
                pr_title=task.payload.get("pull_request", {}).get("title"),
            )
            logger.info("=" * 80)

            pr_data = task.payload.get("pull_request", {})

            if pr_data.get("state") == "closed" or pr_data.get("merged") or pr_data.get("draft"):
                logger.info(
                    "pr_skipped_invalid_state",
                    operation="process_pr",
                    subject_ids={"repo": task.repo_full_name, "pr_number": pr_data.get("number")},
                    decision="skip",
                    state=pr_data.get("state"),
                    merged=pr_data.get("merged"),
                    draft=pr_data.get("draft"),
                    latency_ms=int((time.time() - start_time) * 1000),
                )
                return ProcessingResult(
                    success=True,
                    violations=[],
                    api_calls_made=0,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            github_token = await self.github_client.get_installation_access_token(task.installation_id)

            # Prepare event_data for the agent
            event_data = await self._prepare_event_data_for_agent(task, github_token)
            api_calls += 1

            # Fetch rules
            try:
                rules = await self.rule_provider.get_rules(task.repo_full_name, task.installation_id)
                api_calls += 1
            except RulesFileNotFoundError as e:
                logger.warning("rules_file_not_found", repo=task.repo_full_name, error=str(e))
                # Create a neutral check run for missing rules file with helpful guidance
                await self._create_check_run(
                    task,
                    [],
                    conclusion="neutral",
                    error="Rules not configured. Please create `.watchflow/rules.yaml` in your repository.",
                )
                return ProcessingResult(
                    success=True,  # Not a failure, just needs setup
                    violations=[],
                    api_calls_made=api_calls,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error="Rules not configured",
                )

            # Convert rules to the new format expected by the agent
            formatted_rules = self._convert_rules_to_new_format(rules)

            # Debug logging
            logger.info("rules_loaded", num_rules=len(rules))
            for rule in formatted_rules:
                if "pull_request" in rule.get("event_types", []):
                    logger.info(
                        "rule_applicable",
                        rule_name=rule.get("name", "Unknown"),
                        rule_id=rule.get("id", "unknown"),
                    )

            # Check for existing acknowledgments from previous comments first
            pr_data = task.payload.get("pull_request", {})
            pr_number = pr_data.get("number")
            previous_acknowledgments = {}

            if pr_number:
                # Fetch previous comments to check for acknowledgments
                previous_acknowledgments = await self._get_previous_acknowledgments(
                    task.repo_full_name, pr_number, task.installation_id
                )
                if previous_acknowledgments:
                    logger.info(
                        "previous_acknowledgments_found",
                        pr_number=pr_number,
                        acknowledged_rule_ids=list(previous_acknowledgments.keys()),
                    )

            # Run engine-based rule evaluation
            result = await self.engine_agent.execute(
                event_type="pull_request", event_data=event_data, rules=formatted_rules
            )

            # Extract violations from engine result
            violations = []
            if result.data and "evaluation_result" in result.data:
                eval_result = result.data["evaluation_result"]
                if hasattr(eval_result, "violations"):
                    violations = [v.__dict__ for v in eval_result.violations]

            # Store original violations for acknowledgment tracking
            original_violations = violations.copy()

            # Apply previous acknowledgments to filter violations
            acknowledgable_violations = []
            require_acknowledgment_violations = []

            # Check for previous acknowledgments
            for violation in violations:
                rule_description = violation.get("rule_description", "")
                if rule_description in previous_acknowledgments:
                    # This violation was previously acknowledged
                    logger.info("violation_previously_acknowledged", rule_description=rule_description)
                    acknowledgable_violations.append(violation)
                else:
                    # This violation requires acknowledgment
                    require_acknowledgment_violations.append(violation)

            logger.info(
                "violation_breakdown",
                acknowledged_count=len(acknowledgable_violations),
                requiring_fix_count=len(require_acknowledgment_violations),
            )

            # Use violations requiring fixes for final result
            violations = require_acknowledgment_violations

            # Create check run based on whether we have acknowledgments
            if previous_acknowledgments and original_violations:
                # Create check run with acknowledgment context
                await self._create_check_run_with_acknowledgment(
                    task, acknowledgable_violations, violations, previous_acknowledgments
                )
            else:
                # No acknowledgments or no violations - create normal check run
                await self._create_check_run(task, violations)

            processing_time = int((time.time() - start_time) * 1000)

            # Post violations as comments (if any)
            if violations:
                logger.info("posting_violations_to_pr", num_violations=len(violations))
                await self._post_violations_to_github(task, violations)
                api_calls += 1
            else:
                logger.info("no_violations_skipping_comment", repo=task.repo_full_name)

            # Summary
            logger.info("=" * 80)
            logger.info(
                "pr_processing_complete",
                operation="process_pr",
                subject_ids={"repo": task.repo_full_name, "pr_number": pr_number},
                rules_evaluated=len(formatted_rules),
                violations_found=len(violations),
                api_calls=api_calls,
                latency_ms=processing_time,
            )

            if violations:
                for i, violation in enumerate(violations, 1):
                    logger.warning(
                        "violation_found",
                        num=i,
                        rule_description=violation.get("rule_description", "Unknown"),
                        severity=violation.get("severity", "medium"),
                        message=violation.get("message", ""),
                    )
            else:
                logger.info("all_rules_passed", repo=task.repo_full_name)

            logger.info("=" * 80)

            return ProcessingResult(
                success=(not violations),
                violations=violations,
                api_calls_made=api_calls,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(
                "pr_processing_error",
                operation="process_pr",
                subject_ids={"repo": task.repo_full_name},
                error=str(e),
            )
            # Create a failing check run for errors
            await self._create_check_run(task, [], "failure", error=str(e))
            return ProcessingResult(
                success=False,
                violations=[],
                api_calls_made=api_calls,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def _prepare_event_data_for_agent(self, task: Task, github_token: str) -> dict[str, Any]:
        """Prepare enriched event data for the LangGraph agent."""
        pr_data = task.payload.get("pull_request", {})
        pr_number = pr_data.get("number")

        # Base event data
        event_data = {
            "pull_request_details": pr_data,
            "triggering_user": {"login": pr_data.get("user", {}).get("login")},
            "repository": task.payload.get("repository", {}),
            "organization": task.payload.get("organization", {}),
            "event_id": task.payload.get("event_id"),
            "timestamp": task.payload.get("timestamp"),
            "installation": {"id": task.installation_id},
            "github_client": self.github_client,  # Pass GitHub client for validators
        }

        # Enrich with API data if PR number is available
        if pr_number:
            try:
                # Get reviews
                reviews = await self.github_client.get_pull_request_reviews(
                    task.repo_full_name, pr_number, task.installation_id
                )
                event_data["reviews"] = reviews or []

                # Get files changed
                files = await self.github_client.get_pull_request_files(
                    task.repo_full_name, pr_number, task.installation_id
                )
                event_data["files"] = files or []

            except Exception as e:
                logger.warning("error_enriching_event_data", error=str(e))

        return event_data

    def _convert_rules_to_new_format(self, rules: list[Any]) -> list[dict[str, Any]]:
        """Convert Rule objects to the new flat schema format."""
        formatted_rules = []

        for rule in rules:
            # Convert Rule object to dict format
            rule_dict = {
                "description": rule.description,
                "enabled": rule.enabled,
                "severity": rule.severity.value if hasattr(rule.severity, "value") else rule.severity,
                "event_types": [et.value if hasattr(et, "value") else et for et in rule.event_types],
                "parameters": rule.parameters if hasattr(rule, "parameters") else {},
            }

            # If no parameters field, try to extract from conditions (backward compatibility)
            if not rule_dict["parameters"] and hasattr(rule, "conditions"):
                for condition in rule.conditions:
                    rule_dict["parameters"].update(condition.parameters)

            formatted_rules.append(rule_dict)

        return formatted_rules

    async def _create_check_run(
        self, task: Task, violations: list[dict[str, Any]], conclusion: str | None = None, error: str | None = None
    ):
        """Create a check run with violation results."""
        try:
            pr_data = task.payload.get("pull_request", {})
            sha = pr_data.get("head", {}).get("sha")

            if not sha:
                logger.warning(
                    "no_commit_sha",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name},
                )
                return

            # Determine check run status
            if error:
                status = "completed"
                # Use provided conclusion or default to failure
                conclusion = conclusion or "failure"
            elif violations:
                status = "completed"
                conclusion = "failure"
            else:
                status = "completed"
                conclusion = "success"

            # Format output
            output = self._format_check_run_output(violations, error)

            result = await self.github_client.create_check_run(
                repo=task.repo_full_name,
                sha=sha,
                name="Watchflow Rules",
                status=status,
                conclusion=conclusion,
                output=output,
                installation_id=task.installation_id,
            )

            if result:
                logger.info(
                    "check_run_created",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name, "sha": sha[:8]},
                    conclusion=conclusion,
                )
            else:
                logger.error(
                    "check_run_failed",
                    operation="create_check_run",
                    subject_ids={"repo": task.repo_full_name, "sha": sha[:8]},
                )

        except Exception as e:
            logger.error(
                "check_run_error",
                operation="create_check_run",
                subject_ids={"repo": task.repo_full_name},
                error=str(e),
            )

    def _format_check_run_output(self, violations: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
        """Format violations for check run output."""
        if error:
            # Check if it's a missing rules file error
            if "rules not configured" in error.lower() or "rules file not found" in error.lower():
                return {
                    "title": "Rules not configured",
                    "summary": "⚙️ Watchflow rules setup required",
                    "text": (
                        "**Watchflow rules not configured**\n\n"
                        "No rules file found in your repository. Watchflow can help enforce governance rules for your team.\n\n"
                        "**How to set up rules:**\n"
                        "1. Create a file at `.watchflow/rules.yaml` in your repository root\n"
                        "2. Add your rules in the following format:\n"
                        "   ```yaml\n   rules:\n     - id: pr-approval-required\n       name: PR Approval Required\n       description: All pull requests must have at least 2 approvals\n       enabled: true\n       severity: high\n       event_types: [pull_request]\n       parameters:\n         min_approvals: 2\n   ```\n\n"
                        "**Note:** Rules are currently read from the main branch only.\n\n"
                        "📖 [Read the documentation for more examples](https://github.com/warestack/watchflow/blob/main/docs/getting-started/configuration.md)\n\n"
                        "After adding the file, push your changes to re-run validation."
                    ),
                }
            else:
                return {
                    "title": "Error processing rules",
                    "summary": f"❌ Error: {error}",
                    "text": f"An error occurred while processing rules:\n\n```\n{error}\n```\n\nPlease check the logs for more details.",
                }

        if not violations:
            return {
                "title": "All rules passed",
                "summary": "✅ No rule violations detected",
                "text": "All configured rules in `.watchflow/rules.yaml` have passed successfully.",
            }

        # Group violations by severity
        severity_groups = {"critical": [], "high": [], "medium": [], "low": []}

        for violation in violations:
            severity = violation.get("severity", "medium")
            severity_groups[severity].append(violation)

        # Build summary
        summary_parts = []
        for severity in ["critical", "high", "medium", "low"]:
            if severity_groups[severity]:
                count = len(severity_groups[severity])
                summary_parts.append(f"{count} {severity}")

        summary = f"🚨 {len(violations)} violations found: {', '.join(summary_parts)}"

        # Build detailed text
        text = "# Watchflow Rule Violations\n\n"

        for severity in ["critical", "high", "medium", "low"]:
            if severity_groups[severity]:
                severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")

                text += f"## {severity_emoji} {severity.title()} Severity\n\n"

                for violation in severity_groups[severity]:
                    text += f"### {violation.get('rule_description', 'Unknown Rule')}\n"
                    text += f"Rule validation failed with severity: **{violation.get('severity', 'medium')}**\n"
                    if violation.get("how_to_fix"):
                        text += f"**How to fix:** {violation.get('how_to_fix')}\n"
                    text += "\n"

        text += "---\n"
        text += "*To configure rules, edit the `.watchflow/rules.yaml` file in this repository.*"

        return {"title": f"{len(violations)} rule violations found", "summary": summary, "text": text}

    async def prepare_webhook_data(self, task: Task) -> dict[str, Any]:
        """Extract data available in webhook payload."""
        pr_data = task.payload.get("pull_request", {})

        return {
            "event_type": "pull_request",
            "repo_full_name": task.repo_full_name,
            "action": task.payload.get("action"),
            "pull_request": {
                "number": pr_data.get("number"),
                "title": pr_data.get("title"),
                "body": pr_data.get("body"),
                "state": pr_data.get("state"),
                "created_at": pr_data.get("created_at"),
                "updated_at": pr_data.get("updated_at"),
                "merged_at": pr_data.get("merged_at"),
                "user": pr_data.get("user", {}).get("login"),
                "head": {
                    "ref": pr_data.get("head", {}).get("ref"),
                    "sha": pr_data.get("head", {}).get("sha"),
                },
                "base": {
                    "ref": pr_data.get("base", {}).get("ref"),
                    "sha": pr_data.get("base", {}).get("sha"),
                },
                "labels": pr_data.get("labels", []),
                "files": pr_data.get("files", []),
            },
        }

    async def prepare_api_data(self, task: Task) -> dict[str, Any]:
        """Fetch data not available in webhook."""
        pr_data = task.payload.get("pull_request", {})
        pr_number = pr_data.get("number")

        if not pr_number:
            return {}

        api_data = {}

        try:
            # Fetch reviews
            reviews = await self.github_client.get_pull_request_reviews(
                task.repo_full_name, pr_number, task.installation_id
            )
            api_data["reviews"] = reviews or []

            # Fetch files (if not in webhook)
            if not pr_data.get("files"):
                files = await self.github_client.get_pull_request_files(
                    task.repo_full_name, pr_number, task.installation_id
                )
                api_data["files"] = files or []

        except Exception as e:
            logger.error(
                "fetch_api_data_error",
                operation="prepare_api_data",
                error=str(e),
            )

        return api_data

    async def _post_violations_to_github(self, task: Task, violations: list[dict[str, Any]]):
        """Post violations as comments on the pull request."""
        try:
            pr_number = task.payload.get("pull_request", {}).get("number")
            if not pr_number:
                logger.warning(
                    "no_pr_number",
                    operation="post_violations_to_github",
                    subject_ids={"repo": task.repo_full_name},
                )
                return

            logger.info(
                "posting_violations",
                operation="post_violations_to_github",
                subject_ids={"repo": task.repo_full_name, "pr_number": pr_number},
                num_violations=len(violations),
            )
            comment_body = self._format_violations_comment(violations)
            logger.debug("comment_body_preview", body_preview=comment_body[:200])

            result = await self.github_client.create_pull_request_comment(
                task.repo_full_name, pr_number, comment_body, task.installation_id
            )

            if result:
                logger.info(
                    "violations_comment_posted",
                    operation="post_violations_to_github",
                    subject_ids={"repo": task.repo_full_name, "pr_number": pr_number},
                )
            else:
                logger.error(
                    "violations_comment_failed",
                    operation="post_violations_to_github",
                    subject_ids={"repo": task.repo_full_name, "pr_number": pr_number},
                )

        except Exception as e:
            logger.error(
                "posting_violations_error",
                operation="post_violations_to_github",
                error=str(e),
            )

    def _format_violations_comment(self, violations: list[dict[str, Any]]) -> str:
        """Format violations as a GitHub comment."""
        comment = "## 🚨 Watchflow Rule Violations Detected\n\n"

        # Group violations by severity
        severity_groups = {"critical": [], "high": [], "medium": [], "low": []}

        for violation in violations:
            severity = violation.get("severity", "medium")
            severity_groups[severity].append(violation)

        # Add violations by severity (most severe first)
        for severity in ["critical", "high", "medium", "low"]:
            if severity_groups[severity]:
                severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")

                comment += f"### {severity_emoji} {severity.title()} Severity\n\n"

                for violation in severity_groups[severity]:
                    comment += f"**{violation.get('rule_description', 'Unknown Rule')}**\n"
                    comment += f"Rule validation failed with severity: **{violation.get('severity', 'medium')}**\n"
                    if violation.get("how_to_fix"):
                        comment += f"**How to fix:** {violation.get('how_to_fix')}\n"
                    comment += "\n"

        comment += "---\n"
        comment += "*This comment was automatically generated by [Watchflow](https://watchflow.dev).*\n"
        comment += "*To configure rules, edit the `.watchflow/rules.yaml` file in this repository.*"

        return comment

    async def _get_previous_acknowledgments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> dict[str, dict[str, Any]]:
        """Fetch and parse previous acknowledgments from PR comments."""
        try:
            # Fetch all comments for the PR
            comments = await self.github_client.get_issue_comments(repo, pr_number, installation_id)

            if not comments:
                return {}

            acknowledgments = {}

            for comment in comments:
                comment_body = comment.get("body", "")
                commenter = comment.get("user", {}).get("login", "")
                created_at = comment.get("created_at", "")

                # Check if this is an acknowledgment comment
                if self._is_acknowledgment_comment(comment_body):
                    # Parse the acknowledged violations from the comment
                    acknowledged_violations = self._parse_acknowledgment_comment(comment_body)

                    for violation in acknowledged_violations:
                        rule_id = violation.get("rule_id")
                        if rule_id:
                            acknowledgments[rule_id] = {
                                "rule_description": violation.get("rule_description", ""),
                                "reason": violation.get("reason", ""),
                                "commenter": commenter,
                                "created_at": created_at,
                            }

            return acknowledgments

        except Exception as e:
            logger.error(
                "fetch_acknowledgments_error",
                operation="get_previous_acknowledgments",
                error=str(e),
            )
            return {}

    def _is_acknowledgment_comment(self, comment_body: str) -> bool:
        """Check if a comment is an acknowledgment comment."""
        acknowledgment_indicators = [
            "✅ Violations Acknowledged",
            "🚨 Watchflow Rule Violations Detected",
            "This acknowledgment was validated",
        ]

        return any(indicator in comment_body for indicator in acknowledgment_indicators)

    def _parse_acknowledgment_comment(self, comment_body: str) -> list[dict[str, Any]]:
        """Parse acknowledged violations from a comment."""
        violations = []

        # Extract acknowledgment reason
        reason_match = re.search(r"\*\*Reason:\*\* (.+)", comment_body)
        reason = reason_match.group(1) if reason_match else ""

        # Look for violation lines (bullet points)
        lines = comment_body.split("\n")
        in_violations_section = False

        for line in lines:
            line = line.strip()

            # Check if we're entering the violations section
            if "The following violations have been overridden:" in line:
                in_violations_section = True
                continue

            # Check if we're leaving the violations section
            if in_violations_section and (line.startswith("---") or line.startswith("⚠️") or line.startswith("*")):
                break

            # Parse violation lines
            if in_violations_section and line.startswith("•"):
                violation_text = line[1:].strip()

                # Map violation text to rule IDs
                rule_id = self._map_violation_text_to_rule_id(violation_text)
                rule_description = self._map_violation_text_to_rule_description(violation_text)

                if rule_id:
                    violations.append(
                        {
                            "rule_id": rule_id,
                            "rule_description": rule_description,
                            "message": violation_text,
                            "reason": reason,
                        }
                    )

        return violations

    def _map_violation_text_to_rule_id(self, violation_text: str) -> str:
        """Map violation text to rule ID."""
        mapping = {
            "Pull request does not have the minimum required": "min-pr-approvals",
            "Pull request is missing required label": "required-labels",
            "Pull request title does not match the required pattern": "pr-title-pattern",
            "Pull request description is too short": "pr-description-required",
            "Individual files cannot exceed": "file-size-limit",
            "Force pushes are not allowed": "no-force-push",
            "Direct pushes to main/master branches": "protected-branch-push",
        }

        for key, rule_id in mapping.items():
            if key in violation_text:
                return rule_id

        return ""

    @staticmethod
    def _map_violation_text_to_rule_description(violation_text: str) -> str:
        """Map violation text to rule description."""
        mapping = {
            "Pull request does not have the minimum required": "Pull requests require at least 2 approvals",
            "Pull request is missing required label": "Pull requests must have security and review labels",
            "Pull request title does not match the required pattern": "PR titles must follow conventional commit format",
            "Pull request description is too short": "Pull requests must have descriptions with at least 50 characters",
            "Individual files cannot exceed": "Files must not exceed 10MB",
            "Force pushes are not allowed": "Force pushes are not allowed",
            "Direct pushes to main/master branches": "Direct pushes to main branch are not allowed",
        }

        for key, rule_description in mapping.items():
            if key in violation_text:
                return rule_description

        return "Unknown Rule"

    async def _create_check_run_with_acknowledgment(
        self,
        task: Task,
        acknowledgable_violations: list[dict[str, Any]],
        violations: list[dict[str, Any]],
        acknowledgments: dict[str, dict[str, Any]],
    ):
        """Create a check run that reflects the acknowledgment state."""
        try:
            # Create summary with acknowledgment context
            total_violations = len(acknowledgable_violations) + len(violations)
            acknowledged_count = len(acknowledgable_violations)
            remaining_count = len(violations)

            if remaining_count == 0:
                # All violations acknowledged
                conclusion = "success"
                summary = f"✅ All {total_violations} rule violations have been acknowledged and overridden."
                text = f"""
## Watchflow Rule Evaluation Complete

**Status:** ✅ All violations acknowledged

**Summary:**
- Total violations found: {total_violations}
- Acknowledged violations: {acknowledged_count}
- Violations requiring fixes: {remaining_count}

**Acknowledged Violations:**
{self._format_acknowledgment_summary(acknowledgable_violations, acknowledgments)}

All rule violations have been properly acknowledged and overridden. The pull request is ready for merge.
"""
            else:
                # Some violations still need fixes
                conclusion = "failure"
                summary = f"⚠️ {remaining_count} rule violations require fixes. {acknowledged_count} violations have been acknowledged."
                text = f"""
## Watchflow Rule Evaluation Complete

**Status:** ⚠️ Some violations require fixes

**Summary:**
- Total violations found: {total_violations}
- Acknowledged violations: {acknowledged_count}
- Violations requiring fixes: {remaining_count}

**Acknowledged Violations:**
{self._format_acknowledgment_summary(acknowledgable_violations, acknowledgments)}

**Violations Requiring Fixes:**
{self._format_violations_for_check_run(violations)}

Please address the remaining violations or acknowledge them with a valid reason.
"""

            # Create the check run
            await self.github_client.create_check_run(
                repo=task.repo_full_name,
                sha=task.payload.get("pull_request", {}).get("head", {}).get("sha", ""),
                name="watchflow-rules",
                status="completed",
                conclusion=conclusion,
                output={"title": summary, "summary": summary, "text": text},
                installation_id=task.installation_id,
            )

        except Exception as e:
            logger.error(
                "check_run_with_ack_error",
                operation="create_check_run_with_acknowledgment",
                error=str(e),
            )

    def _format_acknowledgment_summary(
        self, acknowledgable_violations: list[dict[str, Any]], acknowledgments: dict[str, dict[str, Any]]
    ) -> str:
        """Format acknowledged violations for check run output."""
        if not acknowledgable_violations:
            return "No violations were acknowledged."

        lines = []
        for violation in acknowledgable_violations:
            rule_id = violation.get("rule_id", "")
            rule_description = violation.get("rule_description", "")
            message = violation.get("message", "")

            acknowledgment_info = acknowledgments.get(rule_id, {})
            reason = acknowledgment_info.get("reason", "No reason provided")
            commenter = acknowledgment_info.get("commenter", "Unknown")

            lines.append(f"• **{rule_description}** - {message}")
            lines.append(f"  _Acknowledged by {commenter}: {reason}_")

        return "\n".join(lines)

    def _format_violations_for_check_run(self, violations: list[dict[str, Any]]) -> str:
        """Format violations for check run output."""
        if not violations:
            return "None"

        lines = []
        for violation in violations:
            rule_description = violation.get("rule_description", "")
            message = violation.get("message", "")
            lines.append(f"• **{rule_description}** - {message}")

        return "\n".join(lines)
