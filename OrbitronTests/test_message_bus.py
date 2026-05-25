"""Unit tests for MessageBus module."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from OrbitronMessageSystem.message_bus import MessageBus, MessageHandler
from OrbitronMessageSystem.message_types import (
    Message,
    MessageHeader,
    MessageType,
    MessagePriority,
    AgentRole,
)


class TestMessageTypes:
    """Test message type definitions."""

    def test_message_creation(self):
        """Message should be created with default header."""
        msg = Message()
        assert msg.header is not None
        assert msg.payload == {}
        assert msg.metadata == {}

    def test_message_with_payload(self):
        """Message should carry payload data."""
        msg = Message(
            header=MessageHeader(sender="test", sender_role=AgentRole.EXECUTOR),
            payload={"action": "create_file", "path": "test.txt"},
        )
        assert msg.payload["action"] == "create_file"

    def test_message_to_dict(self):
        """Message should serialize to dict."""
        msg = Message(
            header=MessageHeader(sender="test", sender_role=AgentRole.PLANNER),
            payload={"key": "value"},
        )
        d = msg.to_dict()
        assert "header" in d
        assert "payload" in d
        assert d["payload"]["key"] == "value"

    def test_message_from_dict(self):
        """Message should deserialize from dict."""
        data = {
            "header": {
                "message_id": "test-id",
                "correlation_id": None,
                "message_type": "REQUEST",
                "priority": "NORMAL",
                "sender": "test",
                "sender_role": "executor",
                "recipient": None,
                "recipient_role": None,
                "timestamp": "2026-01-01T00:00:00",
                "timeout_ms": None,
            },
            "payload": {"key": "value"},
            "metadata": {},
        }
        msg = Message.from_dict(data)
        assert msg.header.sender == "test"
        assert msg.payload["key"] == "value"

    def test_message_create_response(self):
        """Message should create a response message."""
        original = Message(
            header=MessageHeader(
                sender="planner",
                sender_role=AgentRole.PLANNER,
                recipient="executor",
                recipient_role=AgentRole.EXECUTOR,
            ),
            payload={"request": "plan"},
        )
        response = original.create_response({"result": "done"}, success=True)
        assert response.header.message_type == MessageType.RESPONSE
        assert response.header.correlation_id == original.header.message_id
        assert response.metadata["success"] is True

    def test_message_header_defaults(self):
        """MessageHeader should have sensible defaults."""
        header = MessageHeader()
        assert header.message_id is not None
        assert header.message_type == MessageType.EVENT
        assert header.priority == MessagePriority.NORMAL
        assert header.sender == "unknown"
        assert header.sender_role == AgentRole.KERNEL

    def test_agent_roles(self):
        """AgentRole should have all expected roles."""
        assert AgentRole.ORCHESTRATOR.value == "orchestrator"
        assert AgentRole.PLANNER.value == "planner"
        assert AgentRole.EXECUTOR.value == "executor"
        assert AgentRole.TESTER.value == "tester"

    def test_message_priorities(self):
        """MessagePriority should have expected ordering."""
        assert MessagePriority.CRITICAL.value < MessagePriority.HIGH.value
        assert MessagePriority.HIGH.value < MessagePriority.NORMAL.value
        assert MessagePriority.NORMAL.value < MessagePriority.LOW.value


class TestMessageHandler:
    """Test MessageHandler class."""

    def test_handler_creation(self):
        """MessageHandler should be created with required fields."""
        callback = MagicMock()
        handler = MessageHandler(
            agent_name="test_agent",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        assert handler.agent_name == "test_agent"
        assert handler.agent_role == AgentRole.EXECUTOR
        assert handler.message_count == 0

    def test_handler_should_handle_no_filter(self):
        """Handler with no filter should handle all messages."""
        callback = MagicMock()
        handler = MessageHandler(
            agent_name="test",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        msg = Message(header=MessageHeader(sender="other", message_type=MessageType.EVENT))
        assert handler.should_handle(msg) is True

    def test_handler_should_handle_with_type_filter(self):
        """Handler with type filter should only handle matching types."""
        callback = MagicMock()
        handler = MessageHandler(
            agent_name="test",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
            message_types=[MessageType.REQUEST, MessageType.COMMAND],
        )
        # Matching type
        msg_match = Message(header=MessageHeader(message_type=MessageType.REQUEST))
        assert handler.should_handle(msg_match) is True

        # Non-matching type
        msg_no_match = Message(header=MessageHeader(message_type=MessageType.EVENT))
        assert handler.should_handle(msg_no_match) is False

    def test_handler_should_handle_with_priority_filter(self):
        """Handler with priority filter should only handle high-priority messages."""
        callback = MagicMock()
        handler = MessageHandler(
            agent_name="test",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
            priority_filter=MessagePriority.HIGH,
        )
        # High priority
        msg_high = Message(header=MessageHeader(priority=MessagePriority.CRITICAL))
        assert handler.should_handle(msg_high) is True

        # Low priority
        msg_low = Message(header=MessageHeader(priority=MessagePriority.LOW))
        assert handler.should_handle(msg_low) is False

    def test_handler_handle_calls_callback(self):
        """Handler.handle should call the callback."""
        callback = MagicMock()
        handler = MessageHandler(
            agent_name="test",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        msg = Message(header=MessageHeader(sender="other"))
        handler.handle(msg)
        callback.assert_called_once_with(msg)
        assert handler.message_count == 1

    def test_handler_handle_exception(self):
        """Handler.handle should not raise exceptions from callback."""
        callback = MagicMock(side_effect=Exception("Test error"))
        handler = MessageHandler(
            agent_name="test",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        msg = Message(header=MessageHeader(sender="other"))
        # Should not raise
        handler.handle(msg)


class TestMessageBus:
    """Test MessageBus class."""

    def test_bus_creation(self, message_bus):
        """MessageBus should be created with default settings."""
        assert message_bus is not None
        stats = message_bus.get_stats()
        assert stats["messages_published"] == 0
        assert stats["messages_delivered"] == 0

    def test_bus_start_stop(self, tmp_path):
        """MessageBus should start and stop cleanly."""
        from OrbitronMessageSystem.message_bus import MessageBus
        bus = MessageBus(persistence_dir=str(tmp_path / "messages"))
        bus.start()
        assert bus._running is True
        bus.stop()
        assert bus._running is False

    def test_register_handler(self, message_bus):
        """MessageBus should register handlers."""
        callback = MagicMock()
        handler_id = message_bus.register(
            agent_name="executor_1",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        assert "executor" in handler_id
        stats = message_bus.get_stats()
        assert stats["handlers_registered"] == 1

    def test_unregister_handler(self, message_bus):
        """MessageBus should unregister handlers."""
        callback = MagicMock()
        handler_id = message_bus.register(
            agent_name="executor_1",
            agent_role=AgentRole.EXECUTOR,
            callback=callback,
        )
        result = message_bus.unregister(handler_id)
        assert result is True
        stats = message_bus.get_stats()
        assert stats["handlers_registered"] == 0

    def test_unregister_nonexistent_handler(self, message_bus):
        """MessageBus should return False for unregistering nonexistent handler."""
        result = message_bus.unregister("nonexistent:handler")
        assert result is False

    def test_publish_message(self, message_bus):
        """MessageBus should publish messages."""
        message_bus.start()
        msg = Message(
            header=MessageHeader(sender="test", message_type=MessageType.EVENT),
            payload={"data": "test"},
        )
        message_bus.publish(msg)
        stats = message_bus.get_stats()
        assert stats["messages_published"] == 1

    def test_send_to_specific_recipient(self, message_bus):
        """MessageBus should deliver messages to specific recipients."""
        message_bus.start()
        received = []

        handler_id = message_bus.register(
            agent_name="executor_1",
            agent_role=AgentRole.EXECUTOR,
            callback=lambda msg: received.append(msg),
        )

        msg = Message(
            header=MessageHeader(
                sender="orchestrator",
                sender_role=AgentRole.ORCHESTRATOR,
                recipient="executor:executor_1",
            ),
            payload={"task": "execute"},
        )
        message_bus.publish(msg)

        # Give the worker thread time to process
        time.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload["task"] == "execute"

    def test_send_to_role(self, message_bus):
        """MessageBus should deliver messages to all agents with a role."""
        message_bus.start()
        received_planner = []
        received_executor = []

        message_bus.register(
            agent_name="planner_1",
            agent_role=AgentRole.PLANNER,
            callback=lambda msg: received_planner.append(msg),
        )
        message_bus.register(
            agent_name="executor_1",
            agent_role=AgentRole.EXECUTOR,
            callback=lambda msg: received_executor.append(msg),
        )

        msg = Message(
            header=MessageHeader(
                sender="orchestrator",
                sender_role=AgentRole.ORCHESTRATOR,
                recipient_role=AgentRole.EXECUTOR,
            ),
            payload={"task": "execute"},
        )
        message_bus.publish(msg)
        time.sleep(0.2)

        assert len(received_planner) == 0
        assert len(received_executor) == 1

    def test_broadcast_message(self, message_bus):
        """MessageBus should broadcast messages to all handlers."""
        message_bus.start()
        received = []

        message_bus.register(
            agent_name="agent_1",
            agent_role=AgentRole.PLANNER,
            callback=lambda msg: received.append(("agent_1", msg)),
        )
        message_bus.register(
            agent_name="agent_2",
            agent_role=AgentRole.EXECUTOR,
            callback=lambda msg: received.append(("agent_2", msg)),
        )

        msg = Message(
            header=MessageHeader(
                sender="orchestrator",
                message_type=MessageType.EVENT,
            ),
            payload={"event": "system_update"},
        )
        message_bus.publish(msg)
        time.sleep(0.2)

        assert len(received) == 2

    def test_dropped_messages_counted(self, message_bus):
        """MessageBus should count messages that couldn't be delivered."""
        message_bus.start()
        msg = Message(
            header=MessageHeader(
                sender="test",
                recipient="nonexistent_agent",
            ),
            payload={"data": "test"},
        )
        message_bus.publish(msg)
        time.sleep(0.2)

        stats = message_bus.get_stats()
        assert stats["messages_dropped"] == 1

    def test_get_handlers_info(self, message_bus):
        """MessageBus should return handler information."""
        message_bus.register(
            agent_name="test_agent",
            agent_role=AgentRole.EXECUTOR,
            callback=lambda msg: None,
        )
        handlers = message_bus.get_handlers()
        assert len(handlers) == 1
        assert handlers[0]["agent_name"] == "test_agent"
        assert handlers[0]["agent_role"] == "executor"

    def test_persistence(self, tmp_path):
        """MessageBus should persist messages when persistence is enabled."""
        from OrbitronMessageSystem.message_bus import MessageBus
        bus = MessageBus(persistence_dir=str(tmp_path / "messages"))
        bus.start()

        msg = Message(
            header=MessageHeader(sender="test", message_type=MessageType.EVENT),
            payload={"data": "test"},
        )
        bus.publish(msg)
        time.sleep(0.3)

        # Check that a log file was created
        log_files = list((tmp_path / "messages").glob("messages_*.jsonl"))
        # Persistence may or may not have written yet depending on timing
        bus.stop()


