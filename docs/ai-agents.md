# AI Agents in Watchflow

This document provides a comprehensive overview of the AI agents used in Watchflow, their design principles, and implementation details.

## Agent Architecture

Watchflow uses a multi-agent system built on LangGraph, where each agent specializes in specific aspects of rule evaluation and governance:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Engine Agent   │    │ Feasibility     │    │ Acknowledgment  │
│                 │    │ Agent           │    │ Agent           │
│ • Rule Eval     │    │ • Rule Analysis │    │ • PR Comments   │
│ • Hybrid Logic  │    │ • YAML Gen      │    │ • Context Eval  │
│ • Validators    │    │ • Feasibility   │    │ • Risk Assess   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Core Design Principles

### 1. Specialization
Each agent has a specific, well-defined responsibility:
- **Engine Agent**: Rule evaluation and violation detection
- **Feasibility Agent**: Rule analysis and configuration generation
- **Acknowledgment Agent**: Context-aware acknowledgment evaluation

### 2. Hybrid Intelligence
Combine deterministic logic with AI reasoning:
- Fast validators for common, well-defined checks
- LLM reasoning for complex, contextual decisions
- Intelligent strategy selection based on rule characteristics

### 3. Observability
Comprehensive monitoring and debugging:
- LangSmith integration for trace visualization
- Detailed logging at each step
- Performance metrics and cost tracking

## Engine Agent

The Engine Agent is the core rule evaluation system that processes GitHub events against configured rules.

### Architecture

```python
class RuleEngineAgent(BaseAgent):
    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(EngineState)
        
        # Add nodes
        workflow.add_node("smart_rule_evaluation", smart_rule_evaluation)
        workflow.add_node("validate_violations", validate_violations)
        
        # Add edges
        workflow.add_edge(START, "smart_rule_evaluation")
        workflow.add_edge("smart_rule_evaluation", "validate_violations")
        workflow.add_edge("validate_violations", END)
        
        return workflow.compile()
```

### Workflow Steps

#### 1. Rule Filtering
- Filter rules by event type applicability
- Identify rules that should be evaluated
- Log filtering decisions for transparency

#### 2. Strategy Selection
- Analyze each rule to determine evaluation strategy
- Choose between validators (fast) and LLM reasoning (flexible)
- Consider rule complexity and performance requirements

#### 3. Parallel Evaluation
- Execute validators concurrently for performance
- Batch LLM evaluations to optimize API usage
- Handle failures gracefully with fallback strategies

#### 4. Result Aggregation
- Combine results from multiple evaluation methods
- Normalize violation formats
- Generate comprehensive evaluation reports

### Hybrid Evaluation Strategy

The Engine Agent uses a hybrid approach to balance speed and flexibility:

#### Fast Validators
For common, well-defined checks:
```python
VALIDATOR_REGISTRY = {
    "pr_approval": PRApprovalValidator(),
    "file_size": FileSizeValidator(),
    "title_pattern": TitlePatternValidator(),
    "label_requirement": LabelRequirementValidator(),
}
```

#### LLM Reasoning
For complex, contextual decisions:
- Business logic evaluation
- Security policy interpretation
- Compliance requirement assessment
- Custom rule evaluation

### Performance Optimization

#### Caching Strategy
- Cache validator results for identical inputs
- No caching for LLM results to ensure freshness
- Repository-level rule caching

#### Parallel Processing
- Concurrent validator execution
- Batched LLM API calls
- Async/await throughout the pipeline

## Feasibility Agent

The Feasibility Agent analyzes natural language rule descriptions and determines if they can be implemented.

### Purpose
- Evaluate rule implementability
- Generate YAML configurations
- Provide feedback on rule design
- Suggest improvements and alternatives

### Workflow

```python
class RuleFeasibilityAgent(BaseAgent):
    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(FeasibilityState)
        
        workflow.add_node("analyze_feasibility", analyze_rule_feasibility)
        workflow.add_node("generate_yaml", generate_yaml_config)
        
        workflow.add_edge(START, "analyze_feasibility")
        workflow.add_edge("analyze_feasibility", "generate_yaml")
        workflow.add_edge("generate_yaml", END)
        
        return workflow.compile()
```

### Analysis Process

#### 1. Feasibility Assessment
- Analyze rule complexity and requirements
- Identify potential implementation challenges
- Assess data availability and accessibility
- Evaluate performance implications

#### 2. YAML Generation
- Convert natural language to structured configuration
- Define appropriate parameters and constraints
- Set severity levels and event types
- Generate comprehensive rule definitions

#### 3. Feedback Generation
- Provide implementation recommendations
- Suggest alternative approaches
- Identify potential issues or limitations
- Offer optimization suggestions

### Example Output

```yaml
# Generated YAML for: "All pull requests must have at least 2 approvals"
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
```

