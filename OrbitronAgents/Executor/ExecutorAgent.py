"""Executor Agent - Autonomous Goal-Driven Solver for the Orbitron system.

The Executor Agent is responsible for autonomously implementing goals.
Instead of blindly following plan steps, it receives a goal, explores the codebase,
implement files, runs tests, fixes errors, and self-reviews before submitting results.

Key Principles:
- Receives GOALS, not step-by-step instructions
- Autonomously decides how to implement using tools
- Can read existing files, search codebase, run tests, fix errors
- Self-corrects iteratively until satisfied
- Submits result only when confident
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Import refactored skills from skills module
from OrbitronAgents.Executor.skills import ProgrammingSkill, WordSkill, OpenCodeSkill, ExecutorSkill
from OrbitronAgents.Executor.execution_state import ExecutionState, StepResult

# Import kernel components
from OrbitronKernel.kernel import AgentSkill

# Import autonomous agent base
from OrbitronAgents.base.autonomous_agent import AutonomousAgent, AgentLoopResult

logger = logging.getLogger("ExecutorAgent")


@dataclass
class ExecutionResult:
    """Result of an autonomous execution."""
    success: bool
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    error: Optional[str] = None
    tool_calls: int = 0
    rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "error": self.error,
            "tool_calls": self.tool_calls,
            "rounds": self.rounds,
        }


class ExecutorAgent:
    """Executor Agent - Autonomous Goal-Driven Solver.

    The Executor is the "doer" of the system, but now an INTELLIGENT doer:
    - Receives a GOAL (not step-by-step instructions)
    - Autonomously decides HOW to implement it
    - Reads existing code for context
    - Creates/modifies files as needed
    - Runs tests and checks syntax
    - Fixes errors iteratively
    - Reviews its own work before submission
    - Calls submit_result when satisfied
    """

    # Feature flag for migration
    autonomous_mode: bool = True

    def __init__(
        self,
        agent_name: str = "executor",
        workspace_root: str | None = None,
        kernel=None,
        max_rounds: int = 30,
    ):
        """Initialize the Executor Agent.

        Args:
            agent_name: Unique name for this executor instance
            workspace_root: Root directory for file operations
            kernel: Kernel instance for LLM and tool access (REQUIRED for autonomous mode)
            max_rounds: Maximum tool-calling rounds per goal
        """
        self.agent_name = agent_name
        self.workspace_root = Path(workspace_root) if workspace_root else Path.home() / ".orbitron" / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.kernel = kernel
        self.max_rounds = max_rounds
        self.skills: dict[str, Any] = {}

        # Execution state tracking (per-task)
        self._execution_states: dict[str, ExecutionState] = {}

        # Autonomous agent instance
        self._autonomous_agent: Optional[AutonomousAgent] = None
        if self.kernel:
            self._setup_autonomous_agent()

        # Legacy skills (kept for backward compatibility)
        self._register_default_skills()

        # Register skill tools into autonomous agent (must be after _register_default_skills)
        if self._autonomous_agent:
            self._register_skill_tools("word")

        logger.info("[ExecutorAgent] Initialized: %s (autonomous_mode=%s)", self.agent_name, self.autonomous_mode)
        logger.info("[ExecutorAgent] Workspace: %s", self.workspace_root)

    # ========== Autonomous Agent Setup ==========

    def _setup_autonomous_agent(self) -> None:
        """Create and configure the AutonomousAgent instance."""
        system_prompt = """You are the Orbitron Executor Agent. You receive a GOAL and autonomously implement it.

## Your Identity
You are the system's intelligent builder and implementer. You write code, create files, execute commands, and verify your work.
You do NOT plan or strategize — that is the Planner's job. You receive a goal and IMPLEMENT it.

## CRITICAL: Time Management
You have LIMITED rounds. You MUST call `submit_result` within 10-15 rounds.
- Round 1-2: Read ONLY the most critical files (max 2-3 files). Do NOT read the entire project.
- Round 3-8: Create/modify files to implement the goal. ACT FIRST, verify later.
- Round 8-12: **BUILD AND VERIFY** — Run the build/compile command and check for errors. Fix any errors.
- Round 12-15: Fix any remaining issues and call `submit_result`.
- Do NOT read more than 5 files total. If you need context, read the KEY file and start implementing.
- A working implementation that COMPILES is better than a perfect implementation that never completes.

