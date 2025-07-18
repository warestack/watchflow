"""
Prompts for the Intelligent Acknowledgment Agent.
"""

from typing import Any


def create_evaluation_prompt(
    acknowledgment_reason: str,
    violations: list[dict[str, Any]],
    pr_data: dict[str, Any],
    commenter: str,
    rules: list[dict[str, Any]],
) -> str:
    """Create a comprehensive prompt for acknowledgment evaluation."""

    # Build rule descriptions mapping
    rule_descriptions = {}
    for rule in rules:
        rule_descriptions[rule.get("id", "unknown")] = {
            "name": rule.get("name", "Unknown Rule"),
            "description": rule.get("description", "No description available"),
            "severity": rule.get("severity", "medium"),
            "parameters": rule.get("parameters", {}),
        }

    # Format violations with rule context
    formatted_violations = []
    for violation in violations:
        rule_id = violation.get("rule_id", "unknown")
        rule_info = rule_descriptions.get(rule_id, {})

        formatted_violations.append(
            {
                "rule_id": rule_id,
                "rule_name": violation.get("rule_name", rule_info.get("name", "Unknown Rule")),
                "rule_description": rule_info.get("description", "No description available"),
                "severity": violation.get("severity", rule_info.get("severity", "medium")),
                "message": violation.get("message", "Rule violation detected"),
                "how_to_fix": violation.get("how_to_fix", ""),
                "details": violation.get("details", {}),
            }
        )

    # Calculate PR metrics
    pr_size = pr_data.get("additions", 0) + pr_data.get("deletions", 0)
    pr_files_changed = len(pr_data.get("files", []))
    pr_title = pr_data.get("title", "No title")
    pr_body = pr_data.get("body") or "No description"

    # Safely handle PR body for display
    pr_body_display = pr_body[:500] + ("..." if len(pr_body) > 500 else "") if pr_body else "No description"

    prompt = f"""
You are evaluating a request to acknowledge (override) rule violations in a GitHub pull request.

CONTEXT:
- Commenter: {commenter}
- Acknowledgment Reason: "{acknowledgment_reason}"
- PR Title: "{pr_title}"
- PR Size: {pr_size} lines changed ({pr_data.get("additions", 0)} additions, {pr_data.get("deletions", 0)} deletions)
- Files Changed: {pr_files_changed}
- PR Description: "{pr_body_display}"

VIOLATIONS TO EVALUATE:
"""

    for i, violation in enumerate(formatted_violations, 1):
        prompt += f"""
{i}. Rule: {violation["rule_name"]}
   Description: {violation["rule_description"]}
   Severity: {violation["severity"]}
   Message: {violation["message"]}
   How to Fix: {violation["how_to_fix"]}
   Details: {violation["details"]}
"""

    prompt += """

EVALUATION CRITERIA:
1. **Relevance**: Is this violation directly related to the acknowledgment reason?
2. **Safety**: Can this violation be safely overridden without compromising code quality, security, or compliance?
3. **Urgency**: Does the acknowledgment reason justify the urgency (hotfix, security, emergency)?
4. **Scope**: Is the PR scope small enough to justify the override?
5. **Risk**: What are the risks of acknowledging this violation?

ACKNOWLEDGMENT GUIDELINES:
- ✅ APPROPRIATE for:
  * **Reviewer unavailability**: Only acknowledge approval requirements when reviewers are unavailable for minor changes
  * **Minor documentation changes**: Only acknowledge rules that are irrelevant for docs (like approval requirements for README changes)
  * **Small formatting changes**: Only acknowledge rules that don't apply to formatting (like approval requirements for whitespace changes)
  * **Urgent security fixes**: Only acknowledge rules that would delay critical security fixes
  * **Production hotfixes**: Only acknowledge rules that would delay urgent production fixes
- ❌ INAPPROPRIATE for:
  * **Security policy violations**: Never acknowledge security-related rules
  * **Large code changes**: Don't acknowledge approval requirements for significant code changes
  * **Compliance requirements**: Don't acknowledge compliance rules that cannot be waived
  * **Architectural changes**: Don't acknowledge approval requirements for architectural changes

IMPORTANT: Only acknowledge violations that are DIRECTLY related to the acknowledgment reason. If the reason doesn't justify overriding a specific violation, mark it as requiring fixes.

TASK: Analyze each violation and determine if it can be acknowledged based on the reason and context. Be selective - only acknowledge violations that are truly justified by the acknowledgment reason.

RESPONSE FORMAT (JSON):
{
    "is_valid": true/false,
    "reasoning": "Overall reasoning for the acknowledgment decision",
    "acknowledgable_violations": [
        {
            "rule_id": "rule-id",  // Must match the rule_id from the original violations
            "rule_name": "Rule Name",
            "reason": "Why this violation can be acknowledged",
            "risk_level": "low/medium/high",
            "conditions": "Any conditions for the acknowledgment"
        }
    ],
    "require_fixes": [
        {
            "rule_id": "rule-id",  // Must match the rule_id from the original violations
            "rule_name": "Rule Name",
            "reason": "Why this violation cannot be acknowledged",
            "priority": "high/medium/low"
        }
    ],
    "confidence": 0.0-1.0,
    "recommendations": [
        "Specific recommendations for the team"
    ]
}

IMPORTANT: The rule_id in your response must exactly match the rule_id from the violations list above.

Respond with ONLY the JSON, no other text.
"""

    return prompt


def get_system_prompt() -> str:
    """Get the system prompt for acknowledgment evaluation."""
    return """You are an expert at evaluating rule violation acknowledgments. You understand software development practices, security requirements, and when it's appropriate to override automated checks.

Your role is to:
1. Analyze rule descriptions to understand their purpose and importance
2. Evaluate acknowledgment reasons against the context of the PR
3. Make intelligent decisions about which violations can be safely overridden
4. Provide detailed reasoning for your decisions
5. Consider the risks and implications of each acknowledgment

You should be balanced in your approach:
- Allow acknowledgments for low-risk changes when there's a reasonable justification
- Be more strict with high-severity rules and large changes
- Consider the practical realities of development (reviewer availability, urgent fixes)
- When reviewers are unavailable for minor changes, acknowledge approval requirements
- For weekend merge restrictions, only allow for genuine emergencies or hotfixes"""