## Acknowledgment Agent

The Acknowledgment Agent evaluates requests to acknowledge (override) rule violations based on context and justification.

### Purpose
- Evaluate acknowledgment requests from PR comments
- Assess justification validity and risk
- Make context-aware decisions
- Provide detailed reasoning and recommendations

### Context Analysis

The agent considers multiple factors:

#### 1. Acknowledgment Reason
- Urgency and justification
- Business impact assessment
- Risk evaluation
- Compliance implications

#### 2. PR Context
- Pull request size and scope
- File types and changes
- Author and reviewer information
- Historical context

#### 3. Rule Context
- Rule severity and importance
- Security and compliance implications
- Business impact of violation
- Alternative solutions

### Decision Framework

#### Approval Criteria
- **Urgent fixes**: Critical production issues
- **Minor changes**: Documentation or formatting updates
- **Reviewer unavailability**: When reviewers are unavailable for minor changes
- **Security hotfixes**: Critical security vulnerabilities

#### Rejection Criteria
- **Security violations**: Never approve security policy violations
- **Large changes**: Significant code changes requiring proper review
- **Compliance issues**: Regulatory or compliance requirements
- **Insufficient justification**: Weak or inappropriate reasons

### Example Evaluation

```json
{
  "is_valid": true,
  "reasoning": "This is a critical security hotfix that addresses a production vulnerability. The urgency justifies the acknowledgment.",
  "acknowledgable_violations": [
    {
      "rule_id": "pr-approval-required",
      "rule_name": "PR Approval Required",
      "reason": "Security hotfix requires immediate deployment",
      "risk_level": "low",
      "conditions": "Must be deployed immediately and reviewed post-deployment"
    }
  ],
  "require_fixes": [],
  "confidence": 0.9,
  "recommendations": [
    "Deploy immediately and schedule post-deployment review",
    "Document the security issue and resolution",
    "Implement additional monitoring for similar issues"
  ]
}
```

## Agent Configuration

### Base Agent Class

All agents inherit from `BaseAgent` which provides:

```python
class BaseAgent(ABC):
    def __init__(self):
        self._validate_config()
        self.llm = self._create_llm_client()
        self.graph = self._build_graph()
    
    @abstractmethod
    def _build_graph(self) -> StateGraph:
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> AgentResult:
        pass
```

### Configuration Management

Centralized configuration through environment variables:

```python
class AIConfig:
    provider: str = "openai"
    api_key: str
    model: str = "gpt-4.1-mini"
    max_tokens: int = 4096
    temperature: float = 0.1
```

### LangSmith Integration

Comprehensive observability through LangSmith:

```python
# Environment configuration
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-key
LANGCHAIN_PROJECT=watchflow-dev
```

## Performance and Optimization

### Token Usage Optimization

#### Prompt Engineering
- Concise, focused prompts
- Clear instructions and examples
- Structured output formats
- Context-aware prompt selection

#### Batch Processing
- Group similar evaluations
- Reuse common context
- Optimize API call patterns
- Implement intelligent caching

### Response Time Optimization

#### Parallel Processing
- Concurrent agent execution
- Async/await throughout
- Background task processing
- Non-blocking operations

#### Caching Strategy
- Cache common rule evaluations
- Store frequently accessed data
- Implement TTL-based invalidation
- Use memory-efficient data structures

## Monitoring and Debugging

### LangSmith Integration

#### Trace Visualization
- Step-by-step execution flow
- Input/output at each step
- Performance metrics
- Error tracking and debugging

#### Cost Analysis
- Token usage per request
- API call costs
- Performance optimization opportunities
- Budget monitoring

### Logging and Metrics

#### Structured Logging
```python
logger.info(f"🔧 Engine agent starting evaluation for {event_type}")
logger.info(f"🔧 Found {len(applicable_rules)} applicable rules")
logger.info(f"🔧 Evaluation completed: {len(violations)} violations found")
```

#### Performance Metrics
- Response times per agent
- Success/failure rates
- Token usage statistics
- Error rates and types

## Future Enhancements

### Advanced Features

#### Machine Learning Integration
- ML-based rule optimization
- Predictive violation detection
- Automated rule suggestions
- Performance prediction

#### Multi-Agent Coordination
- Agent-to-agent communication
- Coordinated decision making
- Conflict resolution
- Consensus building

#### Advanced Reasoning
- Chain-of-thought reasoning
- Multi-step problem solving
- Contextual memory
- Learning from feedback

### Enterprise Features

#### Custom Agent Development
- Plugin architecture for custom agents
- Agent marketplace
- Custom prompt templates
- Specialized domain agents

#### Advanced Analytics
- Agent performance analytics
- Rule effectiveness metrics
- Cost optimization insights
- Predictive analytics
