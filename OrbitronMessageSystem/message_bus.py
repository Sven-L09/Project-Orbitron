"""Orbitron Message Bus - Central communication hub for agents.

The MessageBus enables asynchronous communication between agents
using a publish/subscribe pattern with support for request/response.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from queue import Queue, Empty
import threading
import time

from .message_types import (
    Message,
    MessageHeader,
    MessageType,
    MessagePriority,
    AgentRole,
    ErrorMessage,
    CommandResult,
)

logger = logging.getLogger("MessageBus")


class MessageHandler:
    """Represents a message handler subscription."""
    
    def __init__(
        self,
        agent_name: str,
        agent_role: AgentRole,
        callback: Callable[[Message], None],
        message_types: Optional[list[MessageType]] = None,
        priority_filter: Optional[MessagePriority] = None,
    ):
        self.agent_name = agent_name
        self.agent_role = agent_role
        self.callback = callback
        self.message_types = message_types or []
        self.priority_filter = priority_filter
        self.message_count = 0
        self.created_at = datetime.now()
    
    def should_handle(self, message: Message) -> bool:
        """Check if this handler should process the message."""
        # Check message type filter
        if self.message_types and message.header.message_type not in self.message_types:
            return False
        
        # Check priority filter
        if self.priority_filter and message.header.priority.value < self.priority_filter.value:
            return False
        
        return True
    
    def handle(self, message: Message) -> None:
        """Process the message."""
        self.message_count += 1
        try:
            self.callback(message)
        except Exception as e:
            print(f"[MessageHandler] Error in {self.agent_name}: {e}")


class MessageBus:
    """Central message bus for agent communication.
    
    Features:
    - Publish/subscribe messaging
    - Request/response pattern support
    - Priority-based message handling
    - Async and sync message processing
    - Message persistence (optional)
    """
    
    def __init__(self, persistence_dir: Optional[str] = None):
        """Initialize the message bus."""
        self._handlers: dict[str, MessageHandler] = {}
        self._role_handlers: dict[AgentRole, set[str]] = defaultdict(set)
        self._message_queue: Queue[Message] = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # Request/response tracking (thread-safe)
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._response_handlers: dict[str, Callable[[Message], None]] = {}
        
        # Statistics
        self._stats = {
            "messages_published": 0,
            "messages_delivered": 0,
            "messages_dropped": 0,
            "errors": 0,
        }
        
        # Persistence
        self._persistence_dir = Path(persistence_dir) if persistence_dir else None
        if self._persistence_dir:
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
    
    def start(self) -> None:
        """Start the message bus processing."""
        if self._running:
            return
        
        self._running = True
        self._worker_thread = threading.Thread(target=self._process_messages, daemon=True)
        self._worker_thread.start()
        logger.info("[MessageBus] Started")
    
    def stop(self) -> None:
        """Stop the message bus."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
        logger.info("[MessageBus] Stopped")
    
    def _process_messages(self) -> None:
        """Background thread for processing messages."""
        while self._running:
            try:
                message = self._message_queue.get(timeout=0.1)
                self._deliver_message(message)
            except Empty:
                continue
            except Exception as e:
                print(f"[MessageBus] Error processing message: {e}")
                self._stats["errors"] += 1
    
    def _deliver_message(self, message: Message) -> None:
        """Deliver a message to all appropriate handlers."""
        delivered = False
        
        # Try specific recipient first
        if message.header.recipient and message.header.recipient in self._handlers:
            handler = self._handlers[message.header.recipient]
            if handler.should_handle(message):
                handler.handle(message)
                delivered = True
        
        # Try role-based delivery
        if message.header.recipient_role:
            for handler_id in self._role_handlers.get(message.header.recipient_role, set()):
                if handler_id in self._handlers:
                    handler = self._handlers[handler_id]
                    if handler.should_handle(message):
                        handler.handle(message)
                        delivered = True
        
        # Broadcast only when no recipient is specified
        if message.header.recipient is None and message.header.recipient_role is None:
            for handler in self._handlers.values():
                if handler.should_handle(message):
                    handler.handle(message)
                    delivered = True
        
        # Handle responses to pending requests
        if message.header.correlation_id and message.header.correlation_id in self._pending_requests:
            entry = self._pending_requests.get(message.header.correlation_id)
            if entry:
                entry["response"] = message
                entry["event"].set()
        
        # Handle registered response callbacks
        if message.header.correlation_id and message.header.correlation_id in self._response_handlers:
            callback = self._response_handlers.pop(message.header.correlation_id)
            try:
                callback(message)
            except Exception as e:
                print(f"[MessageBus] Error in response callback: {e}")
        
        if delivered:
            self._stats["messages_delivered"] += 1
        else:
            self._stats["messages_dropped"] += 1
        
        # Persist if enabled
        if self._persistence_dir:
            self._persist_message(message)
    
    def _persist_message(self, message: Message) -> None:
        """Persist message to disk with size limits."""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = self._persistence_dir / f"messages_{date_str}.jsonl"
            
            # Create a truncated copy for persistence
            msg_dict = message.to_dict()
            
            # Truncate large payloads in the message
            def _truncate_large_values(obj: Any, max_len: int = 1000) -> Any:
                if isinstance(obj, str) and len(obj) > max_len:
                    return obj[:max_len] + "...[truncated]"
                elif isinstance(obj, dict):
                    return {k: _truncate_large_values(v, max_len) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [_truncate_large_values(item, max_len) for item in obj]
                return obj
            
            msg_dict = _truncate_large_values(msg_dict)
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg_dict, default=str) + "\n")
        except Exception as e:
            print(f"[MessageBus] Error persisting message: {e}")
    
    # Public API
    
    def register(
        self,
        agent_name: str,
        agent_role: AgentRole,
        callback: Callable[[Message], None],
        message_types: Optional[list[MessageType]] = None,
        priority_filter: Optional[MessagePriority] = None,
    ) -> str:
        """Register an agent to receive messages.
        
        Args:
            agent_name: Unique name for the agent
            agent_role: Role of the agent
            callback: Function to call when message is received
            message_types: Optional filter for specific message types
            priority_filter: Optional minimum priority filter
            
        Returns:
            Handler ID for unregistering
        """
        handler_id = f"{agent_role.value}:{agent_name}"
        
        if handler_id in self._handlers:
            logger.warning("[MessageBus] Warning: %s already registered, updating", handler_id)
            if handler_id in self._role_handlers.get(agent_role, []):
                self._role_handlers[agent_role].remove(handler_id)
        
        handler = MessageHandler(
            agent_name=agent_name,
            agent_role=agent_role,
            callback=callback,
            message_types=message_types,
            priority_filter=priority_filter,
        )
        
        self._handlers[handler_id] = handler
        self._role_handlers[agent_role].add(handler_id)
        
        logger.info("[MessageBus] Registered %s", handler_id)
        return handler_id
    
    def unregister(self, handler_id: str) -> bool:
        """Unregister an agent."""
        if handler_id not in self._handlers:
            return False
        
        handler = self._handlers.pop(handler_id)
        if handler_id in self._role_handlers[handler.agent_role]:
            self._role_handlers[handler.agent_role].remove(handler_id)
        
        logger.info("[MessageBus] Unregistered %s", handler_id)
        return True
    
    def publish(self, message: Message) -> None:
        """Publish a message to the bus."""
        self._message_queue.put(message)
        self._stats["messages_published"] += 1
    
    def send(
        self,
        recipient: str,
        message: Message,
        wait_for_response: bool = False,
        timeout_ms: int = 3600000,
    ) -> Optional[Message]:
        """Send a message to a specific recipient.
        
        Args:
            recipient: Name of the recipient agent
            message: Message to send
            wait_for_response: If True, block until response received
            timeout_ms: Timeout for waiting
            
        Returns:
            Response message if wait_for_response=True, else None
        """
        message.header.recipient = recipient
        if wait_for_response:
            event = self._prepare_wait(message.header.message_id)
            self.publish(message)
            return self._wait_for_event(message.header.message_id, event, timeout_ms)

        self.publish(message)
        return None
    
    def send_to_role(
        self,
        recipient_role: AgentRole,
        message: Message,
        wait_for_response: bool = False,
        timeout_ms: int = 3600000,
    ) -> Optional[Message]:
        """Send a message to all agents with a specific role.
        
        Args:
            recipient_role: Role of the recipient agent
            message: Message to send
            wait_for_response: If True, block until response received
            timeout_ms: Timeout for waiting
            
        Returns:
            Response message if wait_for_response=True, else None
        """
        message.header.recipient_role = recipient_role
        if wait_for_response:
            event = self._prepare_wait(message.header.message_id)
            self.publish(message)
            return self._wait_for_event(message.header.message_id, event, timeout_ms)

        self.publish(message)
        return None
    
    def send_to_executor(
        self,
        message: Message,
        wait_for_response: bool = False,
        timeout_ms: int = 3600000,
    ) -> Optional[Message]:
        """Send a message to the Executor Agent.
        
        Args:
            message: Message to send
            wait_for_response: If True, block until response received
            timeout_ms: Timeout for waiting
            
        Returns:
            Response message if wait_for_response=True, else None
        """
        return self.send_to_role(
            recipient_role=AgentRole.EXECUTOR,
            message=message,
            wait_for_response=wait_for_response,
            timeout_ms=timeout_ms,
        )

    def _prepare_wait(self, request_id: str) -> threading.Event:
        """Prepare a wait entry before publishing a request."""
        event = threading.Event()
        self._pending_requests[request_id] = {
            "event": event,
            "response": None,
        }
        return event

    def _wait_for_event(
        self,
        request_id: str,
        event: threading.Event,
        timeout_ms: int,
    ) -> Optional[Message]:
        """Wait for a response using a prepared event."""
        try:
            if not event.wait(timeout=timeout_ms / 1000):
                print(f"[MessageBus] Timeout waiting for response to {request_id}")
                return None
            entry = self._pending_requests.get(request_id)
            return entry.get("response") if entry else None
        except Exception as e:
            print(f"[MessageBus] Error waiting for response: {e}")
            return None
        finally:
            self._pending_requests.pop(request_id, None)
    
    def wait_for_response(
        self,
        request_id: str,
        timeout_ms: int = 3600000,
    ) -> Optional[Message]:
        """Wait for a response to a specific request.
        
        This is a blocking call that waits for a response message
        with the matching correlation_id.
        """
        event = self._prepare_wait(request_id)
        return self._wait_for_event(request_id, event, timeout_ms)
    
    def on_response(
        self,
        request_id: str,
        callback: Callable[[Message], None],
    ) -> None:
        """Register a callback for a specific response."""
        self._response_handlers[request_id] = callback
    
    def get_stats(self) -> dict[str, Any]:
        """Get message bus statistics."""
        return {
            **self._stats,
            "handlers_registered": len(self._handlers),
            "pending_requests": len(self._pending_requests),
            "queue_size": self._message_queue.qsize(),
        }
    
    def get_handlers(self) -> list[dict[str, Any]]:
        """Get information about registered handlers."""
        return [
            {
                "id": hid,
                "agent_name": h.agent_name,
                "agent_role": h.agent_role.value,
                "message_count": h.message_count,
                "created_at": h.created_at.isoformat(),
            }
            for hid, h in self._handlers.items()
        ]


# Singleton instance
_message_bus: Optional[MessageBus] = None


def get_message_bus(persistence_dir: Optional[str] = None) -> MessageBus:
    """Get or create the singleton message bus instance."""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus(persistence_dir=persistence_dir)
    return _message_bus


def reset_message_bus() -> None:
    """Reset the singleton message bus (useful for testing)."""
    global _message_bus
    if _message_bus:
        _message_bus.stop()
    _message_bus = None
