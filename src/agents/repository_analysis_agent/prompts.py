from langchain_core.prompts import ChatPromptTemplate

CONTRIBUTING_GUIDELINES_ANALYSIS_PROMPT = ChatPromptTemplate.from_template("""
You are a senior software engineer analyzing contributing guidelines to recommend appropriate repository governance rules.

Analyze the following CONTRIBUTING.md content and extract patterns, requirements, and best practices that would benefit from automated enforcement via Watchflow rules.

CONTRIBUTING.md Content:
{content}

Your task is to extract:
1. Pull request requirements (templates, reviews, tests, etc.)
2. Code quality standards (linting, formatting, etc.)
3. Documentation requirements
4. Commit message conventions
5. Branch naming conventions
6. Testing requirements
7. Security practices

Provide your analysis in the following JSON format:
{{
    "has_pr_template": boolean,
    "has_issue_template": boolean,
    "requires_tests": boolean,
    "requires_docs": boolean,
    "code_style_requirements": ["list", "of", "requirements"],
    "review_requirements": ["list", "of", "requirements"]
}}

Be thorough but only extract information that is explicitly mentioned or strongly implied in the guidelines.
""")

REPOSITORY_ANALYSIS_PROMPT = ChatPromptTemplate.from_template("""
You are analyzing a GitHub repository to recommend Watchflow rules based on its structure, workflows, and contributing patterns.

Repository Information:
- Name: {repository_full_name}
- Primary Language: {language}
- Contributors: {contributor_count}
- Pull Requests: {pr_count}
- Issues: {issue_count}
- Has Workflows: {has_workflows}
- Has Branch Protection: {has_branch_protection}
- Has CODEOWNERS: {has_codeowners}

Contributing Guidelines Analysis:
{contributing_analysis}

Based on this repository profile, recommend appropriate Watchflow rules that would improve governance, quality, and security.

Consider:
1. Code quality rules (linting, testing, formatting)
2. Security rules (dependency scanning, secret detection)
3. Process rules (PR reviews, branch protection, CI/CD)
4. Documentation rules (README updates, CHANGELOG)

For each recommendation, provide:
- A valid Watchflow rule YAML
- Confidence score (0.0-1.0)
- Reasoning for the recommendation
- Source patterns that led to it
- Category and impact level

Focus on rules that are most relevant to this repository's characteristics and would provide the most value.
""")

RULE_GENERATION_PROMPT = ChatPromptTemplate.from_template("""
Generate a valid Watchflow rule YAML based on the following specification:

Category: {category}
Description: {description}
Parameters: {parameters}
Event Types: {event_types}
Severity: {severity}

Generate a complete, valid Watchflow rule in YAML format that implements this specification.
Ensure the rule follows Watchflow YAML schema and is properly formatted.

Watchflow Rule YAML Format:
```yaml
description: "Rule description"
enabled: true
severity: "medium"
event_types:
  - pull_request
parameters:
  key: "value"
```

Make sure the rule is functional and follows best practices.
""")
