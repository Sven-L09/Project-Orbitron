"""Shared pytest fixtures for Orbitron tests."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to sys.path so imports work
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ========== Directory Fixtures ==========

@pytest.fixture
def tmp_workspace(tmp_path):
    """Provide a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provide a temporary config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def tmp_sessions_dir(tmp_path):
    """Provide a temporary sessions directory."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return sessions_dir


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Provide a temporary memory directory."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return memory_dir


@pytest.fixture
def tmp_context_dir(tmp_path):
    """Provide a temporary context directory."""
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    return context_dir


# ========== Environment Fixtures ==========

@pytest.fixture(autouse=True)
def clean_env():
    """Ensure no leftover env vars from other tests."""
    # Save env vars that might be set
    saved_env = {}
    orbitron_vars = [k for k in os.environ if k.startswith("ORBITRON_") or k.startswith("OLLAMA_")]
    for key in orbitron_vars:
        saved_env[key] = os.environ.pop(key, None)

    yield

    # Restore env vars
    for key, value in saved_env.items():
        if value is not None:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


@pytest.fixture
def env_with_dotenv(tmp_path):
    """Create a .env file in tmp_path and set up environment."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OLLAMA_API_KEY=test-key\n"
        "GOOGLE_CALENDAR_API_KEY=test-cal-key\n"
        "TELEGRAM_BOT_TOKEN=test-telegram-token\n"
    )
    return env_file


# ========== Kernel Fixtures ==========

@pytest.fixture
def mock_ollama_response():
    """Create a mock Ollama API response."""
    def _make_response(content="Test response", tool_calls=None, done=True):
        msg = {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls or [],
            "done": done,
        }
        return {"message": msg, "done": done}

    return _make_response


@pytest.fixture
def mock_ollama_connector():
    """Create a mock OllamaConnector."""
    connector = MagicMock()
    connector.base_url = "https://test-ollama.example.com"
    connector.model = "test-model"
    connector.chat = MagicMock(return_value={
        "message": {"role": "assistant", "content": "Test response", "tool_calls": []},
        "done": True,
    })
    connector.generate_response = MagicMock(return_value="Test response")
    return connector


@pytest.fixture
def mock_kernel(tmp_workspace, mock_ollama_connector):
    """Create a mock OrbitronKernel with common dependencies mocked."""
    with patch("OrbitronKernel.kernel.OllamaConnector", return_value=mock_ollama_connector):
        with patch("OrbitronKernel.kernel.Config") as MockConfig:
            mock_config = MagicMock()
            mock_config.get.side_effect = lambda key, default=None: {
                "kernel.workspace": str(tmp_workspace),
                "kernel.sessions_dir": str(tmp_workspace / "sessions"),
                "kernel.profiles_dir": str(tmp_workspace / "profiles"),
                "ollama.base_url": "https://test-ollama.example.com",
                "ollama.model": "test-model",
                "ollama.api_key": "test-key",
            }.get(key, default)
            MockConfig.return_value = mock_config

            from OrbitronKernel.kernel import OrbitronKernel
            kernel = OrbitronKernel(config_path=str(tmp_workspace / "config.json"))
            return kernel


# ========== FileOperations Fixtures ==========

@pytest.fixture
def file_ops(tmp_workspace):
    """Create a FileOperations instance with a temporary workspace."""
    from OrbitronKernel.file_operations import FileOperations
    ops = FileOperations(workspace=str(tmp_workspace))
    return ops


@pytest.fixture
def populated_workspace(file_ops):
    """Create a FileOperations instance with some pre-populated files."""
    # Create some test files
    file_ops.write_file("test.txt", "Hello, World!")
    file_ops.write_file("subdir/nested.txt", "Nested content")
    file_ops.write_file("code.py", "print('hello')")
    file_ops.create_directory("empty_dir")
    return file_ops


# ========== MessageBus Fixtures ==========

@pytest.fixture
def message_bus(tmp_path):
    """Create a MessageBus instance with a temporary persistence directory."""
    from OrbitronMessageSystem.message_bus import MessageBus
    from OrbitronMessageSystem.message_types import AgentRole

    bus = MessageBus(persistence_dir=str(tmp_path / "messages"))
    yield bus
    bus.stop()


@pytest.fixture
def registered_handler(message_bus):
    """Register a test handler on the message bus."""
    from OrbitronMessageSystem.message_types import AgentRole, MessageType

    received_messages = []

    def handler(message):
        received_messages.append(message)

    handler_id = message_bus.register(
        agent_name="test_agent",
        agent_role=AgentRole.EXECUTOR,
        callback=handler,
    )

    return handler_id, received_messages


# ========== AgentContext Fixtures ==========

@pytest.fixture
def agent_context(tmp_context_dir):
    """Create an AgentContext instance with a temporary directory."""
    from OrbitronAgents.base.agent_context import AgentContext, ContextScope
    context = AgentContext(
        agent_name="test_agent",
        persistence_dir=str(tmp_context_dir),
    )
    return context


# ========== AutonomousAgent Fixtures ==========

@pytest.fixture
def autonomous_agent(mock_kernel):
    """Create an AutonomousAgent with a mock kernel."""
    from OrbitronAgents.base.autonomous_agent import AutonomousAgent

    agent = AutonomousAgent(
        agent_name="test_agent",
        system_prompt="You are a test agent.",
        kernel=mock_kernel,
        max_rounds=5,
    )
    return agent


# ========== Sample Data Fixtures ==========

@pytest.fixture
def sample_messages():
    """Create sample message history for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]


@pytest.fixture
def sample_plan():
    """Create a sample plan for testing."""
    return {
        "plan_id": "test-plan-001",
        "title": "Test Plan",
        "description": "A test plan for unit testing",
        "steps": [
            {"id": "step-1", "description": "First step", "priority": "high"},
            {"id": "step-2", "description": "Second step", "priority": "medium"},
        ],
        "status": "active",
    }


@pytest.fixture
def sample_task_result():
    """Create a sample task result for testing."""
    return {
        "success": True,
        "summary": "Task completed successfully",
        "artifacts": ["output.txt", "report.docx"],
        "duration_seconds": 42.5,
        "iterations": 2,
    }


# ========== TimeoutManager Fixtures ==========

@pytest.fixture
def timeout_manager(tmp_path):
    """Create a TimeoutManager instance with a temporary profiles directory."""
    from OrbitronKernel.timeout_manager import TimeoutManager
    manager = TimeoutManager(profiles_dir=str(tmp_path / "profiles"))
    return manager


# ========== Config Fixtures ==========

@pytest.fixture
def config(tmp_path):
    """Create a Config instance with a temporary config file."""
    from OrbitronKernel.config import Config
    config_path = str(tmp_path / "test_config.json")
    cfg = Config(config_path=config_path)
    return cfg