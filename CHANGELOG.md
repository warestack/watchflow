# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Description-diff alignment** -- `DescriptionDiffAlignmentCondition` uses
  the configured AI provider (OpenAI / Bedrock / Vertex AI) to verify that
  the PR description semantically matches the actual code changes. First
  LLM-backed condition in Watchflow; adds ~1-3s latency. Gracefully skips
  (no violation) if the LLM is unavailable.
- **Risk assessment** -- `/risk` slash command evaluates PR risk level
  (low / medium / high / critical) by running existing rule-engine conditions
  as signal evaluators. Risk labels (`watchflow:risk-*`) are applied and a
  breakdown comment is posted to the PR. Adding a new rule to
  `rules.yaml` automatically surfaces a corresponding risk signal with no
  code changes. Closes #65 (Phase 1).
- **Reviewer recommendation** -- `/reviewers` and `/reviewers --force` slash
  commands post a ranked list of suggested reviewers.
  `ReviewerRecommendationProcessor` uses a 3-tier scoring model: CODEOWNERS +
  commit history → `.watchflow/expertise.yaml` profiles → review history and
  critical-owner rule matches. Resolves team CODEOWNERS entries to individual
  members. Reviewer count scales with risk level (1 for low → 3 for
  critical). Closes #65 (Phases 2 & 3).
- **Review load balancing** -- Pending review counts are fetched per candidate
  (15-minute cache) and overloaded reviewers are penalized in the scoring
  model.
- **Reviewer Reasoning Agent** -- `ReviewerReasoningAgent` is a
  single-responsibility LLM agent that produces a natural-language explanation
  for each recommended reviewer and short topic labels for matched global
  rules. Typed `ReviewerReasoningInput` / `ReviewerReasoningOutput` Pydantic
  models at all boundaries. Supports global and path-specific rule context.
  Gracefully degrades to mechanical scoring reasons on LLM failure.
- **Contributor expertise profiles** -- Expertise data is stored in
  `.watchflow/expertise.yaml` on the default branch. Each contributor entry
  records `languages`, `commit_count`, `path_commit_counts`, `last_active`,
  and `reviews` bucketed by risk level. Profiles are built via a layered
  strategy: CODEOWNERS base → 1-year commit history → merged PR layer; layers
  merge with `max()` to avoid score inflation.
- **Automated expertise refresh** -- `.github/workflows/refresh-expertise.yaml`
  triggers `expertise_scheduler.py` every n time via OIDC-authenticated POST.
  No user-configured secrets required.

### Fixed

- **`FilePatternCondition._get_changed_files`** -- The method previously
  contained only a `TODO` placeholder returning `[]`, silently disabling all
  `files_match_pattern` and `files_not_match_pattern` evaluations. Now
  correctly extracts changed files from the event's `files` /
  `changed_files` arrays.

## [2026-03-01] -- PR #59

### Added

- **Diff pattern scanning** -- `DiffPatternCondition` checks added lines in PR
  diffs against user-defined restricted regex patterns (e.g. `console\.log`,
  `TODO:`). Violations include the filename and matched patterns.
- **Security pattern detection** -- `SecurityPatternCondition` flags hardcoded
  secrets, API keys, and sensitive data in PR diffs with CRITICAL severity.
  Both conditions share a new `_PatchPatternCondition` base class to eliminate
  duplication.
- **Unresolved review comments gate** -- `UnresolvedCommentsCondition` blocks
  PR merges when unresolved (non-outdated) review comment threads exist,
  using GraphQL `reviewThreads` data from the enricher.
- **Test coverage enforcement** -- `TestCoverageCondition` requires that PRs
  modifying source files also touch test files matching a configurable regex
  pattern (`test_file_pattern`).
- **Comment response time SLA** -- `CommentResponseTimeCondition` flags
  unresolved review threads that have exceeded a configurable hour-based SLA
  (`max_comment_response_time_hours`).
