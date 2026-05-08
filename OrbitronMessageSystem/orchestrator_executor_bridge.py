"""Orchestrator-Executor Integration Bridge.

This module provides the bridge between the Orchestrator and Executor agents,
enabling the Orchestrator to send execution requests and receive results.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from OrbitronMessageSystem import (
        AgentCommunicator,
        ExecutorCommunicator,
        Message,
        MessageType,
        AgentRole,
        get_message_bus,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from OrbitronMessageSystem import (
        AgentCommunicator,
        ExecutorCommunicator,
        Message,
        MessageType,
        AgentRole,
        get_message_bus,
    )


logger = logging.getLogger("OrchestratorExecutorBridge")


class OrchestratorExecutorBridge:
    """Bridge class that integrates Orchestrator with Executor via MessageBus.
    
    This class can be used by the Orchestrator to communicate with the Executor
    without directly instantiating the Executor Agent.
    """
    
    def __init__(self, orchestrator_name: str = "orchestrator"):
        """Initialize the bridge.
        
        Args:
            orchestrator_name: Name of the orchestrator instance
        """
        self._communicator = AgentCommunicator(
            agent_name=orchestrator_name,
            agent_role=AgentRole.ORCHESTRATOR,
        )
        self._communicator.connect()
        
        logger.info("[OrchestratorExecutorBridge] Initialized for %s", orchestrator_name)
    
    def request_execution(
        self,
        plan: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Request execution of a plan from the Executor Agent.
        
        This is a synchronous call that waits for the Executor to complete.
        
        Args:
            plan: The plan to execute (from Planner)
            context: Additional context (files, constraints, etc.)
            timeout_seconds: Maximum time to wait for execution
            
        Returns:
            Dictionary containing the execution results
            
        Example:
            ```python
            bridge = OrchestratorExecutorBridge()
            result = bridge.request_execution(
                plan={
                    "steps": [
                        {
                            "id": "1",
                            "description": "Create main.py",
                            "skill": "programming",
                            "action": "create_file",
                            "args": {"filename": "main.py", "content": "..."}
                        }
                    ]
                },
                context={"workspace": "/path/to/workspace"}
            )
            
            if result["success"]:
                print(f"Execution completed: {result['steps_executed']} steps")
            ```
        """
        logger.info("[OrchestratorExecutorBridge] Requesting execution for plan with %d steps", len(plan.get('steps', [])))
        
        # Send execution request and wait for response
        response = self._communicator.send_command(
            command="execute_plan",
            args={
                "plan": plan,
                "context": context or {},
            },
            recipient_role=AgentRole.EXECUTOR,
            wait_for_response=True,
            timeout_ms=timeout_seconds * 1000,
        )
        
        if response is None:
            return {
                "success": False,
                "error": "Execution timed out or no response from Executor",
                "execution_result": None,
            }
        
        # Parse response
        payload = response.payload if hasattr(response, "payload") and isinstance(response.payload, dict) else {}
        metadata = response.metadata if hasattr(response, "metadata") and isinstance(response.metadata, dict) else {}

        execution_result = payload.get("execution_result") if isinstance(payload, dict) else None
        if not isinstance(execution_result, dict):
            execution_result = payload if isinstance(payload, dict) else {}
            if not execution_result and isinstance(payload, dict) and payload.get("result"):
                execution_result = payload.get("result", {})

        success = payload.get("success") if isinstance(payload, dict) else None
        if not isinstance(success, bool):
            success = bool(execution_result.get("success", False)) if isinstance(execution_result, dict) else False

        return {
            "success": success,
            "execution_result": execution_result,
            "error": metadata.get("error") if isinstance(metadata, dict) else None,
        }
    
    def close(self) -> None:
        """Close the bridge and disconnect from message bus."""
        if self._communicator:
            self._communicator.disconnect()
            logger.info("[OrchestratorExecutorBridge] Closed")


class ExecutorMessageHandler:
    """Message handler for the Executor Agent.
    
    This class handles incoming messages for the Executor Agent,
    processing execution requests and sending results back.
    """
    
    def __init__(self, executor_agent, agent_name: str = "executor"):
        """Initialize the message handler.
        
        Args:
            executor_agent: The ExecutorAgent instance
            agent_name: Name for this executor instance
        """
        self.executor = executor_agent
        self.agent_name = agent_name
        self._communicator = ExecutorCommunicator(agent_name=agent_name)
        self._communicator.connect(message_handler=self._handle_message)
        
        logger.info("[ExecutorMessageHandler] Initialized for %s", agent_name)
    
    def _handle_message(self, message: Message) -> None:
        """Handle incoming messages for the Executor."""
        try:
            msg_type = message.header.message_type if hasattr(message, 'header') else None

            if msg_type == MessageType.COMMAND:
                # Handle execution command
                payload = message.payload if hasattr(message, 'payload') else {}
                command = payload.get("command")
                args = payload.get("args", {})

                if command == "execute_plan":
                    plan = args.get("plan", {})
                    context = args.get("context", {})

                    logger.info("[ExecutorMessageHandler] Executing plan with %d steps", len(plan.get('steps', [])))

                    # Check if plan has a goal (adaptive mode)
                    goal = plan.get("goal")
                    if goal and hasattr(self.executor, 'execute_goal'):
                        result = self.executor.execute_goal(goal=goal, task_id=context.get("task_id"))
                        # Convert ExecutionResult to dict
                        if hasattr(result, 'to_dict'):
                            result = result.to_dict()
                    else:
                        # Execute the plan (legacy or autonomous wrapper)
                        result = self.executor.execute_plan(plan)

                    # Send result back
                    self._communicator.send_execution_result(
                        request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                        execution_result=result,
                        success=result.get("success", False) if isinstance(result, dict) else False,
                        error_message=result.get("error") if isinstance(result, dict) and not result.get("success") else None,
                    )

                    logger.info("[ExecutorMessageHandler] Execution complete: success=%s",
                                result.get("success") if isinstance(result, dict) else "unknown")

                elif command == "execute_goal":
                    # Direct goal execution (adaptive mode)
                    goal = args.get("goal", "")
                    context = args.get("context", {})

                    logger.info("[ExecutorMessageHandler] Executing goal: %.80s...", goal)

                    if hasattr(self.executor, 'execute_goal'):
                        result = self.executor.execute_goal(goal=goal, task_id=context.get("task_id"))
                        if hasattr(result, 'to_dict'):
                            result = result.to_dict()
                    else:
                        result = {
                            "success": False,
                            "error": "Executor does not support autonomous goal execution",
                        }

                    self._communicator.send_execution_result(
                        request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                        execution_result=result,
                        success=result.get("success", False) if isinstance(result, dict) else False,
                        error_message=result.get("error") if isinstance(result, dict) and not result.get("success") else None,
                    )

                    logger.info("[ExecutorMessageHandler] Goal execution complete: success=%s",
                                result.get("success") if isinstance(result, dict) else "unknown")

                else:
                    # Unknown command
                    self._communicator.send_execution_result(
                        request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                        execution_result={},
                        success=False,
                        error_message=f"Unknown command: {command}",
                    )

            elif msg_type == MessageType.STATUS:
                # Handle status request
                status = self.executor.get_status()
                self._communicator.send_status(
                    status="idle",
                    details=status,
                )

        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            # Try to send error response
            try:
                self._communicator.send_execution_result(
                    request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                    execution_result={},
                    success=False,
                    error_message=str(e),
                )
            except:
                pass
    
    def close(self) -> None:
        """Close the message handler."""
        if self._communicator:
            self._communicator.disconnect()
            logger.info("[ExecutorMessageHandler] Closed")
