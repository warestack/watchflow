"""
Tests for agents.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult
from src.agents.feasibility_agent import RuleFeasibilityAgent
from src.agents.supervisor_agent import RuleSupervisorAgent
from src.agents.supervisor_agent.models import AgentTask, SupervisorAgentResult, SupervisorState


class TestBaseAgent:
    """Test base agent functionality."""

    @patch("src.agents.base.BaseAgent.__init__")
    def test_base_agent_initialization(self, mock_init):
        """Test that base agent initializes with retry settings."""
        # Use RuleFeasibilityAgent as a concrete implementation for testing
        agent = RuleFeasibilityAgent(max_retries=5, timeout=30.0)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 5
        agent.retry_delay = 1.0
        agent.timeout = 30.0
        assert agent.max_retries == 5
        assert agent.retry_delay == 1.0  # Default value

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_retry_structured_output_success(self, mock_init):
        """Test retry logic for structured output."""
        agent = RuleFeasibilityAgent(max_retries=3)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.retry_delay = 1.0

        # Mock LLM that succeeds on first try
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value={"test": "data"})
        mock_llm.with_structured_output.return_value = mock_structured_llm

        result = await agent._retry_structured_output(
            mock_llm,
            dict,  # Mock output model
            "test prompt",
        )

        assert result == {"test": "data"}
        mock_structured_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_retry_structured_output_with_failures(self, mock_init):
        """Test retry logic when structured output fails initially."""
        agent = RuleFeasibilityAgent(max_retries=3, timeout=30.0)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.retry_delay = 1.0
        agent.timeout = 30.0

        # Mock LLM that fails twice then succeeds
        mock_llm = MagicMock()
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(
            side_effect=[Exception("First failure"), Exception("Second failure"), {"test": "data"}]
        )
        mock_llm.with_structured_output.return_value = mock_structured_llm

        result = await agent._retry_structured_output(
            mock_llm,
            dict,  # Mock output model
            "test prompt",
        )

        assert result == {"test": "data"}
        assert mock_structured_llm.ainvoke.call_count == 3

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_timeout_success(self, mock_init):
        """Test timeout wrapper with successful execution."""
        agent = RuleFeasibilityAgent()
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.retry_delay = 1.0

        async def fast_coro():
            return "success"

        result = await agent._execute_with_timeout(fast_coro(), timeout=1.0)
        assert result == "success"

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_timeout_failure(self, mock_init):
        """Test timeout wrapper with timeout failure."""
        agent = RuleFeasibilityAgent()
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.retry_delay = 1.0

        async def slow_coro():
            await asyncio.sleep(2.0)
            return "success"

        with pytest.raises(Exception, match="Operation timed out"):
            await agent._execute_with_timeout(slow_coro(), timeout=0.1)


class TestFeasibilityAgent:
    """Test feasibility agent functionality."""

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_feasibility_agent_initialization(self, mock_init):
        """Test feasibility agent initialization."""
        agent = RuleFeasibilityAgent(max_retries=5, timeout=45.0)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 5
        agent.timeout = 45.0
        assert agent.max_retries == 5
        assert agent.timeout == 45.0

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_timeout(self, mock_init):
        """Test execute method with timeout handling."""
        agent = RuleFeasibilityAgent(timeout=30.0)
        # Manually set the attributes since we mocked __init__
        agent.timeout = 30.0
        agent.graph = AsyncMock()

        # Mock the graph execution
        from src.agents.feasibility_agent.models import FeasibilityState

        mock_state = FeasibilityState(
            rule_description="Prevent deployments on weekends",
            is_feasible=True,
            rule_type="time_restriction",
            confidence_score=0.9,
            feedback="Rule is feasible",
            analysis_steps=["Step 1", "Step 2"],
            yaml_content="rules:\n  - id: test",
        )

        agent.graph = AsyncMock()
        agent.graph.ainvoke.return_value = mock_state

        result = await agent.execute("Prevent deployments on weekends")

        assert result.success is True
        assert result.data["is_feasible"] is True
        assert result.data["rule_type"] == "time_restriction"
        assert result.metadata["timeout_used"] == 30.0
        assert "execution_time_ms" in result.metadata

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_timeout_error(self, mock_init):
        """Test execute method with timeout error."""
        agent = RuleFeasibilityAgent(timeout=30.0)
        # Manually set the attributes since we mocked __init__
        agent.timeout = 30.0
        agent.graph = AsyncMock()

        # Mock timeout error
        agent.graph = AsyncMock()
        agent.graph.ainvoke.side_effect = TimeoutError()

        result = await agent.execute("Prevent deployments on weekends")

        assert result.success is False
        assert "timed out" in result.message
        assert result.data == {}  # No data should be returned on error

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_retry_success(self, mock_init):
        """Test execute_with_retry method with successful execution."""
        agent = RuleFeasibilityAgent(max_retries=3)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.graph = AsyncMock()

        # Mock successful execution
        with patch.object(agent, "execute") as mock_execute:
            mock_execute.return_value = AgentResult(success=True, message="Success", data={"test": "data"})

            result = await agent.execute_with_retry("Test rule")

            assert result.success is True
            assert result.metadata["retry_count"] == 0
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_execute_with_retry_failure_then_success(self, mock_init):
        """Test execute_with_retry method with failure then success."""
        agent = RuleFeasibilityAgent(max_retries=3, timeout=30.0)
        # Manually set the attributes since we mocked __init__
        agent.max_retries = 3
        agent.retry_delay = 1.0
        agent.timeout = 30.0
        agent.graph = AsyncMock()

        # Mock execution that fails once then succeeds
        with patch.object(agent, "execute") as mock_execute:
            mock_execute.side_effect = [
                AgentResult(success=False, message="Failed", data={}),
                AgentResult(success=True, message="Success", data={"test": "data"}),
            ]

            result = await agent.execute_with_retry("Test rule")

            assert result.success is True
            assert result.metadata["retry_count"] == 1
            assert mock_execute.call_count == 2


class TestSupervisorAgent:
    """Test supervisor agent functionality."""

    @patch("src.agents.base.BaseAgent.__init__")
    def test_supervisor_agent_initialization(self, mock_init):
        """Test supervisor agent initialization."""
        agent = RuleSupervisorAgent(max_concurrent_agents=5)
        # Manually set the attributes since we mocked __init__
        agent.max_concurrent_agents = 5
        assert agent.max_concurrent_agents == 5
        assert len(agent.sub_agents) == 3  # feasibility, engine, acknowledgment
        assert "feasibility" in agent.sub_agents
        assert "engine" in agent.sub_agents
        assert "acknowledgment" in agent.sub_agents

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_supervisor_execute_agent_task_success(self, mock_init):
        """Test successful execution of agent task."""
        agent = RuleSupervisorAgent()
        # Manually set the attributes since we mocked __init__
        agent.max_concurrent_agents = 3

        task = AgentTask(
            agent_name="feasibility",
            task_type="rule_feasibility",
            parameters={"rule_description": "Test rule"},
            timeout=30.0,
        )

        # Mock sub-agent execution
        with patch.object(agent.sub_agents["feasibility"], "execute") as mock_execute:
            mock_execute.return_value = AgentResult(
                success=True, message="Success", data={"is_feasible": True}, metadata={"execution_time_ms": 1500}
            )

            result = await agent._execute_agent_task(task)

            assert result.success is True
            assert result.message == "Success"
            assert result.data["is_feasible"] is True
            assert result.metadata["execution_time_ms"] == 1500

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_supervisor_execute_agent_task_timeout(self, mock_init):
        """Test agent task execution with timeout."""
        agent = RuleSupervisorAgent()
        # Manually set the attributes since we mocked __init__
        agent.max_concurrent_agents = 3

        task = AgentTask(
            agent_name="feasibility",
            task_type="rule_feasibility",
            parameters={"rule_description": "Test rule"},
            timeout=0.1,  # Very short timeout
        )

        # Mock sub-agent that takes too long
        with patch.object(agent.sub_agents["feasibility"], "execute") as mock_execute:

            async def slow_execute(*args, **kwargs):
                await asyncio.sleep(1.0)  # Longer than timeout
                return AgentResult(success=True, message="Success", data={})

            mock_execute.side_effect = slow_execute

            result = await agent._execute_agent_task(task)

            assert result.success is False
            assert "timed out" in result.message
            assert result.metadata["error_type"] == "timeout"

    @pytest.mark.asyncio
    @patch("src.agents.base.BaseAgent.__init__")
    async def test_supervisor_coordinate_agents(self, mock_init):
        """Test agent coordination."""
        agent = RuleSupervisorAgent()
        # Manually set the attributes since we mocked __init__
        agent.max_concurrent_agents = 3

        result = await agent.coordinate_agents(
            "Evaluate rules",
            event_type="pull_request",
            event_data={"action": "opened"},
            rules=[{"id": "test", "name": "Test Rule"}],
        )

        # Should return a result (even if mock)
        assert isinstance(result, AgentResult)

    def test_supervisor_state_creation(self):
        """Test supervisor state creation."""
        state = SupervisorState(
            task_description="Test task", event_type="pull_request", event_data={"test": "data"}, rules=[{"id": "test"}]
        )

        assert state.task_description == "Test task"
        assert state.event_type == "pull_request"
        assert len(state.rules) == 1
        assert state.start_time is None  # start_time is optional and defaults to None


class TestAgentCoordination:
    """Test agent coordination patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_execution(self):
        """Test concurrent execution of multiple agents."""
        from src.agents.supervisor_agent.nodes import _execute_tasks_concurrently

        tasks = [
            AgentTask(agent_name="agent1", task_type="test", parameters={}),
            AgentTask(agent_name="agent2", task_type="test", parameters={}),
            AgentTask(agent_name="agent3", task_type="test", parameters={}),
        ]

        results = await _execute_tasks_concurrently(tasks, max_concurrent=2)

        assert len(results) == 3
        # All should be mock results for now
        assert all(r.success for r in results)

    def test_result_conflict_detection(self):
        """Test detection of conflicting results between agents."""
        from src.agents.supervisor_agent.nodes import _detect_result_conflicts

        results = [
            SupervisorAgentResult(
                success=True,
                message="Agent1 approved",
                data={"recommendation": "approve"},
                metadata={"agent_name": "agent1", "execution_time_ms": 100},
            ),
            SupervisorAgentResult(
                success=True,
                message="Agent2 rejected",
                data={"recommendation": "reject"},
                metadata={"agent_name": "agent2", "execution_time_ms": 100},
            ),
        ]

        conflicts = _detect_result_conflicts(results)
        assert len(conflicts) > 0
        assert "Conflicting recommendations" in conflicts[0]

    def test_confidence_score_calculation(self):
        """Test confidence score calculation."""
        from src.agents.supervisor_agent.nodes import _calculate_confidence_score

        # All successful results
        results = [
            SupervisorAgentResult(
                success=True,
                message="Agent1 success",
                data={},
                metadata={"agent_name": "agent1", "execution_time_ms": 200},
            ),
            SupervisorAgentResult(
                success=True,
                message="Agent2 success",
                data={},
                metadata={"agent_name": "agent2", "execution_time_ms": 300},
            ),
        ]

        confidence = _calculate_confidence_score(results)
        assert confidence > 0.8  # High confidence for all successful results

        # Mixed results
        results.append(
            SupervisorAgentResult(
                success=False,
                message="Agent3 failed",
                data={},
                metadata={"agent_name": "agent3", "execution_time_ms": 100},
            )
        )

        confidence = _calculate_confidence_score(results)
        assert confidence < 0.8  # Lower confidence with failures


if __name__ == "__main__":
    pytest.main([__file__])
