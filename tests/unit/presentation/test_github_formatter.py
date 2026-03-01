from src.core.models import Acknowledgment, Severity, Violation
from src.presentation.github_formatter import (
    format_acknowledgment_summary,
    format_check_run_output,
    format_violations_comment,
    format_violations_for_check_run,
)


def test_format_violations_comment_groups_by_severity():
    violations = [
        Violation(rule_description="Rule 1", severity=Severity.HIGH, message="Error 1", how_to_fix="Fix 1"),
        Violation(rule_description="Rule 2", severity=Severity.CRITICAL, message="Error 2", how_to_fix="Fix 2"),
        Violation(rule_description="Rule 3", severity=Severity.HIGH, message="Error 3"),
    ]

    comment = format_violations_comment(violations)

    assert "### 🛡️ Watchflow Governance Checks" in comment
    assert "**Status:** ❌ 3 Violations Found" in comment
    assert "<summary><b>🔴 Critical Severity (1)</b></summary>" in comment
    assert "<summary><b>🟠 High Severity (2)</b></summary>" in comment
    assert "### Rule 2" in comment
    assert "### Rule 1" in comment
    assert "### Rule 3" in comment
    assert "Fix 1" in comment
    assert "Fix 2" in comment
    assert "💡 *Reply with `@watchflow ack [reason]`" in comment


def test_format_violations_comment_empty():
    comment = format_violations_comment([])
    assert comment == ""


def test_build_collapsible_violations_text_fallback_severity():
    """Test that a violation with an unknown severity falls back to 'low' severity bucket."""
    # Create a violation and use object.__setattr__ to bypass Pydantic validation for testing
    v = Violation(rule_description="Weird Rule", severity=Severity.LOW, message="Weird error")
    object.__setattr__(v, "severity", "super_critical_unknown")

    comment = format_violations_comment([v])

    # It should fall back to low severity
    assert "<summary><b>🟢 Low Severity (1)</b></summary>" in comment
    assert "Weird error" in comment


def test_build_collapsible_violations_text_info_severity():
    """Test that INFO severity violations are correctly formatted."""
    v = Violation(rule_description="Info Rule", severity=Severity.INFO, message="Just an info message")
    comment = format_violations_comment([v])

    assert "<summary><b>⚪ Info Severity (1)</b></summary>" in comment
    assert "Just an info message" in comment


def test_format_check_run_output_success():
    output = format_check_run_output([])
    assert output["title"] == "All rules passed"
    assert "✅ No rule violations detected" in output["summary"]
    assert "passed successfully" in output["text"]


def test_format_check_run_output_with_violations():
    violations = [Violation(rule_description="Missing Issue", severity=Severity.HIGH, message="No issue linked")]

    output = format_check_run_output(violations)

    assert "1 rule violations found" in output["title"]
    assert "🚨 1 violations found: 1 high" in output["summary"]
    assert "<summary><b>🟠 High Severity (1)</b></summary>" in output["text"]
    assert "### Missing Issue" in output["text"]


def test_format_check_run_output_rules_not_configured():
    error = "Rules not configured"
    repo = "owner/repo"
    inst_id = 123

    output = format_check_run_output([], error=error, repo_full_name=repo, installation_id=inst_id)

    assert output["title"] == "Rules not configured"
    assert "Analyze your repository" in output["text"]
    assert f"repo={repo}" in output["text"]
    assert f"installation_id={inst_id}" in output["text"]


def test_format_acknowledgment_summary():
    violations = [Violation(rule_description="PR Title", severity=Severity.MEDIUM, message="Bad title")]
    acks = {"pr-title": Acknowledgment(rule_id="pr-title", reason="One-off", commenter="tom")}

    summary = format_acknowledgment_summary(violations, acks)
    assert "**PR Title**" in summary
    assert "Bad title" in summary


def test_format_violations_for_check_run():
    violations = [Violation(rule_description="Lint", severity=Severity.LOW, message="Trailing space")]

    result = format_violations_for_check_run(violations)
    assert "• **Lint** - Trailing space" in result



def test_format_violations_for_check_run_empty():
    assert format_violations_for_check_run([]) == "None"


def test_format_violations_comment_includes_hash_marker():
    """Test that comment includes hidden HTML marker when content_hash is provided."""
    violations = [
        Violation(rule_description="Rule 1", severity=Severity.HIGH, message="Error 1"),
    ]

    comment = format_violations_comment(violations, content_hash="abc123def456")

    assert "<!-- watchflow-violations-hash:abc123def456 -->" in comment
    assert "### 🛡️ Watchflow Governance Checks" in comment


def test_format_violations_comment_no_hash_marker_when_not_provided():
    """Test that comment does not include marker when content_hash is None."""
    violations = [
        Violation(rule_description="Rule 1", severity=Severity.HIGH, message="Error 1"),
    ]

    comment = format_violations_comment(violations, content_hash=None)

    assert "<!-- watchflow-violations-hash:" not in comment
    assert "### 🛡️ Watchflow Governance Checks" in comment
