"""Kernel Bridge - Connects Orchestrator with OrbitronKernel."""

import logging
from typing import Any

logger = logging.getLogger("KernelBridge")

from OrbitronKernel.kernel import OrbitronKernel
from OrbitronAgents.Orchestrator.Orchestrator import Orchestrator


class KernelBridge:
    """Bridge between Orchestrator (personality) and Kernel (tools)."""
    
    def __init__(self, config_path: str | None = None, workspace_root: str | None = None):
        """Initialize both Kernel and Orchestrator."""
        logger.info("[KernelBridge] Initializing...")
        
        # Initialize Kernel (tools, Ollama, file operations)
        self.kernel = OrbitronKernel(config_path=config_path)
        
        # Use kernel's workspace for context files (IDENTITY.md, SOUL.md, USER.md)
        # This is where the user has placed them
        kernel_workspace = self.kernel.config.get("kernel.workspace")
        
        # Initialize Orchestrator (personality, context, memory)
        # Use provided workspace_root, or kernel's workspace
        self.orchestrator = Orchestrator(
            kernel=self.kernel,
            workspace_root=workspace_root or kernel_workspace
        )
        
        logger.info("[KernelBridge] Workspace: %s", kernel_workspace)
        logger.info("[KernelBridge] Ready")
    
    def chat(self, user_input: str, chat_id: int | None = None) -> str:
        """Process a user message with full personality and tool access."""
        # Get orchestrator context
        thought = self.orchestrator.think(user_input)
        messages = thought["messages"]
        
        # Use kernel's run_chat with orchestrator's context
        response = self.kernel.run_chat(messages, max_rounds=10)
        
        # Store response in orchestrator memory
        self.orchestrator.respond(response)
        
        return response
    
    def chat_with_session(self, user_input: str, chat_id: int) -> str:
        """Chat with persistent session memory.
        
        Includes proper session cleanup on exceptions to prevent memory leaks.
        """
        # Get existing session or create new
        session = self.kernel.get_session(chat_id)

        # If new session, add orchestrator context
        if len(session) == 0:
            session.append({
                "role": "system",
                "content": self.orchestrator.get_system_prompt()
            })

        # Add user message
        session.append({"role": "user", "content": user_input})
        self.orchestrator.memory.add_to_short_term("user", user_input, {"chat_id": chat_id})

        try:
            # Run through kernel
            response = self.kernel.run_chat(session, max_rounds=10)

            # Store in orchestrator memory
            self.orchestrator.respond(response, {"chat_id": chat_id})

            # Persist session after each turn
            self.kernel.save_session(chat_id)

            return response

        except Exception as e:
            # Clean up session on exception to prevent memory leaks
            logger.error("[KernelBridge] Exception in chat_with_session for chat_id=%s: %s", chat_id, e)
            try:
                # Try to save what we have, but don't let cleanup errors mask the original exception
                self.kernel.save_session(chat_id)
            except Exception:
                pass  # Best effort save
            raise
    
    def learn(self, key: str, value: Any) -> None:
        """Teach the orchestrator something new."""
        self.orchestrator.learn(key, value)
    
    def get_status(self) -> dict[str, Any]:
        """Get combined status of kernel and orchestrator."""
        return {
            "kernel": {
                "model": self.kernel.config.get("ollama.model"),
                "workspace": self.kernel.config.get("kernel.workspace"),
            },
            "orchestrator": self.orchestrator.get_status(),
        }


def main():
    """Test the KernelBridge."""
    bridge = KernelBridge()
    
    print("\n" + "="*60)
    print("KERNEL BRIDGE STATUS")
    print("="*60)
    status = bridge.get_status()
    print(f"Model: {status['kernel']['model']}")
    print(f"Workspace: {status['kernel']['workspace']}")
    print(f"Orchestrator ready: {status['orchestrator']['initialized']}")
    print(f"Context files loaded: {status['orchestrator']['context_files_loaded']}")
    
    print("\n" + "="*60)
    print("TEST CHAT")
    print("="*60)
    
    # Test a simple interaction
    test_input = "Hallo Orbitron! Wer bist du?"
    print(f"\nUser: {test_input}")
    
    try:
        response = bridge.chat(test_input)
        print(f"\nOrbitron: {response}")
    except Exception as e:
        print(f"\n[Error] Could not get response: {e}")
        print("(Stelle sicher, dass Ollama läuft)")


if __name__ == "__main__":
    main()
