import logging
from typing import TYPE_CHECKING, Any

from src.core.models import Acknowledgment, Severity, Violation

if TYPE_CHECKING:
    from src.event_processors.risk_assessment.signals import RiskAssessmentResult

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


def _build_collapsible_violations_text(violations: list[Violation]) -> str:
    """Builds a collapsible Markdown string grouped by severity for a list of violations.

    Args:
        violations: A list of Violation objects to format.

    Returns:
        A Markdown formatted string with collapsible details blocks for each severity level.
    """
    if not violations:
        return ""

    text = ""
    severity_order = ["critical", "high", "medium", "low", "info"]
    severity_groups: dict[str, list[Violation]] = {s: [] for s in severity_order}

    for violation in violations:
        sev = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
        if sev in severity_groups:
            severity_groups[sev].append(violation)
        else:
            severity_groups["low"].append(violation)

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

    return text


def format_check_run_output(
    violations: list[Violation],
    error: str | None = None,
    repo_full_name: str | None = None,
    installation_id: int | None = None,
) -> dict[str, Any]:
    """Format violations for check run output.

    Args:
        violations: List of rule violations to report.
        error: Optional error message if rule processing failed entirely.
        repo_full_name: The full repository name (e.g., owner/repo).
        installation_id: The GitHub App installation ID.

    Returns:
        A dictionary matching the GitHub Check Run Output schema containing title, summary, and text.
    """
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
    severity_order = ["critical", "high", "medium", "low", "info"]
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
    text += _build_collapsible_violations_text(violations)
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


def format_suggested_rules_ambiguous_comment(
    rules_translated: int,
    ambiguous: list[dict[str, Any]],
    max_statement_len: int = 200,
    max_reason_len: int = 150,
) -> str:
    """Format a PR comment when some AI rule statements could not be translated (parity with push PR body)."""
    count = len(ambiguous)
    lines = [
        "## Watchflow: Translation summary (AI rule files)",
        "",
        "**Translation summary:**",
        f"- {rules_translated} rule(s) successfully translated and enforced as pre-merge checks.",
        f"- {count} rule statement(s) could not be translated (low confidence or infeasible).",
        "",
    ]
    if ambiguous:
        lines.append("**Could not be translated:**")
        lines.append("")
        for i, item in enumerate(ambiguous[:20], 1):  # cap at 20 for comment length
            st = (item.get("statement") or "") if isinstance(item, dict) else ""
            path = (item.get("path") or "") if isinstance(item, dict) else ""
            reason = (item.get("reason") or "") if isinstance(item, dict) else ""
            if len(st) > max_statement_len:
                st = st[:max_statement_len].rstrip() + "…"
            if len(reason) > max_reason_len:
                reason = reason[:max_reason_len].rstrip() + "…"
            lines.append(f"{i}. `{path}`: {st}")
            if reason:
                lines.append(f"   - *Reason:* {reason}")
            lines.append("")
        if len(ambiguous) > 20:
            lines.append(f"*…and {len(ambiguous) - 20} more.*")
            lines.append("")
    lines.append("---")
    lines.append("*This comment was automatically posted by [Watchflow](https://watchflow.dev).*")
    return "\n".join(lines)


def format_violations_comment(violations: list[Violation], content_hash: str | None = None) -> str:
    """Format violations as a GitHub comment.

    Args:
        violations: List of rule violations to include in the comment.
        content_hash: Optional hash to include as a hidden marker for deduplication.

    Returns:
        A Markdown formatted string suitable for a Pull Request timeline comment.
        Returns an empty string if there are no violations.
    """
    if not violations:
        return ""

    # Add hidden HTML marker for deduplication (not visible in rendered markdown)
    marker = f"<!-- watchflow-violations-hash:{content_hash} -->\n" if content_hash else ""

    comment = marker
    comment += f"### 🛡️ Watchflow Governance Checks\n**Status:** ❌ {len(violations)} Violations Found\n\n"
    comment += _build_collapsible_violations_text(violations)
    comment += "---\n"
    comment += (
        "💡 *Reply with `@watchflow ack [reason]` to override these rules, or `@watchflow help` for commands.*\n\n"
    )
    comment += (
        "Thanks for using [Watchflow](https://watchflow.dev)! It's completely free for OSS and private repositories. "
    )
    comment += "You can also [self-host it easily](https://github.com/warestack/watchflow)."

    return comment


