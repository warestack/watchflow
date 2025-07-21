import logging

import yaml

from src.integrations.github_api import github_client
from src.rules.models import Rule

logger = logging.getLogger(__name__)

DOCS_URL = "https://github.com/warestack/watchflow/docs/getting-started/configuration.md"


async def validate_rules_yaml_from_repo(repo_full_name: str, installation_id: int, pr_number: int):
    validation_result = await _validate_rules_yaml(repo_full_name, installation_id)
    # Only post a comment if the result is not a success (i.e., does not start with the green checkmark)
    if not validation_result.strip().startswith("✅"):
        await github_client.create_pull_request_comment(
            repo=repo_full_name,
            pr_number=pr_number,
            comment=validation_result,
            installation_id=installation_id,
        )
        logger.info(f"Posted validation result to PR #{pr_number} in {repo_full_name}")


async def _validate_rules_yaml(repo: str, installation_id: int) -> str:
    try:
        file_content = await github_client.get_file_content(repo, ".watchflow/rules.yaml", installation_id)
        if file_content is None:
            return (
                "❌ **Watchflow rules file not found**\n\n"
                "The file `.watchflow/rules.yaml` is missing from your repository.\n\n"
                "**How to fix:**\n"
                "1. Create a file at `.watchflow/rules.yaml` in your repository root.\n"
                "2. Add your rules in the following format:\n"
                "   ```yaml\n   rules:\n     - id: example-rule\n       description: Example rule description\n       ...\n   ```\n"
                f"3. [Read the documentation for more details.]({DOCS_URL})\n\n"
                "After adding the file, push your changes to re-run validation."
            )
        try:
            rules_data = yaml.safe_load(file_content)
        except Exception as e:
            return (
                "❌ **Failed to parse `.watchflow/rules.yaml`**\n\n"
                f"Error details: `{e}`\n\n"
                "**How to fix:**\n"
                "- Ensure your YAML is valid. You can use an online YAML validator.\n"
                "- Check for indentation, missing colons, or invalid syntax.\n\n"
                f"[See configuration docs.]({DOCS_URL})"
            )
        if not isinstance(rules_data, dict) or "rules" not in rules_data:
            return (
                "❌ **Invalid `.watchflow/rules.yaml`: missing top-level `rules:` key**\n\n"
                "Your file must start with a `rules:` key, like:\n"
                "```yaml\nrules:\n  - id: ...\n```\n"
                f"[See configuration docs.]({DOCS_URL})"
            )
        if not isinstance(rules_data["rules"], list):
            return (
                "❌ **Invalid `.watchflow/rules.yaml`: `rules` must be a list**\n\n"
                "Example:\n"
                "```yaml\nrules:\n  - id: my-rule\n    description: ...\n```\n"
                f"[See configuration docs.]({DOCS_URL})"
            )
        if not rules_data["rules"]:
            return (
                "✅ **`.watchflow/rules.yaml` is valid but contains no rules.**\n\n"
                "You can add rules at any time. [See documentation for examples.]"
                f"({DOCS_URL})"
            )
        for i, rule_data in enumerate(rules_data["rules"]):
            try:
                Rule.model_validate(rule_data)
            except Exception as e:
                return (
                    f"❌ **Rule #{i + 1} (`{rule_data.get('id', 'N/A')}`) failed validation**\n\n"
                    f"Error: `{e}`\n\n"
                    "Please check your rule definition and fix the error above.\n\n"
                    f"[See rule schema docs.]({DOCS_URL})"
                )
        return f"✅ **`.watchflow/rules.yaml` is valid and contains {len(rules_data['rules'])} rules.**\n\nNo action needed."
    except Exception as e:
        return (
            f"❌ **Error validating `.watchflow/rules.yaml`**\n\nError: `{e}`\n\n[See configuration docs.]({DOCS_URL})"
        )