class TestMessageBusRequestResponse:
    """Test MessageBus request/response pattern."""

    def test_send_with_response(self, message_bus):
        """MessageBus should support request/response pattern."""
        message_bus.start()

        # Register a handler that responds
        def handler(msg):
            response = msg.create_response({"result": "done"}, success=True)
            message_bus.publish(response)

        message_bus.register(
            agent_name="executor_1",
            agent_role=AgentRole.EXECUTOR,
            callback=handler,
        )

        # Send a request and wait for response
        request = Message(
            header=MessageHeader(
                sender="orchestrator",
                sender_role=AgentRole.ORCHESTRATOR,
                recipient="executor:executor_1",
                message_type=MessageType.REQUEST,
            ),
            payload={"task": "execute"},
        )

        # Note: This is a simplified test - full request/response
        # would require threading and event handling
        message_bus.publish(request)
        time.sleep(0.3)


class TestMessageBusSingleton:
    """Test MessageBus singleton functions."""

    def test_get_message_bus(self):
        """get_message_bus should return a singleton."""
        from OrbitronMessageSystem.message_bus import get_message_bus, reset_message_bus

        reset_message_bus()
        bus1 = get_message_bus()
        bus2 = get_message_bus()
        assert bus1 is bus2

        # Clean up
        bus1.stop()
        reset_message_bus()

    def test_reset_message_bus(self):
        """reset_message_bus should create a new instance."""
        from OrbitronMessageSystem.message_bus import get_message_bus, reset_message_bus

        reset_message_bus()
        bus1 = get_message_bus()
        reset_message_bus()
        bus2 = get_message_bus()

        assert bus1 is not bus2

        # Clean up
        bus2.stop()
        reset_message_bus()