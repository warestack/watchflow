"""
Prompt templates for the Reviewer Reasoning Agent.
"""

from src.agents.reviewer_reasoning_agent.models import ReviewerProfile


def get_system_prompt() -> str:
    """System prompt for reviewer reasoning."""
    return """You are a code review assistant for Watchflow, a GitHub governance tool.

Your job is to rewrite a reviewer's scoring signals as a concise, comma-separated list of reasons.
Keep the list format — do NOT write a prose sentence. Each item should be clear and self-explanatory.

Rules:
- Keep the same structure: one short phrase per signal, joined by commas.
- Use the PR context (changed files, risk signals) to make each reason specific where possible.
- If a rule name is available, quote it briefly (e.g. "required reviewer per rule: Auth changes need approval").
- Replace vague phrases with concrete ones using the context provided.
- Max ~15 words per item, max ~6 items total.

Examples of good output:
  "mentioned in CODEOWNERS for src/api, 6 recent commits on changed paths, python expertise (expertise.yaml)"
  "required reviewer per rule: Security-sensitive paths, reviewed 8 high-risk PRs, expertise in src/auth (expertise.yaml)"
  "mentioned in CODEOWNERS (80% of changed files), worked on 3 of the changed files (expertise.yaml), last active >6 months ago"

Respond with structured output matching the ReviewerReasoningOutput model."""


def create_reasoning_prompt(
    risk_level: str,
    changed_files: list[str],
    risk_signals: list[str],
    reviewers: list[ReviewerProfile],
) -> str:
    """Build the human message prompt for reviewer reasoning."""
    file_sample = ", ".join(changed_files[:10]) if changed_files else "unknown"
    signals_text = "\n".join(f"- {s}" for s in risk_signals) if risk_signals else "None"

    reviewer_lines: list[str] = []
    for r in reviewers:
        parts = [r.mechanical_reason or "contributor"]
        if r.rule_mentions:
            parts.append(f"rule_mentions={r.rule_mentions}")
        if r.languages:
            parts.append(f"languages={r.languages}")
        if r.reviews and any(v > 0 for v in r.reviews.values()):
            parts.append(f"reviews={r.reviews}")
        if r.last_active:
            parts.append(f"last_active={r.last_active}")
        reviewer_lines.append(f"- @{r.login} (score={r.score:.0f}): {' | '.join(parts)}")

    reviewers_text = "\n".join(reviewer_lines)

    return f"""Rewrite each reviewer's signals as a concise comma-separated reason list.

**PR context:**
- Risk level: {risk_level}
- Changed files: {file_sample}
- Risk signals:
{signals_text}

**Reviewers to rewrite:**
{reviewers_text}

For each reviewer output one comma-separated string of reasons. Use the changed files and risk signals to add specificity."""
