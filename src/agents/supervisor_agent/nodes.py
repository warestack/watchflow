"""
LangGraph nodes for the Rule Supervisor Agent.
"""

import asyncio
import logging
import time

from src.agents.supervisor_agent.models import AgentTask, CoordinationResult, SupervisorAgentResult, SupervisorState

logger = logging.getLogger(__name__)


async def coordinate_agents(state: SupervisorState) -> SupervisorState:
    """
    Coordinate multiple agents to execute tasks in parallel.
    """
    try:
        logger.info(f"🔧 Starting agent coordination for {state.event_type}")

        # Create tasks for each agent based on the event type and rules
        tasks = _create_agent_tasks(state)
        state.agent_tasks = tasks

        logger.info(f"🔧 Created {len(tasks)} agent tasks")

        # Execute tasks concurrently (with limits to avoid rate limits)
        results = await _execute_tasks_concurrently(tasks, max_concurrent=3)
        state.agent_results = results

        logger.info(f"🔧 Completed {len(results)} agent executions")

        # Log results summary
        successful_results = [r for r in results if r.success]
        logger.info(f"🔧 Successful executions: {len(successful_results)}/{len(results)}")

    except Exception as e:
        logger.error(f"❌ Error in agent coordination: {e}")
        state.errors.append(f"Coordination failed: {str(e)}")

    return state


async def validate_results(state: SupervisorState) -> SupervisorState:
    """
    Validate and cross-check results from multiple agents.
    """
    try:
        logger.info("🔍 Validating agent results")

        # Check for conflicting results
        conflicts = _detect_result_conflicts(state.agent_results)
        if conflicts:
            logger.warning(f"⚠️ Found {len(conflicts)} result conflicts")
            state.errors.extend(conflicts)

        # Validate result quality
        quality_issues = _validate_result_quality(state.agent_results)
        if quality_issues:
            logger.warning(f"⚠️ Found {len(quality_issues)} quality issues")
            state.errors.extend(quality_issues)

        logger.info("🔍 Result validation completed")

    except Exception as e:
        logger.error(f"❌ Error in result validation: {e}")
        state.errors.append(f"Validation failed: {str(e)}")

    return state


async def synthesize_final_result(state: SupervisorState) -> SupervisorState:
    """
    Synthesize final decision from multiple agent results.
    """
    try:
        logger.info("🧠 Synthesizing final result from agent outputs")

        # Create coordination result
        coordination_result = _synthesize_coordination_result(state)
        state.coordination_result = coordination_result

        # Set end time
        state.end_time = time.time()

        logger.info(f"✅ Final synthesis completed: success={coordination_result.overall_success}")
        logger.info(f"✅ Confidence score: {coordination_result.confidence_score}")

    except Exception as e:
        logger.error(f"❌ Error in final synthesis: {e}")
        state.errors.append(f"Synthesis failed: {str(e)}")

        # Create fallback result
        state.coordination_result = CoordinationResult(
            overall_success=False,
            summary=f"Synthesis failed: {str(e)}",
            confidence_score=0.0,
        )

    return state


def _create_agent_tasks(state: SupervisorState) -> list[AgentTask]:
    """
    Create tasks for each agent based on the event type and rules.
    """
    tasks = []

    # Feasibility agent task - check if rules are implementable
    if state.rules:
        tasks.append(
            AgentTask(
                agent_name="feasibility",
                task_type="rule_feasibility_check",
                parameters={"rule_description": "\n".join([rule.get("description", "") for rule in state.rules])},
                priority=1,
                timeout=30.0,
            )
        )

    # Engine agent task - evaluate rules against the event
    if state.rules and state.event_data:
        tasks.append(
            AgentTask(
                agent_name="engine",
                task_type="rule_evaluation",
                parameters={"event_type": state.event_type, "event_data": state.event_data, "rules": state.rules},
                priority=2,
                timeout=45.0,
            )
        )

    # Acknowledgment agent task - if this is an acknowledgment request
    if (
        state.event_type == "issue_comment"
        and "acknowledgment" in state.event_data.get("comment", {}).get("body", "").lower()
    ):
        tasks.append(
            AgentTask(
                agent_name="acknowledgment",
                task_type="acknowledgment_evaluation",
                parameters={
                    "acknowledgment_reason": state.event_data.get("comment", {}).get("body", ""),
                    "violations": state.event_data.get("violations", []),
                    "pr_data": state.event_data.get("pull_request", {}),
                    "commenter": state.event_data.get("comment", {}).get("user", {}).get("login", ""),
                    "rules": state.rules,
                },
                priority=3,
                timeout=30.0,
            )
        )

    return tasks