- **Signed commits verification** -- `SignedCommitsCondition` ensures all
  commits in a PR are cryptographically signed (GPG/SSH/S/MIME), for
  regulated environments that require commit provenance.
- **Changelog requirement** -- `ChangelogRequiredCondition` blocks PRs that
  modify source code without a corresponding `CHANGELOG` or `.changeset`
  update.
- **Self-approval prevention** -- `NoSelfApprovalCondition` enforces
  separation of duties by preventing PR authors from approving their own
  code (CRITICAL severity).
- **Cross-team approval** -- `CrossTeamApprovalCondition` requires approvals
  from members of specified GitHub teams before merge. Uses a simplified
  `requested_teams` check (full team-membership resolution via GraphQL is
  tracked for a future iteration).
- **Diff parsing utilities** -- New `src/rules/utils/diff.py` module with
  `extract_added_lines`, `extract_removed_lines`, and
  `match_patterns_in_patch` for reusable patch analysis.
- **CODEOWNERS parser** -- New `src/rules/utils/codeowners.py` with
  `CodeOwnersParser` class supporting glob-to-regex conversion, owner
  lookup, and critical-file detection. CODEOWNERS content is now fetched
  dynamically from the GitHub API instead of reading from disk.
- **Webhook handlers for review events** -- `PullRequestReviewEventHandler`
  and `PullRequestReviewThreadEventHandler` re-evaluate PR rules when
  reviews are submitted/dismissed or threads are resolved/unresolved.
- **Review thread enrichment** -- `PullRequestEnricher` now fetches
  `reviewThreads` via GraphQL and attaches them to the event context,
  enabling `UnresolvedCommentsCondition` and `CommentResponseTimeCondition`.
- **Full rule evaluation wiring** -- All new conditions are registered in
  `ConditionRegistry` (`AVAILABLE_CONDITIONS`, `RULE_ID_TO_CONDITION`) with
  corresponding `RuleID` enum values, violation-text mappings, and
  human-readable descriptions so they are routed through the fast
  condition-class evaluation path and support acknowledgment workflows.

### Changed

- **GraphQL client consolidation** -- Removed the standalone
  `graphql_client.py` module; all GraphQL operations now go through the
  unified `GitHubAPI` class with Pydantic-typed response models.
- **CODEOWNERS fetched from API** -- `PathHasCodeOwnerCondition` and
  `RequireCodeOwnerReviewersCondition` now receive CODEOWNERS content via
  the event context (fetched by the enricher) rather than reading from the
  local filesystem.
- **`_PatchPatternCondition` base class** -- `DiffPatternCondition` and
  `SecurityPatternCondition` now share a common abstract base, reducing
  ~60 lines of duplicated iteration/matching logic.
- **Removed redundant `validate()` overrides** -- Conditions in
  `compliance.py` and `access_control_advanced.py` that simply delegated to
  `evaluate()` now rely on `BaseCondition.validate()` which does the same
  thing.

### Fixed

- **Fail-closed on invalid regex** -- `TestCoverageCondition` now returns a
  violation (and `validate()` returns `False`) when `test_file_pattern` is
  an invalid regex, instead of silently passing.
- **Consistent file-extension filtering** -- `TestCoverageCondition.validate()`
  now ignores `.txt` and `.json` files, matching the behavior of `evaluate()`.
- **`max_hours=0` edge case** -- `CommentResponseTimeCondition` now uses
  `if max_hours is None` instead of `if not max_hours`, so a 0-hour SLA
  (immediate response required) is correctly enforced.
- **Overly generic violation mapping key** -- Changed the
  `COMMENT_RESPONSE_TIME` acknowledgment mapping from `"exceeded the"` to
  `"response SLA"` to avoid false matches against unrelated violation text.

## [2026-02-27] -- PRs #54, #58

### Added

- **Disabled rule filtering** -- Rules with `enabled: false` in
  `rules.yaml` are now skipped during loading.