## CRITICAL: Build Verification (MANDATORY)
Before calling `submit_result`, you MUST verify that your changes compile/build correctly:
- **BEST**: Use `verify_build` to auto-detect and run the correct build command. It returns structured results with error classification.
- **ALTERNATIVE**: Use `run_command` with the appropriate build command (e.g., `cd project && npm run build 2>&1`).
- ALWAYS check the `returncode` field: 0 = success, any other value = FAILURE.
- When a command fails, read the `stderr` field for error details. The `error_summary` and `suggestion` fields provide actionable guidance.
- If the build FAILS, you MUST fix the errors before submitting. Do NOT submit broken code.
- If you cannot fix all errors within your remaining rounds, still call `submit_result` but note the remaining issues.

## CRITICAL: Reading Command Output
When you run `run_command` or `verify_build`, the result contains structured output:
- `returncode`: 0 means success, any other value means failure. ALWAYS check this.
- `stdout`: The command's standard output. May be truncated for very long outputs.
- `stderr`: The command's error output. When returncode ≠ 0, this contains the error details.
- `error_type`: Classification of the error (build_error, dependency_error, timeout, etc.)
- `suggestion`: Actionable suggestion for fixing the error.
- `error_summary`: First few lines of the error output for quick diagnosis.
- If you see `❌ COMMAND FAILED` or `❌ BUILD FAILED`, the command did NOT succeed. Fix the errors and try again.
- If you see `✅ COMMAND SUCCEEDED` or `✅ BUILD SUCCEEDED`, the command succeeded.

## CRITICAL: You MUST Create/Modify Files
Your job is to IMPLEMENT changes, not just ANALYZE the codebase. You MUST use `create_file`, `update_file`, `create_document`, or `create_report` at least once before calling `submit_result`. If you call `submit_result` without having created or modified any files, that is a FAILURE. Reading files and reporting "looks good" is NOT acceptable.

## Your Capabilities
- Read files and directories to understand context
- Search the codebase for patterns and references
- Create, update, and delete files
- Create professional Word documents and reports
- Run shell commands and Python scripts
- Check syntax of code files
- Run tests to verify correctness
- Fix errors iteratively
- Review your own work before submission

## Workflow
1. **Context Gathering**: Read 1-2 KEY files only. Do NOT explore the entire project structure.
2. **Implementation**: Create and modify files. Write complete, production-ready code.
3. **Build Verification**: Run the build command (e.g., `ng build`, `npm run build`) and check for errors.
4. **Fix Errors**: If the build fails, read the error messages and fix the issues.
5. **Submission**: When the build succeeds OR you've exhausted your rounds, call `submit_result`.

## Important Rules
- Write COMPLETE, working code — no placeholders, no TODOs
- Follow existing patterns and conventions in the codebase
- Handle edge cases appropriately
- Keep code clean, readable, and maintainable
- ALWAYS verify your code compiles/builds before submitting
- If unsure about a requirement, you may call `ask_question`
- When done, ALWAYS call `submit_result` to finish

## Tool Guidelines
- `read_file`: Read existing code to understand context before modifying — but read ONLY what you need
- `list_directory`: Explore project structure — use SPARINGLY, only to find key files
- `search_files`: Find patterns, usages, or references
- `create_file`: Create new files with complete content
- `update_file`: Edit existing files — THREE MODES:
  - **Find & Replace** (RECOMMENDED for edits): Provide `old_content` + `new_content` to surgically replace specific sections. Always use `read_file` first to get the exact text.
  - **Append**: Provide `content` + `append=true` to add content to the end of a file (e.g., adding new CSS styles, appending functions).
  - **Full Overwrite**: Provide `content` only — replaces the ENTIRE file. Use ONLY for complete rewrites.
