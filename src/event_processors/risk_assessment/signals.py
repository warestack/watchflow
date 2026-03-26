"""
Risk assessment signal evaluators.

Each evaluator is pure/synchronous and returns a list of RiskSignal instances,
one per triggered condition. Returns [] if nothing noteworthy was found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.agents import get_agent
from src.core.models import EventType, Severity, Violation
from src.rules.loaders.github_loader import github_rule_loader

if TYPE_CHECKING:
    from src.rules.models import Rule


@dataclass
class RiskSignal:
    category: str
    severity: Severity
    description: str


@dataclass
class RiskAssessmentResult:
    level: Severity
    signals: list[RiskSignal] = field(default_factory=list)


_SEVERITY_SCORE: dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 5,
}


_BOOST_MAX_SEVERITY: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 0.1,
    Severity.HIGH: 0.4,
    Severity.CRITICAL: 0.6,
}


_GENERAL_SEVERITY_TRESHOLD: dict[Severity, int] = {
    Severity.LOW: 0.2,
    Severity.MEDIUM: 0.5,
    Severity.HIGH: 0.8,
    Severity.CRITICAL: 1,
}

# RuleSeverity has legacy ERROR/WARNING values not present in Severity.
# Map them to their canonical equivalents so _SEVERITY_SCORE lookups never KeyError.
_RULE_SEVERITY_TO_SEVERITY: dict[str, Severity] = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
}


def _rule_severity(rule: Rule) -> Severity:
    return _RULE_SEVERITY_TO_SEVERITY.get(str(rule.severity.value).lower(), Severity.MEDIUM)


_REQUIRED_PATTERN_RE = re.compile(r"No files match required pattern '([^']+)'")
_FORBIDDEN_PATTERN_RE = re.compile(r"Files match forbidden pattern '([^']+)':")


def _derive_path_risk_label(default_label: str, violation: Violation) -> str:
    """Derive semantic label from rule description for path-based violations."""
    rule_description = (violation.rule_description or "").strip()
    if not rule_description:
        return default_label

    # Condition-level descriptions are generic and too verbose for comments.
    if rule_description.startswith("Validates if files in the event match or don't match a pattern"):
        return default_label

    # Rule descriptions typically start with "<label>: ...".
    label = rule_description.split(":", 1)[0].strip()
    if not label:
        return default_label

    # For path-based security violations, use clearer path-specific wording.
    if label.lower() == "security risk":
        return "Security path risk"

    return label


def _format_path_signal_description(label: str, violation: Violation) -> str:
    """Format path-based violation messages for reviewer/risk comments."""
    message = violation.message

    required_match = _REQUIRED_PATTERN_RE.search(message)
    if required_match:
        path = required_match.group(1)
        severity = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
        path_label = _derive_path_risk_label(label, violation)
        return f"{path_label} {path} (severity: {severity}) - No files match required pattern"

    forbidden_match = _FORBIDDEN_PATTERN_RE.search(message)
    if forbidden_match:
        path = forbidden_match.group(1)
        severity = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
        path_label = _derive_path_risk_label(label, violation)
        return f"{path_label} {path} (severity: {severity}) - Files match forbidden pattern"

    return f"{label} {message}"


async def _load_pull_request_rules(
    repo: str,
    installation_id: int,
) -> list[Rule]:
    """Load PR rules from repo."""
    try:
        rules: list[Rule] = await github_rule_loader.get_rules(repo, installation_id)
    except Exception:
        return []

    return [rule for rule in rules if EventType.PULL_REQUEST in rule.event_types]


async def _evaluate_rules(
    rules: list[Rule],
    event_data: dict[str, Any],
) -> list[Violation]:
    """Run rule conditions against the PR and return violations."""
    engine_agent = get_agent("engine")
    result = await engine_agent.execute(
        event_type="pull_request",
        event_data=event_data,
        rules=rules,
    )

    return result.data["evaluation_result"].violations


async def evaluate_size(rules: list[Rule], event_data: dict[str, Any]) -> list[RiskSignal]:
    """Produce signals for large PR size."""

    # TODO: add file number and commit number checks
    size_rules = [rule for rule in rules if "max_lines" in rule.parameters or "max_file_size_mb" in rule.parameters]
    if not size_rules:
        return []

    violations = await _evaluate_rules(size_rules, event_data)

    return [
        RiskSignal(
            "size-risk",
            v.severity,
            f"Size risk detected: {v.message}",
        )
        for v in violations
        if v.severity != Severity.INFO
    ]


async def evaluate_critical_path(rules: list[Rule], event_data: dict[str, Any]) -> list[RiskSignal]:
    """One signal per file matching a critical business path pattern."""

    critical_owners_rules = [rule for rule in rules if "critical_owners" in rule.parameters]
    if not critical_owners_rules:
        return []

    violations = await _evaluate_rules(critical_owners_rules, event_data)

    return [
        RiskSignal(
            "critical-path",
            v.severity,
            f"Critical path risk detected: {v.message}",
        )
        for v in violations
        if v.severity != Severity.INFO
    ]


async def evaluate_test_coverage(rules: list[Rule], event_data: dict[str, Any]) -> list[RiskSignal]:
    """Detect test coverage risk signals."""

    test_coverage_rules = [rule for rule in rules if "require_tests" in rule.parameters]
    if not test_coverage_rules:
        return []

    violations = await _evaluate_rules(test_coverage_rules, event_data)

    return [
        RiskSignal(
            "test-coverage",
            v.severity,
            f"Test coverage risk detected: {v.message}",
        )
        for v in violations
        if v.severity != Severity.INFO
    ]


def evaluate_contributor_history(pr_data: dict[str, Any]) -> list[RiskSignal]:
    """Signal based on the author's association to the repository."""
    association = (pr_data.get("author_association") or "").upper()
    if association in ("FIRST_TIME_CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR_ON_CREATE", "FIRST_TIMER", "NONE"):
        return [RiskSignal("contributor", Severity.HIGH, "Author is a first-time contributor")]
    return []