- **CodeRabbit-style PR comments** -- Collapsible `<details>` sections for
  violations, acknowledgment summaries, and check run output.
- **Watchflow footer** -- Branded footer appended to PR comments.
- **Severity grouping fix** -- `INFO` severity rules are now grouped
  correctly instead of falling back to `LOW`.

### Changed

- **Default rules aligned with watchflow.dev** -- Canonical rule set updated
  to match the published documentation examples.
- **`max_pr_loc` parameter alias** -- `MaxPrLocCondition` now accepts
  `max_pr_loc` and `max_changed_lines` in addition to `max_lines`.
- **CODEOWNERS reviewer exclusion** -- PR author is excluded from the
  required code-owner reviewers list.
- **Legacy rule ID references removed** -- Generated PR comments and error
  messages no longer expose internal `RuleID` strings.

### Fixed

- **Acknowledgment text matching** -- Violation text keys updated to
  exactly match the messages emitted by conditions.
- **GitHub App auth env vars** -- Standardized to `APP_CLIENT_ID_GITHUB`
  and `APP_CLIENT_SECRET_GITHUB`.

## [2026-02-26] -- PRs #43 (cont.), event filtering

### Added

- **Event filtering** -- Irrelevant GitHub events (e.g. bot-only,
  label-only) are now dropped before reaching the rule engine, reducing
  noise and unnecessary LLM calls.

### Fixed

- **Deployment status blocking** -- Resolved an issue where deployment
  status events could block without a clear reason.
- **Deployment approval gating** -- Addressed CodeRabbit feedback on
  retry logic, falsy checks, and callback URL handling.

## [2026-01-31] -- PR #43

### Added

- **Core event processing infrastructure** -- `PullRequestProcessor`,
  `PushEventProcessor`, `DeploymentProcessor`, and `CheckRunProcessor`
  with enrichment, rule evaluation, and GitHub reporting pipeline.
- **Task queue with deduplication** -- Async `TaskQueue` for enqueuing
  webhook processing with delivery-ID-based dedup.
- **Rule engine agent (LangGraph)** -- `RuleEngineAgent` with a multi-node
  workflow: analyze rules, select strategy (condition class vs LLM
  reasoning vs hybrid), execute, and validate.
- **Acknowledgment agent** -- `AcknowledgmentAgent` parses `@watchflow ack`
  comments and maps violations to `RuleID` enum values.
- **Webhook dispatcher and handlers** -- Modular handler registry for
  `pull_request`, `push`, `check_run`, `deployment`, `deployment_status`,
  `deployment_protection_rule`, `deployment_review`, and `issue_comment`
  events.
- **Condition-based rule evaluation** -- `BaseCondition` ABC with
  `evaluate()` (returns `list[Violation]`) and `validate()` (legacy bool
  interface). Initial conditions: `TitlePatternCondition`,
  `MinDescriptionLengthCondition`, `RequiredLabelsCondition`,
  `MinApprovalsCondition`, `RequireLinkedIssueCondition`,
  `MaxFileSizeCondition`, `MaxPrLocCondition`, `FilePatternCondition`,
  `PathHasCodeOwnerCondition`, `RequireCodeOwnerReviewersCondition`,
  `CodeOwnersCondition`, `ProtectedBranchesCondition`,
  `NoForcePushCondition`, `AuthorTeamCondition`, `AllowedHoursCondition`,
  `DaysCondition`, `WeekendCondition`, `WorkflowDurationCondition`.
- **Condition registry** -- `ConditionRegistry` with parameter-pattern
  matching to automatically wire YAML rule parameters to condition classes.
- **`RuleID` enum and acknowledgment system** -- Type-safe rule
  identifiers, violation-text-to-rule mapping, and acknowledgment comment
  parsing.
- **Webhook auth** -- HMAC-SHA256 signature verification for GitHub
  webhooks.

