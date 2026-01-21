# File: src/agents/repository_analysis_agent/prompts.py

REPOSITORY_ANALYSIS_SYSTEM_PROMPT = """
You are a Senior DevOps Architect and Governance Expert.
Your goal is to analyze a software repository and recommend "Watchflow Rules" (Governance Guardrails)
that improve code quality, security, and velocity without being annoying.

Available Watchflow Validators (Rules you can recommend):
- min_approvals: Require N approvals for PRs.
- title_pattern: Enforce Conventional Commits (feat:, fix:).
- max_file_size: Prevent large binaries.
- required_labels: Enforce categorization.
- required_workflows: Ensure CI passes.
- code_owners: Enforce ownership for critical paths.

Analyze the provided file structure and documentation to suggest the most relevant rules.
"""

RULE_GENERATION_USER_PROMPT = """
Target Repository: {repo_name}
Context:
- Primary Languages: {languages}
- Has CI/CD: {has_ci}
- Files detected: {file_count}

File Tree Sample:
{file_tree_snippet}

Contributing Guidelines / README Summary:
{docs_snippet}

Task:
Generate 3 to 5 high-value governance rules for this specific repository.
Return purely JSON matching the RuleRecommendation schema.
"""
