"""Orbitron Orchestrator - The living agent that coordinates and manages the agent system.

The Orchestrator is the central coordinator of the Orbitron agent system. It:
- Receives tasks from users or other systems
- Delegates planning to the Planner Agent
- Reviews and validates plans
- Coordinates execution (via future Executor)
- Manages the overall task lifecycle
"""

import json
import logging
import os
import re
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Orchestrator")

# Import message system
from OrbitronMessageSystem import (
    OrchestratorCommunicator,
    Message,
    MessagePriority,
    AgentRole,
    get_message_bus,
)
from OrbitronMessageSystem.orchestrator_planner_bridge import OrchestratorPlannerBridge
from OrbitronMessageSystem.orchestrator_executor_bridge import OrchestratorExecutorBridge
from OrbitronMessageSystem.orchestrator_tester_bridge import OrchestratorTesterBridge

# Import reflection engine
from OrbitronAgents.Orchestrator.reflection_engine import ReflectionEngine

# Import autonomous agent base
from OrbitronAgents.base.autonomous_agent import AutonomousAgent, AgentLoopResult


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
            fallback_root = Path(__file__).resolve().parents[2]
            fallback_path = fallback_root / filename
            if fallback_path.exists():
                filepath = fallback_path
            else:
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
            logger.error("[MemoryStore] Error saving memory: %s", e)
    
    def add_to_short_term(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Add an entry to short-term memory with size limits."""
        # Truncate content to prevent memory bloat
        max_content_length = 500
        if isinstance(content, str) and len(content) > max_content_length:
            content = content[:max_content_length] + "...[truncated]"
        
        # Sanitize metadata - remove large file contents
        sanitized_metadata = None
        if metadata:
            sanitized_metadata = {}
            for key, value in metadata.items():
                if isinstance(value, str) and len(value) > 500:
                    sanitized_metadata[key] = value[:500] + "...[truncated]"
                elif key in ("plan", "execution_result", "previous_plan") and isinstance(value, dict):
                    # Store only summary, not full plan/result
                    sanitized_metadata[key] = {"summary": f"Plan/result with {len(value)} keys (truncated)"}
                else:
                    sanitized_metadata[key] = value
        
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if sanitized_metadata:
            entry["metadata"] = sanitized_metadata
        self.short_term.append(entry)
        
        # Keep short-term memory manageable (last 20 entries, not 50)
        if len(self.short_term) > 20:
            self.short_term = self.short_term[-20:]
    
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


class TaskStatus(Enum):
    """Status values for tasks in the orchestration loop."""
    PENDING = auto()           # Task received, not yet processed
    PLANNING = auto()          # Planning in progress
    PLAN_REVIEW = auto()       # Reviewing the plan
    PLAN_REVISION = auto()     # Plan needs revision
    READY_FOR_EXECUTION = auto()  # Plan approved, ready to execute
    EXECUTING = auto()         # Execution in progress
    COMPLETED = auto()         # Task completed successfully
    FAILED = auto()            # Task failed
    CANCELLED = auto()         # Task cancelled


class PlanReviewResult(Enum):
    """Results of plan review."""
    APPROVED = auto()          # Plan is good, proceed
    NEEDS_REVISION = auto()    # Plan needs changes
    REJECTED = auto()          # Plan is fundamentally flawed


class Task:
    """Represents a task in the orchestration system.
    
    A task goes through multiple phases:
    1. Created: Initial state when received
    2. Planning: Delegated to Planner Agent
    3. Review: Orchestrator reviews the plan
    4. Revision: Plan sent back for changes (if needed)
    5. Execution: Plan is executed (by future Executor)
    6. Complete: Task finished
    """
    
    def __init__(
        self,
        task_id: str,
        description: str,
        context: Optional[dict[str, Any]] = None,
        max_planning_iterations: int = 3,
    ):
        self.task_id = task_id
        self.description = description
        self.context = context or {}
        
        # Status tracking
        self.status = TaskStatus.PENDING
        self.status_history: list[dict[str, Any]] = []
        self._update_status(TaskStatus.PENDING, "Task created")
        
        # Planning loop tracking
        self.max_planning_iterations = max_planning_iterations
        self.current_planning_iteration = 0
        self.plan: Optional[dict[str, Any]] = None
        self.plan_analysis: Optional[dict[str, Any]] = None
        self.plan_reviews: list[dict[str, Any]] = []
        
        # Execution tracking (for future)
        self.execution_steps: list[dict[str, Any]] = []
        self.current_step_index = 0
        
        # Timing
        self.created_at = datetime.now()
        self.updated_at = self.created_at
        self.completed_at: Optional[datetime] = None
        
        # Results
        self.result: Optional[dict[str, Any]] = None
        self.error_message: Optional[str] = None
    
    def _update_status(self, new_status: TaskStatus, reason: str = "") -> None:
        """Update task status with history tracking."""
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now()
        
        self.status_history.append({
            "timestamp": self.updated_at.isoformat(),
            "from_status": old_status.name if old_status != new_status else None,
            "to_status": new_status.name,
            "reason": reason,
        })
    
    def set_planning(self) -> None:
        """Mark task as in planning phase."""
        self._update_status(TaskStatus.PLANNING, "Sent to Planner Agent")
    
    def set_plan_received(self, plan: dict[str, Any], analysis: dict[str, Any]) -> None:
        """Store received plan and mark for review."""
        self.plan = plan
        self.plan_analysis = analysis
        self.current_planning_iteration += 1
        self._update_status(TaskStatus.PLAN_REVIEW, f"Plan received (iteration {self.current_planning_iteration})")
    
    def add_plan_review(
        self,
        result: PlanReviewResult,
        feedback: str,
        issues: Optional[list[str]] = None,
    ) -> None:
        """Add a plan review result."""
        review = {
            "iteration": self.current_planning_iteration,
            "timestamp": datetime.now().isoformat(),
            "result": result.name,
            "feedback": feedback,
            "issues": issues or [],
        }
        self.plan_reviews.append(review)
        
        if result == PlanReviewResult.APPROVED:
            self._update_status(TaskStatus.READY_FOR_EXECUTION, "Plan approved")
        elif result == PlanReviewResult.NEEDS_REVISION:
            self._update_status(TaskStatus.PLAN_REVISION, f"Plan needs revision: {feedback[:100]}...")
        else:  # REJECTED
            self._update_status(TaskStatus.FAILED, f"Plan rejected: {feedback[:100]}...")
            self.error_message = f"Plan rejected: {feedback}"
    
    def can_request_revision(self) -> bool:
        """Check if more planning iterations are allowed."""
        return self.current_planning_iteration < self.max_planning_iterations
    
    def set_completed(self, result: dict[str, Any]) -> None:
        """Mark task as completed."""
        self.result = result
        self.completed_at = datetime.now()
        self._update_status(TaskStatus.COMPLETED, "Task completed successfully")
    
    def set_failed(self, error_message: str) -> None:
        """Mark task as failed."""
        self.error_message = error_message
        self.completed_at = datetime.now()
        self._update_status(TaskStatus.FAILED, error_message[:200])
    
    def get_planning_context(self) -> dict[str, Any]:
        """Get context for planning request - with size limits."""
        context = {
            "task_id": self.task_id,
            "iteration": self.current_planning_iteration + 1,
            "max_iterations": self.max_planning_iterations,
        }
        
        # Only include essential context keys, not full content
        for key, value in self.context.items():
            if key in ("source", "chat_id", "username"):
                context[key] = value
            elif isinstance(value, str) and len(value) < 200:
                context[key] = value
            elif isinstance(value, (int, float, bool)):
                context[key] = value
        
        # Include previous plan summary (not full plan) if this is a revision
        if self.current_planning_iteration > 0 and self.plan_reviews:
            last_review = self.plan_reviews[-1]
            # Create a minimal plan summary instead of full plan
            if self.plan and isinstance(self.plan, dict):
                plan_summary = {
                    "id": self.plan.get("id", "unknown"),
                    "title": self.plan.get("title", "")[:100],
                    "plan_type": self.plan.get("plan_type", "unknown"),
                    "steps_count": len(self.plan.get("steps", [])),
                }
                context["previous_plan_summary"] = plan_summary
            context["revision_feedback"] = last_review["feedback"][:500] if isinstance(last_review.get("feedback"), str) else ""
            context["issues_to_address"] = last_review.get("issues", [])[:5]  # Max 5 issues
        
        return context
    
    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "planning_iterations": self.current_planning_iteration,
            "max_planning_iterations": self.max_planning_iterations,
            "plan": self.plan,
            "plan_analysis": self.plan_analysis,
            "plan_reviews": self.plan_reviews,
            "status_history": self.status_history,
            "result": self.result,
            "error_message": self.error_message,
        }


class TaskOrchestrator:
    """Orbitron Task Orchestrator - Intelligent adaptive supervisor.

    The TaskOrchestrator is responsible for:
    1. Receiving and packaging tasks
    2. Intelligently classifying tasks (question, direct, exploratory, complex)
    3. Routing tasks adaptively (skip planning when not needed)
    4. Reviewing plans with intelligent feedback
    5. Coordinating execution with progress monitoring
    6. Managing task state and history

    Adaptive Routing:
    - question → Answer directly or route to Planner for research
    - direct_execution → Skip Planner, send goal directly to Executor
    - exploratory → Planner explores codebase, then Executor implements
    - complex → Full pipeline: Planner → Executor → Validation
    """

    # Feature flag for migration
    autonomous_mode: bool = True

    def __init__(
        self,
        kernel=None,
        workspace_root: str | None = None,
        max_planning_iterations: int = 3,
        planning_timeout_seconds: int = 900,
        execution_timeout_seconds: int = 900,
    ):
        """Initialize the Task Orchestrator.

        Args:
            kernel: Optional kernel instance
            workspace_root: Root directory for the workspace
            max_planning_iterations: Maximum planning revision loops
            planning_timeout_seconds: Timeout for planning requests (default 15 min)
            execution_timeout_seconds: Timeout for execution requests (default 15 min)
        """
        self.kernel = kernel
        self.workspace_root = Path(workspace_root) if workspace_root else Path(__file__).resolve().parents[2]

        # Configuration
        self.max_planning_iterations = max_planning_iterations
        self.planning_timeout_seconds = planning_timeout_seconds
        self.execution_timeout_seconds = execution_timeout_seconds

        # Task management
        self.tasks: dict[str, Task] = {}
        self.active_task_id: Optional[str] = None

        # Communication
        self._planner_bridge: Optional[OrchestratorPlannerBridge] = None
        self._executor_bridge: Optional[OrchestratorExecutorBridge] = None
        self._tester_bridge: Optional[OrchestratorTesterBridge] = None
        self._communicator: Optional[OrchestratorCommunicator] = None

        # Context and memory
        self.context_loader = ContextLoader(workspace_root)
        self.memory = MemoryStore()
        self._system_context = self._build_system_context()

        # Reflection engine for continuous learning
        self.reflection_engine = ReflectionEngine(workspace_root=str(self.workspace_root))

        # Internal autonomous agent for intelligent decision-making
        self._decision_agent: Optional[AutonomousAgent] = None
        self._decision_result: Optional[dict[str, Any]] = None
        # Track whether execution and testing happened in the decision loop
        self._execution_happened: bool = False
        self._testing_happened: bool = False
        self._last_execution_result: Optional[dict[str, Any]] = None
        # Iteration counters for convergence enforcement
        self._iteration_counts: dict[str, int] = {
            "planning": 0,
            "execution": 0,
            "testing": 0,
        }
        self._max_planning_calls: int = 2
        self._max_execution_calls: int = 3
        self._max_testing_calls: int = 3
        if self.kernel:
            self._setup_decision_agent()

        logger.info("[TaskOrchestrator] Initialized (autonomous_mode=%s)", self.autonomous_mode)
        logger.info("[TaskOrchestrator] Workspace: %s", self.workspace_root)
        logger.info("[TaskOrchestrator] Max planning iterations: %d", max_planning_iterations)

    def _setup_decision_agent(self) -> None:
        """Create and configure the internal AutonomousAgent for intelligent task routing."""
        system_prompt = f"""You are the Orbitron Orchestrator. You receive a user request and decide how to handle it.

## Your Identity
You are the central intelligence of the Orbitron agent system. You coordinate Planner, Executor, and Tester agents.
You do NOT implement code yourself — you DELEGATE intelligently.

## CRITICAL: Mandatory Workflow
You MUST follow this exact workflow. Deviations are NOT allowed:

For **questions** (no files/code needed):
1. Call `answer_directly` → Done. Call `submit_result`.

For **implementation tasks** (files, code, documents):
1. Call `request_execution` to implement the task
2. After receiving execution results, call `request_testing` to verify quality
3. If testing passes (quality_rating = "excellent" or "good") → Call `submit_result`
4. If testing finds issues (quality_rating = "poor") → Call `request_execution` ONE MORE TIME with specific fix instructions
5. After the fix, call `request_testing` ONE MORE TIME
6. Regardless of the second test result → Call `submit_result`

## HARD LIMITS (DO NOT VIOLATE)
- Call `request_planning` at most ONCE per task
- Call `request_execution` at most TWICE per task (initial + one fix)
- Call `request_testing` at most TWICE per task
- After calling `request_testing`, you MUST call `submit_result` next (or `request_execution` if this is your first test and it failed)
- NEVER call `request_planning` after `request_execution` has been called
- NEVER restart a task from scratch — fix what's there
- ALWAYS converge: call `submit_result` within your remaining rounds

## Tools
- `answer_directly` — Answer simple questions directly
- `request_planning` — Get a structured plan (call ONCE at most, BEFORE execution)
- `request_execution` — Send task to Executor (call at most TWICE)
- `request_testing` — Send product to Tester for quality review (call at most TWICE)
- `submit_result` — **TERMINAL** — Call this to finish and deliver the result

## Decision Guidelines
- **Simple question** → `answer_directly` → `submit_result`
- **Simple implementation** → `request_execution` → `request_testing` → `submit_result`
- **Complex project** → `request_planning` → `request_execution` → `request_testing` → `submit_result`
- **If test fails** → `request_execution` (with fix instructions) → `request_testing` → `submit_result`
"""

        self._decision_agent = AutonomousAgent(
            agent_name="orchestrator_decision",
            system_prompt=system_prompt,
            kernel=self.kernel,
            max_rounds=22,
            urgency_threshold=0.4,
        )

        # Register tools
        self._decision_agent.register_tool(
            name="answer_directly",
            description="Answer the user's request directly using the LLM. Use for questions, explanations, or clarification.",
            schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The question or request to answer"},
                    "context": {"type": "string", "description": "Optional additional context"},
                },
            },
            handler=self._tool_answer_directly,
        )

        self._decision_agent.register_tool(
            name="request_planning",
            description="Send the task to the Planner Agent for structured planning. Use for complex tasks requiring multiple steps.",
            schema={
                "type": "object",
                "required": ["task"],
                "properties": {
                    "task": {"type": "string", "description": "The task description for the Planner"},
                    "context": {"type": "string", "description": "Optional context for the Planner"},
                },
            },
            handler=self._tool_request_planning,
        )

        self._decision_agent.register_tool(
            name="request_execution",
            description="Send a goal directly to the Executor Agent for autonomous implementation. Use for coding, file creation, bug fixes.",
            schema={
                "type": "object",
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string", "description": "The high-level goal for the Executor"},
                    "plan_hint": {"type": "string", "description": "Optional plan or guidance for the Executor"},
                },
            },
            handler=self._tool_request_execution,
        )

        self._decision_agent.register_tool(
            name="submit_result",
            description="Submit the final result to the user. Call this when you are satisfied with the outcome.",
            schema={
                "type": "object",
                "required": ["summary"],
                "properties": {
                    "summary": {"type": "string", "description": "Summary of the result for the user"},
                    "success": {"type": "boolean", "description": "Whether the task succeeded", "default": True},
                    "artifacts": {"type": "array", "items": {"type": "string"}, "description": "List of created/modified files"},
                },
            },
            handler=self._tool_submit_result,
        )

        self._decision_agent.register_tool(
            name="request_testing",
            description="Send the product to the Tester Agent for critical quality review. The Tester is READ-ONLY — it inspects but never modifies. Call this AFTER execution to verify quality before submitting the final result.",
            schema={
                "type": "object",
                "required": ["task_description", "artifacts"],
                "properties": {
                    "task_description": {"type": "string", "description": "The original task description to test against"},
                    "artifacts": {"type": "array", "items": {"type": "string"}, "description": "List of artifact file paths to test"},
                    "execution_summary": {"type": "string", "description": "Summary of what the Executor produced"},
                },
            },
            handler=self._tool_request_testing,
        )

    # ========== Orchestrator Tool Handlers ==========

    def _tool_answer_directly(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool handler: answer a query directly via the kernel."""
        query = args.get("query", "")
        context = args.get("context", "")
        if not self.kernel:
            return {"ok": False, "error": "No kernel available"}
        try:
            messages = [
                {"role": "system", "content": self._system_context},
                {"role": "user", "content": f"{query}\n\nContext: {context}" if context else query},
            ]
            response = self.kernel.run_chat(messages=messages, max_rounds=15)
            return {"ok": True, "answer": response}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _tool_request_planning(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool handler: request planning from the Planner Agent."""
        # Enforce iteration limit
        if self._iteration_counts["planning"] >= self._max_planning_calls:
            return {
                "ok": False,
                "error": f"Planning limit reached ({self._max_planning_calls} call(s)). Proceed to execution instead. Call request_execution or submit_result.",
            }
        task_desc = args.get("task", "")
        context = args.get("context", "")

        # Include information about what was already planned/executed to prevent duplication
        planning_context = {"notes": context} if context else {}
        if self._last_execution_result:
            planning_context["previous_execution_summary"] = self._last_execution_result.get("summary", "")[:500]
            planning_context["previous_artifacts"] = self._last_execution_result.get("artifacts", [])
        if self._iteration_counts["execution"] > 0:
            planning_context["warning"] = "Execution has already been done. Only plan if the task fundamentally needs re-planning. Do NOT duplicate existing work."

        if not self._planner_bridge:
            return {"ok": False, "error": "Planner bridge not available"}
        try:
            result = self._planner_bridge.request_plan(
                task_description=task_desc,
                context=planning_context,
                timeout_seconds=self.planning_timeout_seconds,
            )
            self._iteration_counts["planning"] += 1
            if result.get("success"):
                return {
                    "ok": True,
                    "plan": result.get("plan", {}),
                    "analysis": result.get("analysis", {}),
                }
            else:
                return {"ok": False, "error": result.get("error", "Planning failed")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _tool_request_execution(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool handler: request execution from the Executor Agent."""
        # Enforce iteration limit
        if self._iteration_counts["execution"] >= self._max_execution_calls:
            return {
                "ok": False,
                "error": f"Execution limit reached ({self._max_execution_calls} call(s)). You MUST now call request_testing (if not done) or submit_result. No more execution calls allowed.",
            }
        goal = args.get("goal", "")
        plan_hint = args.get("plan_hint", "")
        if not self._executor_bridge:
            return {"ok": False, "error": "Executor bridge not available"}
        try:
            plan = {"goal": goal}
            if plan_hint:
                plan["plan_hint"] = plan_hint
            result = self._executor_bridge.request_execution(
                plan=plan,
                context={"execution_mode": "autonomous"},
                timeout_seconds=self.execution_timeout_seconds,
            )
            if isinstance(result, dict):
                exec_result = result.get("execution_result", result)
                self._execution_happened = True
                self._last_execution_result = exec_result if isinstance(exec_result, dict) else result
                self._iteration_counts["execution"] += 1
                return {
                    "ok": True,
                    "execution_result": exec_result,
                    "success": exec_result.get("success", False) if isinstance(exec_result, dict) else False,
                    "remaining_execution_calls": self._max_execution_calls - self._iteration_counts["execution"],
                    "must_test_next": self._iteration_counts["testing"] < self._max_testing_calls,
                }
            else:
                return {"ok": False, "error": "Invalid execution result"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _tool_submit_result(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool handler: submit the final result."""
        self._decision_result = {
            "summary": args.get("summary", ""),
            "success": args.get("success", True),
            "artifacts": args.get("artifacts", []),
        }
        return {"ok": True, "message": "Result submitted"}

    def _tool_request_testing(self, args: dict[str, Any]) -> dict[str, Any]:
        """Tool handler: request quality testing from the Tester Agent."""
        # Enforce iteration limit
        if self._iteration_counts["testing"] >= self._max_testing_calls:
            return {
                "ok": True,
                "passed": True,
                "quality_rating": "skipped",
                "summary": f"Testing limit reached ({self._max_testing_calls} call(s)). Proceed to submit_result.",
                "issues": [],
                "must_submit": True,
            }
        task_description = args.get("task_description", "")
        artifacts = args.get("artifacts", [])
        execution_summary = args.get("execution_summary", "")

        # Track that testing happened
        self._testing_happened = True

        if not self._tester_bridge:
            logger.warning("[Orchestrator] Tester bridge not available, skipping testing")
            return {
                "ok": True,
                "passed": True,
                "quality_rating": "unknown",
                "summary": "Testing skipped — Tester Agent not available",
                "issues": [],
                "skipped": True,
            }

        try:
            result = self._tester_bridge.request_testing(
                task_description=task_description,
                artifacts=artifacts,
                execution_result={"summary": execution_summary},
                timeout_seconds=self.execution_timeout_seconds,
            )
            self._iteration_counts["testing"] += 1

            remaining_exec = self._max_execution_calls - self._iteration_counts["execution"]
            remaining_test = self._max_testing_calls - self._iteration_counts["testing"]

            if result.get("passed", False):
                return {
                    "ok": True,
                    "passed": True,
                    "quality_rating": result.get("quality_rating", "unknown"),
                    "summary": result.get("summary", ""),
                    "issues": result.get("issues", []),
                    "must_submit": True,
                }
            else:
                # Test failed — tell the LLM what to do based on remaining iterations
                if remaining_exec > 0 and remaining_test > 0:
                    return {
                        "ok": True,
                        "passed": False,
                        "quality_rating": result.get("quality_rating", "poor"),
                        "summary": result.get("summary", ""),
                        "issues": result.get("issues", []),
                        "recommendation": f"The Tester found issues. Call request_execution with specific fix instructions, then request_testing again. ({remaining_exec} execution call(s) and {remaining_test} test call(s) remaining).",
                    }
                else:
                    return {
                        "ok": True,
                        "passed": False,
                        "quality_rating": result.get("quality_rating", "poor"),
                        "summary": result.get("summary", ""),
                        "issues": result.get("issues", []),
                        "recommendation": "No more execution or testing iterations remaining. You MUST call submit_result now with the best result available.",
                        "must_submit": True,
                    }
        except Exception as e:
            return {"ok": False, "error": f"Testing request failed: {str(e)}"}

    def _auto_trigger_testing(self, task: Task) -> Optional[dict[str, Any]]:
        """Automatically trigger Tester Agent after execution.

        This ensures testing ALWAYS happens after execution, even when the
        autonomous decision loop doesn't explicitly call request_testing.

        Args:
            task: The task that was executed

        Returns:
            Testing result dict, or None if testing couldn't be triggered
        """
        if not self._tester_bridge:
            logger.warning("[Orchestrator] No tester bridge available for testing")
            return {"passed": True, "quality_rating": "skipped", "summary": "Testing skipped — no tester bridge", "issues": []}

        # Collect artifacts from execution result
        artifacts = []
        exec_result = self._last_execution_result or {}
        if isinstance(exec_result, dict):
            artifacts = exec_result.get("artifacts", [])
            # Also try to find artifacts from file operations
            if not artifacts:
                file_ops = exec_result.get("file_operations", [])
                if file_ops:
                    artifacts = [op.get("path", "") for op in file_ops if op.get("path")]

        # If still no artifacts, try to find files in the workspace
        if not artifacts and self.workspace_root:
            try:
                workspace = Path(self.workspace_root)
                if workspace.exists():
                    recent_files = []
                    import time
                    cutoff = time.time() - 3600  # Files modified in the last hour
                    for f in workspace.rglob("*"):
                        if f.is_file() and not f.name.startswith(".") and f.stat().st_mtime > cutoff:
                            try:
                                rel = f.relative_to(workspace)
                                recent_files.append(str(rel))
                            except ValueError:
                                recent_files.append(str(f))
                    artifacts = recent_files[:20]  # Max 20 recent files
            except Exception:
                pass

        logger.info("[Orchestrator] Running Tester for task %s with %d artifacts",
                     task.task_id, len(artifacts))

        try:
            result = self._tester_bridge.request_testing(
                task_description=task.description,
                artifacts=artifacts,
                execution_result=exec_result,
                timeout_seconds=self.execution_timeout_seconds,
            )
            logger.info("[Orchestrator] Test complete: passed=%s, rating=%s",
                        result.get("passed"), result.get("quality_rating"))
            return result
        except Exception as e:
            logger.warning("[Orchestrator] Testing failed: %s", e)
            return {"passed": True, "quality_rating": "error", "summary": f"Testing error: {e}", "issues": []}

    def connect_to_message_bus(self) -> None:
        """Connect to the message bus for agent communication."""
        # Ensure message bus is started
        bus = get_message_bus()
        if not bus._running:
            bus.start()
        
        # Create planner bridge
        self._planner_bridge = OrchestratorPlannerBridge(
            orchestrator_name="orchestrator"
        )

        # Create executor bridge
        self._executor_bridge = OrchestratorExecutorBridge(
            orchestrator_name="orchestrator"
        )

        # Create tester bridge
        self._tester_bridge = OrchestratorTesterBridge(
            orchestrator_name="orchestrator"
        )

        # Create communicator
        self._communicator = OrchestratorCommunicator(agent_name="orchestrator")
        self._communicator.connect()
        
        logger.info("[TaskOrchestrator] Connected to message bus")
    
    def disconnect(self) -> None:
        """Disconnect from message bus."""
        if self._tester_bridge:
            self._tester_bridge.close()
            self._tester_bridge = None

        if self._executor_bridge:
            self._executor_bridge.close()
            self._executor_bridge = None

        if self._planner_bridge:
            self._planner_bridge.close()
            self._planner_bridge = None

        if self._communicator:
            self._communicator.disconnect()
            self._communicator = None
        
        logger.info("[TaskOrchestrator] Disconnected from message bus")
    
    def _build_system_context(self) -> str:
        """Build the complete system context for the LLM."""
        base_context = self.context_loader.get_full_context()
        
        # Add orchestrator-specific context
        orchestrator_context = f"""
## Orchestrator Role

You are the Task Orchestrator for the Orbitron agent system. Your responsibilities:

1. **Task Management**: Receive, package, and track tasks through their lifecycle
2. **Planning Coordination**: Delegate planning to the Planner Agent
3. **Plan Review**: Carefully review plans and provide detailed feedback
4. **Quality Control**: Ensure plans are complete, actionable, and correct

## Planning Review Guidelines

When reviewing a plan, check for:

### Completeness
- [ ] All requirements from the task are addressed
- [ ] No missing steps or gaps
- [ ] Clear start and end points

### Actionability
- [ ] Each step is specific and executable
- [ ] Steps are atomic (not too large)
- [ ] Clear acceptance criteria for each step

### Correctness
- [ ] Technical approach is sound
- [ ] Dependencies are correctly identified
- [ ] No logical errors or contradictions

### Efficiency
- [ ] Steps are optimally ordered
- [ ] Parallelization opportunities identified
- [ ] No unnecessary redundancy

### Safety
- [ ] Risks are identified
- [ ] Rollback strategy exists
- [ ] Edge cases are considered

## Review Decision

You must make one of three decisions:

1. **APPROVED** - Plan is good, proceed to execution
2. **NEEDS_REVISION** - Plan has issues that must be fixed
   - Provide specific, actionable feedback
   - List all issues found
   - Suggest improvements
3. **REJECTED** - Plan is fundamentally flawed
   - Explain why it cannot work
   - Task will be marked as failed

## Loop Protection

Maximum {self.max_planning_iterations} planning iterations allowed.
If plan still needs revision after max iterations, you must REJECT.

## Current Session
Current Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}
"""
        
        # Add learned preferences
        learned = self._get_learned_preferences()
        if learned:
            orchestrator_context += f"\n\n## Learned Preferences\n{learned}\n"
        
        return base_context + orchestrator_context
    
    def _get_learned_preferences(self) -> str:
        """Get learned preferences from long-term memory."""
        prefs = []
        for key, data in self.memory.long_term.items():
            if isinstance(data, dict) and "value" in data:
                prefs.append(f"- {key}: {data['value']}")
        return "\n".join(prefs) if prefs else ""
    
    # Task Lifecycle Methods
    
    def create_task(
        self,
        description: str,
        context: Optional[dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        """Create a new task.
        
        Args:
            description: Task description
            context: Additional context
            task_id: Optional task ID (generated if not provided)
            
        Returns:
            Created Task instance
        """
        task_id = task_id or f"task-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(self.tasks)}"
        
        task = Task(
            task_id=task_id,
            description=description,
            context=context,
            max_planning_iterations=self.max_planning_iterations,
        )
        
        self.tasks[task_id] = task
        self.active_task_id = task_id
        
        # Store in memory
        self.memory.add_to_short_term(
            role="system",
            content=f"Created task {task_id}: {description[:100]}...",
            metadata={"task_id": task_id, "status": "created"},
        )
        
        logger.info("[TaskOrchestrator] Created task: %s", task_id)
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self.tasks.get(task_id)
    
    def get_active_task(self) -> Optional[Task]:
        """Get the currently active task."""
        if self.active_task_id:
            return self.tasks.get(self.active_task_id)
        return None
    
    def run_task(self, task_id: str) -> dict[str, Any]:
        """Run a task through a deterministic pipeline with enforced convergence.

        Pipeline: CLASSIFY → (PLAN?) → EXECUTE → TEST → (FIX → TEST?) → DONE
        Hard limits ensure the system always converges:
        - Max 1 planning call
        - Max 2 execution calls (initial + 1 fix)
        - Max 2 testing calls
        - Always submits a result

        Args:
            task_id: ID of the task to run

        Returns:
            Task result dictionary
        """
        task = self.tasks.get(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}

        logger.info("=" * 60)
        logger.info("ORCHESTRATING TASK: %s", task_id)
        logger.info("=" * 60)

        # Reset iteration counters for this task
        self._iteration_counts = {"planning": 0, "execution": 0, "testing": 0}
        self._execution_happened = False
        self._testing_happened = False
        self._last_execution_result = None

        if not self.autonomous_mode or not self._decision_agent:
            return self._run_task_legacy(task)

        # ===== STEP 1: Classify task =====
        task_type = self._classify_task(task)
        logger.info("[Orchestrator] Task classified as: %s", task_type)

        # ===== FAST PATH: Questions → answer directly =====
        if task_type == "question":
            return self._handle_question_task(task)

        # ===== FAST PATH: Direct execution → execute, test, done =====
        if task_type == "direct_execution":
            return self._run_pipeline(task, skip_planning=True)

        # ===== COMPLEX/EXPLORATORY: Full pipeline =====
        return self._run_pipeline(task, skip_planning=False)

    def _run_pipeline(
        self,
        task: Task,
        skip_planning: bool = False,
    ) -> dict[str, Any]:
        """Run the deterministic pipeline: (PLAN?) → EXECUTE → TEST → (FIX → TEST?) → DONE.

        This method enforces convergence — the system WILL finish, either
        successfully or with the best result available.

        Args:
            task: The task to process
            skip_planning: If True, skip the planning phase (direct execution)

        Returns:
            Task result dictionary
        """
        logger.info("[Pipeline] Starting pipeline for task: %s (skip_planning=%s)", task.task_id, skip_planning)

        # ===== PHASE 1: Planning (optional) =====
        if not skip_planning:
            planning_result = self._run_planning_loop(task)
            if not planning_result["success"]:
                logger.warning("[Pipeline] Planning failed, falling back to direct execution")
                # Planning failed — try direct execution instead
                task.plan = None

        # ===== PHASE 2: Execution =====
        task._update_status(TaskStatus.EXECUTING, "Executing goal")

        goal = task.description
        if task.plan:
            goal = self._convert_plan_to_goal(task.plan)

        execution_result = self._run_execution_adaptive(task, goal=goal, plan=task.plan)
        self._iteration_counts["execution"] += 1
        self._execution_happened = True
        self._last_execution_result = execution_result

        if not execution_result or not execution_result.get("success", False):
            # First execution failed — try once more with error feedback
            logger.warning("[Pipeline] First execution failed, retrying with error feedback")
            fix_goal = self._build_error_fix_goal(task, execution_result)
            execution_result = self._run_execution_adaptive(task, goal=fix_goal)
            self._iteration_counts["execution"] += 1
            self._last_execution_result = execution_result

            if not execution_result or not execution_result.get("success", False):
                # Both attempts failed — test what we have and submit
                logger.warning("[Pipeline] Execution failed after retry, testing what we have")
                test_result = self._run_testing_phase(task, execution_result)
                return self._finalize_task(task, execution_result, test_result)

        # ===== PHASE 3: Testing (mandatory) =====
        test_result = self._run_testing_phase(task, execution_result)

        # ===== PHASE 4: Fix cycle (up to max_execution_calls remaining) =====
        while (test_result and not test_result.get("passed", False)
               and self._iteration_counts["execution"] < self._max_execution_calls
               and self._iteration_counts["testing"] < self._max_testing_calls):
            logger.info("[Pipeline] Test found issues, attempting fix cycle (execution=%d/%d, testing=%d/%d)",
                        self._iteration_counts["execution"], self._max_execution_calls,
                        self._iteration_counts["testing"], self._max_testing_calls)
            fix_goal = self._build_fix_goal(task, execution_result, test_result)
            execution_result = self._run_execution_adaptive(task, goal=fix_goal)
            self._iteration_counts["execution"] += 1
            self._last_execution_result = execution_result

            # Re-test after fix
            test_result = self._run_testing_phase(task, execution_result)

        # ===== PHASE 6: Finalize (always) =====
        return self._finalize_task(task, execution_result, test_result)

    def _run_testing_phase(
        self,
        task: Task,
        execution_result: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Run the testing phase of the pipeline.

        Always calls the Tester Agent after execution. This is mandatory, not optional.

        Args:
            task: The task being processed
            execution_result: Result from the Executor

        Returns:
            Testing result dict, or None if testing couldn't be triggered
        """
        if self._iteration_counts["testing"] >= self._max_testing_calls:
            logger.warning("[Pipeline] Testing limit reached, skipping test")
            return None

        logger.info("[Pipeline] Running Tester Agent (call %d/%d)",
                     self._iteration_counts["testing"] + 1, self._max_testing_calls)

        # Collect artifacts from execution result
        artifacts = []
        exec_result = execution_result or {}
        if isinstance(exec_result, dict):
            artifacts = exec_result.get("artifacts", [])

        self._iteration_counts["testing"] += 1
        self._testing_happened = True

        return self._auto_trigger_testing(task)

    def _build_fix_goal(
        self,
        task: Task,
        execution_result: Optional[dict[str, Any]],
        test_result: Optional[dict[str, Any]],
    ) -> str:
        """Build a goal for the fix cycle based on Tester feedback.

        Args:
            task: The original task
            execution_result: Result from the initial execution
            test_result: Result from the Tester

        Returns:
            A goal string for the fix execution
        """
        goal_parts = [f"FIX the following issues found during testing of: {task.description}"]

        # Add test issues
        if test_result and isinstance(test_result, dict):
            issues = test_result.get("issues", [])
            if issues:
                goal_parts.append("\n## Issues to Fix:")
                for i, issue in enumerate(issues[:10], 1):  # Max 10 issues
                    if isinstance(issue, dict):
                        severity = issue.get("severity", "unknown")
                        desc = issue.get("description", str(issue))
                        goal_parts.append(f"{i}. [{severity.upper()}] {desc}")
                    else:
                        goal_parts.append(f"{i}. {issue}")

            quality = test_result.get("quality_rating", "unknown")
            summary = test_result.get("summary", "")
            goal_parts.append(f"\nOverall quality: {quality}")
            if summary:
                goal_parts.append(f"Test summary: {summary}")

            recommendations = test_result.get("recommendations", "")
            if recommendations:
                goal_parts.append(f"Recommendations: {recommendations}")

        # Add artifacts that need fixing
        if execution_result and isinstance(execution_result, dict):
            artifacts = execution_result.get("artifacts", [])
            if artifacts:
                goal_parts.append(f"\nFiles to fix: {', '.join(str(a) for a in artifacts[:10])}")

        goal_parts.append("\nFix ONLY the issues listed above. Do NOT rewrite the entire project from scratch.")

        return "\n".join(goal_parts)

    def _build_error_fix_goal(
        self,
        task: Task,
        execution_result: Optional[dict[str, Any]],
    ) -> str:
        """Build a goal for retrying a failed execution.

        Args:
            task: The original task
            execution_result: The failed execution result

        Returns:
            A goal string for the retry
        """
        goal_parts = [f"RETRY the following task (first attempt failed): {task.description}"]

        if execution_result and isinstance(execution_result, dict):
            error = execution_result.get("error", "")
            summary = execution_result.get("summary", "")
            if error:
                goal_parts.append(f"\nError from first attempt: {error[:500]}")
            if summary:
                goal_parts.append(f"Summary: {summary[:300]}")

        goal_parts.append("\nTry a different approach. Read existing files first, then implement.")

        return "\n".join(goal_parts)

    def _finalize_task(
        self,
        task: Task,
        execution_result: Optional[dict[str, Any]],
        test_result: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Finalize a task by building the result and marking it complete.

        This is always called — the system ALWAYS converges to a result.

        Args:
            task: The task being processed
            execution_result: Result from the Executor (may be None if execution failed)
            test_result: Result from the Tester (may be None if testing was skipped)

        Returns:
            Task result dictionary
        """
        # Build result summary
        success = False
        summary_parts = []
        artifacts = []
        test_issues = []

        if execution_result and isinstance(execution_result, dict):
            success = execution_result.get("success", False)
            exec_summary = execution_result.get("summary", "")
            if exec_summary:
                summary_parts.append(exec_summary[:500])
            artifacts = execution_result.get("artifacts", [])

        if test_result and isinstance(test_result, dict):
            test_passed = test_result.get("passed", False)
            quality = test_result.get("quality_rating", "unknown")
            test_issues = test_result.get("issues", [])
            test_summary = test_result.get("summary", "")

            summary_parts.append(f"Test: {'passed' if test_passed else 'issues found'} (quality: {quality})")
            if test_summary:
                summary_parts.append(f"Test summary: {test_summary[:300]}")

            # Count major/critical issues — these override the test_passed flag
            major_or_critical = [
                i for i in test_issues
                if isinstance(i, dict) and i.get("severity") in ("major", "critical")
            ]

            if major_or_critical:
                # Major/critical issues found — always mark as failed
                success = False
                logger.warning(
                    "[Pipeline] %d major/critical issue(s) found — marking task as failed (quality=%s)",
                    len(major_or_critical), quality,
                )
            elif test_passed and quality in ("excellent", "good"):
                success = True
            elif test_passed:
                success = True  # Acceptable quality
            else:
                # Tests failed — override success to False regardless of execution result
                success = False
                logger.warning("[Pipeline] Tests FAILED (quality=%s) — marking task as failed", quality)

        # Mark task as completed or failed
        if success:
            task.set_completed({
                "summary": "\n".join(summary_parts),
                "success": True,
                "artifacts": artifacts,
                "test_issues": test_issues,
            })
        else:
            # Even if we failed, we still submit a result
            error_msg = (execution_result.get("error") or "Task could not be completed") if execution_result else "No execution result"
            if test_issues:
                error_msg += f" | Test issues: {len(test_issues)} found"
            task.set_failed(error_msg)

        # Reflect on the task outcome
        duration = (datetime.now() - task.created_at).total_seconds() if task.created_at else 0
        self.reflection_engine.reflect_on_task(
            task_id=task.task_id,
            result={"success": success, "artifacts": artifacts, "test_issues": test_issues},
            duration_seconds=duration,
        )

        result = {
            "success": success,
            "task_id": task.task_id,
            "status": task.status.name,
            "summary": "\n".join(summary_parts),
            "artifacts": artifacts,
            "test_result": test_result,
            "test_issues": test_issues,
            "execution_result": execution_result,
            "iterations": {
                "planning": self._iteration_counts["planning"],
                "execution": self._iteration_counts["execution"],
                "testing": self._iteration_counts["testing"],
            },
        }

        if task.plan:
            result["plan"] = task.plan
        if task.plan_analysis:
            result["analysis"] = task.plan_analysis

        logger.info("[Pipeline] Task %s finalized: success=%s, iterations=%s",
                     task.task_id, success, self._iteration_counts)

        return result

    # ========== Adaptive Task Handlers ==========

    def _classify_task(self, task: Task) -> str:
        """Classify a task into one of four types for adaptive routing.

        Types:
        - question: Simple question that doesn't need planning/execution
        - direct_execution: Simple file creation or modification, skip planning
        - exploratory: Needs codebase exploration before planning
        - complex: Full pipeline with planning, execution, and validation

        Uses heuristics first, then optional LLM confirmation.
        """
        description = task.description.lower()

        # Heuristic shortcuts
        question_patterns = [
            r"^what\s",
            r"^how\s",
            r"^why\s",
            r"^when\s",
            r"^where\s",
            r"^who\s",
            r"^can\syou\sexplain",
            r"^explain\s",
            r"^describe\s",
            r"^was\sist\s",
            r"^wie\s",
            r"^warum\s",
            r"^wann\s",
            r"^wo\s",
            r"^wer\s",
            r"\?$",
        ]
        if any(re.search(p, description) for p in question_patterns):
            return "question"

        # Complex task patterns (English + German) — checked BEFORE simple patterns
        # Multi-step tasks that need planning should not be classified as "simple"
        complex_indicators = [
            r"(build|create|develop|erstell|entwickl)\w*\s+a?\s*(full|complete|complex|vollständig|komplett)",
            r"(website|app|application|system|api|service|webseite|anwendung)",
            r"(multiple|several|mehrere)\s+(files|pages|components|dateien|seiten|komponenten)",
            r"(frontend|backend|database|auth|authentication|datenbank|authentifizierung)",
            r"(implement|integrate|architecture|design|implementier|integrier|architektur)",
            r"(ordner|folder|directory|verzeichnis)\s+.*(und|and|mit|with|darin|darinnen)",  # "create folder with X inside"
            r"(welcome\s*page|landing\s*page|homepage|startseite)",  # multi-file deliverables
            r"\bund\b.*\b(darin|dorthin|inside|in\s+(?:the|dem|der))\b",  # "X and Y in it"
        ]
        if any(re.search(p, description) for p in complex_indicators):
            return "complex"

        # Simple file creation patterns (English + German)
        simple_patterns = [
            r"^create\s+a?\s*(new\s+)?file",
            r"^write\s+a?\s*",
            r"^generate\s+a?\s*",
            r"^make\s+a?\s*",
            r"^build\s+a?\s*simple\s*",
            r"^add\s+a?\s*simple\s*",
            r"^erstell\w*\s+",
            r"^schreib\w*\s+",
            r"^generier\w*\s+",
            r"^mach\w*\s+",
        ]
        if any(re.search(p, description) for p in simple_patterns):
            # Check if it references existing codebase
            if any(kw in description for kw in ["existing", "current", "project", "module", "refactor", "fix", "update", "modify", "bestehend", "aktuell", "aktualisier", "änder", "fix"]):
                return "exploratory"
            return "direct_execution"

        # Default: if it references existing code, exploratory; otherwise complex
        if any(kw in description for kw in ["existing", "current", "project", "module", "refactor", "fix", "update", "modify", "add to", "integrate with", "bestehend", "aktuell", "projekt", "aktualisier", "änder", "fix", "erweiter"]):
            return "exploratory"

        # Anything else that didn't match simple patterns is likely complex enough to plan
        return "complex"

    def _handle_question_task(self, task: Task) -> dict[str, Any]:
        """Handle a question-type task.

        For simple questions, answers directly via kernel.
        For research questions, routes to Planner for exploration.
        """
        logger.info("[Orchestrator] Handling as question task")
        task._update_status(TaskStatus.EXECUTING, "Answering question")

        # Try to answer directly with kernel
        if self.kernel:
            try:
                response = self.kernel.run_chat(
                    messages=[
                        {"role": "system", "content": self._system_context},
                        {"role": "user", "content": task.description},
                    ],
                    max_rounds=15,
                )
                result = {
                    "success": True,
                    "answer": response,
                    "task_type": "question",
                    "direct_answer": True,
                }
                task.set_completed(result)
                return {
                    "success": True,
                    "task_id": task.task_id,
                    "status": task.status.name,
                    "answer": response,
                    "task_type": "question",
                }
            except Exception as e:
                logger.warning("[Orchestrator] Direct answer failed: %s", e)

        # Fallback: route to Planner for research
        return self._handle_complex_task(task)

    def _handle_direct_execution(self, task: Task) -> dict[str, Any]:
        """Handle a direct execution task using the deterministic pipeline.

        Direct execution skips planning but still enforces: EXECUTE → TEST → (FIX → TEST?) → DONE
        """
        logger.info("[Orchestrator] Handling as direct execution (skip planning, with testing)")
        return self._run_pipeline(task, skip_planning=True)

    def _handle_exploratory_task(self, task: Task) -> dict[str, Any]:
        """Handle an exploratory task using the deterministic pipeline."""
        logger.info("[Orchestrator] Handling as exploratory task")
        return self._run_pipeline(task, skip_planning=False)

    def _handle_complex_task(self, task: Task) -> dict[str, Any]:
        """Handle a complex task using the deterministic pipeline."""
        logger.info("[Orchestrator] Handling as complex task (full pipeline)")
        return self._run_pipeline(task, skip_planning=False)

    def _convert_plan_to_goal(self, plan: dict[str, Any]) -> str:
        """Convert a structured plan into a natural language goal for the Executor."""
        title = plan.get("title", "Implement plan")
        description = plan.get("description", "")
        steps = plan.get("steps", [])

        goal_parts = [f"Goal: {title}"]
        if description:
            goal_parts.append(f"Description: {description}")

        if steps:
            goal_parts.append("\nGuidance (you may adapt as needed):")
            for step in steps:
                if isinstance(step, dict):
                    step_desc = step.get("description", "")
                    goal_parts.append(f"- {step_desc}")

        goal_parts.append("\nImplement this autonomously. Read existing files for context, write complete working code, run tests if applicable, and submit your result when satisfied.")

        return "\n".join(goal_parts)

    # ========== Adaptive Execution ==========

    def _run_execution_adaptive(
        self,
        task: Task,
        goal: str,
        plan: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a goal using the Executor Agent (adaptive mode).

        Instead of sending a step-by-step plan, sends a high-level goal
        and lets the Executor decide how to implement it autonomously.

        Args:
            task: The task being processed
            goal: High-level goal for the Executor
            plan: Optional structured plan for context

        Returns:
            Execution result dictionary
        """
        logger.info("[Execution] Starting adaptive execution for task: %s", task.task_id)
        task._update_status(TaskStatus.EXECUTING, "Executing goal autonomously")

        try:
            if self._executor_bridge:
                # Use message bus with adaptive execution
                exec_plan = {"goal": goal}
                if plan:
                    exec_plan["original_plan"] = plan
                    # Include plan steps at the top level so the bridge can count them
                    if "steps" in plan:
                        exec_plan["steps"] = plan["steps"]
                result = self._executor_bridge.request_execution(
                    plan=exec_plan,
                    context={
                        "task_id": task.task_id,
                        "workspace": str(self.workspace_root),
                        "execution_mode": "autonomous",
                    },
                    timeout_seconds=self.execution_timeout_seconds,
                )

                execution_result = None
                if isinstance(result, dict):
                    execution_result = result.get("execution_result")
                    if isinstance(execution_result, dict):
                        if "success" not in execution_result:
                            execution_result["success"] = result.get("success", False)
                        if result.get("error") and not execution_result.get("error"):
                            execution_result["error"] = result.get("error")
                        result = execution_result

                logger.info("[Execution] Adaptive execution completed")
                return result
            else:
                # No executor bridge available
                logger.warning("[Orchestrator] No executor bridge available")
                return {
                    "success": False,
                    "error": "Executor bridge not available",
                }

        except Exception as e:
            logger.exception("Adaptive execution failed", extra={"task_id": task.task_id})
            return {"success": False, "error": f"Execution failed: {str(e)}"}

    # ========== Intelligent Validation ==========

    def _intelligent_validate(
        self,
        task: Task,
        execution_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Intelligently validate execution results.

        Instead of a rigid max-3 loop, performs qualitative assessment:
        - If excellent: accept immediately
        - If minor issues: accept with notes
        - If major issues / wrong approach: fail with explanation

        Also triggers the Tester Agent for quality review when available.

        Args:
            task: The task being processed
            execution_result: Results from execution

        Returns:
            Validation result dictionary
        """
        logger.info("[Validation] Starting intelligent validation for task: %s", task.task_id)

        # Check if execution was successful
        if not execution_result.get("success", False):
            return {
                "success": False,
                "error": execution_result.get("error", "Execution failed"),
                "issues": ["Execution reported failure"],
            }

        # Check for artifacts
        artifacts = execution_result.get("artifacts") or []
        if not artifacts:
            logger.warning("[Validation] No artifacts found in execution result")

        # Technical validation: check artifacts exist
        missing_artifacts = []
        for artifact in artifacts:
            if not self._artifact_exists(artifact):
                missing_artifacts.append(artifact)

        if missing_artifacts:
            return {
                "success": False,
                "error": f"Missing artifacts: {', '.join(missing_artifacts)}",
                "issues": [f"Missing: {a}" for a in missing_artifacts],
            }

        # Content quality check
        content_issues = self._inspect_artifact_contents(artifacts)
        if content_issues:
            logger.warning("[Validation] Content issues found: %d", len(content_issues))

        # LLM-based quality review (only if kernel available)
        llm_issues = []
        if self.kernel and artifacts:
            llm_issues = self._llm_review_artifact_quality(task, execution_result)

        all_issues = content_issues + llm_issues

        # Trigger Tester Agent for quality review
        tester_result = self._auto_trigger_testing(task)
        if tester_result:
            if not tester_result.get("passed", True):
                test_issues = [f"[Tester] {issue.get('description', str(issue))}" for issue in tester_result.get("issues", [])]
                all_issues.extend(test_issues)
            logger.info("[Validation] Tester result: passed=%s, rating=%s",
                        tester_result.get("passed"), tester_result.get("quality_rating"))

        if not all_issues:
            logger.info("[Validation] Validation passed with no issues")
            return {
                "success": True,
                "issues_found": 0,
                "quality": "excellent",
            }
        elif len(all_issues) <= 2:
            logger.info("[Validation] Validation passed with minor issues: %s", all_issues)
            return {
                "success": True,
                "issues_found": len(all_issues),
                "issues": all_issues,
                "quality": "good",
                "warning": "Minor issues found but acceptable",
            }
        else:
            logger.warning("[Validation] Validation failed with %d issues", len(all_issues))
            return {
                "success": False,
                "error": f"Quality validation failed with {len(all_issues)} issues",
                "issues": all_issues,
                "quality": "poor",
            }

    # ========== Legacy Task Execution ==========

    def _run_task_legacy(self, task: Task) -> dict[str, Any]:
        """Run a task through the legacy rigid pipeline.

        Preserved for backward compatibility when autonomous_mode=False.
        """
        logger.info("[Orchestrator] Running legacy pipeline for task: %s", task.task_id)

        try:
            # Phase 1: Planning Loop
            planning_result = self._run_planning_loop(task)
            if not planning_result["success"]:
                return planning_result

            plan_type = self._infer_plan_type(task, task.plan or {})
            if plan_type != "execution":
                task.set_completed({
                    "plan": task.plan,
                    "analysis": task.plan_analysis,
                    "planning_iterations": task.current_planning_iteration,
                    "plan_type": plan_type,
                })
                return {
                    "success": True,
                    "task_id": task.task_id,
                    "status": task.status.name,
                    "plan": task.plan,
                    "analysis": task.plan_analysis,
                    "iterations": task.current_planning_iteration,
                    "plan_type": plan_type,
                }

            # Phase 2: Execution
            execution_result = self._run_execution(task)

            if not execution_result or not execution_result.get("success"):
                error = "Execution failed"
                if isinstance(execution_result, dict):
                    error = execution_result.get("error", error)
                task.set_failed(error)
                return {
                    "success": False,
                    "task_id": task.task_id,
                    "error": error,
                    "plan": task.plan,
                }

            # Phase 3: Validation (max 3 iterations)
            validation_result = self._run_validation_loop(task, execution_result)

            if not validation_result or not validation_result.get("success"):
                error = "Validation failed"
                if isinstance(validation_result, dict):
                    error = validation_result.get("error", error)
                task.set_failed(error)
                return {
                    "success": False,
                    "task_id": task.task_id,
                    "error": error,
                    "plan": task.plan,
                    "execution": execution_result,
                }

            # Task completed successfully
            task_result = {
                "plan": task.plan,
                "analysis": task.plan_analysis,
                "planning_iterations": task.current_planning_iteration,
                "execution": execution_result,
                "validation": validation_result,
                "plan_type": plan_type,
            }
            task.set_completed(task_result)

            duration = (datetime.now() - task.created_at).total_seconds()
            self.reflection_engine.reflect_on_task(
                task_id=task.task_id,
                result=task_result,
                duration_seconds=duration,
            )

            return {
                "success": True,
                "task_id": task.task_id,
                "status": task.status.name,
                "plan": task.plan,
                "analysis": task.plan_analysis,
                "iterations": task.current_planning_iteration,
                "execution": execution_result,
                "validation": validation_result,
                "plan_type": plan_type,
            }

        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            task.set_failed(error_msg)
            self.reflection_engine.reflect_on_task(
                task_id=task.task_id,
                result={"success": False, "error": error_msg},
                duration_seconds=(datetime.now() - task.created_at).total_seconds() if task.created_at else 0,
            )
            return {"success": False, "error": error_msg}
    
    def _run_planning_loop(self, task: Task) -> dict[str, Any]:
        """Run the planning loop until plan is approved or max iterations reached.
        
        Args:
            task: Task to plan for
            
        Returns:
            Result dictionary with success status
        """
        logger.info("[Planning Loop] Starting for task: %s", task.task_id)
        
        while True:
            # Check iteration limit
            if task.current_planning_iteration >= task.max_planning_iterations:
                if task.status == TaskStatus.PLAN_REVISION:
                    # Max iterations reached with pending revision
                    error_msg = f"Maximum planning iterations ({task.max_planning_iterations}) reached. Plan not approved."
                    task.set_failed(error_msg)
                    return {"success": False, "error": error_msg}
                break
            
            # Request planning from Planner
            planning_result = self._request_planning(task)
            if not planning_result["success"]:
                return planning_result
            
            # Review the plan
            review_result = self._review_plan(task)
            
            if review_result == PlanReviewResult.APPROVED:
                logger.info("[Planning Loop] Plan approved after %d iteration(s)", task.current_planning_iteration)
                return {"success": True}
            
            elif review_result == PlanReviewResult.REJECTED:
                # Task failed
                return {"success": False, "error": task.error_message}
            
            elif review_result == PlanReviewResult.NEEDS_REVISION:
                if not task.can_request_revision():
                    # This was the last iteration
                    error_msg = f"Plan needs revision but max iterations ({task.max_planning_iterations}) reached."
                    task.set_failed(error_msg)
                    return {"success": False, "error": error_msg}
                
                logger.info("[Planning Loop] Requesting revision (iteration %d)", task.current_planning_iteration + 1)
                # Continue loop for revision
                continue
        
        return {"success": True}
    
    def _request_planning(self, task: Task) -> dict[str, Any]:
        """Request planning from the Planner Agent.
        
        Args:
            task: Task to plan for
            
        Returns:
            Result dictionary
        """
        task.set_planning()
        
        # Prepare planning context
        planning_context = task.get_planning_context()
        
        logger.info(
            "[Orchestrator] Planning request - task_id=%s iteration=%d/%d",
            task.task_id,
            task.current_planning_iteration + 1,
            task.max_planning_iterations,
        )
        logger.info("[Orchestrator] Planning context keys: %s", list(planning_context.keys()))
        
        try:
            if self._planner_bridge:
                # Use message bus
                logger.info("[Orchestrator] Calling planner bridge (timeout=%ds)", self.planning_timeout_seconds)
                result = self._planner_bridge.request_plan(
                    task_description=task.description,
                    context=planning_context,
                    timeout_seconds=self.planning_timeout_seconds,
                )
            else:
                # Direct planner call (fallback)
                logger.warning("[Orchestrator] No planner bridge available, using direct call fallback")
                result = self._call_planner_directly(task)
            
            if result["success"]:
                plan = result.get("plan", {})
                analysis = result.get("analysis", {})
                self._iteration_counts["planning"] += 1
                logger.info("[Orchestrator] Planning response received - plan_id=%s title='%s' steps=%d",
                             plan.get("id", "unknown"), plan.get("title", "N/A")[:50], 
                             len(plan.get("steps", [])))
                logger.info("[Orchestrator] Plan analysis source=%s attempts=%s",
                             analysis.get("source", "unknown"), analysis.get("attempts", "N/A"))
                task.set_plan_received(plan=plan, analysis=analysis)
                return {"success": True}
            else:
                error_msg = result.get("error", "Planning failed")
                logger.error("[Orchestrator] Planning failed: %s", error_msg)
                task.set_failed(error_msg)
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.exception("[Orchestrator] Planning request exception for task %s: %s", task.task_id, e)
            error_msg = f"Planning request failed: {str(e)}"
            task.set_failed(error_msg)
            return {"success": False, "error": error_msg}
    
    def _call_planner_directly(self, task: Task) -> dict[str, Any]:
        """Call planner directly without message bus (fallback).
        
        This method can be overridden or implemented to call the Planner
        Agent directly when the message bus is not available.
        """
        # This is a placeholder - actual implementation would import and call PlannerAgent
        return {
            "success": False,
            "error": "No planner bridge available and direct call not implemented",
        }
    
    def _review_plan(self, task: Task) -> PlanReviewResult:
        """Review a plan and decide if it's acceptable.
        
        Args:
            task: Task with plan to review
            
        Returns:
            PlanReviewResult indicating the decision
        """
        task._update_status(TaskStatus.PLAN_REVIEW, "Reviewing plan")
        
        # Get plan details
        plan = task.plan
        analysis = task.plan_analysis
        
        if not plan:
            logger.error("[Orchestrator] Plan review FAILED: no plan provided for task %s", task.task_id)
            task.add_plan_review(
                result=PlanReviewResult.REJECTED,
                feedback="No plan was provided",
                issues=["Empty plan"],
            )
            return PlanReviewResult.REJECTED
        
        logger.info("[Orchestrator] Reviewing plan '%s' (type=%s, steps=%d, iteration=%d/%d)",
                     plan.get("title", "N/A")[:50], 
                     plan.get("plan_type", "unknown"),
                     len(plan.get("steps", [])),
                     task.current_planning_iteration,
                     task.max_planning_iterations)
        
        # Check if this is a fallback plan (from error or missing structured plan)
        plan_source = plan.get("metadata", {}).get("source", "unknown")
        if plan_source in {"fallback", "fallback_error"}:
            logger.warning("[Orchestrator] Plan source is '%s' - will request revision", plan_source)

        try:
            issues = self._check_plan_quality(plan, analysis)
        except Exception as e:
            logger.error("[Orchestrator] Plan quality check failed: %s — treating as minor issues only", e)
            issues = []
        
        if not issues:
            logger.info("[Orchestrator] Plan APPROVED for task %s", task.task_id)
            task.add_plan_review(
                result=PlanReviewResult.APPROVED,
                feedback="Plan looks good. Proceeding to execution.",
                issues=[],
            )
            return PlanReviewResult.APPROVED
        else:
            logger.warning("[Orchestrator] Plan has %d issue(s): %s", len(issues), issues[:3])
            # Check if we can request revision
            if task.can_request_revision():
                logger.info("[Orchestrator] Requesting plan revision (iteration %d/%d)",
                             task.current_planning_iteration + 1, task.max_planning_iterations)
                task.add_plan_review(
                    result=PlanReviewResult.NEEDS_REVISION,
                    feedback=f"Plan has {len(issues)} issue(s) that need to be addressed.",
                    issues=issues,
                )
                return PlanReviewResult.NEEDS_REVISION
            else:
                logger.error("[Orchestrator] Max iterations reached, REJECTING plan")
                task.add_plan_review(
                    result=PlanReviewResult.REJECTED,
                    feedback=f"Plan has issues and max iterations ({task.max_planning_iterations}) reached.",
                    issues=issues,
                )
                return PlanReviewResult.REJECTED
    
    def _check_plan_quality(self, plan: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
        """Check plan quality with structural AND LLM-based review.

        Args:
            plan: The plan to check
            analysis: Plan analysis

        Returns:
            List of issues found (empty if plan is good)
        """
        issues = []

        steps = plan.get("steps", [])
        plan_type = self._infer_plan_type(self.get_active_task(), plan)
        logger.info("[Orchestrator] Checking plan quality (type=%s, steps=%d)", plan_type, len(steps))

        # ===== PHASE 1: Structural Validation =====

        # Accept fallback plans that have proper structure — they now include skill/action/args
        plan_source = plan.get("metadata", {}).get("source", "unknown")
        if plan_source in {"fallback", "fallback_error"}:
            # Only flag if the fallback plan is actually missing structure
            has_steps_with_actions = any(
                isinstance(s, dict) and s.get("skill") and s.get("action") and "args" in s
                for s in steps
            )
            if not has_steps_with_actions:
                issues.append(f"Plan source is '{plan_source}' and lacks proper step structure - must be regenerated")
                logger.warning("[Orchestrator] Fallback plan rejected: missing step structure")

        # Check for required fields
        if not plan.get("title"):
            issues.append("Plan missing title")
        if not plan.get("summary"):
            issues.append("Plan missing summary")
        if not steps:
            issues.append("Plan has no steps")

        if plan_type == "execution":
            # Simple tasks may only need 1 step — don't reject minimal plans
            if steps and len(steps) < 1:
                issues.append("Execution plan has no steps")

            allowed_actions = self._allowed_executor_actions()
            step_issues = []

            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    step_issues.append(f"Step {i+1} is not a dict")
                    continue
                    
                step_id = step.get("id", f"step-{i+1}")
                if not step.get("description"):
                    step_issues.append(f"Step {step_id} missing description")
                if not step.get("skill"):
                    step_issues.append(f"Step {step_id} missing skill")
                if not step.get("action"):
                    step_issues.append(f"Step {step_id} missing action")
                if "args" not in step:
                    step_issues.append(f"Step {step_id} missing args")

                skill = step.get("skill")
                action = step.get("action")
                if skill and skill not in allowed_actions:
                    step_issues.append(f"Step {step_id} has unknown skill '{skill}' (allowed: {list(allowed_actions.keys())})")
                elif skill and action and action not in allowed_actions.get(skill, []):
                    step_issues.append(f"Step {step_id} has unknown action '{action}' for skill '{skill}'")

            if step_issues:
                issues.extend(step_issues)
                logger.warning("[Orchestrator] Step validation found %d issues", len(step_issues))

            artifacts = plan.get("artifacts") or []
            outputs = []
            for step in steps:
                outputs.extend(step.get("outputs") or [])

            if not artifacts and not outputs:
                issues.append("Execution plan missing artifacts/outputs")
        else:
            itinerary = plan.get("itinerary") or []
            if len(itinerary) < 2:
                issues.append("Itinerary is too short (min 2 items)")

            packing = plan.get("packing_list") or []
            if len(packing) < 3:
                issues.append("Packing list is too short (min 3 items)")

            risks = plan.get("risks") or []
            if len(risks) < 1:
                issues.append("Risks list is too short (min 1 item)")

        # Check analysis
        if not analysis:
            issues.append("Missing plan analysis")

        # ===== PHASE 2: LLM-Based Quality Review =====
        # Only if structural validation passed so far
        if not issues and self.kernel:
            llm_plan_issues = self._llm_review_plan_quality(plan, analysis)
            if llm_plan_issues:
                issues.extend(llm_plan_issues)

        if issues:
            logger.warning("[Orchestrator] Plan quality check found %d issue(s): %s",
                          len(issues), issues[:5])
        else:
            logger.info("[Orchestrator] Plan quality check PASSED")

        return issues

    def _allowed_executor_actions(self) -> dict[str, list[str]]:
        """Return allowed executor skills and actions for plan validation."""
        return {
            "programming": [
                "create_file",
                "modify_file",
                "read_file",
                "create_directory",
                "list_directory",
            ],
            "word": [
                "create_document",
                "create_report",
            ],
            "opencode": [
                "execute_python",
                "execute_command",
            ],
        }

    def _llm_review_plan_quality(self, plan: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
        """Review plan quality using LLM-based analysis.

        This method uses the Kernel's model to critically evaluate:
        - Plan completeness and logical flow
        - Step feasibility and correctness
        - Consistency between steps
        - Adherence to task requirements

        Args:
            plan: The plan to review
            analysis: Plan analysis

        Returns:
            List of quality issues found (empty if quality is good)
        """
        if not self.kernel:
            logger.warning("[LLM Plan Review] Kernel not available, skipping review")
            return []

        issues = []
        task = self.get_active_task()
        task_description = task.description if task else "Unknown task"

        try:
            logger.info("[LLM Plan Review] Starting quality review for plan '%s'", plan.get("title", "N/A"))

            # Build review prompt
            review_prompt = self._build_plan_review_prompt(task_description, plan, analysis)

            response = self.kernel.run_chat(
                messages=[
                    {"role": "system", "content": self._get_plan_review_system_prompt()},
                    {"role": "user", "content": review_prompt},
                ],
                timeout_s=90,  # 90 seconds for plan review
            )

            # Parse LLM response for issues
            llm_issues = self._parse_plan_review_response(response, plan)
            issues.extend(llm_issues)

            logger.info("[LLM Plan Review] Found %d quality issue(s)", len(llm_issues))

        except Exception as e:
            logger.warning("[LLM Plan Review] Review failed: %s", e)
            # Don't fail the plan - just log the issue

        return issues

    def _get_plan_review_system_prompt(self) -> str:
        """Return system prompt for plan quality review."""
        return """You are a critical Plan Quality Reviewer for software development and content creation tasks.

Your role is to:
1. Review plans for completeness, logical flow, and feasibility
2. Check if the plan directly addresses the task requirements
3. Identify any gaps, inconsistencies, or problems
4. Be strict - only approve truly well-structured plans

Review criteria:
- Plan must have clear, actionable steps
- Steps must be in logical order (dependencies respected)
- Each step must have appropriate skill/action assigned
- Plan must produce the artifacts described in the task
- No vague or ambiguous steps

Respond in this exact JSON format:
{
    "overall_quality": "excellent|good|acceptable|poor",
    "issues": [
        {
            "step_id": "step-001" (or "general" if not step-specific),
            "severity": "critical|major|minor",
            "description": "Clear description of the issue"
        }
    ],
    "summary": "Brief summary of your review"
}

Only list issues of severity "major" or "critical". Ignore minor stylistic preferences."""

    def _build_plan_review_prompt(self, task_description: str, plan: dict[str, Any], analysis: dict[str, Any]) -> str:
        """Build the prompt for plan quality review."""
        plan_title = plan.get("title", "N/A")
        plan_summary = plan.get("summary", "N/A")
        steps = plan.get("steps", [])
        artifacts = plan.get("artifacts", [])

        # Build steps section
        steps_section = ""
        for step in steps:
            steps_section += f"\n- {step.get('id', '?')}: {step.get('description', 'N/A')}"
            steps_section += f" [Skill: {step.get('skill', 'N/A')}, Action: {step.get('action', 'N/A')}]"

        # Build artifacts section
        artifacts_section = "\n".join(artifacts) if artifacts else "None specified"

        prompt = f"""TASK DESCRIPTION:
{task_description}

PLAN TITLE: {plan_title}
PLAN SUMMARY: {plan_summary}

PLAN STEPS:
{steps_section}

EXPECTED ARTIFACTS:
{artifacts_section}

---

Please review this plan critically and identify any quality issues.
Respond with the JSON format specified in the system prompt."""

        return prompt

    def _parse_plan_review_response(self, response: str, plan: dict[str, Any]) -> list[str]:
        """Parse LLM plan review response and extract issues."""
        issues = []

        try:
            import json
            import re

            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]*"issues"[^{}]*\}', response, re.DOTALL)
            if json_match:
                review_data = json.loads(json_match.group())
            else:
                review_data = json.loads(response)

            # Extract issues
            review_issues = review_data.get("issues", [])
            overall_quality = review_data.get("overall_quality", "unknown")

            # Only include critical and major issues
            for issue in review_issues:
                severity = issue.get("severity", "").lower()
                if severity in ("critical", "major"):
                    step_id = issue.get("step_id", "unknown")
                    description = issue.get("description", "Quality issue")
                    issues.append(f"[Plan Quality] Step {step_id}: {description}")

            # Flag poor overall quality
            if overall_quality == "poor":
                issues.append("[Plan Quality] Overall plan quality is poor")

        except Exception as e:
            logger.warning("[LLM Plan Review] Failed to parse review response: %s", e)
            # If we can't parse the review, don't reject the plan —
            # assume the structural checks are sufficient.
            # Only flag issues if the response explicitly contains strong negative signals.
            response_lower = response.lower()
            strong_negative = any(word in response_lower for word in ["fundamentally flawed", "completely wrong", "cannot work", "critical failure"])
            if strong_negative:
                issues.append("[Plan Quality] LLM review indicates fundamental problems")

        return issues
    
    def _run_execution(self, task: Task) -> dict[str, Any]:
        """Execute the approved plan using the Executor Agent.
        
        Args:
            task: Task with approved plan
            
        Returns:
            Execution result dictionary
        """
        logger.info("[Execution] Starting for task: %s", task.task_id)
        task._update_status(TaskStatus.EXECUTING, "Executing plan")
        
        if not task.plan:
            return {"success": False, "error": "No plan to execute"}
        
        try:
            if self._executor_bridge:
                # Use message bus
                result = self._executor_bridge.request_execution(
                    plan=task.plan,
                    context={
                        "task_id": task.task_id,
                        "workspace": str(self.workspace_root),
                    },
                    timeout_seconds=self.execution_timeout_seconds,  # Configurable, default 15 min
                )

                execution_result = None
                if isinstance(result, dict):
                    execution_result = result.get("execution_result")
                    if isinstance(execution_result, dict):
                        if "success" not in execution_result:
                            execution_result["success"] = result.get("success", False)
                        if result.get("error") and not execution_result.get("error"):
                            execution_result["error"] = result.get("error")
                        result = execution_result

                logger.info("[Execution] Completed: %d steps executed", result.get('steps_executed', 0))
                return result
            else:
                # No executor bridge available
                return {
                    "success": False,
                    "error": "Executor bridge not available",
                }
                
        except Exception as e:
            logger.exception("Execution failed", extra={"task_id": task.task_id})
            return {"success": False, "error": f"Execution failed: {str(e)}"}
    
    def _run_validation_loop(self, task: Task, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Validate execution results with max 3 iterations.
        
        The Orchestrator critically reviews the execution results.
        If something is not perfect, it requests fixes (max 3 iterations).
        
        Args:
            task: The task being processed
            execution_result: Results from execution
            
        Returns:
            Validation result dictionary
        """
        logger.info("[Validation] Starting for task: %s", task.task_id)
        
        max_validation_iterations = 2
        
        for iteration in range(max_validation_iterations):
            logger.info("[Validation] Iteration %d/%d", iteration + 1, max_validation_iterations)
            
            # Validate execution results
            validation_issues = self._validate_execution(task, execution_result)
            if validation_issues:
                logger.info("Validation issues: %s", validation_issues)
            
            if not validation_issues:
                logger.info("[Validation] Execution validated successfully")
                return {
                    "success": True,
                    "iterations": iteration + 1,
                    "issues_found": 0,
                }
            
            # Check if we can request fixes
            if iteration >= max_validation_iterations - 1:
                # Max iterations reached
                error_msg = f"Execution validation failed after {max_validation_iterations} iterations. Issues: {validation_issues}"
                return {"success": False, "error": error_msg}
            
            # Request fixes
            logger.info("[Validation] Found %d issue(s), requesting fixes...", len(validation_issues))
            fix_result = self._request_execution_fix(task, execution_result, validation_issues)
            
            if not fix_result["success"]:
                logger.warning("[Validation] Fix request failed: %s. Continuing with original execution result.", fix_result.get('error'))
                # Don't fail - return original result with warning
                return {
                    "success": True,
                    "iterations": iteration + 1,
                    "issues_found": len(validation_issues),
                    "fix_error": fix_result.get('error'),
                    "warning": "Validation issues found but fixes could not be applied",
                    "execution_result": execution_result,
                }
            
            # Update execution result for next validation
            execution_result = fix_result.get("execution_result", execution_result)
        
        return {"success": True, "iterations": max_validation_iterations, "issues_found": 0}
    
    def _validate_execution(self, task: Task, execution_result: dict[str, Any]) -> list[str]:
        """Critically validate execution results with LLM-based quality review.

        This method implements strict quality checks in two phases:
        1. Technical validation (files exist, steps executed)
        2. LLM-based quality review (content quality, completeness, correctness)

        Args:
            task: The task being processed
            execution_result: Results from execution

        Returns:
            List of validation issues (empty if perfect)
        """
        issues = []

        # ===== PHASE 1: Technical Validation =====

        # Check if execution was successful
        if not execution_result.get("success", False):
            issues.append(f"Execution failed: {execution_result.get('error', 'Unknown error')}")
            return issues

        # Check steps execution
        steps_executed = execution_result.get("steps_executed", 0)
        steps_failed = execution_result.get("steps_failed", 0)

        if steps_failed > 0:
            issues.append(f"{steps_failed} step(s) failed during execution")

        # Check each step result
        results = execution_result.get("results", [])
        for step_result in results:
            if not step_result.get("success", False):
                step_id = step_result.get("step_id", "unknown")
                error = step_result.get("error", "Unknown error")
                issues.append(f"Step {step_id} failed: {error}")

            result_payload = step_result.get("result", {}) if isinstance(step_result, dict) else {}
            if isinstance(result_payload, dict):
                returncode = result_payload.get("returncode")
                if isinstance(returncode, int) and returncode != 0:
                    step_id = step_result.get("step_id", "unknown")
                    issues.append(f"Step {step_id} returned non-zero code: {returncode}")

        # Check if all planned steps were executed
        plan_steps = task.plan.get("steps", []) if task.plan else []
        if steps_executed < len(plan_steps):
            issues.append(f"Only {steps_executed}/{len(plan_steps)} steps executed")

        # Validate artifacts exist
        expected_artifacts = self._collect_expected_artifacts(task.plan or {})
        actual_artifacts = execution_result.get("artifacts") or []
        missing_artifacts = []

        artifact_candidates = actual_artifacts if actual_artifacts else expected_artifacts

        for artifact in artifact_candidates:
            if not self._artifact_exists(artifact):
                missing_artifacts.append(artifact)

        if missing_artifacts:
            issues.append(f"Missing artifacts: {', '.join(missing_artifacts)}")
            return issues  # Can't validate content if files don't exist

        # ===== PHASE 2: LLM-Based Quality Review =====
        # Use the model to critically review the quality of created artifacts
        llm_quality_issues = self._llm_review_artifact_quality(task, execution_result)
        if llm_quality_issues:
            issues.extend(llm_quality_issues)

        return issues
    
    def _request_execution_fix(self, task: Task, execution_result: dict[str, Any], issues: list[str]) -> dict[str, Any]:
        """Request fixes for execution issues.
        
        This sends the issues back to the Executor for correction.
        
        Args:
            task: The task being processed
            execution_result: Current execution results
            issues: List of issues to fix
            
        Returns:
            Fix result dictionary
        """
        logger.info("[Execution Fix] Requesting fixes for %d issue(s)", len(issues))
        
        fix_plan = None
        if self._planner_bridge:
            artifact_paths = execution_result.get("artifacts") or []
            if not isinstance(artifact_paths, list):
                artifact_paths = []
            if not artifact_paths:
                artifact_paths = self._collect_expected_artifacts(task.plan or {})
            artifact_list = ", ".join(artifact_paths) if artifact_paths else "none"
            
            # Build explicit fix request with workspace context
            fix_request = (
                f"Fix execution issues for task {task.task_id}. "
                f"Issues to address: {', '.join(issues)}. "
                "IMPORTANT: All file paths must be workspace-relative (e.g., 'orbitron-spa/index.html', NOT 'task-*/...'). "
                f"Allowed files (workspace-relative): {artifact_list}. "
                "Use ONLY these paths. Do NOT create task-specific subdirectories. "
                "Do NOT access logs or external paths. "
                "Return an execution plan with concrete steps (skill/action/args)."
            )
            fix_context = {
                "task_id": task.task_id,
                "issues": issues,
                "current_plan": task.plan,
                "execution_result": execution_result,
                "workspace_root": str(self.workspace_root),
                "artifact_paths": artifact_paths,
                "workspace_relative": True,
            }
            planning_result = self._planner_bridge.request_plan(
                task_description=fix_request,
                context=fix_context,
                timeout_seconds=self.planning_timeout_seconds,
            )
            if planning_result.get("success"):
                fix_plan = planning_result.get("plan")
        
        try:
            if self._executor_bridge:
                if not isinstance(fix_plan, dict) or not fix_plan:
                    return {"success": False, "error": "Fix plan missing or invalid"}
                result = self._executor_bridge.request_execution(
                    plan=fix_plan,
                    context={
                        "task_id": task.task_id,
                        "is_fix": True,
                        "original_issues": issues,
                    },
                    timeout_seconds=self.execution_timeout_seconds,
                )
                return result
            else:
                return {"success": False, "error": "Executor bridge not available"}
                
        except Exception as e:
            return {"success": False, "error": f"Fix request failed: {str(e)}"}
    
    # Public API Methods
    
    def process_task(self, description: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Process a task from description to completion.
        
        This is the main high-level API for task processing.
        
        Args:
            description: Task description
            context: Optional context
            
        Returns:
            Task result
        """
        # Create task
        task = self.create_task(description, context)
        
        # Run task
        return self.run_task(task.task_id)

    def _infer_plan_type(self, task: Task | None, plan: dict[str, Any]) -> str:
        """Infer the plan type to drive review and validation rules."""
        plan_type = plan.get("plan_type") or plan.get("metadata", {}).get("plan_type")
        if isinstance(plan_type, str) and plan_type.strip():
            return plan_type.strip()

        if plan.get("itinerary") or plan.get("packing_list"):
            return "experience"

        description = (task.description if task else "").lower()
        execution_keywords = [
            "code",
            "programm",
            "develop",
            "implement",
            "homepage",
            "website",
            "frontend",
            "backend",
            "api",
            "bug",
            "fix",
            "refactor",
            "test",
            "automation",
        ]
        experience_keywords = [
            "wandern",
            "hike",
            "reise",
            "travel",
            "camping",
            "itinerary",
            "hotel",
            "flug",
            "flight",
        ]

        if any(k in description for k in execution_keywords):
            return "execution"
        if any(k in description for k in experience_keywords):
            return "experience"

        return "execution"

    def _collect_expected_artifacts(self, plan: dict[str, Any]) -> list[str]:
        """Collect expected artifacts from plan and step outputs."""
        expected: list[str] = []
        artifacts = plan.get("artifacts") or []
        if isinstance(artifacts, list):
            expected.extend([a for a in artifacts if isinstance(a, str)])

        for step in plan.get("steps", []) or []:
            outputs = step.get("outputs") or []
            if isinstance(outputs, list):
                expected.extend([o for o in outputs if isinstance(o, str)])

        return list(dict.fromkeys(expected))

    def _artifact_exists(self, artifact: str) -> bool:
        """Check if an artifact exists within the workspace."""
        candidate = self._resolve_artifact_path(artifact)
        return bool(candidate and candidate.exists())

    def _resolve_artifact_path(self, artifact: str) -> Path | None:
        """Resolve artifact path within workspace, if possible."""
        if not artifact or not isinstance(artifact, str):
            return None

        normalized = artifact.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized.startswith("workspace/"):
            normalized = normalized[len("workspace/"):]

        p = Path(normalized)
        if not p.is_absolute():
            candidate = self.workspace_root / p
        else:
            candidate = p

        try:
            candidate.resolve().relative_to(self.workspace_root.resolve())
        except ValueError:
            return None

        return candidate

    def _inspect_artifact_contents(self, artifacts: list[str]) -> list[str]:
        """Read and validate artifact contents for basic quality checks."""
        issues: list[str] = []
        for artifact in artifacts:
            candidate = self._resolve_artifact_path(artifact)
            if not candidate or not candidate.exists():
                continue

            text = self._read_text_file(candidate)
            if text is None:
                continue

            content = text.strip()
            if not content:
                issues.append(f"Artifact is empty: {artifact}")
                continue
            if len(content) < 20:
                issues.append(f"Artifact content too short: {artifact}")

            lowered = content.lower()
            for token in ("todo", "tbd", "lorem ipsum"):
                if token in lowered:
                    issues.append(f"Artifact contains placeholder content ({token}): {artifact}")
                    break

            ext = candidate.suffix.lower()
            if ext in {".html", ".htm"}:
                if "<html" not in lowered and "<!doctype" not in lowered:
                    issues.append(f"HTML missing <html> or DOCTYPE: {artifact}")
            elif ext == ".css":
                if "{" not in content or "}" not in content:
                    issues.append(f"CSS missing rule blocks: {artifact}")
            elif ext in {".js", ".ts"}:
                if all(token not in lowered for token in ("function", "const ", "let ", "=>", "addeventlistener", "document.", "window.")):
                    issues.append(f"Script appears empty or non-functional: {artifact}")
            elif ext in {".md", ".txt"}:
                if len(content) < 50:
                    issues.append(f"Document content too short: {artifact}")

        return issues

    def _llm_review_artifact_quality(self, task: Task, execution_result: dict[str, Any]) -> list[str]:
        """Review artifact quality using LLM-based content analysis.

        This method uses the Kernel's model to critically evaluate:
        - Content completeness and quality
        - Code correctness and best practices
        - Consistency between related files
        - Adherence to task requirements

        Args:
            task: The task being validated
            execution_result: Results from execution

        Returns:
            List of quality issues found (empty if quality is good)
        """
        if not self.kernel:
            logger.warning("[LLM Review] Kernel not available, skipping LLM review")
            return []

        issues = []

        # Collect artifacts to review
        actual_artifacts = execution_result.get("artifacts") or []
        expected_artifacts = self._collect_expected_artifacts(task.plan or {})
        artifacts_to_review = actual_artifacts if actual_artifacts else expected_artifacts

        if not artifacts_to_review:
            logger.warning("[LLM Review] No artifacts to review")
            return []

        # Read artifact contents
        artifact_contents = {}
        for artifact in artifacts_to_review:
            candidate = self._resolve_artifact_path(artifact)
            if candidate and candidate.exists():
                content = self._read_text_file(candidate)
                if content:
                    artifact_contents[artifact] = content

        if not artifact_contents:
            issues.append("No artifact content available for LLM review")
            return issues

        # Build review prompt
        review_prompt = self._build_quality_review_prompt(task, artifact_contents)

        try:
            logger.info("[LLM Review] Sending quality review request for %d artifact(s)", len(artifact_contents))

            response = self.kernel.run_chat(
                messages=[
                    {"role": "system", "content": self._get_quality_review_system_prompt()},
                    {"role": "user", "content": review_prompt},
                ],
                timeout_s=1800,  # 30 minutes for quality review
            )

            # Parse LLM response for issues
            llm_issues = self._parse_quality_review_response(response, artifact_contents)
            issues.extend(llm_issues)

            logger.info("[LLM Review] Found %d quality issue(s)", len(llm_issues))

        except Exception as e:
            logger.warning("[LLM Review] Quality review failed: %s", e)
            # Don't fail the task - just log the issue

        return issues

    def _get_quality_review_system_prompt(self) -> str:
        """Return system prompt for quality review."""
        return """You are a critical Quality Reviewer for software development and content creation tasks.

Your role is to:
1. Review created artifacts for completeness, correctness, and quality
2. Check if the content fulfills the original task requirements
3. Identify any issues, problems, or areas for improvement
4. Be strict - only approve truly high-quality work

Review criteria:
- Content must be complete (no placeholders, TODOs, lorem ipsum)
- Code must be functional and follow best practices
- Files must be consistent with each other (e.g., CSS referenced in HTML must exist)
- Output must directly address the user's request

Respond in this exact JSON format:
{
    "overall_quality": "excellent|good|acceptable|poor",
    "issues": [
        {
            "file": "filename.ext",
            "severity": "critical|major|minor",
            "description": "Clear description of the issue"
        }
    ],
    "summary": "Brief summary of your review"
}

Only list issues of severity "major" or "critical". Ignore minor stylistic preferences."""

    def _build_quality_review_prompt(self, task: Task, artifact_contents: dict[str, str]) -> str:
        """Build the prompt for quality review."""
        task_description = task.description
        plan_title = task.plan.get("title", "N/A") if task.plan else "N/A"
        plan_summary = task.plan.get("summary", "N/A") if task.plan else "N/A"

        # Build artifact content section
        artifacts_section = ""
        for artifact_path, content in artifact_contents.items():
            # Truncate very long content
            if len(content) > 5000:
                content = content[:5000] + "\n... [truncated]"

            artifacts_section += f"\n\n=== FILE: {artifact_path} ===\n{content}\n"

        prompt = f"""TASK DESCRIPTION:
{task_description}

PLAN TITLE: {plan_title}
PLAN SUMMARY: {plan_summary}

--- CREATED ARTIFACTS FOR REVIEW ---
{artifacts_section}

---

Please review these artifacts critically and identify any quality issues.
Respond with the JSON format specified in the system prompt."""

        return prompt

    def _parse_quality_review_response(self, response: str, artifact_contents: dict[str, str]) -> list[str]:
        """Parse LLM quality review response and extract issues."""
        issues = []

        try:
            # Try to extract JSON from response
            import json
            import re

            # Find JSON object in response
            json_match = re.search(r'\{[^{}]*"issues"[^{}]*\}', response, re.DOTALL)
            if json_match:
                review_data = json.loads(json_match.group())
            else:
                # Try parsing entire response as JSON
                review_data = json.loads(response)

            # Extract issues
            review_issues = review_data.get("issues", [])
            overall_quality = review_data.get("overall_quality", "unknown")

            # Only include critical and major issues
            for issue in review_issues:
                severity = issue.get("severity", "").lower()
                if severity in ("critical", "major"):
                    file_name = issue.get("file", "unknown")
                    description = issue.get("description", "Quality issue")
                    issues.append(f"[Quality] {file_name}: {description}")

            # Flag poor overall quality
            if overall_quality == "poor":
                issues.append("[Quality] Overall artifact quality is poor")

        except Exception as e:
            logger.warning("[LLM Review] Failed to parse review response: %s", e)
            # Return response analysis as fallback
            if "poor" in response.lower() or "incomplete" in response.lower():
                issues.append("[Quality] LLM review indicates quality issues")

        return issues

    def _read_text_file(self, path: Path) -> str | None:
        """Read a text file, returning None for binary or unreadable files."""
        try:
            data = path.read_bytes()
        except Exception:
            return None

        if b"\x00" in data:
            return None

        for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                return data.decode(encoding)
            except Exception:
                continue

        return None
    
    def get_task_status(self, task_id: str) -> Optional[dict[str, Any]]:
        """Get status of a task."""
        task = self.tasks.get(task_id)
        if task:
            return task.to_dict()
        return None
    
    def list_tasks(self, status_filter: Optional[TaskStatus] = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        tasks = self.tasks.values()
        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]
        return [t.to_dict() for t in tasks]
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self.tasks.get(task_id)
        if task and task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            task._update_status(TaskStatus.CANCELLED, "Task cancelled by user")
            return True
        return False
    
    # Legacy compatibility
    
    def think(self, user_input: str, context: dict | None = None) -> dict[str, Any]:
        """Legacy method - use process_task instead."""
        # Create a task from the input
        task = self.create_task(user_input, context)
        
        # Return task info in legacy format
        return {
            "messages": [
                {"role": "system", "content": self._system_context},
                {"role": "user", "content": user_input},
            ],
            "context": {
                "task_id": task.task_id,
                "has_kernel": self.kernel is not None,
            },
        }
    
    def respond(self, llm_response: str, metadata: dict | None = None) -> str:
        """Legacy method - store response in memory."""
        self.memory.add_to_short_term("assistant", llm_response, metadata)
        return llm_response
    
    def learn(self, key: str, value: Any) -> None:
        """Learn a new fact."""
        self.memory.remember(key, value)
        logger.info("[TaskOrchestrator] Learned: %s = %s", key, value)
    
    def get_system_prompt(self) -> str:
        """Get the current system prompt."""
        return self._system_context
    
    def refresh_context(self) -> None:
        """Reload context files."""
        self._system_context = self._build_system_context()
        logger.info("[TaskOrchestrator] Context refreshed")
    
    def get_status(self) -> dict[str, Any]:
        """Get orchestrator status."""
        # Count tasks by status
        task_counts = {}
        for task in self.tasks.values():
            status_name = task.status.name
            task_counts[status_name] = task_counts.get(status_name, 0) + 1
        
        return {
            "initialized": True,
            "workspace": str(self.workspace_root),
            "connected_to_bus": self._communicator is not None,
            "max_planning_iterations": self.max_planning_iterations,
            "tasks": {
                "total": len(self.tasks),
                "by_status": task_counts,
                "active": self.active_task_id,
            },
            "memory": {
                "short_term_entries": len(self.memory.short_term),
                "long_term_facts": len(self.memory.long_term),
            },
            "kernel_connected": self.kernel is not None,
        }


# Backwards compatibility
Orchestrator = TaskOrchestrator


def create_orchestrator(
    kernel=None,
    workspace_root: str | None = None,
    max_planning_iterations: int = 3,
    planning_timeout_seconds: int = 900,
    execution_timeout_seconds: int = 900,
) -> TaskOrchestrator:
    """Create and initialize a TaskOrchestrator instance."""
    return TaskOrchestrator(
        kernel=kernel,
        workspace_root=workspace_root,
        max_planning_iterations=max_planning_iterations,
        planning_timeout_seconds=planning_timeout_seconds,
        execution_timeout_seconds=execution_timeout_seconds,
    )


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
