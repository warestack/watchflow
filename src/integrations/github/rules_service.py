from typing import Any

import structlog

from src.integrations.github import github_client
from src.rules.utils.validation import validate_rules_config

logger = structlog.get_logger()


async def validate_rules_yaml_from_repo(repo_full_name: str, installation_id: int, pr_number: int):
    """Validate rules YAML and post results to PR comment."""
    validation_result = await _validate_rules_yaml(repo_full_name, installation_id)
    # Only post a comment if the result is not a success
    if not validation_result["success"]:
        await github_client.create_pull_request_comment(
            repo=repo_full_name,
            pr_number=pr_number,
            comment=validation_result["message"],
            installation_id=installation_id,
        )
        logger.info(f"Posted validation result to PR #{pr_number} in {repo_full_name}")


async def _validate_rules_yaml(repo: str, installation_id: int) -> dict[str, Any]:
    """Validate rules YAML file from repository."""
    try:
        file_content = await github_client.get_file_content(repo, ".watchflow/rules.yaml", installation_id)
        if file_content is None:
            return {
                "success": False,
                "message": (
                    "⚙️ **Watchflow rules not configured**\n\n"
                    "No rules file found in your repository. Watchflow can help enforce governance rules for your team.\n\n"
                    "**How to set up rules:**\n"
                    "1. Create a file at `.watchflow/rules.yaml` in your repository root\n"
                    "2. Add your rules in the following format:\n"
                    "   ```yaml\n   rules:\n     - description: All pull requests must have at least 2 approvals\n       enabled: true\n       severity: high\n       event_types: [pull_request]\n       parameters:\n         min_approvals: 2\n   ```\n\n"
                    "**Note:** Rules are currently read from the main branch only.\n\n"
                    "📖 [Read the documentation for more examples](https://github.com/warestack/watchflow/blob/main/docs/getting-started/configuration.md)\n\n"
                    "After adding the file, push your changes to re-run validation."
                ),
            }

        return validate_rules_config(file_content)

    except Exception as e:
        logger.error(f"Error validating rules for {repo}: {e}")
        return {
            "success": False,
            "message": f"❌ **Error validating rules**\n\nAn unexpected error occurred: {str(e)}",
        }
