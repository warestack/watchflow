# Enterprise & Regulated Industry Guardrails

Watchflow's rule engine supports strict compliance, auditability, and advanced access control for large engineering teams and highly regulated industries (FinTech, HealthTech, Enterprise SaaS). This page tracks what's shipped and what's planned.

## Implemented

The following enterprise conditions are fully registered in the condition registry, wired into the evaluation pipeline, and support acknowledgment workflows. See [Configuration](getting-started/configuration.md) for YAML parameter reference.

### Compliance & security verification

| Condition | Parameter | Description |
|-----------|-----------|-------------|
| `SignedCommitsCondition` | `require_signed_commits: true` | Ensure all commits are signed (GPG/SSH/S/MIME). Required by SOC2, FedRAMP. |
| `SecurityPatternCondition` | `security_patterns: [...]` | Detect hardcoded secrets, API keys, or sensitive data in PR diffs. |
| `ChangelogRequiredCondition` | `require_changelog_update: true` | Require CHANGELOG or `.changeset` update when source files change. |

### Advanced access control (separation of duties)

| Condition | Parameter | Description |
|-----------|-----------|-------------|
| `NoSelfApprovalCondition` | `block_self_approval: true` | Block PR authors from approving their own PRs. SOX/SOC2 requirement. |
| `CrossTeamApprovalCondition` | `required_team_approvals: [...]` | Require approvals from specified GitHub teams. Simplified check; full team-membership resolution via GraphQL is tracked below. |

### Code quality & review workflow

| Condition | Parameter | Description |
|-----------|-----------|-------------|
| `DiffPatternCondition` | `diff_restricted_patterns: [...]` | Flag restricted regex patterns in added lines of PR diffs. |
| `UnresolvedCommentsCondition` | `block_on_unresolved_comments: true` | Block merge when unresolved review threads exist. |
| `TestCoverageCondition` | `require_tests: true` | Source changes must include corresponding test file changes. |
| `CommentResponseTimeCondition` | `max_comment_response_time_hours: N` | Enforce SLA for responding to review comments. |

---

## Planned

### Operations & reliability

#### `MigrationSafetyCondition`
**Purpose:** If a PR modifies database schemas/migrations (e.g., `alembic/`, `prisma/migrations/`), enforce that it does *not* contain destructive operations like `DROP TABLE` or `DROP COLUMN`.
**Why:** Prevents accidental production data loss.
**Parameters:** `safe_migrations_only: true`

#### `FeatureFlagRequiredCondition`
**Purpose:** If a PR exceeds a certain size or modifies core routing, ensure a feature flag is added.
**Why:** Enables safe rollbacks and trunk-based development.
**Parameters:** `require_feature_flags_for_large_prs: true`

### External integrations

#### `SecretScanningCondition` (Enhanced)
**Purpose:** Integrate with GitHub Advanced Security's native secret scanner alerts, beyond regex matching.
**Parameters:** `block_on_secret_alerts: true`

#### `BannedDependenciesCondition`
**Purpose:** Parse dependency diffs to block banned licenses (e.g., AGPL) or deprecated libraries.
**Parameters:** `banned_licenses: ["AGPL", "GPL"]`, `banned_packages: ["requests<2.0.0"]`

#### `JiraTicketStatusCondition`
**Purpose:** Verify Jira ticket state via API (must be "In Progress" or "In Review").
**Parameters:** `require_active_jira_ticket: true`

#### `CrossTeamApprovalCondition` -- full team membership
**Purpose:** Resolve reviewer-to-team membership via GraphQL instead of relying on `requested_teams`.
**Tracking:** Depends on GitHub's Team Members API access via GitHub App installation tokens.

### GitHub ecosystem integrations

#### `CodeQLAnalysisCondition`
**Purpose:** Block merges if CodeQL has detected critical vulnerabilities in the PR diff.
**How:** Call `code-scanning/alerts` API for the current `head_sha`.
**Parameters:** `block_on_critical_codeql: true`

#### `DependabotAlertsCondition`
**Purpose:** Ensure PRs don't introduce dependencies with known CVEs.
**How:** Hook into the `dependabot/alerts` REST API.
**Parameters:** `max_dependabot_severity: "high"`

### Open-source ecosystem integrations

#### OPA / Rego Validation
**Purpose:** Validate Kubernetes manifests or `.rego` files against OPA engine on PR.

#### Pydantic Schema Breakage Detection
**Purpose:** Detect backward-incompatible changes to REST API models by diffing ASTs.

#### Linter Suppression Detection
**Purpose:** Flag PRs that introduce `# noqa`, `# type: ignore`, or `// eslint-disable`.
**Parameters:** `allow_linter_suppressions: false`
