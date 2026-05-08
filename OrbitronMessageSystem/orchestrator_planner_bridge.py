"""Orchestrator-Planner Integration Example.

This module demonstrates how the Orchestrator and Planner agents
communicate using the OrbitronMessageSystem API.
"""

from datetime import datetime
import json
import logging
import re
from typing import Any, Optional

try:
    from OrbitronMessageSystem import (
        AgentCommunicator,
        OrchestratorCommunicator,
        PlannerCommunicator,
        Message,
        MessageType,
        AgentRole,
        get_message_bus,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from OrbitronMessageSystem import (
        AgentCommunicator,
        OrchestratorCommunicator,
        PlannerCommunicator,
        Message,
        MessageType,
        AgentRole,
        get_message_bus,
    )


class OrchestratorPlannerBridge:
    """Bridge class that integrates Orchestrator with Planner via MessageBus.
    
    This class can be used by the Orchestrator to communicate with the Planner
    without directly instantiating the Planner Agent.
    """
    
    def __init__(self, orchestrator_name: str = "orchestrator"):
        """Initialize the bridge.
        
        Args:
            orchestrator_name: Name of the orchestrator instance
        """
        self._communicator = OrchestratorCommunicator(agent_name=orchestrator_name)
        self._communicator.connect()
        
        logger = logging.getLogger("OrchestratorPlannerBridge")
        logger.info("[OrchestratorPlannerBridge] Initialized for %s", orchestrator_name)
    
    def request_plan(
        self,
        task_description: str,
        context: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 3600,
    ) -> dict[str, Any]:
        """Request a plan from the Planner Agent.
        
        This is a synchronous call that waits for the Planner to complete.
        
        Args:
            task_description: Description of what needs to be planned
            context: Additional context (files, constraints, etc.)
            timeout_seconds: Maximum time to wait for planning
            
        Returns:
            Dictionary containing the plan and analysis
            
        Example:
            ```python
            bridge = OrchestratorPlannerBridge()
            result = bridge.request_plan(
                task_description="Implement user authentication",
                context={
                    "existing_files": ["auth.py", "models.py"],
                    "constraints": ["use JWT", "support OAuth"],
                }
            )
            
            if result["success"]:
                plan = result["plan"]
                print(f"Plan has {len(plan['steps'])} steps")
            ```
        """
        logger = logging.getLogger("OrchestratorPlannerBridge")
        logger.info("[OrchestratorPlannerBridge] Requesting plan for: %s...", task_description[:50])
        
        # Send planning request and wait for response
        response = self._communicator.request_planning(
            request=task_description,
            context=context,
            timeout_ms=timeout_seconds * 1000,
        )
        
        if response is None:
            return {
                "success": False,
                "error": "Planning request timed out",
                "plan": None,
                "analysis": None,
            }
        
        # Parse response
        success = response.metadata.get("success", False)
        
        return {
            "success": success,
            "error": response.metadata.get("error") if not success else None,
            "plan": response.payload.get("plan") if success else None,
            "analysis": response.payload.get("analysis") if success else None,
            "request_id": response.header.correlation_id,
        }
    
    def request_plan_async(
        self,
        task_description: str,
        callback: callable,
        context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Request a plan asynchronously.
        
        Args:
            task_description: Description of what needs to be planned
            callback: Function to call when planning is complete
            context: Additional context
            
        Returns:
            Request ID for tracking
            
        Example:
            ```python
            def on_plan_complete(result_message):
                plan = result_message.payload.get("plan")
                print(f"Plan received: {plan['title']}")
            
            bridge = OrchestratorPlannerBridge()
            request_id = bridge.request_plan_async(
                task_description="Refactor database layer",
                callback=on_plan_complete,
            )
            ```
        """
        logger = logging.getLogger("OrchestratorPlannerBridge")
        logger.info("[OrchestratorPlannerBridge] Async planning request: %s...", task_description[:50])
        
        def _wrapper_callback(message: Message):
            """Wrap the user callback to extract plan data."""
            try:
                callback(message)
            except Exception as e:
                logger.error("[OrchestratorPlannerBridge] Error in callback: %s", e)
        
        return self._communicator.request_planning_async(
            request=task_description,
            callback=_wrapper_callback,
            context=context,
        )
    
    def send_status_to_planner(self, status: str, details: Optional[dict] = None) -> None:
        """Send a status update to the Planner."""
        self._communicator.send_status(status, details)
    
    def get_communicator(self) -> OrchestratorCommunicator:
        """Get the underlying communicator for advanced usage."""
        return self._communicator
    
    def close(self) -> None:
        """Close the bridge and disconnect from message bus."""
        self._communicator.disconnect()
        logger = logging.getLogger("OrchestratorPlannerBridge")
        logger.info("[OrchestratorPlannerBridge] Closed")


class PlannerMessageHandler:
    """Message handler for the Planner Agent.
    
    This class handles incoming messages for the Planner and routes them
to the appropriate Planner Agent methods.
    """
    
    def __init__(self, planner_agent, agent_name: str = "planner"):
        """Initialize the message handler.
        
        Args:
            planner_agent: The PlannerAgent instance to route messages to
            agent_name: Name of this planner instance
        """
        self._planner = planner_agent
        self._communicator = PlannerCommunicator(agent_name=agent_name)
        self._communicator.connect(
            message_handler=self._handle_message,
            message_types=[MessageType.PLANNING_REQUEST, MessageType.COMMAND],
        )
        
        self._logger = logging.getLogger("PlannerMessageHandler")
        self._logger.info("[PlannerMessageHandler] Initialized for %s", agent_name)
    
    def _handle_message(self, message: Message) -> None:
        """Handle incoming messages."""
        self._logger.info("[PlannerMessageHandler] Received %s from %s", 
                          message.header.message_type.name, message.header.sender)
        
        if message.header.message_type == MessageType.PLANNING_REQUEST:
            self._handle_planning_request(message)
        elif message.header.message_type == MessageType.COMMAND:
            self._handle_command(message)
        else:
            self._logger.warning("[PlannerMessageHandler] Unknown message type: %s", message.header.message_type)
    
    def _handle_planning_request(self, message: Message) -> None:
        """Handle a planning request."""
        request_id = message.header.message_id
        self._logger.info("[PlannerHandler] Processing planning request %s", request_id)
        
        try:
            request = message.payload.get("request", "")
            context = message.payload.get("context", {})
            timeout_s = None
            if message.header.timeout_ms:
                timeout_s = max(30, int(message.header.timeout_ms / 1000) - 30)
            
            self._logger.info("[PlannerHandler] Request content: %s...", request[:80])
            self._logger.info("[PlannerHandler] Context keys: %s", list(context.keys()) if context else "none")
            
            plan_data = None
            analysis_data = None

            # Use planner to generate a full plan
            try:
                self._logger.info("[PlannerHandler] Calling planner.generate_plan()...")
                plan_data, analysis_data = self._planner.generate_plan(
                    request,
                    context,
                    timeout_s=timeout_s,
                )
                self._logger.info("[PlannerHandler] Planner.generate_plan() succeeded")
            except Exception as e:
                self._logger.exception("[PlannerHandler] Planner generate_plan failed: %s", e)
                plan_data = self._build_basic_plan(request, context)
                if isinstance(plan_data.get("metadata"), dict):
                    plan_data["metadata"]["source"] = "fallback_error"
                    plan_data["metadata"]["error"] = str(e)
                analysis_data = {
                    "complexity": "unknown",
                    "estimated_effort": "unknown",
                    "notes": f"Planner failed to return a structured plan: {e}",
                    "source": "fallback_error",
                }

            # If planner did not return a plan, generate a basic one
            if not isinstance(plan_data, dict) or not plan_data:
                self._logger.warning("[PlannerHandler] No plan returned, using fallback")
                plan_data = self._build_basic_plan(request, context)
                analysis_data = {
                    "complexity": "unknown",
                    "estimated_effort": "unknown",
                    "notes": "Planner failed to return a structured plan",
                    "source": "fallback",
                }
            if not isinstance(analysis_data, dict):
                analysis_data = {
                    "complexity": "unknown",
                    "estimated_effort": "unknown",
                    "notes": "Planner analysis missing",
                    "source": "unknown",
                }
            
            # Send response back
            self._logger.info("[PlannerHandler] Sending planning result for request %s (plan_id=%s, steps=%d)",
                             request_id, plan_data.get("id", "unknown"), len(plan_data.get("steps", [])))
            self._communicator.send_planning_result(
                request_id=message.header.message_id,
                plan=plan_data,
                analysis=analysis_data,
                success=True,
            )
            
            self._logger.info("[PlannerHandler] Planning complete for request %s", request_id)
            
        except Exception as e:
            self._logger.exception("[PlannerHandler] Error handling planning request %s: %s", request_id, e)
            
            # Send error response
            self._communicator.send_planning_result(
                request_id=message.header.message_id,
                plan={},
                analysis={},
                success=False,
                error_message=str(e),
            )

    def _build_basic_plan(self, request: str, context: dict[str, Any]) -> dict[str, Any]:
        """Build a minimal fallback plan when no plan was returned."""
        title = request.strip()
        if len(title) > 80:
            title = f"Plan: {title[:77]}..."
        else:
            title = f"Plan: {title}" if title else "Plan: Unnamed task"

        plan_type = "execution"
        text = request.lower()
        if any(k in text for k in ["wandern", "hike", "reise", "travel", "camping", "itinerary", "hotel", "flug", "flight"]):
            plan_type = "experience"

        steps = [
            {
                "id": "step-001",
                "description": "Ziele und Anforderungen klar definieren",
                "priority": "high",
                "depends_on": [],
            },
            {
                "id": "step-002",
                "description": "Plan strukturieren und notwendige Ressourcen sammeln",
                "priority": "medium",
                "depends_on": ["step-001"],
            },
            {
                "id": "step-003",
                "description": "Ablauf und Zeitplan festlegen sowie Risiken bewerten",
                "priority": "medium",
                "depends_on": ["step-002"],
            },
        ]

        return {
            "plan_type": plan_type,
            "id": f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "title": title,
            "description": request,
            "summary": "Auto-generierter Plan, da kein strukturierter Plan vorlag.",
            "status": "draft",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "steps": steps,
            "artifacts": [],
            "edge_cases": [],
            "itinerary": [],
            "risks": [],
            "packing_list": [],
            "metadata": {
                "source": "fallback",
                "plan_type": plan_type,
                "context_keys": list(context.keys()) if isinstance(context, dict) else [],
            },
        }

    def _plan_with_kernel(self, request: str, context: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Generate a structured plan using the kernel LLM."""
        messages = []

        planning_context = self._planner.plan(request, context)
        if isinstance(planning_context, dict) and "messages" in planning_context:
            messages = planning_context["messages"]

        # Inject strict JSON output instruction
        messages.insert(1, {
            "role": "system",
            "content": (
                "Return ONLY valid JSON with this schema: "
                "{id,title,description,summary,steps:[{id,description,priority,depends_on,estimated_time}],"
                "itinerary:[{time,activity}],risks:[string],packing_list:[string],metadata:{}}. "
                "Do not include markdown, commentary, or code fences."
            )
        })

        response_text = self._planner.kernel.run_chat(messages, max_rounds=1)
        plan = self._extract_json(response_text)
        analysis = {
            "source": "kernel",
            "raw_response": response_text[:500],
        }

        if not plan:
            self._logger.warning("LLM did not return valid JSON plan")
        else:
            self._logger.info("LLM plan generated")

        return plan, analysis

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from text."""
        # Try fenced JSON first
        fence = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            try:
                return json.loads(fence.group(1))
            except Exception:
                pass

        # Try first JSON object
        obj = re.search(r"(\{.*\})", text, re.DOTALL)
        if obj:
            try:
                return json.loads(obj.group(1))
            except Exception:
                return None

        return None
    
    def _handle_command(self, message: Message) -> None:
        """Handle a command message."""
        command = message.payload.get("command", "")
        args = message.payload.get("args", {})
        
        self._logger.info("[PlannerMessageHandler] Executing command: %s", command)
        
        # Handle specific commands
        if command == "get_status":
            status = self._planner.get_status()
            self._communicator.respond_to(
                original_message=message,
                payload={"status": status},
                success=True,
            )
        elif command == "reload_skills":
            # Reload planning skills
            self._planner._planning_context = self._planner._load_planning_context()
            self._communicator.respond_to(
                original_message=message,
                payload={"reloaded": True},
                success=True,
            )
        else:
            self._communicator.respond_to(
                original_message=message,
                payload={},
                success=False,
                error_message=f"Unknown command: {command}",
            )
    
    def get_communicator(self) -> PlannerCommunicator:
        """Get the underlying communicator."""
        return self._communicator
    
    def close(self) -> None:
        """Close the message handler."""
        self._communicator.disconnect()
        self._logger.info("[PlannerMessageHandler] Closed")


# Example usage and testing

if __name__ == "__main__":
    print("=" * 60)
    print("Orchestrator-Planner Integration Demo")
    print("=" * 60)
    
    # Start message bus
    bus = get_message_bus()
    bus.start()
    
    # Create a mock planner agent
    class MockPlannerAgent:
        def plan(self, request: str, context: dict) -> dict:
            """Mock planning method."""
            return {
                "plan": {
                    "id": "plan-001",
                    "title": f"Plan for: {request[:30]}...",
                    "steps": [
                        {"id": "step-1", "description": "Analyze requirements"},
                        {"id": "step-2", "description": "Design solution"},
                        {"id": "step-3", "description": "Implement"},
                    ],
                },
                "analysis": {
                    "complexity": "medium",
                    "estimated_hours": 4,
                },
            }
        
        def get_status(self) -> dict:
            return {"status": "idle", "plans_created": 5}
    
    # Create planner and its message handler
    mock_planner = MockPlannerAgent()
    planner_handler = PlannerMessageHandler(mock_planner, agent_name="planner-1")
    
    # Create orchestrator bridge
    bridge = OrchestratorPlannerBridge(orchestrator_name="orchestrator-1")
    
    # Test 1: Synchronous planning request
    print("\n--- Test 1: Synchronous Planning Request ---")
    result = bridge.request_plan(
        task_description="Implement a user authentication system with JWT support",
        context={"priority": "high", "deadline": "2026-05-15"},
        timeout_seconds=10,
    )
    
    if result["success"]:
        print(f"✓ Plan received: {result['plan']['title']}")
        print(f"  Steps: {len(result['plan']['steps'])}")
        print(f"  Complexity: {result['analysis'].get('complexity', 'unknown')}")
    else:
        print(f"✗ Planning failed: {result['error']}")
    
    # Test 2: Async planning request
    print("\n--- Test 2: Async Planning Request ---")
    
    async_results = {}
    
    def on_plan_ready(message):
        async_results["received"] = True
        print(f"✓ Async plan received: {message.payload.get('plan', {}).get('title')}")
    
    request_id = bridge.request_plan_async(
        task_description="Refactor database layer for better performance",
        callback=on_plan_ready,
        context={"current_db": "sqlite", "target": "postgresql"},
    )
    print(f"  Request ID: {request_id}")
    
    # Wait a bit for async processing
    import time
    time.sleep(1)
    
    # Cleanup
    print("\n--- Cleanup ---")
    bridge.close()
    planner_handler.close()
    bus.stop()
    
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)
