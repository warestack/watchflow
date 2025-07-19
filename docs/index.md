# Welcome to Watchflow

<div class="grid cards" markdown>

-   :fontawesome-solid-rocket: __[Quick Start](getting-started/quick-start.md)__

    Get up and running in minutes

-   :fontawesome-solid-shield: __[Features](features.md)__

    Explore context-aware monitoring capabilities

-   :fontawesome-solid-chart-line: __[Comparative Analysis](benchmarks.md)__

    See real-world impact and results

-   :fontawesome-solid-cog: __[Configuration](getting-started/configuration.md)__

    Advanced rule configuration

</div>

## What is Watchflow?

Watchflow replaces static protection rules with **context-aware monitoring**. We ensure consistent quality standards so
teams can focus on building, increase trust, and move fast.

Instead of rigid, binary rules, Watchflow uses **AI agents** to make intelligent decisions about pull requests,
deployments, and workflow changes based on real context.

### The Problem

Traditional GitHub protection rules are:

- **Static**: Rigid true/false decisions
- **Context-blind**: Don't consider urgency, roles, or circumstances
- **High maintenance**: Require constant updates
- **Limited coverage**: Catch only obvious violations

### The Solution

Watchflow introduces **Agentic GitHub Guardrails**, where decisions are made dynamically by AI agents that understand:

- **Developer roles** and permissions
- **Project urgency** and business context
- **Code complexity** and risk factors
- **Temporal patterns** (time of day, day of week)
- **Historical context** and team patterns

## Key Features

### Context-Aware Monitoring
- **Intelligent decisions** based on real context
- **Natural language rules** written in plain English
- **Clear explanations** for all actions
- **Learning capabilities** that improve over time

### Plug n Play Integration
- **GitHub App** for instant setup
- **Comment-based interactions** for team communication
- **Real-time feedback** through status checks
- **No additional UI** required

### Quality Standards
- **Consistent enforcement** across all repositories
- **Trust building** through transparent decisions
- **Fast iteration** with intelligent exceptions
- **Audit trails** for compliance

## Quick Example

Instead of a static rule like:
```yaml
# Traditional approach
require_approvals: 2
```

Watchflow uses context-aware rules like:
```yaml
# Agentic approach
"Require 2 approvals for PRs to main unless it's a hotfix by a senior engineer on-call"
```

The system automatically:
- Detects if it's a hotfix
- Identifies the developer's role
- Checks if they're on-call
- Makes a contextual decision
- Provides clear justification

## Architecture

Watchflow combines the best of both worlds:

- **Real-time processing** via GitHub webhooks for immediate response
- **AI reasoning** for complex decision-making
- **Static fallbacks** for reliability
- **Hybrid architecture** for optimal performance

## Get Started

Ready to replace static protection rules with context-aware monitoring? Start with our
[Quick Start Guide](getting-started/quick-start.md) or explore the [Features](features.md) to see how Agentic GitHub
Guardrails work.

## Community

- **GitHub**: [warestack/watchflow](https://github.com/warestack/watchflow)
- **Discussions**: [GitHub Discussions](https://github.com/warestack/watchflow/discussions)
- **Issues**: [GitHub Issues](https://github.com/warestack/watchflow/issues)

---

*Watchflow ensures consistent quality standards so teams can focus on building, increase trust, and move fast.*