- `delete_file`: Remove files when needed
- `run_command`: Execute shell commands — USE THIS TO BUILD AND VERIFY YOUR CODE (e.g., `cd project && npm run build`, `ng build`). Always use `timeout: 120` or higher for builds.
- `verify_build`: **PREFERRED for build verification** — Auto-detects project type and runs the correct build command. Returns structured results with error classification and suggestions. Use this instead of `run_command` for builds.
- `check_syntax`: Validate your code before running tests
- `run_tests`: Run tests to verify correctness
- `web_search`: Search the web for documentation, APIs, or solutions to errors
- `web_fetch`: Fetch and read web pages for reference documentation
- `create_document`: Create a professional Word document from Markdown content
- `create_report`: Create a structured Word report with a title and multiple sections
- `submit_result`: **TERMINAL TOOL** — Call this when you are satisfied with your work
- `ask_question`: **TERMINAL TOOL** — Call this if you need clarification

## CRITICAL: File Editing Rules
- ⚠️ **ALWAYS read a file BEFORE editing it.** The system will BLOCK edits to files you haven't read first. This prevents accidental overwrites.
- NEVER use `update_file` with just `content` on an existing file unless you intend to replace the ENTIRE file. This will DELETE all existing content. The system will BLOCK overwrites that are much shorter than the existing content.
- When adding new sections to an existing file (e.g., new CSS styles, new functions), use `append=true` mode.
- When modifying specific parts of a file, ALWAYS use `old_content` + `new_content` (Find & Replace mode). Read the file first to get the exact text.
- When creating a brand new file, use `create_file`.
- **Workflow**: `read_file` → understand the code → `update_file` with `old_content`/`new_content`. NEVER skip the read step.

