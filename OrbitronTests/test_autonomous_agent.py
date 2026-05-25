"""Unit tests for AutonomousAgent module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from OrbitronAgents.base.autonomous_agent import AutonomousAgent, AgentLoopResult
from OrbitronAgents.base.agent_tools import ToolDefinition, ToolResult


class TestAgentLoopResult:
    """Test AgentLoopResult dataclass."""

    def test_default_values(self):
        """AgentLoopResult should have sensible defaults."""
        result = AgentLoopResult()
        assert result.content == ""
        assert result.done is False
        assert result.terminal_tool is None
        assert result.tool_calls_made == 0
        assert result.rounds_used == 0
        assert result.file_operations == []

    def test_to_dict(self):
        """AgentLoopResult.to_dict should serialize all fields."""
        result = AgentLoopResult(
            content="Test result",
            done=True,
            terminal_tool="submit_result",
            tool_calls_made=5,
            rounds_used=10,
        )
        d = result.to_dict()
        assert d["content"] == "Test result"
        assert d["done"] is True
        assert d["terminal_tool"] == "submit_result"
        assert d["tool_calls_made"] == 5
        assert d["rounds_used"] == 10


class TestAutonomousAgentInit:
    """Test AutonomousAgent initialization."""

    def test_basic_initialization(self, mock_kernel):
        """AutonomousAgent should initialize with required parameters."""
        agent = AutonomousAgent(
            agent_name="test_agent",
            system_prompt="You are a test agent.",
            kernel=mock_kernel,
        )
        assert agent.agent_name == "test_agent"
        assert agent.system_prompt == "You are a test agent."
        assert agent.kernel == mock_kernel
        assert agent.max_rounds == 40  # default

    def test_custom_max_rounds(self, mock_kernel):
        """AutonomousAgent should accept custom max_rounds."""
        agent = AutonomousAgent(
            agent_name="test_agent",
            system_prompt="Test",
            kernel=mock_kernel,
            max_rounds=20,
        )
        assert agent.max_rounds == 20

    def test_progress_callback(self, mock_kernel):
        """AutonomousAgent should accept progress callback."""
        callback = MagicMock()
        agent = AutonomousAgent(
            agent_name="test_agent",
            system_prompt="Test",
            kernel=mock_kernel,
            on_progress=callback,
        )
        assert agent._on_progress == callback


class TestAutonomousAgentTools:
    """Test AutonomousAgent tool management."""

    def test_register_tool(self, autonomous_agent):
        """register_tool should add tool to the agent."""
        autonomous_agent.register_tool(
            name="test_tool",
            description="A test tool",
            schema={"type": "object", "properties": {"input": {"type": "string"}}},
            handler=lambda args: args.get("input", "default"),
        )
        assert "test_tool" in autonomous_agent._tools
        assert "test_tool" in autonomous_agent._handlers

    def test_get_tool_definitions(self, autonomous_agent):
        """get_tool_definitions should return Ollama-format tool schemas."""
        autonomous_agent.register_tool(
            name="test_tool",
            description="A test tool",
            schema={"type": "object", "properties": {"input": {"type": "string"}}},
            handler=lambda args: "ok",
        )
        defs = autonomous_agent.get_tool_definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "test_tool"

    def test_execute_tool_success(self, autonomous_agent):
        """execute_tool should call handler and return ToolResult."""
        autonomous_agent.register_tool(
            name="echo",
            description="Echo input",
            schema={"type": "object"},
            handler=lambda args: args.get("text", ""),
        )
        result = autonomous_agent.execute_tool("echo", {"text": "hello"})
        assert result.success is True
        assert result.result == "hello"

    def test_execute_tool_unknown(self, autonomous_agent):
        """execute_tool should return error for unknown tools."""
        result = autonomous_agent.execute_tool("nonexistent", {})
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_execute_tool_exception(self, autonomous_agent):
        """execute_tool should catch handler exceptions."""
        autonomous_agent.register_tool(
            name="failing",
            description="Always fails",
            schema={"type": "object"},
            handler=lambda args: 1 / 0,
        )
        result = autonomous_agent.execute_tool("failing", {})
        assert result.success is False
        assert "ZeroDivisionError" in result.error or "division" in result.error.lower()


class TestAutonomousAgentParseToolCall:
    """Test AutonomousAgent tool call parsing."""

    def test_parse_valid_tool_call(self, autonomous_agent):
        """_parse_tool_call should extract name and args."""
        call = {
            "function": {
                "name": "create_file",
                "arguments": {"path": "test.txt", "content": "Hello"},
            }
        }
        name, args = autonomous_agent._parse_tool_call(call)
        assert name == "create_file"
        assert args == {"path": "test.txt", "content": "Hello"}

    def test_parse_tool_call_missing_name(self, autonomous_agent):
        """_parse_tool_call should handle missing tool name."""
        call = {"function": {}}
        name, args = autonomous_agent._parse_tool_call(call)
        assert name == "unknown_tool"

    def test_parse_tool_call_missing_args(self, autonomous_agent):
        """_parse_tool_call should default to empty args."""
        call = {"function": {"name": "test_tool"}}
        name, args = autonomous_agent._parse_tool_call(call)
        assert name == "test_tool"
        assert args == {}

    def test_parse_tool_call_non_dict_args(self, autonomous_agent):
        """_parse_tool_call should handle non-dict arguments."""
        call = {"function": {"name": "test_tool", "arguments": "invalid"}}
        name, args = autonomous_agent._parse_tool_call(call)
        assert name == "test_tool"
        assert "error" in args


class TestAutonomousAgentTerminalTools:
    """Test AutonomousAgent terminal tool detection."""

    def test_terminal_tools(self, autonomous_agent):
        """Known terminal tools should be detected."""
        assert autonomous_agent._is_terminal_tool("submit_plan") is True
        assert autonomous_agent._is_terminal_tool("submit_result") is True
        assert autonomous_agent._is_terminal_tool("ask_question") is True
        assert autonomous_agent._is_terminal_tool("terminate") is True

    def test_non_terminal_tools(self, autonomous_agent):
        """Non-terminal tools should not be detected."""
        assert autonomous_agent._is_terminal_tool("read_file") is False
        assert autonomous_agent._is_terminal_tool("create_file") is False
        assert autonomous_agent._is_terminal_tool("run_command") is False


class TestAutonomousAgentFormatResult:
    """Test AutonomousAgent result formatting."""

    def test_format_successful_result(self, autonomous_agent):
        """_format_tool_result should format successful results."""
        result = ToolResult(success=True, result={"data": "test"})
        formatted = autonomous_agent._format_tool_result("test_tool", result)
        parsed = json.loads(formatted)
        assert parsed["success"] is True
        assert parsed["result"]["data"] == "test"

    def test_format_error_result(self, autonomous_agent):
        """_format_tool_result should format error results."""
        result = ToolResult(success=False, error="Something went wrong")
        formatted = autonomous_agent._format_tool_result("test_tool", result)
        parsed = json.loads(formatted)
        assert parsed["success"] is False
        assert parsed["error"] == "Something went wrong"

    def test_format_truncates_large_result(self, autonomous_agent):
        """_format_tool_result should truncate very large results."""
        large_result = "x" * (autonomous_agent.MAX_TOOL_RESULT_CHARS + 1000)
        result = ToolResult(success=True, result=large_result)
        formatted = autonomous_agent._format_tool_result("test_tool", result)
        assert len(formatted) <= autonomous_agent.MAX_TOOL_RESULT_CHARS + 200  # Allow some overhead

    def test_format_command_result_larger_limit(self, autonomous_agent):
        """_format_tool_result should use larger limit for command results."""
        # Command results should use MAX_COMMAND_OUTPUT_CHARS instead of MAX_TOOL_RESULT_CHARS
        assert autonomous_agent.MAX_COMMAND_OUTPUT_CHARS > autonomous_agent.MAX_TOOL_RESULT_CHARS


class TestAutonomousAgentTrimMessages:
    """Test AutonomousAgent message trimming."""

    def test_trim_short_history(self, autonomous_agent):
        """_trim_messages should not trim short histories."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        original_len = len(messages)
        autonomous_agent._trim_messages(messages)
        assert len(messages) == original_len

    def test_trim_long_history(self, autonomous_agent):
        """_trim_messages should trim long histories."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]
        # Add many tool call messages
        for i in range(60):
            messages.append({"role": "assistant", "content": f"Response {i}"})
            messages.append({"role": "tool", "tool_name": "read_file", "content": f"Result {i}"})

        autonomous_agent._trim_messages(messages)
        # Should be trimmed to a reasonable size
        assert len(messages) < 70  # Was 122 before trimming