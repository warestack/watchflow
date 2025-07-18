# Development Guide

This guide covers setting up the Watchflow development environment for local development and testing.

## Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager (recommended) or pip
- [ngrok](https://ngrok.com/) for local webhook testing
- [LangSmith](https://langsmith.com/) account for AI agent debugging
- GitHub App credentials

## Development Setup

### 1. Clone and Setup

```bash
git clone https://github.com/watchflow/watchflow.git
cd watchflow
```

### 2. Install Dependencies

Using uv (recommended):
```bash
uv sync
```

Or using pip:
```bash
pip install -e ".[dev]"
```

### 3. Environment Configuration

Create and configure your environment file:

```bash
cp .env.example .env
```

Required environment variables:

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

# LangSmith Configuration
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

### 4. GitHub App Setup

Create a GitHub App for development:

1. Go to [GitHub Developer Settings](https://github.com/settings/apps)
2. Click "New GitHub App"
3. Configure with these settings:
   - **App name**: `watchflow-dev`
   - **Homepage URL**: `http://localhost:8000`
   - **Webhook URL**: `https://your-ngrok-url.ngrok.io/webhooks/github`
   - **Webhook secret**: Generate a secure random string

4. **Permissions**:
   - Repository permissions:
     - Checks: Read & write
     - Contents: Read-only
     - Deployments: Read & write
     - Issues: Read & write
     - Metadata: Read-only
     - Pull requests: Read & write
     - Commit statuses: Read & write

5. **Subscribe to events**:
   - Check run
   - Deployment
   - Deployment protection rule
   - Deployment review
   - Deployment status
   - Issue comment
   - Pull request
   - Push

6. **Generate private key** and encode it:
   ```bash
   cat /path/to/private-key.pem | base64 | tr -d '\n'
   ```

### 5. Local Webhook Testing with ngrok

Install ngrok and start a tunnel:

```bash
# Install ngrok
npm install -g ngrok

# Start tunnel
ngrok http 8000
```

Update your GitHub App webhook URL with the ngrok URL.

### 6. LangSmith Integration

For debugging AI agents:

1. Create a [LangSmith](https://langsmith.com/) account
2. Get your API key
3. Add to environment:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=your-langsmith-api-key
   LANGCHAIN_PROJECT=watchflow-dev
   ```

## Running the Application

### Development Server

```bash
# Using uv
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Using pip
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

### Docker Development

```bash
# Build and run with Docker Compose
docker-compose up --build

# Or build manually
docker build -t watchflow-dev .
docker run -p 8000:8000 watchflow-dev
```

## Development Workflow

### Code Quality

```bash
# Format code
uv run black src/
uv run isort src/

# Lint code
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run mypy src/
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run specific test file
uv run pytest tests/test_agents.py

# Run with verbose output
uv run pytest -v
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files
```

## Testing AI Agents

### Rule Evaluation Testing

Test rule evaluation with the API:

```bash
curl -X POST "http://localhost:8000/api/v1/rules/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "rule_text": "All pull requests must have at least 2 approvals"
  }'
```

### LangSmith Debugging

With LangSmith configured, you can:

1. View agent execution traces in the LangSmith dashboard
2. Debug prompt engineering and agent logic
3. Monitor performance and token usage
4. Iterate on agent behavior

### Local Rule Testing

Create a test repository with `.watchflow/rules.yaml`:

```yaml
rules:
  - id: test-rule
    name: Test Rule
    description: Test rule for development
    enabled: true
    severity: medium
    event_types: [pull_request]
    parameters:
      test_param: "test_value"
```

## Debugging

### Logging

Configure logging level in `.env`:

```bash
LOG_LEVEL=DEBUG
```

### Agent Debugging

Enable detailed agent logging:

```bash
# Add to .env
AGENT_DEBUG=true
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-key
```

### Webhook Debugging

Test webhook delivery:

```bash
# Use ngrok webhook inspection
# Visit https://your-ngrok-url.ngrok.io/inspect/http
```

## Common Issues

### GitHub App Permissions

If webhooks aren't being received:
1. Verify webhook URL is accessible
2. Check GitHub App permissions
3. Verify webhook secret matches

### AI Agent Issues

If agents aren't working:
1. Verify OpenAI API key
2. Check LangSmith configuration
3. Review agent logs for errors

### Development Environment

If dependencies aren't working:
1. Ensure Python 3.12+
2. Try recreating virtual environment
3. Check uv/pip installation

## Performance Testing

### Load Testing

```bash
# Install locust
pip install locust

# Run load test
locust -f load_test.py --host=http://localhost:8000
```

### Agent Performance

Monitor agent performance with LangSmith:
- Token usage per request
- Response times
- Error rates
- Cost analysis

## Documentation

- [API Documentation](http://localhost:8000/docs) - Auto-generated FastAPI docs
- [LangSmith Dashboard](https://smith.langchain.com/) - AI agent debugging
- [GitHub App Documentation](https://docs.github.com/en/apps) - GitHub App setup
