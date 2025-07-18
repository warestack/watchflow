# Contributing to Watchflow

Thank you for your interest in contributing to Watchflow! This document provides guidelines for contributing to the
project.

## Types of Contributions

We welcome various types of contributions:

- **Feature Development**: New AI agents, rule validators, or event processors
- **Bug Fixes**: Resolving issues in existing functionality
- **Documentation**: Improving guides, API docs, or code comments
- **Testing**: Adding tests or improving test coverage
- **Performance**: Optimizing agent performance or API response times
- **Security**: Security improvements or vulnerability fixes

## Development Setup

Before contributing, ensure you have the development environment set up:

1. Follow the [Development Guide](DEVELOPMENT.md)
2. Set up GitHub App credentials
3. Configure LangSmith for AI agent debugging
4. Install pre-commit hooks

## Contribution Workflow

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/your-username/watchflow.git
cd watchflow

# Add upstream remote
git remote add upstream https://github.com/watchflow/watchflow.git
```

### 2. Create Feature Branch

```bash
# Create and switch to feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/your-bug-description
```

### 3. Make Changes

Follow these guidelines when making changes:

#### Code Style

- Use Python 3.12+ features
- Follow PEP 8 with 120 character line length
- Use type hints for all function parameters and return values
- Add docstrings for all public functions and classes

#### AI Agent Development

When working on AI agents:

1. **Use LangSmith**: Configure LangSmith for debugging and iteration
2. **Test Prompts**: Validate prompts with various inputs
3. **Monitor Performance**: Track token usage and response times
4. **Add Tests**: Include unit tests for agent logic

#### Rule System Development

When working on rules:

1. **Validator Development**: Create fast validators for common checks
2. **Parameter Validation**: Ensure rule parameters are properly validated
3. **Event Type Support**: Verify event type compatibility
4. **Documentation**: Update rule documentation and examples

### 4. Testing

Run the test suite before submitting:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run specific test categories
uv run pytest tests/test_agents/
uv run pytest tests/test_rules/
uv run pytest tests/test_webhooks/
```

### 5. Code Quality

Ensure code quality standards:

```bash
# Format code
uv run black src/
uv run isort src/

# Lint code
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run mypy src/

# Run pre-commit hooks
uv run pre-commit run --all-files
```

### 6. Commit and Push

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add new rule validator for file size checks

- Add FileSizeValidator class
- Support max_file_size parameter
- Add comprehensive tests
- Update documentation"

# Push to your fork
git push origin feature/your-feature-name
```

### 7. Create Pull Request

1. Go to your fork on GitHub
2. Click "New Pull Request"
3. Select your feature branch
4. Fill out the PR template
5. Request review from maintainers

## Pull Request Guidelines

### PR Template

Use the provided PR template and include:

- **Description**: Clear description of changes
- **Type**: Feature, bug fix, documentation, etc.
- **Testing**: How you tested the changes
- **Breaking Changes**: Any breaking changes
- **Screenshots**: For UI changes

### Review Process

1. **Automated Checks**: Ensure all CI checks pass
2. **Code Review**: Address reviewer feedback
3. **Testing**: Verify functionality works as expected
4. **Documentation**: Update relevant documentation

## Development Guidelines

### AI Agent Development

When developing AI agents:

1. **Inherit from BaseAgent**: Use the base agent class for consistency
2. **LangGraph Integration**: Use LangGraph for complex workflows
3. **Error Handling**: Implement robust error handling
4. **Logging**: Add comprehensive logging for debugging
5. **Testing**: Create unit tests for agent logic

Example agent structure:

```python
from src.agents.base import BaseAgent, AgentResult
from langgraph.graph import StateGraph

class MyAgent(BaseAgent):
    def _build_graph(self) -> StateGraph:
        # Build LangGraph workflow
        pass
    
    async def execute(self, **kwargs) -> AgentResult:
        # Execute agent logic
        pass
```

### Rule Validator Development

When creating rule validators:

1. **Async Interface**: Implement async validate method
2. **Parameter Validation**: Validate input parameters
3. **Performance**: Optimize for speed
4. **Error Handling**: Handle edge cases gracefully

Example validator:

```python
from src.rules.validators import BaseValidator

class MyValidator(BaseValidator):
    async def validate(self, parameters: dict, event_data: dict) -> bool:
        # Implement validation logic
        pass
```

### Event Processor Development

When developing event processors:

1. **Inherit from BaseEventProcessor**: Use the base class
2. **Async Processing**: Implement async process method
3. **Error Handling**: Handle processing errors gracefully
4. **Logging**: Add detailed logging

Example processor:

```python
from src.event_processors.base import BaseEventProcessor, ProcessingResult

class MyProcessor(BaseEventProcessor):
    async def process(self, task: Task) -> ProcessingResult:
        # Implement processing logic
        pass
```

## Testing Guidelines

### Unit Tests

- Test individual functions and classes
- Mock external dependencies
- Test edge cases and error conditions
- Aim for high test coverage

### Integration Tests

- Test component interactions
- Test API endpoints
- Test webhook processing
- Test AI agent workflows

### AI Agent Testing

- Test agent logic with various inputs
- Mock LLM responses for consistent testing
- Test error handling and edge cases
- Validate agent outputs

## Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Include type hints for better IDE support
- Document complex algorithms and business logic
- Add inline comments for non-obvious code

### API Documentation

- Update OpenAPI specifications
- Add example requests and responses
- Document error codes and messages
- Keep documentation in sync with code changes

## Performance Considerations

### AI Agent Performance

- Monitor token usage and costs
- Optimize prompts for efficiency
- Use caching where appropriate
- Implement rate limiting

### API Performance

- Optimize database queries
- Use async processing for long-running tasks
- Implement proper connection pooling
- Monitor response times

## Security Guidelines

- Never commit sensitive data (API keys, secrets)
- Validate all input data
- Use parameterized queries
- Follow security best practices
- Report security issues privately

## Getting Help

- **Issues**: Create GitHub issues for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Check existing documentation first
- **Code Review**: Ask questions during code review

## Recognition

Contributors will be recognized in:

- GitHub contributors list
- Release notes
- Project documentation
- Community acknowledgments

Thank you for contributing to Watchflow!
