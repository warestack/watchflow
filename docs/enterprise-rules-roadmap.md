# Enterprise & Regulated Industry Guardrails

To level up Watchflow for large engineering teams and highly regulated industries (FinTech, HealthTech, Enterprise SaaS), we should expand our rule engine to support strict compliance, auditability, and advanced access control.

## 1. Compliance & Security Verification Rules

### `SignedCommitsCondition`
**Purpose:** Ensure all commits in a PR are signed (GPG/SSH/S/MIME).
**Why:** Required by SOC2, FedRAMP, and most enterprise security teams to prevent impersonation.
**Parameters:** `require_signed_commits: true`

### `SecretScanningCondition` (Enhanced)
**Purpose:** Integrate with GitHub Advanced Security or detect specific sensitive file extensions.
**Why:** Catching hardcoded secrets before they merge is a massive pain point. We built regex parsing, but we can add native hooks to check if GitHub's native secret scanner triggered alerts on the branch.
**Parameters:** `block_on_secret_alerts: true`

### `BannedDependenciesCondition`
**Purpose:** Parse `package.json`, `requirements.txt`, or `go.mod` diffs to block banned licenses (e.g., AGPL) or deprecated libraries.
**Why:** Open-source license compliance and CVE prevention.
**Parameters:** `banned_licenses: ["AGPL", "GPL"]`, `banned_packages: ["requests<2.0.0"]`

## 2. Advanced Access Control (Separation of Duties)

### `CrossTeamApprovalCondition`
**Purpose:** Require approvals from at least two different GitHub Teams.
**Why:** Regulated environments require "Separation of Duties" (e.g., a dev from `backend-team` and a dev from `qa-team` must both approve).
**Parameters:** `required_team_approvals: ["@org/backend", "@org/qa"]`

### `NoSelfApprovalCondition`
**Purpose:** Explicitly block PR authors from approving their own PRs (or using a secondary admin account to do so).
**Why:** Strict SOX/SOC2 requirement.
**Parameters:** `block_self_approval: true`

## 3. Operations & Reliability

### `MigrationSafetyCondition`
**Purpose:** If a PR modifies database schemas/migrations (e.g., `alembic/`, `prisma/migrations/`), enforce that it does *not* contain destructive operations like `DROP TABLE` or `DROP COLUMN`.
**Why:** Prevents junior devs from accidentally wiping production data.
**Parameters:** `safe_migrations_only: true`

### `FeatureFlagRequiredCondition`
**Purpose:** If a PR exceeds a certain size or modifies core routing, ensure a feature flag is added.
**Why:** Enables safe rollbacks and trunk-based development.
**Parameters:** `require_feature_flags_for_large_prs: true`

## 4. Documentation & Traceability

### `JiraTicketStatusCondition`
**Purpose:** Instead of just checking if a Jira ticket *exists* in the title, make an API call to Jira to ensure the ticket is in the "In Progress" or "In Review" state.
**Why:** Prevents devs from linking to closed, backlog, or fake tickets just to bypass the basic `RequireLinkedIssue` rule.
**Parameters:** `require_active_jira_ticket: true`

### `ChangelogRequiredCondition`
**Purpose:** If `src/` files change, require an addition to `CHANGELOG.md` or a `.changeset/` file.
**Why:** Maintains release notes for compliance audits automatically.
**Parameters:** `require_changelog_update: true`

## 5. Potential GitHub Ecosystem Integrations

To make Watchflow a true "single pane of glass" for governance, we can build custom condition handlers that hook directly into GitHub's native ecosystem.

### `CodeQLAnalysisCondition`
**Purpose:** Block merges if CodeQL (or other static analysis tools) has detected critical vulnerabilities in the PR diff.
**How to build:** Call the GitHub `code-scanning/alerts` API for the current `head_sha`.
**Why:** Instead of developers having to check multiple tabs, Watchflow summarizes the CodeQL alerts and makes them enforceable via YAML.
**Parameters:** `block_on_critical_codeql: true`

### `DependabotAlertsCondition`
**Purpose:** Ensure developers do not merge PRs that introduce new dependencies with known CVEs.
**How to build:** Hook into the `dependabot/alerts` REST API for the repository, filtering by the PR's branch.
**Why:** Shifting security left.
**Parameters:** `max_dependabot_severity: "high"`

## 6. Open-Source Ecosystem Integrations

We can leverage popular open-source Python SDKs directly within our rule engine to parse specific file types during the event evaluation.

### Open Policy Agent (OPA) / Rego Validation
**Purpose:** If a PR modifies `.rego` files or Kubernetes manifests, validate them against the OPA engine.
**How to build:** Embed the `opa` CLI or use the `PyOPA` library to evaluate the diff.
**Why:** Infrastructure-as-Code (IaC) teams need a way to ensure PRs don't introduce misconfigurations.

### Pydantic Schema Breakage Detection
**Purpose:** Detect backward-incompatible changes to REST API models.
**How to build:** If `models.py` changes, parse the old and new AST (Abstract Syntax Tree) to see if a required field was deleted or changed types.
**Why:** Breaking API contracts is a massive incident vector in enterprise microservices.

### Ruff / Black / ESLint Override Detection
**Purpose:** Flag PRs that introduce new `# noqa`, `# type: ignore`, or `// eslint-disable` comments.
**How to build:** Use our existing diff/patch parser to explicitly hunt for suppression comments in the added lines.
**Why:** Keeps technical debt from quietly slipping into the codebase.
**Parameters:** `allow_linter_suppressions: false`
