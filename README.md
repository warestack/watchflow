# Watchflow

Intelligent GitHub workflow monitoring and enforcement powered by AI agents.

## Overview

Watchflow is an intelligent governance solution for GitHub repositories that uses AI agents to automate policy enforcement and improve collaboration. By combining natural language rule definitions with real-time event processing, Watchflow provides nuanced governance that adapts to your team's workflow.

## Problem Statement

Traditional CI/CD rules are rigid and often fail to capture the complexity of real-world development scenarios. Teams need:

- **Intelligent rule evaluation** that understands context and intent
- **Flexible acknowledgment systems** that allow for justified exceptions
- **Real-time governance** that scales with repository activity
- **Natural language interfaces** that make rule creation accessible

## Solution

Watchflow addresses these challenges through:

- **AI-Powered Rule Engine**: Uses LangGraph agents with GPT-4.1-mini to intelligently evaluate rules against repository events
- **Hybrid Evaluation Strategy**: Combines fast validators for common checks with LLM reasoning for complex scenarios
- **Intelligent Acknowledgments**: Processes acknowledgment requests through PR comments with context-aware decision making
- **Stateless Architecture**: Fully scalable FastAPI backend with no persistent storage requirements

## Core Features

### Natural Language Rules
Define governance rules in plain English. Watchflow translates these into actionable YAML configurations and provides intelligent evaluation.

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

### Agent-Powered Decisions
Three specialized AI agents work together:

- **Engine Agent**: Hybrid rule evaluation using validators and LLM reasoning
- **Feasibility Agent**: Analyzes rule descriptions and generates YAML configurations
- **Acknowledgment Agent**: Evaluates acknowledgment requests with context awareness

### Real-time Event Processing
Processes GitHub events (push, pull_request, check_run, deployment, etc.) securely and asynchronously, with dynamic context enrichment via GitHub API.

## Architecture

### Key Components

- **Webhook Handlers**: Secure GitHub event processing with signature verification
- **Event Processors**: Context enrichment and rule evaluation orchestration
- **AI Agents**: LangGraph-based intelligent decision making
- **Task Queue**: Asynchronous processing for scalability
- **Rule System**: YAML-based rule definition and validation

## Quick Start

### Prerequisites

- Python 3.12+
- GitHub App credentials
- OpenAI API key
- Public webhook endpoint (ngrok for local development)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/watchflow/watchflow.git
   cd watchflow
   ```

2. **Install dependencies**:
   ```bash
   pip install -e .
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

4. **Run the application**:
   ```bash
   uvicorn src.main:app --reload
   ```

### Environment Variables

```bash
# GitHub App Configuration
APP_NAME_GITHUB=your-app-name
CLIENT_ID_GITHUB=your-app-id
APP_CLIENT_SECRET=your-client-secret
PRIVATE_KEY_BASE64_GITHUB=your-base64-private-key
GITHUB_WEBHOOK_SECRET=your-webhook-secret

# AI Configuration
OPENAI_API_KEY=your-openai-api-key
AI_MODEL=gpt-4.1-mini
AI_MAX_TOKENS=4096
AI_TEMPERATURE=0.1

# LangSmith Configuration (Optional - for debugging AI agents)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=watchflow-dev

# Development Settings
DEBUG=true
LOG_LEVEL=DEBUG
ENVIRONMENT=development

# CORS Configuration
CORS_HEADERS=["*"]
CORS_ORIGINS='["http://localhost:3000", "http://127.0.0.1:3000"]'
```

## Usage

### Creating Rules

Define rules in `.watchflow/rules.yaml` in your repository:

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

### Acknowledging Violations

When rules are violated, team members can acknowledge them via PR comments:

```
@watchflow acknowledge: This is a hotfix for a critical production issue
```

The acknowledgment agent will evaluate the request and approve or reject based on context.

## API Reference

### Webhook Endpoints

- `POST /webhooks/github` - GitHub webhook receiver

### Public API

- `GET /` - Health check
- `POST /api/v1/rules/evaluate` - Evaluate natural language rules
- `GET /health/tasks` - Task queue status
- `GET /health/scheduler` - Scheduler status

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed development setup instructions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Deployment

### Docker

```bash
docker-compose up --build
```

### Kubernetes

Helm charts are available in the `eks_deploy/helm/` directory for Kubernetes deployment.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- [Documentation](https://docs.watchflow.dev)
- [Issues](https://github.com/warestack/watchflow/issues)
- [Discussions](https://github.com/warestack/watchflow/discussions)
- [Email](mailto:team@warestack.com)