async def evaluate_security_sensitive(rules: list[Rule], event_data: dict[str, Any]) -> list[RiskSignal]:
    """One signal per file matching security-sensitive infrastructure patterns."""

    security_pattern_rules = [rule for rule in rules if "security_patterns" in rule.parameters]
    if not security_pattern_rules:
        return []

    violations = await _evaluate_rules(security_pattern_rules, event_data)

    return [
        RiskSignal(
            "security-sensitive",
            v.severity,
            _format_path_signal_description("Security path risk", v),
        )
        for v in violations
        if v.severity != Severity.INFO
    ]


async def evaluate_rule_matches(rules: list[Rule], event_data: dict[str, Any]) -> list[RiskSignal]:
    """One signal per rule violation."""

    already_processed_rule_parameters = [
        "max_lines",
        "max_file_size_mb",
        "critical_owners",
        "require_tests",
        "security_patterns",
    ]
    leftover_rules = [
        rule for rule in rules if all(k not in rule.parameters for k in already_processed_rule_parameters)
    ]
    if not leftover_rules:
        return []

    violations = await _evaluate_rules(leftover_rules, event_data)

    return [
        RiskSignal(
            "rule-match",
            v.severity,
            _format_path_signal_description("Rule match risk detected:", v),
        )
        for v in violations
        if v.severity != Severity.INFO
    ]


def compute_risk(rules: list[Rule], signals: list[RiskSignal]) -> RiskAssessmentResult:
    """Overall risk level = maximum severity across all triggered signals."""
    if not signals:
        return RiskAssessmentResult(level=Severity.LOW, signals=signals)

    max_level = max((s.severity for s in signals), key=lambda sev: _SEVERITY_SCORE[sev])
    max_score = sum(_SEVERITY_SCORE[_rule_severity(rule)] for rule in rules)

    if max_score == 0:
        # No rules configured — cannot normalise; use the highest signal severity directly.
        return RiskAssessmentResult(level=max_level, signals=signals)

    pr_score = max_score * _BOOST_MAX_SEVERITY[max_level] + sum(_SEVERITY_SCORE[signal.severity] for signal in signals)
    pr_score_percentage = pr_score / max_score

    general_severity = next(
        (level for level, percentage in _GENERAL_SEVERITY_TRESHOLD.items() if pr_score_percentage <= percentage),
        Severity.CRITICAL,
    )
    return RiskAssessmentResult(level=general_severity, signals=signals)


async def generate_risk_assessment(
    repo: str,
    installation_id: int,
    pr_data: dict[str, Any],
    pr_files: list[dict[str, Any]],
):
    rules = await _load_pull_request_rules(repo, installation_id)

    # Prepare event data in the format expected by the agentic analysis
    event_data = {
        "pull_request_details": pr_data,
        "files": pr_files,
        "repository": {"full_name": repo},
        "installation": {"id": installation_id},
    }

    signals = []
    signals.extend(await evaluate_size(rules, event_data))
    signals.extend(await evaluate_critical_path(rules, event_data))
    signals.extend(await evaluate_test_coverage(rules, event_data))
    signals.extend(evaluate_contributor_history(pr_data))
    signals.extend(await evaluate_security_sensitive(rules, event_data))
    signals.extend(await evaluate_rule_matches(rules, event_data))

    return compute_risk(rules, signals)
