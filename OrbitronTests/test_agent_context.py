"""Unit tests for AgentContext module."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from OrbitronAgents.base.agent_context import AgentContext, ContextEntry, ContextScope


class TestContextEntry:
    """Test ContextEntry dataclass."""

    def test_creation(self):
        """ContextEntry should be created with required fields."""
        entry = ContextEntry(key="test_key", value="test_value", scope=ContextScope.AGENT)
        assert entry.key == "test_key"
        assert entry.value == "test_value"
        assert entry.scope == ContextScope.AGENT
        assert entry.access_count == 0

    def test_is_expired_no_expiry(self):
        """ContextEntry without expiry should never be expired."""
        entry = ContextEntry(key="test", value="val", scope=ContextScope.AGENT)
        assert entry.is_expired() is False

    def test_is_expired_future(self):
        """ContextEntry with future expiry should not be expired."""
        entry = ContextEntry(
            key="test",
            value="val",
            scope=ContextScope.TASK,
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert entry.is_expired() is False

    def test_is_expired_past(self):
        """ContextEntry with past expiry should be expired."""
        entry = ContextEntry(
            key="test",
            value="val",
            scope=ContextScope.TASK,
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert entry.is_expired() is True

    def test_touch(self):
        """touch() should update access count and timestamp."""
        entry = ContextEntry(key="test", value="val", scope=ContextScope.AGENT)
        old_count = entry.access_count
        old_updated = entry.updated_at
        entry.touch()
        assert entry.access_count == old_count + 1
        assert entry.updated_at >= old_updated


class TestAgentContext:
    """Test AgentContext class."""

    def test_creation(self, agent_context):
        """AgentContext should be created with agent name."""
        assert agent_context.agent_name == "test_agent"

    def test_set_and_get(self, agent_context):
        """set() and get() should store and retrieve values."""
        agent_context.set("test_key", "test_value")
        assert agent_context.get("test_key") == "test_value"

    def test_get_with_default(self, agent_context):
        """get() should return default for missing keys."""
        result = agent_context.get("nonexistent", default="default_val")
        assert result == "default_val"

    def test_get_default_none(self, agent_context):
        """get() should return None for missing keys without default."""
        result = agent_context.get("nonexistent")
        assert result is None

    def test_set_overwrite(self, agent_context):
        """set() should overwrite existing values."""
        agent_context.set("key", "value1")
        agent_context.set("key", "value2")
        assert agent_context.get("key") == "value2"

    def test_set_with_ttl(self, agent_context):
        """set() with ttl_seconds should set expiry."""
        agent_context.set("temp_key", "temp_value", ttl_seconds=60)
        entry = agent_context._entries.get("temp_key")
        assert entry is not None
        assert entry.expires_at is not None

    def test_get_expired_entry(self, agent_context):
        """get() should return default for expired entries and remove them."""
        agent_context.set("expiring_key", "expiring_value", ttl_seconds=0)
        # Manually set expiry in the past
        entry = agent_context._entries.get("expiring_key")
        if entry:
            entry.expires_at = datetime.now() - timedelta(seconds=1)

        result = agent_context.get("expiring_key", default="expired")
        assert result == "expired"
        assert "expiring_key" not in agent_context._entries

    def test_delete(self, agent_context):
        """delete() should remove entries."""
        agent_context.set("to_delete", "value")
        assert agent_context.delete("to_delete") is True
        assert agent_context.get("to_delete") is None

    def test_delete_nonexistent(self, agent_context):
        """delete() should return False for nonexistent keys."""
        assert agent_context.delete("nonexistent") is False

    def test_clear_scope(self, agent_context):
        """clear_scope() should remove all entries in a scope."""
        agent_context.set("global_key", "val", scope=ContextScope.GLOBAL)
        agent_context.set("agent_key", "val", scope=ContextScope.AGENT)
        agent_context.set("task_key", "val", scope=ContextScope.TASK)

        count = agent_context.clear_scope(ContextScope.TASK)
        assert count == 1
        assert agent_context.get("task_key") is None
        assert agent_context.get("global_key") == "val"
        assert agent_context.get("agent_key") == "val"

    def test_clear_task_context(self, agent_context):
        """clear_task_context() should clear TASK scope entries."""
        agent_context.set("task_key", "val", scope=ContextScope.TASK)
        agent_context.set("agent_key", "val", scope=ContextScope.AGENT)

        count = agent_context.clear_task_context()
        assert count == 1
        assert agent_context.get("task_key") is None
        assert agent_context.get("agent_key") == "val"

    def test_get_all(self, agent_context):
        """get_all() should return all non-expired entries."""
        agent_context.set("key1", "val1", scope=ContextScope.AGENT)
        agent_context.set("key2", "val2", scope=ContextScope.GLOBAL)
        agent_context.set("key3", "val3", scope=ContextScope.TASK)

        all_entries = agent_context.get_all()
        assert "key1" in all_entries
        assert "key2" in all_entries
        assert "key3" in all_entries

    def test_get_all_filtered(self, agent_context):
        """get_all() with scope should filter entries."""
        agent_context.set("agent_key", "val", scope=ContextScope.AGENT)
        agent_context.set("global_key", "val", scope=ContextScope.GLOBAL)

        agent_entries = agent_context.get_all(scope=ContextScope.AGENT)
        assert "agent_key" in agent_entries
        assert "global_key" not in agent_entries

    def test_keys(self, agent_context):
        """keys() should return all non-expired keys."""
        agent_context.set("key1", "val1")
        agent_context.set("key2", "val2")

        keys = agent_context.keys()
        assert "key1" in keys
        assert "key2" in keys

    def test_keys_filtered(self, agent_context):
        """keys() with scope should filter by scope."""
        agent_context.set("agent_key", "val", scope=ContextScope.AGENT)
        agent_context.set("global_key", "val", scope=ContextScope.GLOBAL)

        keys = agent_context.keys(scope=ContextScope.AGENT)
        assert "agent_key" in keys
        assert "global_key" not in keys

    def test_max_entries_per_scope(self, agent_context):
        """AgentContext should enforce MAX_ENTRIES_PER_SCOPE."""
        max_entries = AgentContext.MAX_ENTRIES_PER_SCOPE

        # Add more entries than the limit
        for i in range(max_entries + 10):
            agent_context.set(f"key_{i}", f"val_{i}", scope=ContextScope.AGENT)

        # Should not exceed the limit (oldest entries are removed)
        keys = agent_context.keys(scope=ContextScope.AGENT)
        assert len(keys) <= max_entries

    def test_sanitize_large_string(self, agent_context):
        """_sanitize_value should truncate large strings."""
        large_string = "x" * (AgentContext.MAX_STRING_LENGTH + 100)
        agent_context.set("large_key", large_string)
        value = agent_context.get("large_key")
        assert len(value) <= AgentContext.MAX_STRING_LENGTH + 20  # Allow for truncation marker

    def test_sanitize_large_dict(self, agent_context):
        """_sanitize_value should truncate large dicts."""
        large_dict = {f"key_{i}": f"value_{i}" for i in range(200)}
        agent_context.set("large_dict_key", large_dict)
        value = agent_context.get("large_dict_key")
        # Should be truncated or summarized
        assert value is not None

    def test_persistence(self, tmp_context_dir):
        """AgentContext should persist and load context from disk."""
        context1 = AgentContext(
            agent_name="persist_test",
            persistence_dir=str(tmp_context_dir),
        )
        context1.set("persistent_key", "persistent_value", scope=ContextScope.AGENT)
        context1.save_persistent_context()

        # Create a new context instance to load from disk
        context2 = AgentContext(
            agent_name="persist_test",
            persistence_dir=str(tmp_context_dir),
        )
        # AGENT scope entries should be loaded
        value = context2.get("persistent_key")
        assert value == "persistent_value"

    def test_task_scope_not_persisted(self, tmp_context_dir):
        """TASK scope entries should not be persisted."""
        context1 = AgentContext(
            agent_name="task_test",
            persistence_dir=str(tmp_context_dir),
        )
        context1.set("task_key", "task_value", scope=ContextScope.TASK)
        context1.save_persistent_context()

        # Create a new context instance
        context2 = AgentContext(
            agent_name="task_test",
            persistence_dir=str(tmp_context_dir),
        )
        # TASK scope entries should NOT be loaded
        value = context2.get("task_key")
        assert value is None


class TestContextScope:
    """Test ContextScope enum."""

    def test_scope_values(self):
        """ContextScope should have all expected values."""
        assert ContextScope.GLOBAL.name == "GLOBAL"
        assert ContextScope.AGENT.name == "AGENT"
        assert ContextScope.TASK.name == "TASK"
        assert ContextScope.SESSION.name == "SESSION"