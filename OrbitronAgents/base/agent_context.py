"""Context management for Orbitron agents."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("AgentContext")


class ContextScope(Enum):
    """Scope levels for context data."""
    GLOBAL = auto()      # Shared across all agents
    AGENT = auto()       # Specific to one agent
    TASK = auto()        # Specific to one task (temporary)
    SESSION = auto()     # User session context


@dataclass
class ContextEntry:
    """A single context entry with metadata."""
    key: str
    value: Any
    scope: ContextScope
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    access_count: int = 0

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def touch(self) -> None:
        """Update access time and count."""
        self.access_count += 1
        self.updated_at = datetime.now()


class AgentContext:
    """Context manager for agent data.

    Provides:
    - Scoped context storage (global, agent, task, session)
    - Automatic expiration of temporary data
    - Persistence to disk for long-term memory
    - Size limits to prevent bloat
    """

    MAX_STRING_LENGTH = 1000  # Max chars per string value
    MAX_ENTRIES_PER_SCOPE = 100  # Max entries per scope

    def __init__(
        self,
        agent_name: str,
        persistence_dir: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.persistence_dir = Path(persistence_dir) if persistence_dir else Path.home() / ".orbitron" / "context"
        self.persistence_dir.mkdir(parents=True, exist_ok=True)

        self._entries: dict[str, ContextEntry] = {}
        self._lock = None  # Could add threading.Lock if needed

        self._load_persistent_context()

    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize value for storage (prevent bloat)."""
        if isinstance(value, str):
            if len(value) > self.MAX_STRING_LENGTH:
                return value[:self.MAX_STRING_LENGTH] + "...[truncated]"
            return value
        elif isinstance(value, (dict, list)):
            # Truncate large collections
            try:
                serialized = json.dumps(value, ensure_ascii=False)
                if len(serialized) > self.MAX_STRING_LENGTH * 2:
                    # Too large, store a summary instead
                    if isinstance(value, dict):
                        return {"_truncated": True, "keys": list(value.keys())[:10]}
                    else:
                        return {"_truncated": True, "items_count": len(value)}
            except (TypeError, ValueError):
                pass
            return value
        return value

    def set(
        self,
        key: str,
        value: Any,
        scope: ContextScope = ContextScope.AGENT,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Set a context value."""
        sanitized = self._sanitize_value(value)

        now = datetime.now()
        expires_at = None
        if ttl_seconds is not None:
            from datetime import timedelta
            expires_at = now + timedelta(seconds=ttl_seconds)

        if key in self._entries:
            # Update existing
            entry = self._entries[key]
            entry.value = sanitized
            entry.updated_at = now
            entry.expires_at = expires_at
        else:
            # Check scope limit
            scope_count = sum(1 for e in self._entries.values() if e.scope == scope)
            if scope_count >= self.MAX_ENTRIES_PER_SCOPE:
                # Remove oldest entry in this scope
                oldest_key = min(
                    (k for k, e in self._entries.items() if e.scope == scope),
                    key=lambda k: self._entries[k].updated_at,
                )
                del self._entries[oldest_key]

            # Create new
            self._entries[key] = ContextEntry(
                key=key,
                value=sanitized,
                scope=scope,
                expires_at=expires_at,
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        if key not in self._entries:
            return default

        entry = self._entries[key]
        if entry.is_expired():
            del self._entries[key]
            return default

        entry.touch()
        return entry.value

    def delete(self, key: str) -> bool:
        """Delete a context value."""
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def clear_scope(self, scope: ContextScope) -> int:
        """Clear all entries in a scope. Returns count of cleared entries."""
        keys_to_delete = [k for k, e in self._entries.items() if e.scope == scope]
        for key in keys_to_delete:
            del self._entries[key]
        return len(keys_to_delete)

    def clear_task_context(self) -> int:
        """Clear task-scoped context (called after task completion)."""
        return self.clear_scope(ContextScope.TASK)

    def get_all(self, scope: Optional[ContextScope] = None) -> dict[str, Any]:
        """Get all context values, optionally filtered by scope."""
        result = {}
        for key, entry in self._entries.items():
            if not entry.is_expired():
                if scope is None or entry.scope == scope:
                    result[key] = entry.value
        return result

    def keys(self, scope: Optional[ContextScope] = None) -> list[str]:
        """List all context keys, optionally filtered by scope."""
        return [
            k for k, e in self._entries.items()
            if not e.is_expired() and (scope is None or e.scope == scope)
        ]

    def garbage_collect(self) -> int:
        """Remove all expired entries from the context.
        
        Unlike get() which only removes entries on access, this method
        proactively scans and removes all expired entries.
        
        Returns:
            Number of entries removed.
        """
        expired_keys = [k for k, e in self._entries.items() if e.is_expired()]
        for key in expired_keys:
            del self._entries[key]
        if expired_keys:
            logger.info("[AgentContext] Garbage collected %d expired entries for %s", 
                       len(expired_keys), self.agent_name)
        return len(expired_keys)

    # ========== Persistence ==========

    def _load_persistent_context(self) -> None:
        """Load persistent context from disk."""
        persist_file = self.persistence_dir / f"{self.agent_name}_context.json"
        if not persist_file.exists():
            return

        try:
            with open(persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, entry_data in data.items():
                # Only restore AGENT and GLOBAL scope (not TASK)
                scope_name = entry_data.get("scope", "AGENT")
                try:
                    scope = ContextScope[scope_name]
                except KeyError:
                    scope = ContextScope.AGENT

                if scope in (ContextScope.AGENT, ContextScope.GLOBAL):
                    self._entries[key] = ContextEntry(
                        key=key,
                        value=entry_data.get("value"),
                        scope=scope,
                        created_at=datetime.fromisoformat(entry_data.get("created_at", datetime.now().isoformat())),
                        updated_at=datetime.fromisoformat(entry_data.get("updated_at", datetime.now().isoformat())),
                    )
        except Exception as e:
            # Silently ignore load errors, start fresh
            pass

    def save_persistent_context(self) -> None:
        """Save persistent context to disk."""
        persist_file = self.persistence_dir / f"{self.agent_name}_context.json"

        data = {}
        for key, entry in self._entries.items():
            if entry.scope in (ContextScope.AGENT, ContextScope.GLOBAL) and not entry.is_expired():
                data[key] = {
                    "key": entry.key,
                    "value": entry.value,
                    "scope": entry.scope.name,
                    "created_at": entry.created_at.isoformat(),
                    "updated_at": entry.updated_at.isoformat(),
                }

        try:
            with open(persist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            pass  # Silently ignore save errors

    # ========== Utilities ==========

    def get_summary(self) -> str:
        """Get a human-readable summary of context."""
        lines = [f"Context for {self.agent_name}:"]

        for scope in ContextScope:
            entries = [k for k, e in self._entries.items() if e.scope == scope and not e.is_expired()]
            if entries:
                lines.append(f"  {scope.name}: {len(entries)} entries")

        return "\n".join(lines)

    def __len__(self) -> int:
        """Get number of non-expired entries."""
        return sum(1 for e in self._entries.values() if not e.is_expired())
