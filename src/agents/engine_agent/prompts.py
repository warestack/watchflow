"""
Prompts for the Rule Engine Agent.
"""

import json
from typing import Any


def create_rule_filtering_prompt(event_type: str, rules: list[dict[str, Any]], available_validators: list[str]) -> str:
    """Create a prompt for LLM rule filtering and strategy selection."""

    system_prompt = f"""
You are a rule evaluation expert. Your job is to analyze rules and decide the best evaluation strategy.

AVAILABLE VALIDATORS (fast, deterministic):
{available_validators}

EVENT TYPE: {event_type}

For each rule, you must decide:
1. Is this rule applicable to the event type?
2. Should I use a validator (fast) or LLM reasoning (flexible)?

EVALUATION STRATEGY:
- Use VALIDATORS for: Standard checks like PR approvals, file size limits, title patterns, label requirements
- Use LLM REASONING for: Complex business logic, custom rules, security policies, compliance requirements

RESPONSE FORMAT (JSON):
{{
    "applicable_rules": [
        {{
            "rule_id": "rule-id",
            "rule_name": "Rule Name",
            "evaluation_strategy": "validator" | "llm_reasoning",
            "validator_name": "validator_name" (if strategy is "validator"),
            "reasoning": "why this strategy was chosen"
        }}
    ]
}}

RULES TO ANALYZE:
"""

    # Add rules to the prompt
    for rule in rules:
        system_prompt += f"""
- ID: {rule.get("id", "unknown")}
- Name: {rule.get("name", "Unknown")}
- Description: {rule.get("description", "No description")}
- Parameters: {rule.get("parameters", {})}
- Event Types: {rule.get("event_types", [])}
"""

    return system_prompt


def create_llm_evaluation_prompt(rule: dict[str, Any], event_data: dict[str, Any], event_type: str) -> str:
    """Create a prompt for LLM rule evaluation."""

    # Format parameters for better readability
    parameters_str = json.dumps(rule.get("parameters", {}), indent=2)

    evaluation_prompt = f"""
You are evaluating a rule against a GitHub event using intelligent reasoning.

RULE:
- ID: {rule.get("id", "unknown")}
- Name: {rule.get("name", "Unknown")}
- Description: {rule.get("description", "No description")}
- Parameters: {parameters_str}
- Severity: {rule.get("severity", "medium")}

EVENT TYPE: {event_type}

EVENT DATA:
{json.dumps(event_data, indent=2)}

TASK: Determine if this rule is violated by the event.

EVALUATION APPROACH:
1. Understand the rule's purpose from its description
2. Analyze the event data in context of the rule's requirements
3. **Carefully consider the rule's parameters** - these define the specific thresholds, patterns, or conditions
4. Consider the rule's severity level
5. Make a reasoned judgment about compliance

PARAMETER ANALYSIS:
The rule parameters define specific requirements. For example:
- min_approvals: 2 → Requires at least 2 approvals
- max_file_size: 1000000 → Files cannot exceed 1MB
- required_labels: ["security", "review"] → Must have these labels
- title_pattern: "^feat|^fix|^docs" → Title must match this pattern

RESPONSE FORMAT (JSON):
{{
    "is_violated": true/false,
    "message": "Clear explanation of the violation or why it passed",
    "details": {{
        "parameter_check": "How parameters were evaluated",
        "thresholds_checked": "Specific thresholds/conditions verified",
        "other_key": "other_value"
    }},
    "how_to_fix": "Specific steps to fix the violation",
    "reasoning": "Your detailed reasoning process including parameter analysis",
    "confidence": 0.0-1.0
}}

Respond with ONLY the JSON, no other text.
"""

    return evaluation_prompt


def get_llm_evaluation_system_prompt() -> str:
    """Get the system prompt for LLM rule evaluation."""
    return """You are a rule evaluation expert with deep understanding of software development practices, security requirements, and compliance standards.

Your role is to:
1. Analyze rule descriptions to understand their purpose and importance
2. Carefully evaluate rule parameters to understand specific requirements
3. Compare event data against the rule's parameters and thresholds
4. Make reasoned judgments about compliance
5. Provide clear explanations and actionable feedback

You should be thorough in your parameter analysis and provide specific details about how each parameter was evaluated."""


def create_validator_selection_prompt(rules: list[dict[str, Any]], event_type: str, validator_list: list[str]) -> str:
    """Create a prompt for LLM validator selection."""

    prompt = (
        f"You are an expert at mapping rules to validators for GitHub events.\n"
        f"Current event type: {event_type}\n"
        f"For each rule below, select the best validator from this list: {validator_list}, "
        f"or respond with 'llm_reasoning' if none are suitable.\n"
        f"IMPORTANT: Only evaluate rules that are applicable to {event_type} events.\n"
        f"Respond as a JSON list: "
        f'[{{"rule_id": ..., "validator_name": ...}}, ...]\n\n'
        f"Rules:\n"
    )

    for rule in rules:
        # Include the rule's event_types in the prompt for better context
        rule_event_types = rule.get("event_types", [])
        prompt += (
            f"- id: {rule.get('id')}\n"
            f"  name: {rule.get('name')}\n"
            f"  description: {rule.get('description')}\n"
            f"  event_types: {rule_event_types}\n"
            f"  parameters: {rule.get('parameters')}\n"
        )

    return prompt
