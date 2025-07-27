# Status Check Rules - Implementation Guide

This document explains how to use the newly implemented status check functionality in Watchflow to enforce CI/CD pipeline requirements.

## Overview

Watchflow now supports monitoring and enforcing requirements for GitHub status checks (both modern check runs and legacy commit statuses). This allows you to create rules that ensure pull requests pass required CI/CD checks before they can be merged.

## Supported Event Types

- `check_run` - Modern GitHub check runs (recommended)
- `status` - Legacy GitHub commit status API
- `pull_request` - Includes status check validation during PR processing

## Rule Configuration

### Basic Status Check Rule

```yaml
rules:
  - id: ci-checks-required
    name: CI Checks Required
    description: All pull requests must pass CI tests and linting
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      required_checks: ["ci/test", "lint"]
```

### Comprehensive Status Check Rule

```yaml
rules:
  - id: comprehensive-checks
    name: Comprehensive CI/CD Checks
    description: Enforce all required checks for production readiness
    enabled: true
    severity: critical
    event_types: [pull_request]
    parameters:
      required_checks:
        - "ci/test"
        - "ci/lint"
        - "ci/build"
        - "security/scan"
        - "codecov/patch"
        - "continuous-integration/travis-ci/pr"
      message: "All CI/CD checks must pass before merging to ensure code quality and security"
```

## How It Works

### 1. Pull Request Processing

When a pull request event occurs, Watchflow:

1. Fetches the PR details from GitHub
2. Retrieves all check runs and commit statuses for the PR's head commit
3. Evaluates rules that include `required_checks` parameters
4. Creates violations for any failed or missing required checks

### 2. Check Run/Status Processing

When individual check runs or status updates occur, Watchflow:

1. Processes the event if rules are configured for `check_run` or `status` events
2. Evaluates the check against any applicable rules
3. Can trigger additional actions based on rule configuration

### 3. Status Check Validation

The `RequiredChecksValidator` checks:

- **Passing checks**: `conclusion: "success"` (check runs) or `state: "success"` (statuses)
- **Failing checks**: `conclusion: "failure"|"error"|"cancelled"|"timed_out"` or `state: "failure"|"error"`
- **Missing checks**: Required checks that don't appear in the current status list

## Example Scenarios

### Scenario 1: Basic CI Enforcement

**Rule Configuration:**
```yaml
rules:
  - id: basic-ci
    name: Basic CI Required
    description: Ensure tests pass before merge
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      required_checks: ["ci/test"]
```

**Behavior:**
- ✅ **PR with passing tests**: No violations, PR can be merged
- ❌ **PR with failing tests**: Violation reported, PR blocked
- ❌ **PR without test results**: Violation reported, PR blocked

### Scenario 2: Multi-Check Enforcement

**Rule Configuration:**
```yaml
rules:
  - id: production-ready
    name: Production Ready Checks
    description: All quality gates must pass
    enabled: true
    severity: critical
    event_types: [pull_request]
    parameters:
      required_checks: ["ci/test", "lint", "security-scan", "build"]
```

**Behavior:**
- ✅ **All checks pass**: No violations
- ❌ **Any check fails**: Violation reported with details about which checks failed
- ❌ **Missing checks**: Violation reported with details about which checks are missing

## Troubleshooting

### Common Issues

1. **Rules not triggering**
   - Verify the rule `event_types` includes `pull_request`
   - Check that `required_checks` parameter is properly configured
   - Ensure the GitHub App has `Checks: Read` permissions

2. **Check names not matching**
   - Check the exact names of your CI/CD checks in GitHub
   - Use the GitHub API or PR checks tab to verify check names
   - Check names are case-sensitive

3. **Legacy vs Modern Checks**
   - Modern CI/CD tools use check runs (`ci/test`)
   - Legacy tools use statuses (`continuous-integration/travis-ci/pr`)
   - Watchflow supports both formats

### Debugging

Enable debug logging to see detailed check validation:

```bash
LOG_LEVEL=DEBUG
```

This will show:
- Which checks were found for the PR
- Which required checks are missing or failing
- Detailed validation results

## Migration Guide

### From Static Branch Protection

If you're currently using GitHub's branch protection rules for status checks:

1. **Identify your current required checks** in GitHub branch protection settings
2. **Create equivalent Watchflow rules** using the check names
3. **Test the rules** on a test repository first
4. **Gradually migrate** by enabling Watchflow rules and disabling branch protection

### Example Migration

**Before (GitHub Branch Protection):**
- Required status checks: `ci/test`, `lint`

**After (Watchflow Rule):**
```yaml
rules:
  - id: migrate-from-branch-protection
    name: Required CI Checks
    description: Migrated from branch protection rules
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      required_checks: ["ci/test", "lint"]
```

## Best Practices

1. **Start Simple**: Begin with basic test requirements and add more checks gradually
2. **Use Descriptive Names**: Make rule IDs and names clear about what they enforce
3. **Set Appropriate Severity**: Use `critical` for security/build checks, `high` for tests, `medium` for linting
4. **Test Rules**: Always test new rules in a development environment first
5. **Monitor Performance**: Status check validation adds API calls, monitor for rate limits

## API Integration

### Fetching Check Data

The system automatically fetches both check runs and commit statuses:

```python
# This is handled automatically by the PullRequestProcessor
checks = await github_client.get_pr_checks(repo, pr_number, installation_id)
```

### Manual Check Validation

You can also validate checks manually:

```python
from src.rules.validators import RequiredChecksValidator

validator = RequiredChecksValidator()
result = await validator.validate(
    parameters={"required_checks": ["ci/test", "lint"]},
    event={"checks": checks_data}
)
```

## Support

For issues or questions about status check rules:

1. Check the debug logs for validation details
2. Verify check names match exactly what appears in GitHub
3. Ensure proper GitHub App permissions
4. Review the rule configuration syntax