## CRITICAL: HTML/XML Tag Consistency
- When you change an opening HTML/XML tag (e.g., `<div>` → `<main>`), you MUST also change the corresponding closing tag (e.g., `</div>` → `</main>`).
- The system validates HTML tag matching after every file edit. If you see `html_warnings` in the result, you MUST fix them before calling `submit_result`.
- Common mistake: Changing `<div class="container">` to `<main class="container">` but forgetting to change the closing `</div>` to `</main>`.
"""

        self._autonomous_agent = AutonomousAgent(
            agent_name=self.agent_name,
            system_prompt=system_prompt,
            kernel=self.kernel,
            max_rounds=self.max_rounds,
            urgency_threshold=0.5,
        )

        # Register all standard tools
        self._autonomous_agent.register_file_tools()
        self._autonomous_agent.register_search_tool()
        self._autonomous_agent.register_command_tool()
        self._autonomous_agent.register_syntax_tool()
        self._autonomous_agent.register_test_tool()
        self._autonomous_agent.register_git_tools()
        self._autonomous_agent.register_verify_build_tool()

        # Register word document generation tools from skills
        # (Skills must be registered first via _register_default_skills,
        #  which happens in __init__ after this method. So we defer this
        #  registration to be called after skills are set up.)
        # self._register_skill_tools("word")  -- moved to __init__

        # Register web search/fetch tools for looking up documentation
        self._autonomous_agent.register_tool(
            name="web_search",
            description="Search the web for information. Useful for looking up documentation, APIs, library usage, error solutions, and best practices.",
            schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The search query string"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return (1-10, default 5)", "default": 5},
                },
            },
            handler=lambda args: self.kernel._dispatch_tool("web_search", args) if self.kernel else {"ok": False, "error": "No kernel available"},
        )
        self._autonomous_agent.register_tool(
            name="web_fetch",
            description="Fetch and read a web page by URL. Useful for reading documentation pages, API references, or tutorials.",
            schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "The URL of the web page to fetch"},
                },
            },
            handler=lambda args: self.kernel._dispatch_tool("web_fetch", args) if self.kernel else {"ok": False, "error": "No kernel available"},
        )

        # Register submit_result terminal tool
        self._submit_result_data: Optional[dict[str, Any]] = None
        self._autonomous_agent.register_tool(
            name="submit_result",
            description="Submit the final execution result. Call this when you are satisfied with your work.",
            schema={
                "type": "object",
                "required": ["summary"],
                "properties": {
                    "summary": {"type": "string", "description": "Summary of what was implemented"},
                    "artifacts": {"type": "array", "items": {"type": "string"}, "description": "List of created/modified files"},
                    "success": {"type": "boolean", "description": "Whether the implementation succeeded", "default": True},
                    "notes": {"type": "string", "description": "Optional notes or observations"},
                },
            },
            handler=self._handle_submit_result,
        )

        # Register ask_question terminal tool
        self._autonomous_agent.register_tool(
            name="ask_question",
            description="Ask the Orchestrator for clarification on a requirement.",
            schema={
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"},
                },
            },
            handler=self._handle_ask_question,
        )

    def _handle_submit_result(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle submit_result tool call from the autonomous loop."""
        self._submit_result_data = {
            "summary": args.get("summary", ""),
            "artifacts": args.get("artifacts", []),
            "success": args.get("success", True),
            "notes": args.get("notes", ""),
        }
        return {"ok": True, "message": "Result submitted successfully"}

    def _handle_ask_question(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle ask_question tool call from the autonomous loop."""
        return {
            "ok": True,
            "message": "Question forwarded to Orchestrator",
            "question": args.get("question", ""),
        }

    # ========== Autonomous Execution ==========

    def execute_goal(
        self,
        goal: str,
        task_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a goal autonomously using the tool-calling loop.

        Args:
            goal: The high-level goal to implement (e.g., "Create a JWT auth module")
            task_id: Optional task ID for tracking
            context: Optional context (e.g., existing files, constraints)

        Returns:
            ExecutionResult with summary, artifacts, and status
        """
        if not self._autonomous_agent:
            logger.error("[ExecutorAgent] Cannot execute goal: no autonomous agent (kernel missing?)")
            return ExecutionResult(
                success=False,
                error="Autonomous agent not initialized. Kernel is required.",
            )

        logger.info("[ExecutorAgent] Executing goal for task %s: %.100s...", task_id, goal)

        # Reset submit result data
        self._submit_result_data = None

        # Track execution state
        state = self.get_execution_state(task_id or "adhoc")

        # Run the autonomous loop
        loop_result = self._autonomous_agent.run_task(
            task_description=goal,
            context=context,
            max_rounds=self.max_rounds,
        )

        # Collect artifacts from tool calls in the autonomous loop
        loop_artifacts = []
        file_operations = loop_result.file_operations if hasattr(loop_result, 'file_operations') else []
        if not file_operations and hasattr(self._autonomous_agent, '_file_operations'):
            file_operations = self._autonomous_agent._file_operations
        for op in file_operations:
            path = op.get("path", "")
            action = op.get("action", "")
            if path and action in ("create_file", "update_file", "create_document", "create_report") and path not in loop_artifacts:
                loop_artifacts.append(path)
                state.record_file_created(path, op.get("size_bytes", 0))
            elif path and action == "delete_file":
                state.record_file_deleted(path)

        # Build result from loop output
        if self._submit_result_data:
            submitted_success = self._submit_result_data.get("success", True)
            # If no files were created/modified and the task was to fix/implement something,
            # override success to False — reading files is not implementing
            if not loop_artifacts and submitted_success:
                logger.warning("[ExecutorAgent] submit_result called with success=True but no files created — overriding to success=False")
                submitted_success = False
            result = ExecutionResult(
                success=submitted_success,
                summary=self._submit_result_data.get("summary", ""),
                artifacts=self._submit_result_data.get("artifacts", []) or loop_artifacts,
                tool_calls=loop_result.tool_calls_made,
                rounds=loop_result.rounds_used,
            )
        elif loop_result.done and loop_result.content:
            # Loop finished naturally — use the content as summary
            result = ExecutionResult(
                success=True,
                summary=loop_result.content[:500],
                artifacts=loop_artifacts,
                tool_calls=loop_result.tool_calls_made,
                rounds=loop_result.rounds_used,
            )
        elif loop_artifacts:
            # Loop exceeded max_rounds but files were created — treat as partial success
            logger.warning(
                "[ExecutorAgent] Max rounds exceeded but %d file(s) were created. Treating as partial success.",
                len(loop_artifacts),
            )
            result = ExecutionResult(
                success=True,
                summary=f"Implementation completed {len(loop_artifacts)} file(s) but ran out of rounds before calling submit_result.",
                artifacts=loop_artifacts,
                tool_calls=loop_result.tool_calls_made,
                rounds=loop_result.rounds_used,
            )
        else:
            result = ExecutionResult(
                success=False,
                summary=loop_result.content[:500] if loop_result.content else "",
                error="Execution did not complete successfully and no files were created",
                tool_calls=loop_result.tool_calls_made,
                rounds=loop_result.rounds_used,
            )

        # Update execution state
        state.mark_completed(success=result.success, error_message=result.error)

        logger.info(
            "[ExecutorAgent] Goal execution complete: success=%s, tools=%d, rounds=%d",
            result.success,
            result.tool_calls,
            result.rounds,
        )

        return result

    # ========== Legacy Plan Execution (Backward Compatible) ==========

    def execute_plan(self, plan: dict[str, Any], task_id: Optional[str] = None) -> dict[str, Any]:
        """Execute a plan and return results.

        If autonomous_mode is True, converts the plan to a goal and uses
        the autonomous execution loop. Otherwise, falls back to the
        legacy step-by-step execution.

        Args:
            plan: The plan dictionary from Planner
            task_id: Optional task ID for state tracking

        Returns:
            Execution results with status and any errors
        """
        if not self.autonomous_mode or not self._autonomous_agent:
            return self._legacy_execute_plan(plan, task_id)

        # Convert plan to a goal for autonomous execution
        goal = self._convert_plan_to_goal(plan)
        result = self.execute_goal(goal=goal, task_id=task_id)

        # Convert ExecutionResult to legacy format for compatibility
        return {
            "success": result.success,
            "summary": result.summary,
            "artifacts": result.artifacts,
            "error": result.error,
            "tool_calls": result.tool_calls,
            "rounds": result.rounds,
            "autonomous": True,
        }

    def _convert_plan_to_goal(self, plan: dict[str, Any]) -> str:
        """Convert a structured plan into a natural language goal."""
        title = plan.get("title", "Implement plan")
        description = plan.get("description", "")
        steps = plan.get("steps", [])

        goal_parts = [f"Goal: {title}"]
        if description:
            goal_parts.append(f"Description: {description}")

        if steps:
            goal_parts.append("\nPlan steps (for guidance):")
            for step in steps:
                if isinstance(step, dict):
                    step_desc = step.get("description", "")
                    step_action = step.get("action", "")
                    step_args = step.get("args", {})
                    goal_parts.append(f"- {step_desc}")
                    if step_action and step_args:
                        goal_parts.append(f"  Action: {step_action} with {step_args}")

        goal_parts.append("\nImplement this autonomously. Read existing files for context, write complete working code, run tests if applicable, and submit your result when satisfied.")

        return "\n".join(goal_parts)

    def _legacy_execute_plan(self, plan: dict[str, Any], task_id: Optional[str] = None) -> dict[str, Any]:
        """Legacy step-by-step plan execution (preserved for backward compatibility)."""
        # Get or create execution state
        if task_id:
            state = self.get_execution_state(task_id)
        else:
            state = ExecutionState(
                task_id="adhoc",
                workspace_root=str(self.workspace_root),
            )

        steps = plan.get("steps", [])
        if not isinstance(steps, list):
            result = {
                "success": False,
                "error": "Plan steps must be a list",
                "steps_executed": 0,
                "steps_failed": 0,
                "results": [],
                "errors": [],
                "artifacts": [],
            }
            state.mark_completed(success=False, error_message=result["error"])
            return result

        results = []
        errors = []
        artifacts: list[str] = []

        for step in steps:
            if not isinstance(step, dict):
                step_result = {
                    "step_id": "unknown",
                    "success": False,
                    "error": "Step must be an object",
                    "description": "",
                }
            else:
                step_result = self._execute_step(step, state=state)
            results.append(step_result)
            artifacts.extend(self._extract_artifacts(step_result))

            if not step_result.get("success", False):
                errors.append(step_result)
                logger.warning(
                    "Step failed: %s | %s",
                    step_result.get("step_id", "unknown"),
                    step_result.get("error") or step_result.get("result"),
                )

        error_message = None
        if errors:
            messages = []
            for err in errors:
                if not isinstance(err, dict):
                    continue
                msg = err.get("error")
                if not msg and isinstance(err.get("result"), dict):
                    msg = err["result"].get("error")
                if msg:
                    messages.append(str(msg))
            if messages:
                error_message = "; ".join(messages)[:800]

        execution_result = {
            "success": len(errors) == 0,
            "steps_executed": len(steps),
            "steps_failed": len(errors),
            "results": results,
            "errors": errors,
            "artifacts": self._dedupe_artifacts(artifacts),
            "error": error_message,
        }

        state.mark_completed(
            success=execution_result["success"],
            error_message=error_message,
        )

        return execution_result

    # ========== Skill Management (Legacy) ==========

    def _build_executor_context(self) -> str:
        """Build the Executor's own identity and context (legacy)."""
        return """You are the Orbitron Executor Agent. Your role is implementation and execution.

## Your Identity
You are the system's builder and implementer. You write code, create files, and execute commands.
You do NOT plan, strategize, or analyze requirements — that is the Planner's job.
You do NOT have access to user identity, system soul, or orchestrator memory.
You receive a plan step and implement it with high-quality code.

## Your Capabilities
- Generate complete, production-ready code in any language
- Create and modify files
- Execute Python scripts and shell commands
- Create documents and reports
- Follow best practices and modern standards

## Code Generation Rules
- Write complete, working code — no placeholders or TODOs
- Include comments where helpful
- Follow language-specific best practices
- Make code clean, readable, and maintainable
- Handle edge cases appropriately
- Use modern patterns and standards
"""

    def _register_default_skills(self) -> None:
        """Register all default executor skills (legacy)."""
        programming_skill = ProgrammingSkill()
        programming_skill.set_workspace(str(self.workspace_root))
        self.register_skill(programming_skill)

        word_skill = WordSkill(workspace=str(self.workspace_root))
        self.register_skill(word_skill)

        opencode_skill = OpenCodeSkill(workspace=str(self.workspace_root))
        self.register_skill(opencode_skill)

    def register_skill(self, skill: Any) -> None:
        """Register a skill with the executor."""
        self.skills[skill.name] = skill
        logger.info("[ExecutorAgent] Registered skill: %s", skill.name)

    def get_skill(self, name: str) -> Optional[Any]:
        """Get a registered skill by name."""
        return self.skills.get(name)

    def _register_skill_tools(self, skill_name: str) -> None:
        """Register all tools from a skill into the autonomous agent."""
        skill = self.skills.get(skill_name)
        if not skill or not self._autonomous_agent:
            return
        handlers = skill.get_handlers()
        for tool_schema in skill.get_tools():
            func_info = tool_schema.get("function", {})
            tool_name = func_info.get("name")
            description = func_info.get("description", "")
            parameters = func_info.get("parameters", {})
            handler = handlers.get(tool_name)
            if tool_name and handler:
                self._autonomous_agent.register_tool(
                    name=tool_name,
                    description=description,
                    schema=parameters,
                    handler=handler,
                )

    # ========== Execution State Management ==========

    def get_execution_state(self, task_id: str) -> ExecutionState:
        """Get or create execution state for a task."""
        if task_id not in self._execution_states:
            self._execution_states[task_id] = ExecutionState(
                task_id=task_id,
                workspace_root=str(self.workspace_root),
            )
        return self._execution_states[task_id]

    def clear_execution_state(self, task_id: str) -> None:
        """Clear execution state for a task (called after completion)."""
        if task_id in self._execution_states:
            del self._execution_states[task_id]
            logger.debug("[ExecutorAgent] Cleared execution state for task %s", task_id)

    # ========== Legacy Step Execution ==========

    def _execute_step(self, step: dict[str, Any], state: Optional[ExecutionState] = None) -> dict[str, Any]:
        """Execute a single step from the plan (legacy)."""
        step_id = step.get("id", "unknown")
        description = step.get("description", "")
        skill_name = step.get("skill", "programming")
        action = step.get("action", "")
        args = step.get("args", {})
        if not isinstance(args, dict):
            return {
                "step_id": step_id,
                "success": False,
                "error": "Step args must be an object",
                "description": description,
            }
        args = self._normalize_args_for_action(action, args)

        # If create_file and no content provided, generate content via LLM
        if action == "create_file" and not args.get("content") and self.kernel:
            logger.info("[ExecutorAgent] Step %s: No content provided, generating via LLM...", step_id)

            related_context = ""
            if state:
                filename = args.get("filename", "")
                related_context = state.get_related_files_context(filename)

            generated = self._generate_file_content(
                filename=args.get("filename", ""),
                description=description,
                step=step,
                related_context=related_context,
            )
            if generated:
                args["content"] = generated
            else:
                return {
                    "step_id": step_id,
                    "success": False,
                    "error": "Failed to generate file content via LLM",
                    "description": description,
                }

        logger.info("[ExecutorAgent] Executing step %s: %s...", step_id, description[:50])

        try:
            skill = self.skills.get(skill_name)
            if not skill:
                logger.error("[ExecutorAgent] Unknown skill '%s' for step %s", skill_name, step_id)
                result = {
                    "step_id": step_id,
                    "success": False,
                    "error": f"Unknown skill: {skill_name}"
                }
            else:
                handler = skill.get_handlers().get(action)
                if not handler:
                    result = {
                        "step_id": step_id,
                        "success": False,
                        "error": f"Unknown action: {action} in skill {skill_name}"
                    }
                else:
                    handler_result = handler(args)

                    if isinstance(handler_result, str):
                        try:
                            handler_result = json.loads(handler_result)
                        except json.JSONDecodeError:
                            handler_result = {"ok": True, "result": handler_result}

                    result = {
                        "step_id": step_id,
                        "success": handler_result.get("ok", False),
                        "result": handler_result,
                        "description": description,
                    }

                    if state and handler_result.get("ok"):
                        self._track_file_operation(state, action, handler_result)

            if state:
                state.record_step_result(StepResult(
                    step_id=step_id,
                    success=result.get("success", False),
                    action=action,
                    skill=skill_name,
                    result=result.get("result"),
                    error=result.get("error"),
                    artifacts=self._extract_artifacts(result),
                ))

            return result

        except Exception as e:
            logger.exception("[ExecutorAgent] Step execution failed")
            result = {
                "step_id": step_id,
                "success": False,
                "error": str(e),
                "description": description,
            }

            if state:
                state.record_step_result(StepResult(
                    step_id=step_id,
                    success=False,
                    action=action,
                    skill=skill_name,
                    error=str(e),
                    artifacts=[],
                ))

            return result

    def _track_file_operation(self, state: ExecutionState, action: str, result: dict[str, Any]) -> None:
        """Track file operations in execution state."""
        path = result.get("path", "")
        if not path:
            return

        try:
            p = Path(path)
            root = self.workspace_root.resolve()
            if p.is_absolute():
                try:
                    rel_path = str(p.relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel_path = str(p).replace("\\", "/")
            else:
                rel_path = str(p).replace("\\", "/")
        except Exception:
            rel_path = path

        if action == "create_file":
            state.record_file_created(rel_path, result.get("size_bytes", 0))
        elif action in {"update_file", "modify_file"}:
            state.record_file_modified(rel_path, result.get("size_bytes", 0))
        elif action == "delete_file":
            state.record_file_deleted(rel_path)

    def _normalize_args_for_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Normalize common arg aliases to reduce planner mismatches."""
        normalized = dict(args)

        if action in {"create_file", "modify_file", "read_file"}:
            if "filename" not in normalized:
                for key in ("path", "file", "file_path", "filepath"):
                    if key in normalized:
                        normalized["filename"] = normalized[key]
                        break
        if action == "create_file":
            if "content" not in normalized:
                for key in ("text", "body", "source"):
                    if key in normalized:
                        normalized["content"] = normalized[key]
                        break
        if action in {"create_directory", "list_directory"}:
            if "dirname" not in normalized:
                for key in ("path", "dir", "directory", "folder"):
                    if key in normalized:
                        normalized["dirname"] = normalized[key]
                        break
        if action in {"modify_file", "update_file"}:
            if "old_content" not in normalized:
                for key in ("find", "old", "old_text"):
                    if key in normalized:
                        normalized["old_content"] = normalized[key]
                        break
            if "new_content" not in normalized:
                for key in ("replace", "new", "new_text"):
                    if key in normalized:
                        normalized["new_content"] = normalized[key]
                        break

        return normalized

    def _generate_file_content(
        self,
        filename: str,
        description: str,
        step: dict[str, Any],
        related_context: str = "",
    ) -> str | None:
        """Generate file content using the LLM when the Planner didn't provide it."""
        if not self.kernel:
            logger.error("[ExecutorAgent] Cannot generate content: no kernel connected")
            return None

        ext = Path(filename).suffix.lower()
        file_type_map = {
            ".html": "HTML",
            ".css": "CSS",
            ".js": "JavaScript",
            ".py": "Python",
            ".md": "Markdown",
            ".txt": "Text",
            ".json": "JSON",
            ".xml": "XML",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".ts": "TypeScript",
            ".tsx": "TypeScript React",
            ".jsx": "React JSX",
            ".vue": "Vue",
            ".php": "PHP",
            ".sql": "SQL",
            ".sh": "Shell/Bash",
            ".ps1": "PowerShell",
            ".bat": "Batch",
            ".cmd": "Batch",
        }
        file_type = file_type_map.get(ext, "code")

        plan_context = step.get("plan_context", "")
        outputs = step.get("outputs", [])
        acceptance = step.get("acceptance_criteria", [])

        prompt = f"""{self._build_executor_context()}

## Current Task
Generate complete, production-ready {file_type} code.

Task: {description}
File: {filename}

Requirements:
- Create a complete, working file
- Follow best practices for {file_type}
- Include comments where helpful
- Make it professional and polished
{f"- Expected outputs: {outputs}" if outputs else ""}
{f"- Acceptance criteria: {acceptance}" if acceptance else ""}
{f"- Plan context: {plan_context}" if plan_context else ""}
{related_context}

## Important Rules
- If this file references other files, ensure consistency with existing files.
- Return ONLY the file content. No markdown fences, no explanations, no commentary.
"""

        try:
            logger.info("[ExecutorAgent] Requesting LLM content generation for %s (%s)...", filename, file_type)

            timeout_s = self.kernel.timeout_manager.calculate_execution_timeout(
                plan={"steps": [step]},
                model_name=self.kernel.config.get("ollama.model"),
            )

            response = self.kernel.ollama.chat(
                messages=[
                    {"role": "system", "content": "You are a code generation engine. Output only raw code, no markdown, no explanations."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                timeout_s=timeout_s,
            )
            content = str((response.get("message") or {}).get("content") or "")

            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            logger.info("[ExecutorAgent] Generated %d chars of %s for %s", len(content), file_type, filename)
            return content

        except Exception as e:
            logger.error("[ExecutorAgent] LLM content generation failed: %s", e)
            return None

    # ========== Artifact Utilities ==========

    def _extract_artifacts(self, step_result: dict[str, Any]) -> list[str]:
        """Extract artifact paths from a step result."""
        result = step_result.get("result") if isinstance(step_result, dict) else None
        if not isinstance(result, dict):
            return []

        artifacts: list[str] = []
        path = result.get("path")
        if isinstance(path, str) and path.strip():
            artifacts.append(self._normalize_artifact_path(path))

        for key in ("paths", "files", "artifacts", "output_files"):
            value = result.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        artifacts.append(self._normalize_artifact_path(item))

        return artifacts

    def _normalize_artifact_path(self, path: str) -> str:
        """Normalize artifact paths to workspace-relative when possible."""
        try:
            p = Path(path)
            root = Path(self.workspace_root).resolve()
            if p.is_absolute():
                try:
                    return str(p.resolve().relative_to(root)).replace("\\", "/")
                except ValueError:
                    return str(p.resolve())
            return str(p).replace("\\", "/")
        except Exception:
            return path

    def _dedupe_artifacts(self, artifacts: list[str]) -> list[str]:
        """Return deduplicated artifact list while preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for item in artifacts:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    # ========== Status ==========

    def get_status(self) -> dict[str, Any]:
        """Get executor status."""
        return {
            "agent_name": self.agent_name,
            "workspace": str(self.workspace_root),
            "skills": list(self.skills.keys()),
            "skills_count": len(self.skills),
            "active_execution_states": len(self._execution_states),
            "autonomous_mode": self.autonomous_mode,
            "autonomous_agent_ready": self._autonomous_agent is not None,
        }


def create_executor_agent(
    agent_name: str = "executor",
    workspace_root: str | None = None,
    kernel=None,
) -> ExecutorAgent:
    """Factory function to create an Executor Agent."""
    return ExecutorAgent(
        agent_name=agent_name,
        workspace_root=workspace_root,
        kernel=kernel,
    )
