# Quick Start Guide

Get Watchflow up and running in minutes to replace static protection rules with context-aware rule guardrails.

## What You'll Get

- **Context-aware rule evaluation** for issues, pull requests and deployments
- **Intelligent governance** that adapts to your context and team dynamics
- **Plug n play GitHub integration** via GitHub App - no additional UI required
- **Comment-based acknowledgments** for rule violations with AI-powered evaluation
- **Real-time feedback** to developers through status checks and comments
- **Audit trails** for compliance and transparency

## Prerequisites

- **GitHub repository** with admin access
- **5 minutes** to set up
- **Team understanding** of governance rules you want to enforce

## Step 1: Install Watchflow GitHub App

1. **Install the GitHub App**
   - Visit [Watchflow GitHub App](https://github.com/apps/watchflow)
   - Click "Install" and select your repositories
   - Grant required permissions (Watchflow only reads content and responds to events)

2. **Verify Installation**
   - Check that Watchflow appears in your repository's "Installed GitHub Apps"
   - The app will start monitoring your repository immediately

## Step 2: Create Your Rules

Create `.watchflow/rules.yaml` in your repository root to define your governance rules:

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

**Pro Tip**: Start with simple rules and gradually add complexity as your team gets comfortable with the tool.

## Step 3: Test Your Setup

1. **Create a test pull request**
   - Make a small change to trigger rule evaluation
   - Watch for Watchflow comments and status checks
   - Verify that rules are being applied correctly

2. **Try acknowledgment workflow**
   - When a rule violation occurs, comment: `@watchflow acknowledge`
   - Add reasoning: `@watchflow acknowledge - Emergency fix, all comments have been resolved`
   - Watch how AI evaluates your acknowledgment request

3. **Verify rule enforcement**
   - Check that blocking rules prevent merging when appropriate
   - Verify comments provide clear guidance and explanations
   - Test both acknowledgable and non-acknowledgable violations

## How It Works

### Rule Evaluation Flow

1. **Event Trigger**: GitHub event (PR, deployment, etc.) occurs
2. **Rule Matching**: Watchflow identifies applicable rules
3. **Context Analysis**: AI agents evaluate context and rule conditions
4. **Decision Making**: Intelligent decision based on multiple factors
5. **Action Execution**: Block, comment, or approve based on evaluation
6. **Feedback Loop**: Developers can acknowledge or appeal decisions

### Acknowledgment Workflow

When a rule violation occurs:

1. **Violation Detected**: Watchflow identifies rule violation
2. **Comment Posted**: Clear explanation of the violation
3. **Developer Response**: Comment with acknowledgment command
4. **AI Evaluation**: AI agent evaluates acknowledgment request
5. **Decision**: Approve, reject, or escalate based on context
6. **Action**: Update PR status and provide feedback

### Comment Commands

Use these commands in PR comments to interact with Watchflow:

```bash
# Acknowledge a violation
@watchflow acknowledge

# Acknowledge with reasoning
@watchflow acknowledge - Emergency fix, all comments have been resolved

# Request escalation for urgent cases
@watchflow escalate - Critical security fix needed

# Check current rule status
@watchflow status

# Get help and available commands
@watchflow help
```

**Pro Tips:**
- Be specific in your reasoning for better AI evaluation
- Use acknowledgment for legitimate exceptions, not to bypass important rules
- Escalation is for truly urgent cases that require immediate attention

## Key Features

### Context-Aware Intelligence

- **Context Awareness**: Understands repository structure and team dynamics
- **Adaptive Decisions**: Considers historical patterns and current context
- **Intelligent Reasoning**: Provides detailed explanations for decisions
- **Learning Capability**: Improves over time based on team feedback

### Plug n Play Integration

- **Native GitHub Experience**: Works through comments and checks
- **No UI Required**: Everything happens in GitHub interface
- **Real-time Feedback**: Immediate responses to events
- **Team Collaboration**: Supports team-based acknowledgments

### Flexible Governance

- **Custom Rules**: Define rules specific to your organization
- **Multiple Severity Levels**: From warnings to critical blocks
- **Environment Awareness**: Different rules for different environments
- **Exception Handling**: Acknowledgment workflow for legitimate exceptions

## Example Scenarios

### Can Acknowledge: Emergency Fix

**Situation**: PR lacks required approvals but it's an emergency fix
**Watchflow Action**: Blocks PR, requires acknowledgment
**Developer Response**: `@watchflow acknowledge - Emergency fix, team is unavailable`
**Result**: PR approved with documented exception

### Remains Blocked: Security Review

**Situation**: Deploying to production without security review
**Watchflow Action**: Deployment stays blocked even with acknowledgment
**Developer Response**: Cannot acknowledge - security review is mandatory
**Result**: Deployment blocked until security review completed

### Can Acknowledge: Weekend Deployment

**Situation**: Weekend deployment rules are violated for critical issue
**Watchflow Action**: Blocks deployment, allows acknowledgment
**Developer Response**: `@watchflow acknowledge - Critical production fix needed`
**Result**: Deployment proceeds with documented exception

### Remains Blocked: Sensitive Files

**Situation**: Sensitive files modified without proper review
**Watchflow Action**: PR remains blocked until security team approval
**Developer Response**: Cannot acknowledge - security team approval required
**Result**: PR blocked until security team reviews and approves

## Next Steps

- **Explore Advanced Configuration**: See the [Configuration Guide](configuration.md) for detailed rule options
- **Learn About Features**: Check out [Features](../features.md) to understand all capabilities
- **View Performance**: See [Performance Benchmarks](../benchmarks.md) for real-world results
- **Get Support**: Visit our [GitHub Discussions](https://github.com/warestack/watchflow/discussions) for help

**Congratulations!** You've successfully set up Watchflow with context-aware rule guardrails. Your team can now focus on building while maintaining consistent quality standards.
