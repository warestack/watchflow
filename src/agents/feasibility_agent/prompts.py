"""
Prompt templates for the Rule Feasibility Agent.
"""

RULE_FEASIBILITY_PROMPT = """
You are an expert in Watchflow rules and GitHub automation. Your task is to analyze whether a natural language rule description is feasible to implement using Watchflow.

Rule Description: {rule_description}

Please analyze this rule and determine:
1. Is it feasible to implement with Watchflow's rule system?
2. What type of rule is it (time restriction, branch pattern, approval requirement, etc.)?
3. Provide feedback on implementation considerations

Consider the following rule types:
- time_restriction: Rules about when actions can occur (weekends, hours, days)
- branch_pattern: Rules about branch naming conventions
- title_pattern: Rules about PR title formatting
- label_requirement: Rules requiring specific labels
- file_size: Rules about file size limits
- approval_requirement: Rules about required approvals
- commit_message: Rules about commit message format
- branch_protection: Rules about protected branches

FEEDBACK GUIDELINES:
Keep feedback concise and practical. Focus on:
- How Watchflow will implement and enforce the rule
- Key configuration considerations (.watchflow/rules.yaml)
- What happens when rules are violated (comments, status checks)
- Practical implementation details
- Severity and enforcement level recommendations

Keep feedback under 200 words and avoid technical jargon.

Provide your analysis with step-by-step reasoning in the analysis_steps field.
"""

RULE_TYPE_ANALYSIS_PROMPT = """
Analyze the following rule description and identify the primary rule type:

Rule: {rule_description}

Available rule types:
- time_restriction: Rules about when actions can occur (weekends, hours, days)
- branch_pattern: Rules about branch naming conventions
- title_pattern: Rules about PR title formatting
- label_requirement: Rules requiring specific labels
- file_size: Rules about file size limits
- approval_requirement: Rules about required approvals
- commit_message: Rules about commit message format
- branch_protection: Rules about protected branches

Respond with just the rule type as a string.
"""

YAML_GENERATION_PROMPT = """
Generate Watchflow rules YAML configuration for the following rule:

Rule Type: {rule_type}
Description: {rule_description}

Generate a complete Watchflow rule configuration that follows this EXACT structure and format:

```yaml
- id: "ready-for-review-label"
  name: "Ready PRs Must Have ready-for-review Label"
  description: "Pull requests marked as ready must have the ready-for-review label"
  enabled: true
  severity: "medium"
  event_types: ["pull_request"]
  parameters:
    required_labels: ["ready-for-review"]
```

IMPORTANT:
- Generate ONLY the rule entry (starting with "- id:")
- Use the Watchflow rules format, NOT GitHub Actions workflow format
- Include only the rule configuration, not the full rules.yaml file structure
- Make the id descriptive and kebab-case
- Set appropriate severity (low, medium, high, critical)
- Include relevant event_types for the rule
- Add appropriate parameters based on the rule type

Rule type specific parameters:
- label_requirement: use "required_labels" parameter with array of required labels
- time_restriction: use "days" parameter for restricted days or "hours" for restricted hours
- approval_requirement: use "min_approvals" parameter with number
- title_pattern: use "title_pattern" parameter with regex pattern
- file_size: use "max_file_size_mb" parameter with number
- commit_message: use "pattern" parameter with regex pattern
- branch_protection: use "protected_branches" parameter with array of branch names

Return only the YAML rule configuration content.
"""
