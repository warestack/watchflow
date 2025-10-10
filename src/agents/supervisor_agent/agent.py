"""
Rule Supervisor Agent for coordinating multiple specialized agents.
"""

import asyncio
import logging
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.acknowledgment_agent import AcknowledgmentAgent
from src.agents.base import AgentResult, SupervisorAgent
from src.agents.engine_agent import RuleEngineAgent
from src.agents.feasibility_agent import RuleFeasibilityAgent
from src.agents.supervisor_agent.models import AgentTask, SupervisorAgentResult, SupervisorState
from src.agents.supervisor_agent.nodes import coordinate_agents, synthesize_final_result, validate_results

logger = logging.getLogger(__name__)


class RuleSupervisorAgent(SupervisorAgent):
    """
    Supervisor agent that coordinates multiple specialized agents for complex rule evaluation.

    Architecture:
    1. Feasibility Agent: Determines if rules are implementable
    2. Engine Agent: Evaluates rules against events
    3. Acknowledgment Agent: Processes violation acknowledgments
    4. Supervisor: Coordinates and synthesizes results
    """

    def __init__(self, max_concurrent_agents: int = 3, timeout: float = 300.0, **kwargs):  # Increased to 5 minutes
        super().__init__(**kwargs)
        self.max_concurrent_agents = max_concurrent_agents
        self.timeout = timeout

        # Initialize sub-agents
        self.sub_agents = {
            "feasibility": RuleFeasibilityAgent(),
            "engine": RuleEngineAgent(),
            "acknowledgment": AcknowledgmentAgent(),
        }

        logger.info(f"🔧 RuleSupervisorAgent initialized with {len(self.sub_agents)} sub-agents")
        logger.info(f"🔧 Max concurrent agents: {max_concurrent_agents}")
        logger.info(f"🔧 Timeout: {timeout}s")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow for supervisor coordination."""
        workflow = StateGraph(SupervisorState)

        # Add nodes
        workflow.add_node("coordinate_agents", coordinate_agents)
        workflow.add_node("validate_results", validate_results)
        workflow.add_node("synthesize_final_result", synthesize_final_result)

        # Add edges
        workflow.add_edge(START, "coordinate_agents")
        workflow.add_edge("coordinate_agents", "validate_results")
        workflow.add_edge("validate_results", "synthesize_final_result")
        workflow.add_edge("synthesize_final_result", END)

        logger.info("🔧 RuleSupervisorAgent graph built with coordination workflow")
        return workflow.compile()

    async def execute(
        self, event_type: str, event_data: dict[str, Any], rules: list[dict[str, Any]], **kwargs
    ) -> AgentResult:
        """
        Execute coordinated rule evaluation using multiple specialized agents.
        """
        start_time = time.time()

        try:
            logger.info(f"🚀 RuleSupervisorAgent starting coordinated evaluation for {event_type}")
            logger.info(f"🚀 Processing {len(rules)} rules with {len(self.sub_agents)} agents")

            # Prepare initial state
            initial_state = SupervisorState(
                task_description=f"Evaluate {len(rules)} rules for {event_type} event",
                event_type=event_type,
                event_data=event_data,
                rules=rules,
                start_time=time.time(),
            )

            # Run the coordination graph with timeout
            result = await self._execute_with_timeout(self.graph.ainvoke(initial_state), timeout=self.timeout)

            execution_time = time.time() - start_time
            logger.info(f"✅ RuleSupervisorAgent coordination completed in {execution_time:.2f}s")

            # Extract coordination result
            coordination_result = result.get("coordination_result")
            if not coordination_result:
                raise Exception("No coordination result produced")

            return AgentResult(
                success=coordination_result.overall_success,
                message=coordination_result.summary,
                data={
                    "coordination_result": coordination_result.dict(),
                    "agent_results": result.get("agent_results", []),
                    "conflicts": result.get("conflicts", []),
                },
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "agents_used": len(result.get("agent_results", [])),
                    "conflicts_detected": len(result.get("conflicts", [])),
                    "coordination_type": "supervisor",
                },
            )

        except TimeoutError:
            execution_time = time.time() - start_time
            logger.error(f"⏰ RuleSupervisorAgent coordination timed out after {execution_time:.2f}s")
            return AgentResult(
                success=False,
                message=f"Supervisor coordination timed out after {self.timeout}s",
                data={},
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "timeout_used": self.timeout,
                    "error_type": "timeout",
                },
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"❌ RuleSupervisorAgent coordination failed: {e}")
            return AgentResult(
                success=False,
                message=f"Supervisor coordination failed: {str(e)}",
                data={},
                metadata={"execution_time_ms": execution_time * 1000, "error_type": type(e).__name__},
            )

    async def coordinate_agents(self, task: str, **kwargs) -> AgentResult:
        """
        Coordinate multiple agents to complete a complex task.
        """
        try:
            logger.info(f"🔧 Coordinating agents for task: {task}")

            # Create tasks for each sub-agent
            tasks = []
            for agent_name, _agent in self.sub_agents.items():
                task_obj = AgentTask(agent_name=agent_name, task_type=task, parameters=kwargs, priority=1)
                tasks.append(task_obj)

            # Execute tasks concurrently with rate limiting
            results = []
            for i in range(0, len(tasks), self.max_concurrent_agents):
                batch = tasks[i : i + self.max_concurrent_agents]
                batch_results = await asyncio.gather(
                    *[self._execute_agent_task(task) for task in batch], return_exceptions=True
                )
                results.extend(batch_results)

            # Filter out exceptions and convert to results
            agent_results = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"❌ Agent task failed: {result}")
                    agent_results.append(
                        SupervisorAgentResult(success=False, message=f"Agent task failed: {str(result)}", data={})
                    )
                else:
                    agent_results.append(result)

            return AgentResult(
                success=any(r.success for r in agent_results),
                message=f"Coordinated {len(agent_results)} agents",
                data={"agent_results": agent_results},
                metadata={"agents_executed": len(agent_results)},
            )

        except Exception as e:
            logger.error(f"❌ Agent coordination failed: {e}")
            return AgentResult(
                success=False,
                message=f"Agent coordination failed: {str(e)}",
                data={},
                metadata={"error_type": type(e).__name__},
            )

    async def _execute_agent_task(self, task: AgentTask) -> SupervisorAgentResult:
        """
        Execute a single agent task with timeout and error handling.
        """
        try:
            agent = self.sub_agents.get(task.agent_name)
            if not agent:
                raise Exception(f"Unknown agent: {task.agent_name}")

            logger.info(f"🔧 Executing {task.agent_name} agent for {task.task_type}")

            # Execute the agent with timeout
            result = await asyncio.wait_for(agent.execute(**task.parameters), timeout=task.timeout)

            return SupervisorAgentResult(
                success=result.success,
                message=result.message,
                data=result.data,
                metadata={
                    "agent_name": task.agent_name,
                    "task_type": task.task_type,
                    "execution_time_ms": result.metadata.get("execution_time_ms", 0),
                },
            )

        except TimeoutError:
            logger.error(f"⏰ {task.agent_name} agent timed out after {task.timeout}s")
            return SupervisorAgentResult(
                success=False,
                message=f"{task.agent_name} agent timed out after {task.timeout}s",
                data={},
                metadata={"agent_name": task.agent_name, "timeout_used": task.timeout, "error_type": "timeout"},
            )

        except Exception as e:
            logger.error(f"❌ {task.agent_name} agent failed: {e}")
            return SupervisorAgentResult(
                success=False,
                message=f"{task.agent_name} agent failed: {str(e)}",
                data={},
                metadata={"agent_name": task.agent_name, "error_type": type(e).__name__},
            )
