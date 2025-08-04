"""
Prompt templates for the Rule Feasibility Agent.
"""

RULE_FEASIBILITY_PROMPT = """
You are an expert in Watchflow rules and GitHub automation. Analyze whether a natural language rule description is feasible to implement using Watchflow.

Rule Description: {rule_description}

Analyze this rule and determine:
1. Is it feasible to implement with Watchflow's rule system?
2. What type of rule is it?
3. Provide concise feedback on implementation considerations

Available rule types:
- label_requirement: Rules requiring specific labels
- time_restriction: Rules about when actions can occur (weekends, hours, days)
- approval_requirement: Rules about required approvals
- title_pattern: Rules about PR title formatting
- branch_pattern: Rules about branch naming conventions
- file_size: Rules about file size limits
- commit_message: Rules about commit message format
- branch_protection: Rules about protected branches

Focus on:
- Practical implementation with Watchflow
- Key configuration considerations
- Severity and enforcement level recommendations
- Keep feedback under 150 words
"""

YAML_GENERATION_PROMPT = """
Generate a complete Watchflow rule configuration for the following rule:

Rule Type: {rule_type}
Description: {rule_description}

Generate a complete rules.yaml file that follows this EXACT structure:

```yaml
rules:
  - description: "Clear description of what this rule does"
    enabled: true
    severity: "medium"
    event_types: ["pull_request"]
    parameters:
      required_labels: ["security", "review"]
```

IMPORTANT REQUIREMENTS:
- Generate the COMPLETE rules.yaml file including the "rules:" wrapper
- Use the rule description as the primary identifier
- Include enabled: true (allows rule activation/deactivation)
- Set appropriate severity (low, medium, high, critical)
- Include relevant event_types
- Add correct parameters based on rule type
- For regex patterns, use single quotes to avoid YAML parsing issues

Rule type parameters:
- label_requirement: use "required_labels" with array of labels
- time_restriction: use "days" for restricted days or "allowed_hours" for restricted hours
- approval_requirement: use "min_approvals" with number
- title_pattern: use "title_pattern" with regex pattern (use single quotes for regex)
- file_size: use "max_file_size_mb" with number
- commit_message: use "pattern" with regex pattern (use single quotes for regex)
- branch_protection: use "protected_branches" with array of branch names

Examples of proper regex patterns:
- title_pattern: '^feat|^fix|^docs'  # Use single quotes
- pattern: '^[A-Z]+-\\d+'  # Use single quotes for regex

Return the complete YAML file content.
"""
