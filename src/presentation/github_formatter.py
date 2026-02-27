import logging
from typing import Any

from src.core.models import Acknowledgment, Severity, Violation

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🟢",
    Severity.INFO: "⚪",
}

# String fallback mapping for Literal types if needed
SEVERITY_STR_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "⚪",
}


def format_check_run_output(
    violations: list[Violation],
    error: str | None = None,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
) -> dict[str, Any]:
    """Format violations for check run output."""
    if error:
        # Check if it's a missing rules file error
        if "rules not configured" in error.lower() or "rules file not found" in error.lower():
            # Build landing page URL with context
            landing_url = "https://watchflow.dev"
            if repo_full_name and installation_id:
                landing_url = f"https://watchflow.dev/analyze?installation_id={installation_id}&repo={repo_full_name}"
            elif repo_full_name:
                landing_url = f"https://watchflow.dev/analyze?repo={repo_full_name}"

            return {
                "title": "Rules not configured",
                "summary": "Watchflow rules setup required",
                "text": (
                    "**Watchflow rules not configured**\n\n"
                    "No rules file found in your repository. Watchflow can help enforce governance rules for your team.\n\n"
                    "**Quick setup:**\n"
                    f"1. [Analyze your repository and generate rules]({landing_url}) - Get AI-powered rule recommendations based on your repository patterns\n"
                    "2. Review and customize the generated rules\n"
                    "3. Create a PR with the recommended rules\n"
                    "4. Merge to activate automated enforcement\n\n"
                    "**Manual setup:**\n"
                    "1. Create a file at `.watchflow/rules.yaml` in your repository root\n"
                    "2. Add your rules in the following format:\n"
                    '   ```yaml\n   rules:\n     - description: "PRs must reference a linked issue (e.g. Fixes #123)"\n       enabled: true\n       severity: medium\n       event_types: [pull_request]\n       parameters:\n         require_linked_issue: true\n   ```\n\n'
                    "**Note:** Rules are currently read from the main branch only.\n\n"
                    "[Read the documentation for more examples](https://github.com/warestack/watchflow/blob/main/docs/getting-started/configuration.md)\n\n"
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
    severity_order = ["critical", "high", "medium", "low"]
    severity_groups: dict[str, list[Violation]] = {s: [] for s in severity_order}

    for violation in violations:
        sev = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
        if sev in severity_groups:
            severity_groups[sev].append(violation)
        else:
            # Fallback for unexpected severities
            if "low" not in severity_groups:
                severity_groups["low"] = []
            severity_groups["low"].append(violation)

    # Build summary
    summary_parts = []
    for severity in severity_order:
        if severity_groups[severity]:
            count = len(severity_groups[severity])
            summary_parts.append(f"{count} {severity}")

    summary = f"🚨 {len(violations)} violations found: {', '.join(summary_parts)}"

    # Build detailed text
    text = "# Watchflow Rule Violations\n\n"

    for severity in severity_order:
        if severity_groups[severity]:
            emoji = SEVERITY_STR_EMOJI.get(severity, "⚪")
            count = len(severity_groups[severity])
            
            text += "<details>\n"
            text += f"<summary><b>{emoji} {severity.title()} Severity ({count})</b></summary>\n\n"

            for violation in severity_groups[severity]:
                text += f"### {violation.rule_description or 'Unknown Rule'}\n"
                text += f"{violation.message}\n"
                if violation.how_to_fix:
                    text += f"**How to fix:** {violation.how_to_fix}\n"
                text += "\n"
            
            text += "</details>\n\n"

    text += "---\n"
    text += "💡 *To configure rules, edit the `.watchflow/rules.yaml` file in this repository.*"

    return {"title": f"{len(violations)} rule violations found", "summary": summary, "text": text}


def format_rules_not_configured_comment(
    repo_full_name: str | None = None,
    installation_id: int | None = None,
) -> str:
    """Format the welcome/instructions comment when no rules file exists (for PR comment)."""
    landing_url = "https://watchflow.dev"
    if repo_full_name and installation_id:
        landing_url = f"https://watchflow.dev/analyze?installation_id={installation_id}&repo={repo_full_name}"
    elif repo_full_name:
        landing_url = f"https://watchflow.dev/analyze?repo={repo_full_name}"

    return (
        "## ⚙️ Watchflow rules not configured\n\n"
        "No rules file found in your repository. Watchflow can help enforce governance rules for your team.\n\n"
        "**Quick setup:**\n"
        f"1. [Analyze your repository and generate rules]({landing_url}) – Get AI-powered rule recommendations based on your repository patterns\n"
        "2. Review and customize the generated rules\n"
        "3. Create a PR with the recommended rules\n"
        "4. Merge to activate automated enforcement\n\n"
        "**Manual setup:**\n"
        "1. Create a file at `.watchflow/rules.yaml` in your repository root\n"
        "2. Add your rules in the following format:\n\n"
        '   ```yaml\n   rules:\n     - description: "PRs must reference a linked issue (e.g. Fixes #123)"\n       enabled: true\n       severity: medium\n       event_types: [pull_request]\n       parameters:\n         require_linked_issue: true\n   ```\n\n'
        "**Note:** Rules are currently read from the main branch only.\n\n"
        "[Read the documentation for more examples](https://github.com/warestack/watchflow/blob/main/docs/getting-started/configuration.md)\n\n"
        "After adding the file, push your changes to re-run validation.\n\n"
        "---\n"
        "*This comment was automatically posted by [Watchflow](https://watchflow.dev).*"
    )


def format_violations_comment(violations: list[Violation]) -> str:
    """Format violations as a GitHub comment."""
    if not violations:
        return ""

    comment = f"### 🛡️ Watchflow Governance Checks\n**Status:** ❌ {len(violations)} Violations Found\n\n"

    # Group violations by severity
    severity_order = ["critical", "high", "medium", "low"]
    severity_groups: dict[str, list[Violation]] = {s: [] for s in severity_order}

    for violation in violations:
        sev = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
        if sev in severity_groups:
            severity_groups[sev].append(violation)

    # Add violations by severity (most severe first)
    for severity in severity_order:
        if severity_groups[severity]:
            emoji = SEVERITY_STR_EMOJI.get(severity, "⚪")
            count = len(severity_groups[severity])
            
            comment += "<details>\n"
            comment += f"<summary><b>{emoji} {severity.title()} Severity ({count})</b></summary>\n\n"

            for violation in severity_groups[severity]:
                comment += f"**{violation.rule_description or 'Unknown Rule'}**\n"
                comment += f"{violation.message}\n"
                if violation.how_to_fix:
                    comment += f"**How to fix:** {violation.how_to_fix}\n"
                comment += "\n"
            
            comment += "</details>\n\n"

    comment += "---\n"
    comment += "💡 *Reply with `@watchflow ack [reason]` to override these rules, or `@watchflow help` for commands.*"

    return comment


def format_acknowledgment_summary(
    acknowledgable_violations: list[Violation], acknowledgments: dict[str, Acknowledgment]
) -> str:
    """Format acknowledged violations for check run output."""
    if not acknowledgable_violations:
        return "No violations were acknowledged."

    lines = []
    for violation in acknowledgable_violations:
        rule_description = violation.rule_description
        message = violation.message
        lines.append(f"• **{rule_description}** - {message}")

    return "\n".join(lines)


def format_violations_for_check_run(violations: list[Violation]) -> str:
    """Format violations for check run output list."""
    if not violations:
        return "None"

    lines = []
    for violation in violations:
        rule_description = violation.rule_description
        message = violation.message
        lines.append(f"• **{rule_description}** - {message}")

    return "\n".join(lines)


def format_acknowledgment_check_run(
    acknowledgable_violations: list[Violation],
    violations: list[Violation],
    acknowledgments: dict[str, Acknowledgment],
) -> dict[str, str]:
    """Format check run output for acknowledgment state."""
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
{format_acknowledgment_summary(acknowledgable_violations, acknowledgments)}

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
{format_acknowledgment_summary(acknowledgable_violations, acknowledgments)}

**Violations Requiring Fixes:**
{format_violations_for_check_run(violations)}

Please address the remaining violations or acknowledge them with a valid reason.
"""
    return {"title": summary, "summary": summary, "text": text, "conclusion": conclusion}
