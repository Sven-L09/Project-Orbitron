"""Orbitron Orchestrator - A living agent with personality and context."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class ContextLoader:
    """Loads and manages context files (IDENTITY, SOUL, USER)."""
    
    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = Path(workspace_root) if workspace_root else Path(__file__).resolve().parents[2]
        self._cache: dict[str, str] = {}
        self._last_modified: dict[str, float] = {}
    
    def load_file(self, filename: str) -> str:
        """Load a markdown file, with caching based on modification time."""
        filepath = self.workspace_root / filename
        
        if not filepath.exists():
            return f"# {filename}\n\n[File not found]"
        
        try:
            current_mtime = filepath.stat().st_mtime
            
            # Return cached version if file hasn't changed
            if filename in self._cache and self._last_modified.get(filename) == current_mtime:
                return self._cache[filename]
            
            # Load and cache
            content = filepath.read_text(encoding="utf-8")
            self._cache[filename] = content
            self._last_modified[filename] = current_mtime
            
            return content
        except Exception as e:
            return f"# {filename}\n\n[Error loading file: {e}]"
    
    def get_identity(self) -> str:
        """Load IDENTITY.md."""
        return self.load_file("IDENTITY.md")
    
    def get_soul(self) -> str:
        """Load SOUL.md."""
        return self.load_file("SOUL.md")
    
    def get_user(self) -> str:
        """Load USER.md."""
        return self.load_file("USER.md")
    
    def get_full_context(self) -> str:
        """Combine all context files into a single system prompt."""
        identity = self.get_identity()
        soul = self.get_soul()
        user = self.get_user()
        
        return f"""{identity}

---

{soul}

---

{user}

---

## Current Session
Current Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}
"""


class MemoryStore:
    """Simple memory store for conversation history and learned facts."""
    
    def __init__(self, memory_dir: str | None = None):
        self.memory_dir = Path(memory_dir) if memory_dir else Path.home() / ".orbitron" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.short_term: list[dict[str, Any]] = []  # Current session
        self._load_long_term()
    
    def _load_long_term(self) -> None:
        """Load long-term memory from disk."""
        memory_file = self.memory_dir / "facts.json"
        if memory_file.exists():
            try:
                with open(memory_file, "r", encoding="utf-8") as f:
                    self.long_term: dict[str, Any] = json.load(f)
            except Exception:
                self.long_term = {}
        else:
            self.long_term = {}
    
    def save_long_term(self) -> None:
        """Save long-term memory to disk."""
        memory_file = self.memory_dir / "facts.json"
        try:
            with open(memory_file, "w", encoding="utf-8") as f:
                json.dump(self.long_term, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[MemoryStore] Error saving memory: {e}")
    
    def add_to_short_term(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Add an entry to short-term memory."""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            entry["metadata"] = metadata
        self.short_term.append(entry)
        
        # Keep short-term memory manageable (last 50 entries)
        if len(self.short_term) > 50:
            self.short_term = self.short_term[-50:]
    
    def remember(self, key: str, value: Any) -> None:
        """Store a fact in long-term memory."""
        self.long_term[key] = {
            "value": value,
            "updated": datetime.now().isoformat()
        }
        self.save_long_term()
    
    def recall(self, key: str) -> Any | None:
        """Recall a fact from long-term memory."""
        if key in self.long_term:
            return self.long_term[key]["value"]
        return None
    
    def get_recent_context(self, n: int = 10) -> str:
        """Get recent conversation context as formatted string."""
        recent = self.short_term[-n:] if len(self.short_term) > n else self.short_term
        lines = []
        for entry in recent:
            role = entry["role"].upper()
            content = entry["content"][:200]  # Truncate long messages
            if len(entry["content"]) > 200:
                content += "..."
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)


