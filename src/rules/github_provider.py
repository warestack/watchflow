import logging
from typing import Any

import yaml

from src.core.config import config
from src.core.models import EventType
from src.integrations.github_api import GitHubClient, github_client
from src.rules.interface import RuleLoader
from src.rules.models import Rule, RuleAction, RuleSeverity

logger = logging.getLogger(__name__)


class RulesFileNotFoundError(Exception):
    """Raised when the rules file is not found in the repository."""

    pass


class GitHubRuleLoader(RuleLoader):
    """
    Loads rules from a GitHub repository's rules yaml file.
    This provider does NOT map parameters to condition types; it loads rules as-is.
    """

    def __init__(self, github_client: GitHubClient):
        self.github_client = github_client

    async def get_rules(self, repository: str, installation_id: int) -> list[Rule]:
        try:
            # Construct the rules file path using config
            rules_file_path = f"{config.repo_config.base_path}/{config.repo_config.rules_file}"

            logger.info(f"Fetching rules for repository: {repository} (installation: {installation_id})")
            content = await self.github_client.get_file_content(repository, rules_file_path, installation_id)
            if not content:
                logger.warning(f"No rules.yaml file found in {repository}")
                raise RulesFileNotFoundError(f"Rules file not found: {rules_file_path}")

            rules_data = yaml.safe_load(content)
            if not rules_data or "rules" not in rules_data:
                logger.warning(f"No rules found in {repository}/{rules_file_path}")
                return []

            rules = []
            for rule_data in rules_data["rules"]:
                try:
                    rule = self._parse_rule(rule_data)
                    if rule:
                        rules.append(rule)
                except Exception as e:
                    logger.error(f"Error parsing rule {rule_data.get('id', 'unknown')}: {e}")
                    continue

            logger.info(f"Successfully loaded {len(rules)} rules from {repository}")
            return rules
        except RulesFileNotFoundError:
            # Re-raise this specific exception
            raise
        except Exception as e:
            logger.error(f"Error fetching rules for {repository}: {e}")
            raise

    def _parse_rule(self, rule_data: dict[str, Any]) -> Rule:
        event_types = []
        if "event_types" in rule_data:
            for event_type_str in rule_data["event_types"]:
                try:
                    event_type = EventType(event_type_str)
                    event_types.append(event_type)
                except ValueError:
                    logger.warning(f"Unknown event type: {event_type_str}")
        # No mapping: just pass parameters as-is
        parameters = rule_data.get("parameters", {})
        # Actions are optional and not mapped
        actions = []
        if "actions" in rule_data:
            for action_data in rule_data["actions"]:
                action = RuleAction(type=action_data["type"], parameters=action_data.get("parameters", {}))
                actions.append(action)
        rule = Rule(
            id=rule_data["id"],
            name=rule_data["name"],
            description=rule_data["description"],
            enabled=rule_data.get("enabled", True),
            severity=RuleSeverity(rule_data.get("severity", "medium")),
            event_types=event_types,
            # No conditions: parameters are passed as-is
            conditions=[],
            actions=actions,
            parameters=parameters,
        )
        return rule


github_rule_loader = GitHubRuleLoader(github_client)