### Changed

- **Architectural modernization** -- Migrated from monolithic processor to
  modular event-processor / agent / handler architecture with Pydantic
  models throughout.
- **Documentation overhaul** -- All docs aligned with the rule engine
  architecture, description-based rule format, and supported validation
  logic.

### Fixed

- **Dead code removal** -- Cleaned up unused webhook and PR processing code.
- **JSON parse errors** -- Webhook handler now returns proper error
  responses on malformed payloads.
- **WebhookResponse status normalization** -- Consistent status field
  values across all handlers.

## [2025-12-01] -- PRs #27-35

### Added

- **Repository Analysis Agent** -- `RepositoryAnalysisAgent` with LangGraph
  workflow analyzing PR history, contributing guidelines, and repository
  hygiene. Includes Pydantic models, LLM prompt templates, and API
  endpoints for rule recommendations.
- **Diff-aware validators** -- `diff_pattern`, `related_tests`, and
  `required_field_in_diff` validators with normalized diff metadata and
  LLM-friendly summaries for PR files.
- **Feasibility agent validator selection** -- `FeasibilityAgent` now
  dynamically chooses validators from a catalog.
- **AI Immune System metrics** -- Repository health scoring with hygiene
  metrics and structured API responses.
- **PR automation** -- Automated PR creation from repository analysis
  recommendations.

### Changed

- **Diff-aware rule presets** -- Default rule bundles updated to use the
  new diff-aware parameters and threading guardrails.

### Fixed

- **PR creation 404 prevention** -- Proper error handling for `create_git_ref`
  422 responses and repository analysis caching.
- **Repository analysis reliability** -- Improved logging, formatting, and
  content checks in analysis nodes.

## [2025-10-01] -- PRs #18-21

### Added

- **Multi-provider AI abstraction** -- Provider-agnostic `get_chat_model()`
  factory supporting OpenAI, AWS Bedrock, and Google Vertex AI (Model
  Garden). Registry pattern for provider selection.
- **Python version compatibility checks** -- Pre-commit hook validates
  syntax against target Python version.

### Changed

- **Provider-agnostic LLM usage** -- Replaced direct `ChatOpenAI`
  instantiation with the `get_chat_model()` abstraction throughout.
- **Module restructuring** -- Reorganized package layout and updated
  configuration.

## [2025-08-05] -- PRs #10-13

### Added

- **CODEOWNERS integration** -- Initial CODEOWNERS file parsing and
  contributor analysis.
- **Agent architecture enhancements** -- Improved consistency and
  reliability for `FeasibilityAgent` and `RuleEngineAgent`.
- **Structured output for FeasibilityAgent** -- LLM responses parsed into
  Pydantic models.
- **Testing framework** -- Coverage reporting, CI test pipeline, and
  mocking infrastructure for agents and LLM clients.
- **GitHub Pages documentation** -- MkDocs site deployed via GitHub
  Actions.

### Changed

- **FastAPI lifespan** -- Replaced deprecated `on_event` handlers with
  lifespan context manager.
- **Description-based rule format** -- Rules in YAML now use natural
  language descriptions matched to conditions.

### Fixed

- **CI pipeline** -- Python setup, coverage reporting, Codecov auth,
  MkDocs dependencies.
- **Test isolation** -- Proper mocking of agent creation, config
  validation, and LLM client initialization.

## [2025-07-18] -- Initial release

### Added

- **Watchflow AI governance engine** -- First open-source release.
  LangGraph-based rule evaluation for GitHub webhook events
  (pull requests, pushes, deployments).
- **EKS deployment** -- Helm chart, Kubernetes manifests, and GitHub
  Actions workflow for AWS EKS.
- **Pre-commit hooks** -- Ruff linting and formatting, YAML checks,
  trailing whitespace, large file detection.
- **Development tooling** -- `uv` package management, development guides,
  contributor guidelines.
