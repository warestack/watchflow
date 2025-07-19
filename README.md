# Watchflow

Agentic Guardrails for GitHub repositories that enforces rules and improves team collaboration.

## Overview

Watchflow is a governance tool that uses AI agents to automate policy enforcement across your GitHub repositories. By
combining rule-based logic with AI-powered intelligence, Watchflow provides context-aware governance that adapts to your
team's workflow and scales with your organization.

## Why Watchflow?

Traditional governance tools are rigid and often fail to capture the complexity of real-world development scenarios.
Teams need:

- **Intelligent rule evaluation** that understands context and intent
- **Flexible acknowledgment systems** that allow for legitimate exceptions
- **Real-time governance** that scales with repository activity
- **Plug n play GitHub integration** that works within existing workflows

## How It Works

Watchflow addresses these challenges through:

- **AI-Powered Rule Engine**: Uses AI agents to intelligently evaluate rules against repository events
- **Hybrid Architecture**: Combines rule-based logic with AI intelligence for optimal performance
- **Intelligent Acknowledgments**: Processes acknowledgment requests through PR comments with context-aware decision
  making
- **Plug n play Integration**: Works within GitHub interface with no additional UI required

## Key Features

### Natural Language Rules
Define governance rules in plain English. Watchflow translates these into actionable YAML configurations and provides
intelligent evaluation.

```yaml
rules:
  - id: no-weekend-deployments
    name: No Weekend Deployments
    description: Prevent deployments on weekends to avoid maintenance issues
    enabled: true
    severity: high
    event_types: [deployment]
    parameters:
      days: [Saturday, Sunday]
      message: "Deployments are not allowed on weekends"
```

### Flexible Rule System
Define governance rules in YAML format with rich conditions and actions. Support for approval requirements, security
reviews, deployment protection, and more.

### Intelligent Acknowledgment Workflow
When rules are violated, developers can acknowledge them with simple comments. AI agents evaluate requests and provide
context-aware decisions.

## Hybrid Architecture

Watchflow uses a unique hybrid architecture that combines rule-based logic with AI-powered intelligence:

- **Rule Engine**: Fast, deterministic rule evaluation for common scenarios
- **AI Agents**: Intelligent context analysis and decision making
- **Decision Orchestrator**: Combines both approaches for optimal results
- **GitHub Integration**: Plug n play event processing and action execution

## Quick Start

Get Watchflow up and running in minutes to start enforcing governance rules in your GitHub repositories.

### Step 1: Install GitHub App

1. **Go to GitHub App Installation**
   - Visit [Watchflow GitHub App](https://github.com/apps/watchflow)
   - Click "Install"

2. **Configure App Settings**
   - Select repositories to install on
   - Grant required permissions:
     - Repository permissions: Contents (Read), Pull requests (Read & write), Issues (Read & write)
     - Subscribe to events: Pull requests, Push, Deployment

### Step 2: Create Rules Configuration

Create `.watchflow/rules.yaml` in your repository root:

```yaml
rules:
  - id: pr-approval-required
    name: PR Approval Required
    description: All pull requests must have at least 2 approvals
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2
      message: "Pull requests require at least 2 approvals"

  - id: no-deploy-weekends
    name: No Weekend Deployments
    description: Prevent deployments on weekends
    enabled: true
    severity: medium
    event_types: [deployment]
    parameters:
      restricted_days: [Saturday, Sunday]
      message: "Deployments are not allowed on weekends"
```

### Step 3: Test Your Setup

1. **Create a test pull request**
2. **Try acknowledgment workflow**: Comment `@watchflow acknowledge` when rules are violated
3. **Verify rule enforcement**: Check that blocking rules prevent merging

## Configuration

For advanced configuration options, see the [Configuration Guide](docs/getting-started/configuration.md).

## Usage

### Comment Commands

Use these commands in PR comments to interact with Watchflow:

```bash
# Acknowledge a violation
@watchflow acknowledge

# Acknowledge with reasoning
@watchflow acknowledge - Documentation updates only, no code changes

# Request escalation
@watchflow escalate - Critical security fix needed, reviewers unavailable

# Check rule status
@watchflow status

# Get help
@watchflow help
```

### Example Scenarios

**Can Acknowledge**: When a PR lacks required approvals but it's an emergency fix, developers can acknowledge with
`@watchflow acknowledge - Emergency fix, team is unavailable`.

**Remains Blocked**: When deploying to production without security review, the deployment stays blocked even with
acknowledgment - security review is mandatory.

**Can Acknowledge**: When weekend deployment rules are violated for a critical issue, developers can acknowledge with
`@watchflow acknowledge - Critical production fix needed`.

**Remains Blocked**: When sensitive files are modified without proper review, the PR remains blocked until security team
approval - no acknowledgment possible.

## Documentation

- [Quick Start Guide](docs/getting-started/quick-start.md) - Get up and running in 5 minutes
- [Configuration Guide](docs/getting-started/configuration.md) - Advanced rule configuration
- [Features](docs/features.md) - Platform capabilities and benefits
- [Performance Benchmarks](docs/benchmarks.md) - Impact metrics and results

## Support

- **GitHub Issues**: [Report problems](https://github.com/warestack/watchflow/issues)
- **Discussions**: [Ask questions](https://github.com/warestack/watchflow/discussions)
- **Documentation**: [Full documentation](docs/)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