def _sanitize_mention(text: str) -> str:
    """Escape @ mentions in user-controlled text to prevent accidental GitHub notifications."""
    return text.replace("@", "@\u200b")


def format_reviewer_recommendation_comment(
    risk_level: str,
    risk_reason: str,
    reviewers: list[tuple[str, str]],
    reasoning_lines: list[str],
    review_load: dict[str, int] | None = None,
) -> str:
    """Format a reviewer recommendation as a GitHub PR comment.

    Args:
        risk_level: One of "critical", "high", "medium", "low".
        risk_reason: Human-readable explanation of the risk assessment.
        reviewers: List of (username, expertise_reason) tuples, ordered by rank.
        reasoning_lines: Bullet-point reasoning strings (rules, risk signals, context).
        review_load: Optional dict mapping username -> pending review count.

    Returns:
        Markdown formatted comment matching the Watchflow reviewer recommendation template.
    """
    risk_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(risk_level, "⚪")

    lines = [
        "## Watchflow: Reviewer Recommendation",
        "",
        f"**Risk:** {risk_emoji} {risk_level.title()} ({risk_reason})",
        "",
    ]

    if reviewers:
        lines.append("**Recommended:**")
        for i, (username, reason) in enumerate(reviewers, 1):
            pending = (review_load or {}).get(username, 0)
            load_note = f" · {pending} pending reviews" if review_load and pending > 0 else ""
            lines.append(f"{i}. @{username} — {reason}{load_note}")
        lines.append("")
    else:
        lines.append("**Recommended:** No candidates found — consider requesting a review manually.")
        lines.append("")

    if reasoning_lines:
        lines.append("**Reasoning:**")
        for line in reasoning_lines:
            lines.append(f"- {line}")
        lines.append("")

    lines.append("---")
    lines.append("*This recommendation was generated by [Watchflow](https://watchflow.dev).*")

    return "\n".join(lines)


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
{_build_collapsible_violations_text(violations)}

Please address the remaining violations or acknowledge them with a valid reason.
"""
    return {"title": summary, "summary": summary, "text": text, "conclusion": conclusion}


def format_risk_assessment_comment(result: "RiskAssessmentResult") -> str:
    """Format a risk assessment result as a GitHub PR comment."""
    from src.event_processors.risk_assessment.signals import _SEVERITY_SCORE

    risk_emoji = SEVERITY_EMOJI.get(result.level, "⚪")
    risk_label = result.level.capitalize()

    lines = [f"### ⚠️ Watchflow Risk Assessment — {risk_emoji} {risk_label}"]

    if not result.signals:
        lines.append("")
        lines.append("No risk signals detected.")
    else:
        # Sort signals by severity descending (CRITICAL first)
        sorted_signals = sorted(result.signals, key=lambda s: _SEVERITY_SCORE.get(s.severity, 0), reverse=True)

        lines.append("")
        lines.append(f"<details><summary>📊 Risk Signals ({len(sorted_signals)} triggered)</summary>")
        lines.append("")
        lines.append("| Severity | Category | Signal |")
        lines.append("|----------|----------|--------|")

        for signal in sorted_signals:
            sev_emoji = SEVERITY_EMOJI.get(signal.severity, "⚪")
            sev_name = signal.severity.name
            lines.append(f"| {sev_emoji} {sev_name} | {signal.category} | {signal.description} |")

        lines.append("")
        lines.append("</details>")

    lines.append("")
    lines.append("> _Triggered by /risk command_")

    return "\n".join(lines)
