"""Orbitron Message System - Core message types and protocols.

This module defines the fundamental message types used for communication
between agents in the Orbitron system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional
import uuid


class MessageType(Enum):
    """Types of messages that can be exchanged between agents."""
    
    # Request/Response pattern
    REQUEST = auto()      # A request requiring a response
    RESPONSE = auto()     # A response to a request
    
    # Event pattern
    EVENT = auto()        # An event notification (fire-and-forget)
    
    # Command pattern
    COMMAND = auto()      # A command to execute
    COMMAND_RESULT = auto()  # Result of a command execution
    
    # Planning specific
    PLANNING_REQUEST = auto()   # Request for planning
    PLANNING_RESPONSE = auto()  # Planning result
    PLAN_UPDATE = auto()       # Update to an existing plan

    # Testing specific
    TESTING_REQUEST = auto()   # Request for quality testing
    TESTING_RESPONSE = auto()  # Testing result
    
    # Status and monitoring
    STATUS = auto()       # Status update
    HEARTBEAT = auto()    # Keep-alive signal
    ERROR = auto()        # Error notification


class MessagePriority(Enum):
    """Priority levels for messages."""
    
    CRITICAL = 0    # Must be processed immediately
    HIGH = 1        # Important, process soon
    NORMAL = 2      # Standard priority
    LOW = 3         # Can be delayed
    BACKGROUND = 4  # Process when idle


class AgentRole(Enum):
    """Defined agent roles in the system."""
    
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    EXECUTOR = "executor"
    TESTER = "tester"
    CODER = "coder"
    REVIEWER = "reviewer"
    KERNEL = "kernel"
    USER = "user"


@dataclass
class MessageHeader:
    """Header information for all messages."""
    
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None  # Links related messages
    message_type: MessageType = MessageType.EVENT
    priority: MessagePriority = MessagePriority.NORMAL
    
    # Routing information
    sender: str = "unknown"
    sender_role: AgentRole = AgentRole.KERNEL
    recipient: Optional[str] = None  # None = broadcast
    recipient_role: Optional[AgentRole] = None
    
    # Timing
    timestamp: datetime = field(default_factory=datetime.now)
    timeout_ms: Optional[int] = None  # Request timeout
    
    def to_dict(self) -> dict[str, Any]:
        """Convert header to dictionary."""
        return {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "message_type": self.message_type.name,
            "priority": self.priority.name,
            "sender": self.sender,
            "sender_role": self.sender_role.value,
            "recipient": self.recipient,
            "recipient_role": self.recipient_role.value if self.recipient_role else None,
            "timestamp": self.timestamp.isoformat(),
            "timeout_ms": self.timeout_ms,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageHeader":
        """Create header from dictionary."""
        return cls(
            message_id=data["message_id"],
            correlation_id=data.get("correlation_id"),
            message_type=MessageType[data["message_type"]],
            priority=MessagePriority[data["priority"]],
            sender=data["sender"],
            sender_role=AgentRole(data["sender_role"]),
            recipient=data.get("recipient"),
            recipient_role=AgentRole(data["recipient_role"]) if data.get("recipient_role") else None,
            timestamp=datetime.fromisoformat(data["timestamp"]),
            timeout_ms=data.get("timeout_ms"),
        )


@dataclass
class Message:
    """Base message class for all agent communication."""
    
    header: MessageHeader = field(default_factory=MessageHeader)
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary."""
        return {
            "header": self.header.to_dict(),
            "payload": self.payload,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create message from dictionary."""
        return cls(
            header=MessageHeader.from_dict(data["header"]),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )
    
    def create_response(
        self,
        payload: dict[str, Any],
        success: bool = True,
        error_message: Optional[str] = None
    ) -> "Message":
        """Create a response message to this message."""
        response_header = MessageHeader(
            message_type=MessageType.RESPONSE,
            sender=self.header.recipient or "unknown",
            sender_role=self.header.recipient_role or AgentRole.KERNEL,
            recipient=self.header.sender,
            recipient_role=self.header.sender_role,
            correlation_id=self.header.message_id,
        )
        
        response_metadata = {"success": success}
        if error_message:
            response_metadata["error"] = error_message
        
        return Message(
            header=response_header,
            payload=payload,
            metadata=response_metadata,
        )


# Specific message types for common use cases

@dataclass
class PlanningRequest(Message):
    """Message for requesting planning from the Planner Agent."""
    
    @staticmethod
    def create(
        request: str,
        context: Optional[dict[str, Any]] = None,
        sender: str = "orchestrator",
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Message:
        """Create a planning request message."""
        header = MessageHeader(
            message_type=MessageType.PLANNING_REQUEST,
            sender=sender,
            sender_role=AgentRole.ORCHESTRATOR,
            recipient_role=AgentRole.PLANNER,
            priority=priority,
            timeout_ms=timeout_ms,
        )
        
        return Message(
            header=header,
            payload={
                "request": request,
                "context": context or {},
            },
            metadata={
                "request_type": "planning",
                "requires_response": True,
            },
        )


@dataclass
class PlanningResponse(Message):
    """Message containing planning results from the Planner Agent."""
    
    @staticmethod
    def create(
        request_id: str,
        plan: dict[str, Any],
        analysis: Optional[dict[str, Any]] = None,
        sender: str = "planner",
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> Message:
        """Create a planning response message."""
        header = MessageHeader(
            message_type=MessageType.PLANNING_RESPONSE,
            sender=sender,
            sender_role=AgentRole.PLANNER,
            recipient_role=AgentRole.ORCHESTRATOR,
            correlation_id=request_id,
        )
        
        metadata = {"success": success}
        if error_message:
            metadata["error"] = error_message
        
        return Message(
            header=header,
            payload={
                "plan": plan,
                "analysis": analysis or {},
            },
            metadata=metadata,
        )


@dataclass
class CommandMessage(Message):
    """Message for executing commands."""
    
    @staticmethod
    def create(
        command: str,
        args: Optional[dict[str, Any]] = None,
        sender: str = "orchestrator",
        recipient_role: AgentRole = AgentRole.KERNEL,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> Message:
        """Create a command message."""
        header = MessageHeader(
            message_type=MessageType.COMMAND,
            sender=sender,
            sender_role=AgentRole.ORCHESTRATOR,
            recipient_role=recipient_role,
            priority=priority,
        )
        
        return Message(
            header=header,
            payload={
                "command": command,
                "args": args or {},
            },
            metadata={"requires_response": True},
        )


@dataclass
class StatusMessage(Message):
    """Message for status updates."""
    
    @staticmethod
    def create(
        agent_name: str,
        agent_role: AgentRole,
        status: str,
        details: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Create a status message."""
        header = MessageHeader(
            message_type=MessageType.STATUS,
            sender=agent_name,
            sender_role=agent_role,
        )
        
        return Message(
            header=header,
            payload={
                "status": status,
                "details": details or {},
            },
        )


@dataclass
class ErrorMessage(Message):
    """Message for error notifications."""
    
    @staticmethod
    def create(
        error_code: str,
        error_message: str,
        sender: str = "unknown",
        sender_role: AgentRole = AgentRole.KERNEL,
        original_message_id: Optional[str] = None,
    ) -> Message:
        """Create an error message."""
        header = MessageHeader(
            message_type=MessageType.ERROR,
            sender=sender,
            sender_role=sender_role,
        )
        
        return Message(
            header=header,
            payload={
                "error_code": error_code,
                "error_message": error_message,
            },
            metadata={
                "original_message_id": original_message_id,
            },
        )


@dataclass
class CommandResult(Message):
    """Message for command execution results."""
    
    @staticmethod
    def create(
        command: str,
        result: dict[str, Any],
        success: bool = True,
        error_message: Optional[str] = None,
        sender: str = "executor",
        sender_role: AgentRole = AgentRole.EXECUTOR,
        original_message_id: Optional[str] = None,
    ) -> Message:
        """Create a command result message."""
        header = MessageHeader(
            message_type=MessageType.COMMAND_RESULT,
            sender=sender,
            sender_role=sender_role,
            correlation_id=original_message_id,
        )
        
        return Message(
            header=header,
            payload={
                "command": command,
                "result": result,
                "success": success,
            },
            metadata={
                "error": error_message,
            },
        )


@dataclass
class TestingRequest(Message):
    """Message for requesting quality testing from the Tester Agent."""

    @staticmethod
    def create(
        task_description: str,
        artifacts: list[str],
        requirements: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
        sender: str = "orchestrator",
        priority: MessagePriority = MessagePriority.NORMAL,
        timeout_ms: int = 300000,
    ) -> Message:
        """Create a testing request message."""
        header = MessageHeader(
            message_type=MessageType.TESTING_REQUEST,
            sender=sender,
            sender_role=AgentRole.ORCHESTRATOR,
            recipient_role=AgentRole.TESTER,
            priority=priority,
            timeout_ms=timeout_ms,
        )

        return Message(
            header=header,
            payload={
                "task_description": task_description,
                "artifacts": artifacts,
                "requirements": requirements or {},
                "execution_result": execution_result or {},
            },
            metadata={
                "request_type": "testing",
                "requires_response": True,
            },
        )


@dataclass
class TestingResponse(Message):
    """Message containing testing results from the Tester Agent."""

    @staticmethod
    def create(
        request_id: str,
        quality_rating: str,
        issues: list[dict[str, Any]],
        summary: str,
        passed: bool = True,
        sender: str = "tester",
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> Message:
        """Create a testing response message."""
        header = MessageHeader(
            message_type=MessageType.TESTING_RESPONSE,
            sender=sender,
            sender_role=AgentRole.TESTER,
            recipient_role=AgentRole.ORCHESTRATOR,
            correlation_id=request_id,
        )

        metadata = {"success": success}
        if error_message:
            metadata["error"] = error_message

        return Message(
            header=header,
            payload={
                "quality_rating": quality_rating,
                "issues": issues,
                "summary": summary,
                "passed": passed,
            },
            metadata=metadata,
        )
