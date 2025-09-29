# Configuration Guide

This guide covers how to configure Watchflow rules to replace static protection rules with context-aware guardrails.
Learn how to create effective governance rules that adapt to your team's needs and workflow.

## Rule Configuration

### Basic Rule Structure

Rules are defined in YAML format and stored in `.watchflow/rules.yaml` in your repository. Each rule consists of
metadata, event triggers, and parameters that define the rule's behavior:

```yaml
rules:
  - description: All pull requests must have a min num of approvals unless the author is a maintainer
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2
```

### Rule Components

| Component     | Description                       | Required | Type    |
|---------------|-----------------------------------|----------|---------|
| `description` | Rule description                  | Yes      | string  |
| `enabled`     | Whether rule is active            | No       | boolean |
| `severity`    | Rule severity level               | No       | string  |
| `event_types` | Applicable events                 | Yes      | array   |
| `parameters`  | Rule parameters and configuration | Yes      | object  |

## Rule Examples

### Security Review Rule

This rule ensures that security-sensitive changes are properly reviewed:

```yaml
rules:
  - description: Security-sensitive changes require security team review
    enabled: true
    severity: critical
    event_types: [pull_request]
    parameters:
      file_patterns: ["**/security/**", "**/auth/**", "**/config/security.yaml"]
      required_teams: ["security-team"]
```

### Deployment Protection Rule

This rule prevents deployments during restricted time periods:

```yaml
rules:
  - description: Prevent deployments on weekends
    enabled: true
    severity: medium
    event_types: [deployment]
    parameters:
      restricted_days: [Saturday, Sunday]
```

### Large PR Rule

This rule helps maintain code quality by flagging large changes:

```yaml
rules:
  - description: Warn about large pull requests that may be difficult to review
    enabled: true
    severity: medium
    event_types: [pull_request]
    parameters:
      max_files: 20
      max_lines: 500
```

## Parameter Types

### Common Parameters

Watchflow supports various parameter types to create flexible and powerful rules:

```yaml
parameters:
  # Approval requirements
  min_approvals: 2
  required_teams: ["security-team", "senior-engineers"]
  excluded_reviewers: ["author"]

  # File patterns (glob syntax)
  file_patterns: ["**/security/**", "**/auth/**", "*.env*"]
  excluded_files: ["docs/**", "*.md", "**/test/**"]

  # Time restrictions
  restricted_days: [Saturday, Sunday]
  restricted_hours: [22, 23, 0, 1, 2, 3, 4, 5, 6]
  timezone: "UTC"

  # Size limits
  max_files: 20
  max_lines: 500
  max_deletions: 100
  max_additions: 1000

  # Branch patterns
  protected_branches: ["main", "master", "production"]
  excluded_branches: ["feature/*", "hotfix/*"]
```

## Severity Levels

### Severity Configuration

- **low** - Informational violations, no blocking
- **medium** - Warning-level violations, may block with acknowledgment
- **high** - Critical violations that should block
- **critical** - Emergency violations that always block

### Example Severity Usage

```yaml
rules:
  - description: Remind developers to update documentation for significant changes
    severity: low
    event_types: [pull_request]
    parameters:
      file_patterns: ["src/**", "lib/**"]

  - description: Warn about large pull requests that may be difficult to review
    severity: medium
    event_types: [pull_request]
    parameters:
      max_files: 20
      max_lines: 500

  - description: Block security-sensitive changes without proper review
    severity: critical
    event_types: [pull_request]
    parameters:
      file_patterns: ["**/security/**", "**/auth/**"]
      required_teams: ["security-team"]
```

## Event Types

### Supported Events

- **pull_request** - PR creation, updates, merges
- **push** - Code pushes to branches
- **deployment** - Deployment events
- **deployment_status** - Deployment status updates
- **issue_comment** - Comments on issues and PRs

### Event-Specific Rules

```yaml
rules:
  # PR-specific rule
  - description: All pull requests must be reviewed before merging
    event_types: [pull_request]
    parameters:
      min_approvals: 1

  # Deployment-specific rule
  - description: Production deployments require explicit approval
    event_types: [deployment]
    parameters:
      environment: "production"
      min_approvals: 2

  # Multi-event rule
  - description: Security-sensitive changes require security team review
    event_types: [pull_request, push, deployment]
    parameters:
      file_patterns: ["**/security/**", "**/auth/**"]
      required_teams: ["security-team"]
```

## Advanced Configuration

### Custom Parameters

```yaml
rules:
  - description: Configurable approval requirements based on team and branch
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2
      required_teams: ["security", "senior-engineers"]
      excluded_branches: ["feature/*"]
```

### Environment-Specific Rules

```yaml
rules:
  - description: Strict rules for production deployments requiring multiple approvals
    enabled: true
    severity: critical
    event_types: [deployment]
    parameters:
      environment: "production"
      min_approvals: 3
      required_teams: ["security", "senior-engineers", "product"]

  - description: Moderate rules for staging deployments with basic approval requirements
    enabled: true
    severity: high
    event_types: [deployment]
    parameters:
      environment: "staging"
      min_approvals: 1
      required_teams: ["senior-engineers"]
```

## Best Practices

### Rule Design

1. **Keep rules simple** and focused on single concerns
2. **Use descriptive names** and clear descriptions
3. **Test rules thoroughly** before deployment
4. **Document rule rationale** and business context
5. **Review rules regularly** for effectiveness

### Rule Management

1. **Version control rules** alongside code
2. **Use rule templates** for consistency
3. **Implement gradual rollouts** for new rules
4. **Monitor rule effectiveness** and adjust as needed
5. **Provide clear feedback** to developers

### Rule Optimization

1. **Optimize rule conditions** for performance
2. **Use appropriate severity levels**
3. **Balance automation with human oversight**
4. **Regularly review and update rules**
5. **Collect feedback from teams**
