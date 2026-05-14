"""Agent Communication API - High-level API for agent communication.

This module provides a simplified API for agents to communicate with each other,
abstracting away the details of the message bus.
"""

from datetime import datetime
from typing import Any, Optional, Callable

from .message_types import (
    Message,
    MessageHeader,
    MessageType,
    MessagePriority,
    AgentRole,
    PlanningRequest,
    PlanningResponse,
    CommandMessage,
    StatusMessage,
    ErrorMessage,
    TestingRequest,
    TestingResponse,
)
from .message_bus import MessageBus, get_message_bus


class AgentCommunicator:
    """High-level communication interface for agents.
    
    This class provides a simple API for agents to:
    - Send and receive messages
    - Request planning from the Planner
    - Execute commands
    - Broadcast status updates
    """
    
    def __init__(
        self,
        agent_name: str,
        agent_role: AgentRole,
        message_bus: Optional[MessageBus] = None,
    ):
        """Initialize the communicator.
        
        Args:
            agent_name: Unique name for this agent
            agent_role: Role of this agent
            message_bus: Optional message bus instance (uses singleton if None)
        """
        self.agent_name = agent_name
        self.agent_role = agent_role
        self._bus = message_bus or get_message_bus()
        self._handler_id: Optional[str] = None
    
    def connect(
        self,
        message_handler: Optional[Callable[[Message], None]] = None,
        message_types: Optional[list[MessageType]] = None,
    ) -> None:
        """Connect to the message bus.
        
        Args:
            message_handler: Callback for received messages
            message_types: Optional filter for message types
        """
        if message_handler:
            self._handler_id = self._bus.register(
                agent_name=self.agent_name,
                agent_role=self.agent_role,
                callback=message_handler,
                message_types=message_types,
            )
        
        if not self._bus._running:
            self._bus.start()
    
    def disconnect(self) -> None:
        """Disconnect from the message bus."""
        if self._handler_id:
            self._bus.unregister(self._handler_id)
            self._handler_id = None
    
    # Planning API

    def request_planning(
        self,
        request: str,
        context: Optional[dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Request planning from the Planner Agent.
        
        Args:
            request: The planning request description
            context: Additional context for the planner
            priority: Priority of the request
            timeout_ms: Timeout for waiting for response
            
        Returns:
            PlanningResponse message or None if timeout
        """
        message = PlanningRequest.create(
            request=request,
            context=context,
            sender=self.agent_name,
            priority=priority,
            timeout_ms=timeout_ms,
        )
        
        return self._bus.send_to_role(
            recipient_role=AgentRole.PLANNER,
            message=message,
            wait_for_response=True,
            timeout_ms=timeout_ms,
        )
    
    def request_planning_async(
        self,
        request: str,
        callback: Callable[[Message], None],
        context: Optional[dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> str:
        """Request planning asynchronously.
        
        Args:
            request: The planning request description
            callback: Function to call when planning is complete
            context: Additional context for the planner
            priority: Priority of the request
            
        Returns:
            Request ID for tracking
        """
        message = PlanningRequest.create(
            request=request,
            context=context,
            sender=self.agent_name,
            priority=priority,
        )
        
        self._bus.on_response(message.header.message_id, callback)
        self._bus.send_to_role(
            recipient_role=AgentRole.PLANNER,
            message=message,
            wait_for_response=False,
        )
        
        return message.header.message_id
    
    # Command API
    
    def send_command(
        self,
        command: str,
        args: Optional[dict[str, Any]] = None,
        recipient_role: AgentRole = AgentRole.KERNEL,
        wait_for_response: bool = True,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Send a command to execute.
        
        Args:
            command: Command name
            args: Command arguments
            recipient_role: Target agent role
            wait_for_response: Whether to wait for result
            timeout_ms: Timeout for response
            
        Returns:
            Command result message or None
        """
        message = CommandMessage.create(
            command=command,
            args=args,
            sender=self.agent_name,
            recipient_role=recipient_role,
        )
        
        return self._bus.send_to_role(
            recipient_role=recipient_role,
            message=message,
            wait_for_response=wait_for_response,
            timeout_ms=timeout_ms,
        )
    
    def send_command_to_agent(
        self,
        agent_name: str,
        command: str,
        args: Optional[dict[str, Any]] = None,
        wait_for_response: bool = True,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Send a command to a specific agent.
        
        Args:
            agent_name: Name of the target agent
            command: Command name
            args: Command arguments
            wait_for_response: Whether to wait for result
            timeout_ms: Timeout for response
            
        Returns:
            Command result message or None
        """
        message = CommandMessage.create(
            command=command,
            args=args,
            sender=self.agent_name,
        )
        
        return self._bus.send(
            recipient=agent_name,
            message=message,
            wait_for_response=wait_for_response,
            timeout_ms=timeout_ms,
        )
    
    # Status API
    
    def send_status(
        self,
        status: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Broadcast a status update.
        
        Args:
            status: Status string (e.g., "idle", "working", "error")
            details: Additional status details
        """
        message = StatusMessage.create(
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            status=status,
            details=details,
        )
        self._bus.publish(message)
    
    # Response API
    
    def respond_to(
        self,
        original_message: Message,
        payload: dict[str, Any],
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Send a response to a message.
        
        Args:
            original_message: The message being responded to
            payload: Response payload
            success: Whether the operation succeeded
            error_message: Optional error message
        """
        response = original_message.create_response(
            payload=payload,
            success=success,
            error_message=error_message,
        )
        self._bus.publish(response)
    
    def send_planning_response(
        self,
        request_id: str,
        plan: dict[str, Any],
        analysis: Optional[dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Send a planning response (for Planner Agent use).
        
        Args:
            request_id: ID of the planning request
            plan: The created plan
            analysis: Optional analysis results
            success: Whether planning succeeded
            error_message: Optional error message
        """
        message = PlanningResponse.create(
            request_id=request_id,
            plan=plan,
            analysis=analysis,
            sender=self.agent_name,
            success=success,
            error_message=error_message,
        )
        self._bus.publish(message)
    
    # Error API
    
    def send_error(
        self,
        error_code: str,
        error_message: str,
        original_message_id: Optional[str] = None,
    ) -> None:
        """Send an error notification.
        
        Args:
            error_code: Error code string
            error_message: Human-readable error description
            original_message_id: ID of message that caused the error
        """
        message = ErrorMessage.create(
            error_code=error_code,
            error_message=error_message,
            sender=self.agent_name,
            sender_role=self.agent_role,
            original_message_id=original_message_id,
        )
        self._bus.publish(message)
    
    # Utility
    
    def get_stats(self) -> dict[str, Any]:
        """Get message bus statistics."""
        return self._bus.get_stats()


class OrchestratorCommunicator(AgentCommunicator):
    """Specialized communicator for the Orchestrator Agent."""
    
    def __init__(self, agent_name: str = "orchestrator", message_bus: Optional[MessageBus] = None):
        super().__init__(agent_name, AgentRole.ORCHESTRATOR, message_bus)
    
    def request_planning(
        self,
        request: str,
        context: Optional[dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Request planning from the Planner Agent."""
        # Add orchestrator context
        full_context = {
            "requester": "orchestrator",
            "timestamp": datetime.now().isoformat(),
            **(context or {}),
        }
        return super().request_planning(request, full_context, priority, timeout_ms)


class PlannerCommunicator(AgentCommunicator):
    """Specialized communicator for the Planner Agent."""
    
    def __init__(self, agent_name: str = "planner", message_bus: Optional[MessageBus] = None):
        super().__init__(agent_name, AgentRole.PLANNER, message_bus)
    
    def send_planning_result(
        self,
        request_id: str,
        plan: dict[str, Any],
        analysis: Optional[dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Send planning results back to the requester."""
        self.send_planning_response(
            request_id=request_id,
            plan=plan,
            analysis=analysis,
            success=success,
            error_message=error_message,
        )


class ExecutorCommunicator(AgentCommunicator):
    """Specialized communicator for the Executor Agent."""

    def __init__(self, agent_name: str = "executor", message_bus: Optional[MessageBus] = None):
        super().__init__(agent_name, AgentRole.EXECUTOR, message_bus)

    def send_execution_result(
        self,
        request_id: str,
        execution_result: dict[str, Any],
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Send execution results back to the requester (usually Orchestrator).

        Args:
            request_id: ID of the execution request
            execution_result: Results of the execution
            success: Whether execution succeeded
            error_message: Optional error message
        """
        message = Message(
            header=MessageHeader(
                message_type=MessageType.COMMAND_RESULT,
                sender=self.agent_name,
                sender_role=AgentRole.EXECUTOR,
                recipient_role=AgentRole.ORCHESTRATOR,
                correlation_id=request_id,
            ),
            payload={
                "execution_result": execution_result,
                "success": success,
            },
            metadata={
                "error": error_message,
            },
        )
        self._bus.publish(message)

    def request_execution(
        self,
        plan: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Request execution of a plan.

        Args:
            plan: The plan to execute
            context: Additional execution context
            priority: Priority of execution
            timeout_ms: Timeout for execution

        Returns:
            Execution result message or None if timeout
        """
        message = CommandMessage.create(
            command="execute_plan",
            args={
                "plan": plan,
                "context": context or {},
            },
            sender=self.agent_name,
            recipient_role=AgentRole.EXECUTOR,
            priority=priority,
        )

        return self._bus.send_to_role(
            recipient_role=AgentRole.EXECUTOR,
            message=message,
            wait_for_response=True,
            timeout_ms=timeout_ms,
        )


class TesterCommunicator(AgentCommunicator):
    """Specialized communicator for the Tester Agent."""

    def __init__(self, agent_name: str = "tester", message_bus: Optional[MessageBus] = None):
        super().__init__(agent_name, AgentRole.TESTER, message_bus)

    def send_testing_result(
        self,
        request_id: str,
        quality_rating: str,
        issues: list[dict[str, Any]],
        summary: str,
        passed: bool = True,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Send testing results back to the Orchestrator.

        Args:
            request_id: ID of the testing request
            quality_rating: Overall quality rating (excellent/good/poor)
            issues: List of issues found during testing
            summary: Summary of the testing result
            passed: Whether the product passed quality checks
            success: Whether the testing process itself succeeded
            error_message: Optional error message
        """
        message = TestingResponse.create(
            request_id=request_id,
            quality_rating=quality_rating,
            issues=issues,
            summary=summary,
            passed=passed,
            sender=self.agent_name,
            success=success,
            error_message=error_message,
        )
        self._bus.publish(message)

    def request_testing(
        self,
        task_description: str,
        artifacts: list[str],
        requirements: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Optional[Message]:
        """Request quality testing from the Tester Agent.

        Args:
            task_description: Description of the original task
            artifacts: List of artifact file paths to test
            requirements: Original requirements for validation
            execution_result: Result from the Executor
            priority: Priority of the testing request
            timeout_ms: Timeout for testing

        Returns:
            TestingResponse message or None if timeout
        """
        message = TestingRequest.create(
            task_description=task_description,
            artifacts=artifacts,
            requirements=requirements,
            execution_result=execution_result,
            sender=self.agent_name,
            priority=priority,
            timeout_ms=timeout_ms,
        )

        return self._bus.send_to_role(
            recipient_role=AgentRole.TESTER,
            message=message,
            wait_for_response=True,
            timeout_ms=timeout_ms,
        )


# Convenience functions

def create_orchestrator_communicator(
    agent_name: str = "orchestrator",
    message_bus: Optional[MessageBus] = None,
) -> OrchestratorCommunicator:
    """Create an orchestrator communicator."""
    return OrchestratorCommunicator(agent_name, message_bus)


def create_planner_communicator(
    agent_name: str = "planner",
    message_bus: Optional[MessageBus] = None,
) -> PlannerCommunicator:
    """Create a planner communicator."""
    return PlannerCommunicator(agent_name, message_bus)


def create_executor_communicator(
    agent_name: str = "executor",
    message_bus: Optional[MessageBus] = None,
) -> ExecutorCommunicator:
    """Create an executor communicator."""
    return ExecutorCommunicator(agent_name, message_bus)


def create_tester_communicator(
    agent_name: str = "tester",
    message_bus: Optional[MessageBus] = None,
) -> TesterCommunicator:
    """Create a tester communicator."""
    return TesterCommunicator(agent_name, message_bus)


def create_agent_communicator(
    agent_name: str,
    agent_role: AgentRole,
    message_bus: Optional[MessageBus] = None,
) -> AgentCommunicator:
    """Create a generic agent communicator."""
    return AgentCommunicator(agent_name, agent_role, message_bus)
