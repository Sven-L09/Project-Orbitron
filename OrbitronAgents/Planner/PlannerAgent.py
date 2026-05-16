"""Planner Agent - Autonomous Explorer-Strategist for the Orbitron system.

The Planner Agent analyzes complex requests, explores the codebase autonomously,
and creates structured plans. Instead of planning in a vacuum, it now uses tools
to read files, search patterns, and understand context BEFORE planning.

Key Principles:
- Receives a task, explores the codebase autonomously
- Uses tools to gather context: read_file, list_directory, search_files
- Creates structured JSON plans when ready
- Calls submit_plan to deliver the plan
- Calls ask_question when requirements are unclear
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Import kernel components
from OrbitronKernel.kernel import AgentSkill

# Import autonomous agent base
from OrbitronAgents.base.autonomous_agent import AutonomousAgent, AgentLoopResult

logger = logging.getLogger("PlannerAgent")


class PlannerSkill(AgentSkill):
    """Skill for planning and task decomposition capabilities (legacy, kept for compatibility)."""

    def __init__(self):
        super().__init__(
            name="planner",
            description="Strategic planning, task decomposition, and plan management"
        )
        self._plans: dict[str, dict[str, Any]] = {}
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register all planner tools."""

        # Tool: Create a new plan
        self.register_tool(
            "create_plan",
            {
                "description": "Create a structured plan with goals, steps, and dependencies",
                "parameters": {
                    "type": "object",
                    "required": ["plan_id", "title", "steps"],
                    "properties": {
                        "plan_id": {
                            "type": "string",
                            "description": "Unique identifier for the plan"
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the plan"
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of what the plan aims to achieve"
                        },
                        "steps": {
                            "type": "array",
                            "description": "List of steps to execute",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "description": {"type": "string"},
                                    "depends_on": {"type": "array", "items": {"type": "string"}},
                                    "estimated_time": {"type": "string"},
                                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]}
                                }
                            }
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Additional metadata like priority, tags, constraints"
                        }
                    }
                }
            },
            self._handle_create_plan
        )

        # Tool: Analyze task complexity
        self.register_tool(
            "analyze_task",
            {
                "description": "Analyze a task and break it down into sub-tasks with complexity assessment",
                "parameters": {
                    "type": "object",
                    "required": ["task"],
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task to analyze"
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context about the task"
                        }
                    }
                }
            },
            self._handle_analyze_task
        )

        # Tool: Get plan status
        self.register_tool(
            "get_plan",
            {
                "description": "Retrieve a plan by ID",
                "parameters": {
                    "type": "object",
                    "required": ["plan_id"],
                    "properties": {
                        "plan_id": {
                            "type": "string",
                            "description": "The plan ID to retrieve"
                        }
                    }
                }
            },
            self._handle_get_plan
        )

        # Tool: List all plans
        self.register_tool(
            "list_plans",
            {
                "description": "List all created plans",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["draft", "active", "completed", "archived"]
                        }
                    }
                }
            },
            self._handle_list_plans
        )

        # Tool: Update plan step
        self.register_tool(
            "update_step",
            {
                "description": "Update the status of a plan step",
                "parameters": {
                    "type": "object",
                    "required": ["plan_id", "step_id", "status"],
                    "properties": {
                        "plan_id": {"type": "string"},
                        "step_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked"]},
                        "notes": {"type": "string"}
                    }
                }
            },
            self._handle_update_step
        )

    def _handle_create_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create a new plan."""
        plan_id = args["plan_id"]
        plan = {
            "id": plan_id,
            "title": args["title"],
            "description": args.get("description", ""),
            "steps": args.get("steps", []),
            "metadata": args.get("metadata", {}),
            "status": "draft",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        self._plans[plan_id] = plan
        return {"plan_id": plan_id, "status": "created", "steps_count": len(plan["steps"])}

    def _handle_analyze_task(self, args: dict[str, Any]) -> dict[str, Any]:
        """Analyze a task and return structured analysis."""
        task = args["task"]
        context = args.get("context", "")

        analysis = {
            "original_task": task,
            "context": context,
            "complexity": "unknown",
            "estimated_effort": "unknown",
            "sub_tasks": [],
            "considerations": [],
            "risks": [],
            "suggested_approach": ""
        }
        return analysis

    def _handle_get_plan(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """Get a plan by ID."""
        plan_id = args["plan_id"]
        return self._plans.get(plan_id)

    def _handle_list_plans(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """List all plans, optionally filtered by status."""
        status_filter = args.get("status")
        plans = list(self._plans.values())
        if status_filter:
            plans = [p for p in plans if p["status"] == status_filter]
        return [{"id": p["id"], "title": p["title"], "status": p["status"]} for p in plans]

    def _handle_update_step(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update a step in a plan."""
        plan_id = args["plan_id"]
        step_id = args["step_id"]
        status = args["status"]
        notes = args.get("notes", "")

        if plan_id not in self._plans:
            return {"error": f"Plan {plan_id} not found"}

        plan = self._plans[plan_id]
        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = status
                if notes:
                    step["notes"] = notes
                plan["updated_at"] = datetime.now().isoformat()
                return {"plan_id": plan_id, "step_id": step_id, "status": status}

        return {"error": f"Step {step_id} not found in plan {plan_id}"}