class Orchestrator:
    """Orbitron Orchestrator - The living agent that coordinates and thinks."""
    
    def __init__(self, kernel=None, workspace_root: str | None = None):
        """Initialize the Orchestrator with context and memory."""
        self.kernel = kernel
        self.context_loader = ContextLoader(workspace_root)
        self.memory = MemoryStore()
        
        # Load initial context
        self._system_context = self._build_system_context()
        
        print("[Orchestrator] Initialized with personality and context")
        print(f"[Orchestrator] Workspace: {self.context_loader.workspace_root}")
    
    def _build_system_context(self) -> str:
        """Build the complete system context for the LLM."""
        base_context = self.context_loader.get_full_context()
        
        # Add any learned preferences from memory
        learned = self._get_learned_preferences()
        if learned:
            base_context += f"\n\n## Learned Preferences\n{learned}\n"
        
        return base_context
    
    def _get_learned_preferences(self) -> str:
        """Get learned preferences from long-term memory."""
        prefs = []
        for key, data in self.memory.long_term.items():
            if isinstance(data, dict) and "value" in data:
                prefs.append(f"- {key}: {data['value']}")
        return "\n".join(prefs) if prefs else ""
    
    def refresh_context(self) -> None:
        """Reload context files (call if they changed)."""
        self._system_context = self._build_system_context()
        print("[Orchestrator] Context refreshed")
    
    def think(self, user_input: str, context: dict | None = None) -> dict[str, Any]:
        """Process user input and prepare a thoughtful response."""
        # Store in memory
        self.memory.add_to_short_term("user", user_input, context)
        
        # Build messages for the LLM
        messages = [
            {"role": "system", "content": self._system_context},
        ]
        
        # Add recent conversation history
        recent = self.memory.get_recent_context(n=5)
        if recent:
            messages.append({
                "role": "system",
                "content": f"Recent conversation:\n{recent}"
            })
        
        # Add current input
        messages.append({"role": "user", "content": user_input})
        
        return {
            "messages": messages,
            "context": {
                "has_kernel": self.kernel is not None,
                "memory_entries": len(self.memory.short_term),
                "learned_facts": len(self.memory.long_term),
            }
        }
    
    def respond(self, llm_response: str, metadata: dict | None = None) -> str:
        """Process and store the LLM response."""
        self.memory.add_to_short_term("assistant", llm_response, metadata)
        return llm_response
    
    def learn(self, key: str, value: Any) -> None:
        """Learn a new fact about the user or preferences."""
        self.memory.remember(key, value)
        print(f"[Orchestrator] Learned: {key} = {value}")
    
    def get_system_prompt(self) -> str:
        """Get the current system prompt with full context."""
        return self._system_context
    
    def get_status(self) -> dict[str, Any]:
        """Get current orchestrator status."""
        # Check if files actually exist (not just if content is returned)
        identity_path = self.context_loader.workspace_root / "IDENTITY.md"
        soul_path = self.context_loader.workspace_root / "SOUL.md"
        user_path = self.context_loader.workspace_root / "USER.md"
        
        identity_exists = identity_path.exists()
        soul_exists = soul_path.exists()
        user_exists = user_path.exists()
        
        # Check if content indicates file not found
        identity_content = self.context_loader.get_identity()
        soul_content = self.context_loader.get_soul()
        user_content = self.context_loader.get_user()
        
        identity_loaded = identity_exists and "[File not found]" not in identity_content
        soul_loaded = soul_exists and "[File not found]" not in soul_content
        user_loaded = user_exists and "[File not found]" not in user_content
        
        return {
            "initialized": True,
            "workspace": str(self.context_loader.workspace_root),
            "context_files": {
                "IDENTITY.md": {"exists": identity_exists, "loaded": identity_loaded, "size": len(identity_content) if identity_loaded else 0},
                "SOUL.md": {"exists": soul_exists, "loaded": soul_loaded, "size": len(soul_content) if soul_loaded else 0},
                "USER.md": {"exists": user_exists, "loaded": user_loaded, "size": len(user_content) if user_loaded else 0},
            },
            "memory": {
                "short_term_entries": len(self.memory.short_term),
                "long_term_facts": len(self.memory.long_term),
            },
            "kernel_connected": self.kernel is not None,
            "system_prompt_length": len(self._system_context),
        }


# Convenience function for direct usage
def create_orchestrator(kernel=None, workspace_root: str | None = None) -> Orchestrator:
    """Create and initialize an Orchestrator instance."""
    return Orchestrator(kernel=kernel, workspace_root=workspace_root)


if __name__ == "__main__":
    # Test the orchestrator
    orch = create_orchestrator()
    
    print("\n" + "="*50)
    print("ORCHESTRATOR STATUS")
    print("="*50)
    status = orch.get_status()
    for key, value in status.items():
        print(f"{key}: {value}")
    
    print("\n" + "="*50)
    print("SYSTEM CONTEXT (first 500 chars)")
    print("="*50)
    context = orch.get_system_prompt()
    print(context[:500] + "..." if len(context) > 500 else context)
