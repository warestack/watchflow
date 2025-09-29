# Watchflow

[![Works with GitHub](https://img.shields.io/badge/Works%20with-GitHub-1f1f23?style=for-the-badge&logo=github)](https://github.com/warestack/watchflow)

![Watchflow - Agentic GitHub Guardrails](docs/images/Watchflow%20-%20Agentic%20GitHub%20Guardrails.png)

Replace static protection rules with agentic guardrails. Watchflow ensures consistent quality standards with smarter,
context-aware protection for every repo.

> **Experience the power of agentic governance** - then scale to enterprise with [Warestack](https://www.warestack.com/)

## Overview

Watchflow is the open-source rule engine that powers [Warestack's](https://www.warestack.com/) enterprise-grade agentic guardrails. Start with Watchflow to understand the technology, then upgrade to Warestack for production-scale deployment with advanced features.

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
- **Intelligent ACKs**: Processes acknowledgment requests through PR comments with context-aware
  decision-making
- **Plug n play Integration**: Works within GitHub interface with no additional UI required

## Key Features

### Natural Language Rules

Define governance rules in plain English. Watchflow translates these into actionable YAML configurations and provides
intelligent evaluation.

```yaml
rules:
  - description: All pull requests must have a min num of approvals unless the author is a maintainer
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2

  - description: Prevent deployments on weekends
    enabled: true
    severity: medium
    event_types: [deployment]
    parameters:
      restricted_days: [Saturday, Sunday]
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

**Go to GitHub App Installation**
  - Visit [Watchflow GitHub App](https://github.com/apps/watchflow)
  - Click "Install"
  - Select the repositories you want to protect
  - Grant the necessary permissions for webhook access and repository content

### Step 2: Create Rules Configuration

Create `.watchflow/rules.yaml` in your repository root:

```yaml
rules:
  - description: All pull requests must have a min num of approvals unless the author is a maintainer
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2

  - description: Prevent deployments on weekends
    enabled: true
    severity: medium
    event_types: [deployment]
    parameters:
      restricted_days: [Saturday, Sunday]
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
@watchflow acknowledge "Documentation updates only, no code changes"
@watchflow ack "Documentation updates only, no code changes"

# Acknowledge with reasoning
@watchflow acknowledge "Emergency fix, team is unavailable"
@watchflow ack "Emergency fix, team is unavailable"

# Evaluate the feasibility of a rule
@watchflow evaluate "Require 2 approvals for PRs to main"

# Get help
@watchflow help
```

### Example Scenarios

**Can Acknowledge**: When a PR lacks required approvals but it's an emergency fix, developers can acknowledge with
`@watchflow acknowledge "Emergency fix, team is unavailable"` or `@watchflow ack "Emergency fix, team is unavailable"`.

**Remains Blocked**: When deploying to production without security review, the deployment stays blocked even with
acknowledgment - security review is mandatory.

**Can Acknowledge**: When weekend deployment rules are violated for a critical issue, developers can acknowledge with
`@watchflow acknowledge "Critical production fix needed"`.

**Remains Blocked**: When sensitive files are modified without proper review, the PR remains blocked until security team
approval - no acknowledgment possible.

## GitHub Integration

Watchflow integrates seamlessly with GitHub through:

- **GitHub App**: Secure, scoped access to your repositories
- **Webhooks**: Real-time event processing for immediate rule evaluation
- **Check Runs**: Visual status updates in your GitHub interface
- **Comments**: Natural interaction through PR and issue comments
- **Deployment Protection**: Intelligent deployment approval workflows

### Supported GitHub Events

Watchflow processes the following GitHub events:
- `push` - Code pushes and branch updates
- `pull_request` - PR creation, updates, and merges
- `issue_comment` - Comments on issues and PRs
- `check_run` - CI/CD check run status
- `deployment` - Deployment creation and updates
- `deployment_status` - Deployment status changes
- `deployment_review` - Deployment protection rule reviews
- `deployment_protection_rule` - Deployment protection rule events
- `workflow_run` - GitHub Actions workflow runs

## Looking for enterprise-grade features on top?

[Move to Warestack](https://www.warestack.com/) for:
- **Team Management**: Assign teams to repos with custom rules
- **Advanced Integrations**: Slack, Linear, Jira, Vanta
- **Real-Time Monitoring**: Comprehensive dashboard and analytics
- **Enterprise Support**: 24/7 support and SLA guarantees
- **SOC-2 Compliance**: Audit reports and compliance tracking
- **Custom Onboarding**: Dedicated success management

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

## Rule Format

Watchflow uses a simple, description-based rule format that eliminates hardcoded if-else logic:

```yaml
rules:
  - description: All pull requests must have a min num of approvals unless the author is a maintainer
    enabled: true
    severity: high
    event_types: [pull_request]
    parameters:
      min_approvals: 2

  - description: Prevent deployments on weekends
    enabled: true
    severity: medium
    event_types: [deployment]
    parameters:
      restricted_days: [Saturday, Sunday]
```

This format allows for intelligent, context-aware rule evaluation while maintaining simplicity and readability.

## Contributing & Development

For instructions on running tests, local development, and contributing, see [DEVELOPMENT.md](DEVELOPMENT.md).
