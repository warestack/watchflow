from __future__ import annotations

import fnmatch
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.rules.models import RuleWhen

logger = logging.getLogger(__name__)


def should_apply_rule(when: RuleWhen | None, event_data: dict[str, Any]) -> tuple[bool, str]:
    """
    Return whether the rule should be evaluated for this event, and a reason if skipped.

    Args:
        when: Parsed RuleWhen block (or None when the rule has no predicates).
        event_data: Enriched event data, expected to include `contributor_context`
            and `changed_files` when the predicates reference them.

    Returns:
        A tuple of (applies, reason). ``applies`` is True when all named
        predicates in ``when`` hold (or ``when`` is empty/None). ``reason``
        is a human-readable explanation when the rule is skipped, or an
        empty string when the rule applies. If a predicate is present but
        its required context is missing, the rule is applied (fail-open)
        and a warning is logged — skipping silently on missing data would
        hide misconfiguration.
    """
    if when is None:
        return True, ""

    contributor_ctx = event_data.get("contributor_context") or {}

    if when.contributor is not None:
        if not contributor_ctx:
            logger.warning("when.contributor set but contributor_context missing — applying rule")
        elif contributor_ctx.get("merged_pr_count") is None:
            # API failure: we cannot tell whether the author is first-time or trusted.
            # Fail-open (apply the rule) so a transient Search API outage does not
            # silently disable stricter checks for newcomers.
            logger.warning(f"when.contributor='{when.contributor}' set but merged_pr_count is unknown — applying rule")
        else:
            predicate = when.contributor.strip().lower()
            if predicate == "first_time":
                if not contributor_ctx.get("is_first_time", False):
                    return False, "contributor is not first-time"
            elif predicate == "trusted":
                if not contributor_ctx.get("trusted", False):
                    return False, "contributor is not trusted"
            else:
                logger.warning(f"Unknown contributor predicate '{when.contributor}' — ignoring")

    if when.pr_count_below is not None:
        if not contributor_ctx:
            logger.warning("when.pr_count_below set but contributor_context missing — applying rule")
        else:
            merged_count = contributor_ctx.get("merged_pr_count")
            if merged_count is None:
                logger.warning("when.pr_count_below set but merged_pr_count is None — applying rule")
            elif merged_count >= when.pr_count_below:
                return False, f"contributor has {merged_count} merged PRs (threshold: {when.pr_count_below})"

    if when.files_match is not None:
        patterns: list[str] = [when.files_match] if isinstance(when.files_match, str) else list(when.files_match)
        changed_files = event_data.get("changed_files") or []
        filenames = [f.get("filename", "") for f in changed_files if isinstance(f, dict) and f.get("filename")]
        if not any(fnmatch.fnmatch(name, pat) for name in filenames for pat in patterns):
            return False, f"no changed files match pattern {patterns}"

    return True, ""