class PlannerAgent:
    """Planner Agent - Autonomous Explorer-Strategist.

    The Planner Agent:
    - Receives a task
    - Explores the codebase using tools (read_file, list_directory, search_files)
    - Understands context before planning
    - Creates structured, actionable plans
    - Identifies dependencies and risks
    - Submits plans via submit_plan terminal tool
    - Asks questions via ask_question when unclear
    """

    # Feature flag for migration
    autonomous_mode: bool = True

    def __init__(self, kernel=None, workspace_root: str | None = None, max_rounds: int = 22):
        """Initialize the Planner Agent."""
        self.kernel = kernel
        self.workspace_root = Path(workspace_root) if workspace_root else Path(__file__).resolve().parents[2]
        self.max_rounds = max_rounds

        # Legacy skill (kept for backward compatibility)
        self.skill = PlannerSkill()
        if kernel:
            kernel.register_skill(self.skill)

        # Load planning context and guidelines
        self._planning_context = self._load_planning_context()

        # Autonomous agent instance
        self._autonomous_agent: Optional[AutonomousAgent] = None
        if self.kernel:
            self._setup_autonomous_agent()

        self._logger = logging.getLogger("PlannerAgent")
        self._logger.info("[PlannerAgent] Initialized with autonomous capabilities (mode=%s)", self.autonomous_mode)
        self._logger.info("[PlannerAgent] Workspace: %s", self.workspace_root)

    def _setup_autonomous_agent(self) -> None:
        """Create and configure the AutonomousAgent instance."""
        system_prompt = f"""You are the Orbitron Planner Agent. You receive a task and create a CONCISE, FOCUSED plan for its implementation.

## Your Identity
You are the system's strategist. You create MINIMAL, ACTIONABLE plans.
You do NOT write code — that is the Executor's job.
You create plans that the Executor can FINISH in a single pass.

## CRITICAL: Professional Quality Standard
Every plan you create must result in a PROFESSIONAL, POLISHED product. This means:
- **Visual Design**: Clean layouts, proper spacing, consistent typography, harmonious colors, professional aesthetics
- **UX Quality**: Intuitive navigation, clear visual hierarchy, responsive design, accessible interactions
- **Attention to Detail**: No rough edges, no placeholder content, no "good enough" solutions
- **Production-Ready**: The result should look like it was made by a professional designer/developer, not a prototype

When planning UI/frontend changes, ALWAYS include steps for:
- Proper spacing, padding, and margins (not just "adjust spacing" — specify values)
- Visual consistency across all components
- Responsive behavior for different screen sizes
- Hover states, transitions, and micro-interactions
- Professional color palette and typography

A plan that produces a "working but ugly" result is a FAILED plan. Quality is non-negotiable.

## CRITICAL: Convergence Rules
- Create the SMALLEST plan that solves the task
- Do NOT add optional features, nice-to-haves, or future improvements
- Do NOT create steps that duplicate what already exists
- Every step must be ESSENTIAL to solving the task
- If the task is simple, create a MINIMAL plan (2-3 steps max)
- NEVER expand or add to an existing plan when revising — only fix issues

## CRITICAL: Time Management
You have LIMITED rounds. You MUST call `submit_plan` within 3-5 rounds.
- Round 1-2: Read 1-2 key files to understand the codebase (ONLY what's necessary)
- Round 3-5: Formulate and submit your plan
- Do NOT read every file in the project. Read ONLY what's directly relevant to the task.
- Do NOT explore directories endlessly. Focus on the task, not the entire project.
- If you find yourself reading more than 3 files, STOP and submit your plan.
- CALL `submit_plan` EARLY. A good plan submitted quickly is better than a perfect plan that never gets submitted.

## Capabilities
- Read files and directories to understand the codebase
- Search for patterns and references across files
- Create structured JSON plans

## Workflow
1. **Context Gathering**: Read 1-2 relevant files (NO MORE than 3 files total)
2. **Gap Analysis**: Identify ONLY what's missing or broken
3. **Planning**: Create the minimal plan to fill the gaps — with PROFESSIONAL quality expectations
4. **Submission**: IMMEDIATELY call `submit_plan` with a structured JSON plan

## Plan Format (JSON)
Your plan MUST follow this JSON schema:
{{
  "plan_type": "execution",
  "id": "plan-unique-id",
  "title": "Short title",
  "description": "Detailed description",
  "summary": "Brief summary",
  "steps": [
    {{
      "id": "step-1",
      "description": "What to do — be SPECIFIC about visual/UX expectations",
      "priority": "high",
      "estimated_time": "10m",
      "depends_on": [],
      "skill": "programming",
      "action": "create_file",
      "args": {{"path": "relative/path", "description": "what this file does"}},
      "outputs": ["expected output"],
      "acceptance_criteria": ["how to verify — include visual/UX criteria"]
    }}
  ],
  "artifacts": ["file1.py", "file2.py"],
  "edge_cases": ["possible issues"],
  "risks": ["potential problems"],
  "assumptions": ["what we assume"],
  "metadata": {{}}
}}

## Important Rules
- You ONLY plan — you do NOT execute
- Steps describe WHAT, not HOW (no code in args)
- args MUST contain only: path, description, name, options
- The Executor creates all actual content
- All file paths must be workspace-relative
- Be critical: include risks, edge cases, and assumptions
- If the task is simple, submit a MINIMAL plan
- When ready, call `submit_plan` with the JSON plan
- When unclear, call `ask_question`
- **NEVER duplicate steps that already exist in the codebase**
- **ALWAYS plan for professional visual quality, not just functional correctness**

## Allowed Executor Actions
- programming: create_file, modify_file, read_file, create_directory, list_directory
- word: create_document, create_report
- opencode: execute_python, execute_command
"""

        self._autonomous_agent = AutonomousAgent(
            agent_name="planner",
            system_prompt=system_prompt,
            kernel=self.kernel,
            max_rounds=self.max_rounds,
            urgency_threshold=0.4,
        )

        # Register standard tools
        self._autonomous_agent.register_file_tools()
        self._autonomous_agent.register_search_tool()
        self._autonomous_agent.register_command_tool()

        # Register submit_plan terminal tool
        self._submitted_plan: Optional[dict[str, Any]] = None
        self._autonomous_agent.register_tool(
            name="submit_plan",
            description="Submit a structured plan. Call this when you are ready with your plan.",
            schema={
                "type": "object",
                "required": ["plan"],
                "properties": {
                    "plan": {
                        "type": "object",
                        "description": "The structured plan JSON object"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about the plan"
                    }
                },
            },
            handler=self._handle_submit_plan,
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

    def _handle_submit_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle submit_plan tool call from the autonomous loop."""
        plan = args.get("plan", {})
        # Validate the submitted plan
        if not isinstance(plan, dict):
            return {"ok": False, "error": "Plan must be a JSON object"}

        # Coerce and validate — accept even if validation has minor issues
        coerced = self._coerce_plan(plan, "")
        if not self._validate_plan(coerced):
            # Log validation failure but still accept the plan with a warning
            # Don't reject entirely — the Executor can adapt
            self._logger.warning("[Planner] Plan validation failed, but accepting with warnings: %s",
                                 coerced.get("title", "unknown"))
            coerced.setdefault("metadata", {})["validation_warnings"] = True

        self._submitted_plan = coerced
        return {"ok": True, "message": "Plan submitted successfully", "plan_id": coerced.get("id")}

    def _handle_ask_question(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle ask_question tool call from the autonomous loop."""
        return {
            "ok": True,
            "message": "Question forwarded to Orchestrator",
            "question": args.get("question", ""),
        }

    # ========== Autonomous Planning ==========

    def plan_autonomously(
        self,
        request: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a plan autonomously using the tool-calling loop.

        The Planner will:
        1. Explore the codebase if needed
        2. Analyze requirements
        3. Create a structured plan
        4. Submit it via submit_plan

        If context contains previous execution results or artifacts, the Planner
        will be instructed NOT to duplicate what's already been done.

        Returns:
            dict with plan, metadata, and status
        """
        if not self._autonomous_agent:
            raise RuntimeError("PlannerAgent has no autonomous agent (kernel missing?)")

        self._logger.info("[Planner] Starting autonomous planning for: %.100s...", request)

        # Reset submitted plan
        self._submitted_plan = None

        # Build context to prevent duplication
        planning_context = context or {}
        if planning_context.get("previous_execution_summary") or planning_context.get("previous_artifacts"):
            existing = planning_context.get("previous_artifacts", [])
            summary = planning_context.get("previous_execution_summary", "")
            existing_note = (
                f"\n\n## IMPORTANT: Existing Work\n"
                f"The following has ALREADY been done. Do NOT plan it again:\n"
            )
            if summary:
                existing_note += f"- Summary: {summary}\n"
            if existing:
                existing_note += f"- Files already created/modified: {', '.join(str(a) for a in existing[:20])}\n"
            existing_note += "\nOnly plan what is MISSING or needs FIXING. Do not duplicate existing work."
            planning_context["existing_work_note"] = existing_note

        if planning_context.get("warning"):
            planning_context["planning_note"] = (
                f"WARNING: {planning_context['warning']}\n"
                "You MUST NOT duplicate or expand existing work. Only plan what is truly needed."
            )

        # Run the autonomous loop
        loop_result = self._autonomous_agent.run_task(
            task_description=request,
            context=planning_context if planning_context != context else planning_context,
            max_rounds=self.max_rounds,
        )

        if self._submitted_plan:
            self._logger.info("[Planner] Plan submitted successfully via autonomous loop")
            return {
                "plan": self._submitted_plan,
                "metadata": {
                    "source": "autonomous",
                    "rounds": loop_result.rounds_used,
                    "tool_calls": loop_result.tool_calls_made,
                },
            }
        elif loop_result.done:
            # Loop finished without submit_plan — try to extract plan from content
            plan = self._extract_json(loop_result.content)
            if plan and self._validate_plan(plan):
                self._logger.info("[Planner] Extracted valid plan from loop content")
                return {
                    "plan": self._coerce_plan(plan, request),
                    "metadata": {
                        "source": "autonomous_content",
                        "rounds": loop_result.rounds_used,
                        "tool_calls": loop_result.tool_calls_made,
                    },
                }
            else:
                self._logger.warning("[Planner] Autonomous loop finished but no valid plan submitted")
                return {
                    "plan": None,
                    "error": "No valid plan was submitted",
                    "content": loop_result.content,
                    "metadata": {
                        "rounds": loop_result.rounds_used,
                        "tool_calls": loop_result.tool_calls_made,
                    },
                }
        else:
            # Max rounds exceeded — try to extract plan from content before giving up
            self._logger.warning("[Planner] Autonomous loop exceeded max rounds, attempting plan extraction")
            plan = self._extract_json(loop_result.content)
            if plan and self._validate_plan(plan):
                self._logger.info("[Planner] Extracted valid plan from loop content after max rounds")
                return {
                    "plan": self._coerce_plan(plan, request),
                    "metadata": {
                        "source": "autonomous_extracted",
                        "rounds": loop_result.rounds_used,
                        "tool_calls": loop_result.tool_calls_made,
                    },
                }
            else:
                self._logger.error("[Planner] Autonomous loop did not complete and no plan could be extracted")
                return {
                    "plan": None,
                    "error": loop_result.content or "Autonomous planning did not complete",
                    "metadata": {
                        "rounds": loop_result.rounds_used,
                        "tool_calls": loop_result.tool_calls_made,
                    },
                }

    # ========== Legacy Plan Generation (Backward Compatible) ==========

    def generate_plan(
        self,
        request: str,
        context: dict | None = None,
        *,
        max_attempts: int = 2,
        timeout_s: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Generate a structured plan using the kernel LLM.

        If autonomous_mode is True, uses the autonomous planning loop.
        Otherwise, falls back to the legacy direct LLM call.

        Returns a tuple of (plan, metadata).
        """
        if not self.autonomous_mode or not self._autonomous_agent:
            return self._legacy_generate_plan(request, context, max_attempts=max_attempts, timeout_s=timeout_s)

        result = self.plan_autonomously(request=request, context=context)

        if result.get("plan"):
            return result["plan"], result.get("metadata", {})
        else:
            error = result.get("error", "Unknown planning error")
            self._logger.error("[Planner] Autonomous planning failed: %s", error)
            raise RuntimeError(error)

    def _legacy_generate_plan(
        self,
        request: str,
        context: dict | None = None,
        *,
        max_attempts: int = 2,
        timeout_s: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Legacy plan generation via direct LLM call (preserved for backward compatibility)."""
        if not self.kernel:
            raise RuntimeError("PlannerAgent has no kernel connected")

        self._logger.info("[Planner] Starting legacy plan generation for request: %s...", request[:80])
        self._logger.info("[Planner] Context keys: %s", list(context.keys()) if context else "none")

        messages = self._build_planning_messages(request, context or {})
        last_error = None
        total_response_chars = 0

        for attempt in range(1, max_attempts + 1):
            self._logger.info("[Planner] Plan generation attempt %d/%d", attempt, max_attempts)

            chat_kwargs = {
                "messages": messages,
                "tools": None,
                "stream": False,
                "think": None,
            }
            if timeout_s is not None:
                chat_kwargs["timeout_s"] = timeout_s

            try:
                response = self.kernel.ollama.chat(**chat_kwargs)
            except Exception as e:
                self._logger.error("[Planner] Ollama chat failed on attempt %d: %s", attempt, e)
                last_error = f"Ollama chat error: {e}"
                continue

            content = str((response.get("message") or {}).get("content") or "")
            total_response_chars = len(content)
            self._logger.info("[Planner] Received response from Ollama (%d chars)", total_response_chars)

            plan = self._extract_json(content)
            if plan:
                self._logger.info("[Planner] Extracted JSON plan with keys: %s", list(plan.keys()))
                if self._validate_plan(plan):
                    coerced = self._coerce_plan(plan, request)
                    self._logger.info("[Planner] Plan validated and coerced successfully (attempt %d)", attempt)
                    return coerced, {
                        "source": "kernel",
                        "attempts": attempt,
                        "response_length": total_response_chars,
                    }
                else:
                    self._logger.warning("[Planner] Plan JSON extracted but validation failed (attempt %d)", attempt)
            else:
                self._logger.warning("[Planner] Could not extract JSON from response (attempt %d)", attempt)
                preview = content.replace("\n", " ").replace("\r", " ").strip()
                if preview:
                    self._logger.warning("[Planner] Response preview (first 300 chars): %s", preview[:300])

            last_error = "Invalid or incomplete plan JSON"
            messages.insert(1, {
                "role": "system",
                "content": (
                    "Your previous response was invalid. Return ONLY valid JSON with all required fields. "
                    "No markdown, no commentary."
                ),
            })

        self._logger.error("[Planner] Failed to generate valid plan after %d attempts. Last error: %s",
                           max_attempts, last_error)
        raise RuntimeError(last_error or "Failed to generate plan")

    def _build_planning_messages(self, request: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Build messages for LLM planning with strict JSON output."""
        system_prompt = f"""You are the Orbitron Planner Agent. Your role is to think strategically and create structured plans.

## Your Identity
You are the system's strategist and architect. You analyze, decompose, and structure tasks.
You do NOT write code, file contents, or implementation details.
You do NOT have access to user identity, system soul, or orchestrator memory.
You only know your planning skills and the task at hand.

## Your Planning Skills
{self._planning_context}

Return ONLY valid JSON with this schema:
{self._plan_schema_description()}

Allowed executor skills and actions:
{self._allowed_executor_actions()}

Rules:
- No markdown, no code fences, no commentary
- You are a PLANNER — you do NOT write code, file contents, or implementation details
- Each step describes WHAT should be done, not HOW (no code in args)
- For plan_type "execution", each step MUST include: skill, action, args
- args MUST contain only parameters like file paths, names, descriptions — NEVER full file contents, HTML, CSS, JS, or code
- The Executor will create the actual code/content based on your step descriptions
- Provide concrete itinerary and logistics for plan_type "experience"
- Be critical: include risks and assumptions
- Set plan_type to "execution" for software/build tasks (websites, coding, automation)
- Set plan_type to "experience" for travel/itinerary tasks
- For plan_type "execution", include outputs and acceptance_criteria per step
- For plan_type "execution", include artifacts (list of expected files)
- For plan_type "execution", include edge_cases (list of checks to consider)
- All file paths must be workspace-relative; never use absolute paths or drive letters
- Do not access logs or files outside the workspace
- Prefer using artifact_paths from context when provided
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request},
        ]

        if context:
            # Sanitize context before adding to messages - prevent context bloat
            sanitized_context = {}
            for key, value in context.items():
                if isinstance(value, str) and len(value) > 500:
                    sanitized_context[key] = value[:500] + "...[truncated]"
                elif key in ("previous_plan", "execution_result", "plan") and isinstance(value, dict):
                    sanitized_context[key] = {
                        "summary": f"Object with {len(value)} keys (truncated)",
                        "keys": list(value.keys())[:10],
                    }
                else:
                    sanitized_context[key] = value

            messages.insert(1, {
                "role": "system",
                "content": f"Context (JSON): {json.dumps(sanitized_context, ensure_ascii=False)}",
            })

            if context.get("artifact_paths"):
                allowed = context.get("artifact_paths")
                if isinstance(allowed, list):
                    allowed_list = ", ".join(str(p) for p in allowed if isinstance(p, str))
                else:
                    allowed_list = str(allowed)
                messages.insert(2, {
                    "role": "system",
                    "content": (
                        "You MUST only use the following workspace-relative files in args: "
                        f"{allowed_list}. "
                        "Do not reference any other paths."
                    ),
                })

            if context.get("revision_feedback") or context.get("issues_to_address"):
                issues = context.get("issues_to_address") or []
                feedback = context.get("revision_feedback") or ""
                messages.insert(2, {
                    "role": "system",
                    "content": (
                        "This is a revision request. You must fix all issues listed. "
                        f"Issues: {issues}. Feedback: {feedback}. "
                        "Return a corrected, complete JSON plan."
                    ),
                })

        return messages

    def _load_planning_context(self) -> str:
        """Load planning guidelines and context (cached)."""
        skills_dir = self.workspace_root / "OrbitronAgents" / "Planner" / "Skills"
        fallback_dir = Path(__file__).resolve().parents[2] / "OrbitronAgents" / "Planner" / "Skills"

        context_parts = []

        search_dir = skills_dir if skills_dir.exists() else fallback_dir
        if search_dir.exists():
            essential_files = ["01_planning_philosophy.md", "02_task_analysis.md", "03_plan_structure.md"]
            for filename in essential_files:
                skill_file = search_dir / filename
                if skill_file.exists():
                    try:
                        content = skill_file.read_text(encoding="utf-8")
                        if len(content) > 2000:
                            content = content[:2000] + "\n...[truncated]"
                        context_parts.append(f"## {skill_file.stem}\n\n{content}")
                    except Exception as e:
                        print(f"[PlannerAgent] Warning: Could not load {skill_file}: {e}")

        if not context_parts:
            context_parts.append(self._get_default_planning_context())

        return "\n\n---\n\n".join(context_parts)

    def _get_default_planning_context(self) -> str:
        """Get default planning context if no skill files are present."""
        return """# Planning Guidelines

## Core Principles
1. Think before acting - always analyze first
2. Break complex tasks into manageable steps
3. Identify dependencies between steps
4. Consider risks and edge cases
5. Prioritize based on impact and urgency

## Planning Process
1. Understand the goal completely
2. Gather necessary context
3. Break down into atomic steps
4. Identify dependencies
5. Estimate effort for each step
6. Create execution order
7. Document assumptions

## Output Format
Always provide structured plans with:
- Clear step descriptions
- Dependencies between steps
- Priority levels
- Estimated effort
- Potential risks
"""

    def _plan_schema_description(self) -> str:
        """Return the JSON schema description for planning output."""
        return (
            "{\n"
            "  \"plan_type\": \"execution|experience\",\n"
            "  \"id\": string,\n"
            "  \"title\": string,\n"
            "  \"description\": string,\n"
            "  \"summary\": string,\n"
            "  \"steps\": [ {\"id\": string, \"description\": string, \"priority\": string, \"estimated_time\": string, \"depends_on\": [string], \"skill\": \"programming|word|opencode\", \"action\": string, \"args\": { \"path\": string, \"description\": string, \"name\": string, \"options\": object }, \"outputs\": [string], \"acceptance_criteria\": [string]} ],\n"
            "  \"artifacts\": [string],\n"
            "  \"edge_cases\": [string],\n"
            "  \"itinerary\": [ {\"time\": string, \"activity\": string} ],\n"
            "  \"logistics\": {\"transport\": string, \"permits\": string, \"campsite\": string, \"weather\": string},\n"
            "  \"packing_list\": [string],\n"
            "  \"risks\": [string],\n"
            "  \"assumptions\": [string],\n"
            "  \"metadata\": { }\n"
            "}\n\n"
            "IMPORTANT: args MUST NOT contain code, HTML, CSS, JS, or any file contents. "
            "Only use: path, description, name, options. "
            "The Executor creates all actual content."
        )

    def _allowed_executor_actions(self) -> dict[str, list[str]]:
        """Return allowed executor skills and actions."""
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

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from text, handling markdown fences and nested objects."""
        if not text:
            return None

        # 1. Try parsing the entire text as JSON
        try:
            obj = json.loads(text.strip())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        # 2. Try fenced JSON blocks
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        for fence in re.finditer(fence_pattern, text):
            try:
                candidate = fence.group(1).strip()
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        # 3. Brace-matching: find the first '{' and match its closing '}'
        # This is O(n) instead of the old O(n^2) brute-force approach
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        # Try the next '{' position
                        next_start = text.find("{", i + 1)
                        if next_start == -1:
                            return None
                        # Recurse from next '{' (limited depth to prevent issues)
                        return self._extract_json_from(text, next_start)
                    break

        return None

    def _extract_json_from(self, text: str, start: int) -> dict[str, Any] | None:
        """Extract JSON starting from a specific position using brace-matching."""
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        return None

    def _validate_plan(self, plan: dict[str, Any]) -> bool:
        """Validate plan completeness with detailed logging."""
        if not isinstance(plan, dict):
            return False

        plan_type = self._infer_plan_type(plan, "", {})

        # Check top-level required fields
        required_fields = ["title", "description", "summary", "steps"]
        missing_fields = [f for f in required_fields if f not in plan or not plan.get(f)]
        if missing_fields:
            return False

        steps = plan.get("steps") or []
        if not isinstance(steps, list):
            return False
        if len(steps) == 0:
            return False

        if plan_type == "execution":
            allowed = self._allowed_executor_actions()

            for step in steps:
                if not isinstance(step, dict):
                    continue

                skill = step.get("skill")
                action = step.get("action")
                if skill and skill not in allowed:
                    return False
                elif skill and action and action not in allowed.get(skill, []):
                    return False

                # Validate args does NOT contain code/content
                args = step.get("args")
                if isinstance(args, dict):
                    for arg_key, arg_value in args.items():
                        if isinstance(arg_value, str) and len(arg_value) > 1000:
                            return False
                        if isinstance(arg_value, str) and any(marker in arg_value for marker in ["<!DOCTYPE", "<html", "<!doctype", "<HTML", "function ", "def ", "class ", "import ", "#include", "<?php", "<?xml"]):
                            return False

            if "artifacts" not in plan:
                return False

            return True

        # Experience plan validation
        for field in ["itinerary", "packing_list", "risks"]:
            if field not in plan:
                return False

        return True

    def _coerce_plan(self, plan: dict[str, Any], request: str) -> dict[str, Any]:
        """Ensure plan has required fields and defaults."""
        plan_type = self._infer_plan_type(plan, request, {})
        plan.setdefault("plan_type", plan_type)
        plan.setdefault("id", f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        plan.setdefault("title", request[:80])
        plan.setdefault("description", request)
        plan.setdefault("summary", plan.get("description", ""))
        plan.setdefault("steps", [])
        plan.setdefault("artifacts", [])
        plan.setdefault("edge_cases", [])
        plan.setdefault("itinerary", [])
        plan.setdefault("logistics", {})
        plan.setdefault("packing_list", [])
        plan.setdefault("risks", [])
        plan.setdefault("assumptions", [])
        plan.setdefault("metadata", {})
        if isinstance(plan.get("metadata"), dict):
            plan["metadata"].setdefault("plan_type", plan_type)
        return plan

    def _infer_plan_type(self, plan: dict[str, Any] | None, request: str, context: dict[str, Any]) -> str:
        """Infer plan type for validation and defaults."""
        if isinstance(plan, dict):
            plan_type = plan.get("plan_type")
            if isinstance(plan_type, str) and plan_type.strip():
                return plan_type.strip()
            metadata_type = plan.get("metadata", {}).get("plan_type")
            if isinstance(metadata_type, str) and metadata_type.strip():
                return metadata_type.strip()

            steps = plan.get("steps") or []
            if any(isinstance(step, dict) and step.get("skill") for step in steps):
                return "execution"

        text = f"{request} {json.dumps(context, ensure_ascii=False)}".lower()
        execution_keywords = [
            "code", "programm", "develop", "implement", "homepage", "website", "web",
            "frontend", "backend", "api", "bug", "fix", "refactor", "test", "automation",
        ]
        experience_keywords = [
            "wandern", "hike", "reise", "travel", "camping", "itinerary", "hotel", "flug", "flight",
        ]

        if any(k in text for k in execution_keywords):
            return "execution"
        if any(k in text for k in experience_keywords):
            return "experience"

        return "execution"

    def think(self, request: str, context: dict | None = None) -> dict[str, Any]:
        """Analyze a request and prepare planning context (legacy)."""
        messages = [
            {
                "role": "system",
                "content": f"""You are the Orbitron Planner Agent. Your role is to think strategically and create structured plans.

{self._planning_context}

## Your Capabilities
You have access to planning tools:
- create_plan: Create a structured plan with steps
- analyze_task: Break down tasks into sub-tasks
- get_plan: Retrieve existing plans
- list_plans: List all plans
- update_step: Update step status

## Important Rules
1. You ONLY plan - you do NOT execute
2. Always think through the entire problem before creating a plan
3. Consider edge cases and dependencies
4. Be specific in step descriptions
5. Identify what could go wrong
6. Suggest which agent or tool should execute each step

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
            },
            {
                "role": "user",
                "content": request
            }
        ]

        return {
            "messages": messages,
            "context": {
                "has_kernel": self.kernel is not None,
                "workspace": str(self.workspace_root),
                "available_tools": [t["function"]["name"] for t in self.skill.get_tools()]
            }
        }

    def plan(self, request: str, context: dict | None = None) -> dict[str, Any]:
        """Create a complete plan for the given request (legacy)."""
        planning_context = self.think(request, context)

        # Add planning-specific instructions
        planning_context["messages"].insert(1, {
            "role": "system",
            "content": """For this request, please:
1. First analyze the task complexity
2. Break it down into logical steps
3. Create a structured plan using the create_plan tool
4. Include dependencies between steps
5. Assign priorities (critical/high/medium/low)
6. Estimate effort for each step
7. Identify potential risks

Respond with your analysis and the created plan."""
        })

        return planning_context

    def get_skill(self) -> PlannerSkill:
        """Get the planner skill for registration with kernel."""
        return self.skill

    def get_status(self) -> dict[str, Any]:
        """Get current planner status."""
        return {
            "initialized": True,
            "workspace": str(self.workspace_root),
            "plans_count": len(self.skill._plans),
            "available_tools": [t["function"]["name"] for t in self.skill.get_tools()],
            "kernel_connected": self.kernel is not None,
            "autonomous_mode": self.autonomous_mode,
            "autonomous_agent_ready": self._autonomous_agent is not None,
        }


def create_planner_agent(kernel=None, workspace_root: str | None = None) -> PlannerAgent:
    """Create and initialize a Planner Agent instance."""
    return PlannerAgent(kernel=kernel, workspace_root=workspace_root)


# Skill factory function for dynamic loading
def create_skill() -> AgentSkill:
    """Create and return a PlannerSkill instance.

    This function is used by the kernel's skill loading system.
    """
    return PlannerSkill()


if __name__ == "__main__":
    # Test the planner agent
    planner = create_planner_agent()

    print("\n" + "="*50)
    print("PLANNER AGENT STATUS")
    print("="*50)
    status = planner.get_status()
    for key, value in status.items():
        print(f"{key}: {value}")

    print("\n" + "="*50)
    print("PLANNING CONTEXT (first 800 chars)")
    print("="*50)
    print(planner._planning_context[:800] + "..." if len(planner._planning_context) > 800 else planner._planning_context)

    print("\n" + "="*50)
    print("AVAILABLE TOOLS")
    print("="*50)
    for tool in planner.skill.get_tools():
        print(f"- {tool['function']['name']}: {tool['function']['description']}")
