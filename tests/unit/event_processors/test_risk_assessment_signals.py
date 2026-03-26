from src.core.models import Severity, Violation
from src.event_processors.risk_assessment.signals import _format_path_signal_description


def test_format_required_pattern_signal_description():
    violation = Violation(
        rule_description="Security risk: changes to security-sensitive paths require explicit review.",
        severity=Severity.HIGH,
        message="No files match required pattern 'app/auth/*'",
    )

    formatted = _format_path_signal_description("Security sensitive risk", violation)

    assert (
        formatted
        == "Security path risk app/auth/* (severity: high) - No files match required pattern"
    )


def test_format_forbidden_pattern_signal_description():
    violation = Violation(
        rule_description="Critical path risk: changes under app/payments require risk review.",
        severity=Severity.MEDIUM,
        message="Files match forbidden pattern 'app/payments/*': ['app/payments/processor.py']",
    )

    formatted = _format_path_signal_description("Rule match risk detected:", violation)

    assert (
        formatted == "Critical path risk app/payments/* (severity: medium) - Files match forbidden pattern"
    )


def test_format_non_path_signal_description_falls_back_to_default():
    violation = Violation(
        rule_description="rule",
        severity=Severity.LOW,
        message="Some other non-path violation message",
    )

    formatted = _format_path_signal_description("Rule match risk detected:", violation)

    assert formatted == "Rule match risk detected: Some other non-path violation message"