async def _execute_tasks_concurrently(tasks: list[AgentTask], max_concurrent: int = 3) -> list[SupervisorAgentResult]:
    """
    Execute tasks concurrently with rate limiting.
    """
    results = []

    # Execute tasks in batches to avoid overwhelming the system
    for i in range(0, len(tasks), max_concurrent):
        batch = tasks[i : i + max_concurrent]
        batch_results = await asyncio.gather(*[_execute_single_task(task) for task in batch], return_exceptions=True)

        # Convert exceptions to error results
        for result in batch_results:
            if isinstance(result, Exception):
                results.append(
                    SupervisorAgentResult(
                        success=False,
                        message=f"Task execution failed: {str(result)}",
                        data={},
                        metadata={"error_type": type(result).__name__},
                    )
                )
            else:
                results.append(result)

    return results


async def _execute_single_task(task: AgentTask) -> SupervisorAgentResult:
    """
    Execute a single agent task.
    """
    # This would be implemented by the supervisor agent
    # For now, return a placeholder result
    return SupervisorAgentResult(
        success=True,
        message=f"Task {task.task_type} completed successfully",
        data={"task_type": task.task_type, "agent_name": task.agent_name},
        metadata={"execution_time_ms": 1000},
    )


def _detect_result_conflicts(results: list[SupervisorAgentResult]) -> list[str]:
    """
    Detect conflicts between agent results.
    """
    conflicts = []

    # Check for contradictory success/failure states
    success_results = [r for r in results if r.success]
    failure_results = [r for r in results if not r.success]

    if success_results and failure_results:
        conflicts.append("Conflicting success/failure states between agents")

    # Check for contradictory recommendations
    recommendations = []
    for result in results:
        if "recommendation" in result.data:
            recommendations.append(result.data["recommendation"])

    if len(set(recommendations)) > 1:
        conflicts.append("Conflicting recommendations between agents")

    return conflicts


def _validate_result_quality(results: list[SupervisorAgentResult]) -> list[str]:
    """
    Validate the quality of agent results.
    """
    issues = []

    for result in results:
        # Check for empty or missing data
        if not result.data:
            issues.append(f"Agent result has no data: {result.message}")

        # Check for very short messages (might indicate errors)
        if len(result.message) < 10:
            issues.append(f"Agent result has very short message: {result.message}")

    return issues


def _synthesize_coordination_result(state: SupervisorState) -> CoordinationResult:
    """
    Synthesize final coordination result from agent outputs.
    """
    # Calculate overall success
    successful_results = [r for r in state.agent_results if r.success]
    overall_success = len(successful_results) > 0 and len(state.errors) == 0

    # Generate summary
    summary = _generate_final_decision(state.agent_results, state.errors)

    # Calculate confidence score
    confidence_score = _calculate_confidence_score(state.agent_results)

    # Detect conflicts
    conflicts = _detect_result_conflicts(state.agent_results)

    # Generate reasoning
    reasoning = _generate_reasoning(state.agent_results, state.errors)

    return CoordinationResult(
        overall_success=overall_success,
        summary=summary,
        agent_results=state.agent_results,
        conflicts=conflicts,
        confidence_score=confidence_score,
        reasoning=reasoning,
    )


def _calculate_confidence_score(results: list[SupervisorAgentResult]) -> float:
    """
    Calculate confidence score based on agent results.
    """
    if not results:
        return 0.0

    # Base confidence on success rate
    successful_results = [r for r in results if r.success]
    success_rate = len(successful_results) / len(results)

    # Adjust based on result quality
    quality_score = 0.0
    for result in results:
        if result.success and result.data:
            quality_score += 0.2  # Bonus for successful results with data

    return min(1.0, success_rate + quality_score)


def _generate_final_decision(results: list[SupervisorAgentResult], errors: list[str]) -> str:
    """
    Generate final decision based on agent results.
    """
    if errors:
        return f"Coordination completed with {len(errors)} errors: {'; '.join(errors[:3])}"

    successful_results = [r for r in results if r.success]
    if not successful_results:
        return "All agent executions failed"

    return f"Coordination completed successfully with {len(successful_results)}/{len(results)} agents"


def _generate_reasoning(results: list[SupervisorAgentResult], errors: list[str]) -> list[str]:
    """
    Generate step-by-step reasoning for the final decision.
    """
    reasoning = []

    reasoning.append(f"Coordinated {len(results)} agents")

    successful_results = [r for r in results if r.success]
    reasoning.append(f"Successful executions: {len(successful_results)}/{len(results)}")

    if errors:
        reasoning.append(f"Errors encountered: {len(errors)}")

    conflicts = _detect_result_conflicts(results)
    if conflicts:
        reasoning.append(f"Conflicts detected: {len(conflicts)}")

    return reasoning
