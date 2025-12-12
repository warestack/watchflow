"""
Prompt templates for the Rule Feasibility Agent.
"""

RULE_FEASIBILITY_PROMPT = """
You are an expert in Watchflow rules and GitHub automation. Analyze whether a natural language rule description is feasible to implement using Watchflow’s existing validator catalog. Do NOT invent custom logic; choose from the provided validators. If none fit, mark as not feasible.

Rule Description:
{rule_description}

Available validators (name, event_types, parameter_patterns, description):
{validator_catalog}

Decide:
1) is_feasible (true/false)
2) rule_type (short label you infer)
3) chosen_validators (list of validator names from the catalog that can implement this rule; empty if not feasible)
4) feedback (practical, under 120 words)
5) analysis_steps (succinct bullets)
"""

YAML_GENERATION_PROMPT = """
Generate a complete Watchflow rules.yaml for the rule below using ONLY the selected validators. Do not introduce parameters that the chosen validators do not support.

Rule Type: {rule_type}
Description: {rule_description}
Chosen Validators: {chosen_validators}

Rules YAML format:
```yaml
rules:
  - description: "<concise description>"
    enabled: true
    severity: "medium"
    event_types: ["pull_request"]
    parameters:
      <validator-appropriate-parameters>
```

Guidelines:
- Keep severity appropriate (low/medium/high/critical).
- event_types must align with the validators chosen.
- For regex, use single quotes.
- If no validators fit, return an empty yaml_content.
Return only the YAML content.
"""
