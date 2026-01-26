# File: src/agents/repository_analysis_agent/prompts.py

REPOSITORY_ANALYSIS_SYSTEM_PROMPT = """
Generate RuleRecommendation objects based on hygiene metrics.

Issue → Validator Mapping:
- High unlinked_issue_rate → `required_labels`, `title_pattern` (enforce issue linking)
- High average_pr_size (>500) → `max_file_size_mb`, `diff_pattern` (limit PR size)
- High codeowner_bypass_rate → `code_owners` (enforce CODEOWNERS)
- Low new_code_test_coverage → `related_tests`, `required_field_in_diff` (require tests)
- High ci_skip_rate → `required_checks` (enforce CI)
- High first_time_contributor_count → `min_approvals`, `past_contributor_approval` (extra review)
- High issue_diff_mismatch_rate → `title_pattern`, `min_description_length` (enforce descriptions)
- High ghost_contributor_rate → `min_approvals` (require engagement)
- High ai_generated_rate → `min_approvals`, `past_contributor_approval` (quality gate)

Use only validators from: {validator_catalog}
Return JSON matching RuleRecommendation schema.
Generate 3-5 rules. Prioritize highest-risk metrics.
"""

RULE_GENERATION_USER_PROMPT = """
Repository: {repo_name}
Languages: {languages}
CI/CD: {has_ci}
CODEOWNERS: {has_codeowners}
Files: {file_count}
Workflows: {workflow_patterns}

Hygiene Metrics (Issues Identified):
{hygiene_summary}

Available Validators:
{validator_catalog}

File Tree Sample:
{file_tree_snippet}

Docs Summary:
{docs_snippet}

Generate 3-5 rules that address the specific issues identified in metrics above.
Map each issue to appropriate validators from the catalog.
Return JSON matching RuleRecommendation schema.
"""
