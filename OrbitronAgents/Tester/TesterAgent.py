"""Tester Agent - Critical Quality Assurance for the Orbitron system.

The Tester Agent is a read-only evaluator that rigorously tests products
created by the Executor. It does NOT modify any files — it only reads,
inspects, and evaluates quality, then reports findings.

Key Principles:
- NEVER modifies the product — read-only inspection
- Very critical quality assessment — finds every flaw
- Uses specialized testing skills (quality checks, browser testing)
- Can trigger a second iteration by reporting quality failures
- Has its own context and system prompt separate from Executor
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from OrbitronAgents.Tester.skills.quality_check import QualityCheckSkill
from OrbitronAgents.Tester.skills.browser_testing import BrowserTestingSkill

# Import autonomous agent base
from OrbitronAgents.base.autonomous_agent import AutonomousAgent, AgentLoopResult

logger = logging.getLogger("TesterAgent")


@dataclass
class TestResult:
    """Result of a quality test."""
    passed: bool
    quality_rating: str = "poor"  # excellent, good, poor
    issues: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "quality_rating": self.quality_rating,
            "issues": self.issues,
            "summary": self.summary,
            "details": self.details,
        }


class TesterAgent:
    """Tester Agent — Critical Quality Assurance Evaluator.

    The Tester Agent is the system's quality gate. It receives artifacts from
    the Executor and rigorously tests them for quality, completeness, and
    correctness. It NEVER modifies files — it only inspects and reports.

    Quality Ratings:
    - "excellent": No issues found, product is production-ready
    - "good": Minor issues found, but product is usable
    - "poor": Critical/major issues found, needs rework
    """

    autonomous_mode: bool = True

    def __init__(
        self,
        agent_name: str = "tester",
        workspace_root: str | None = None,
        kernel=None,
        max_rounds: int = 18,
    ):
        """Initialize the Tester Agent.

        Args:
            agent_name: Unique name for this tester instance
            workspace_root: Root directory for file access
            kernel: Kernel instance for LLM and tool access
            max_rounds: Maximum tool-calling rounds per test
        """
        self.agent_name = agent_name
        self.workspace_root = Path(workspace_root) if workspace_root else Path.home() / ".orbitron" / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.kernel = kernel
        self.max_rounds = max_rounds

        # Skills
        self._quality_skill = QualityCheckSkill()
        self._browser_skill = BrowserTestingSkill()

        # Autonomous agent instance
        self._autonomous_agent: Optional[AutonomousAgent] = None
        self._submit_test_data: Optional[dict[str, Any]] = None

        if self.kernel:
            self._setup_autonomous_agent()

        logger.info("[TesterAgent] Initialized: %s (autonomous_mode=%s)", self.agent_name, self.autonomous_mode)

    def _setup_autonomous_agent(self) -> None:
        """Create and configure the AutonomousAgent instance."""
        system_prompt = """You are the Orbitron Tester Agent. You are a CRITICAL quality assurance evaluator.

## Your Identity
You are the system's quality gate. Your job is to find EVERY flaw, every missing feature, every inconsistency.
You are NOT the builder — you are the critic. You do NOT modify files. You only READ, INSPECT, and EVALUATE.
Be thorough. Be strict. Be critical. A product that passes your review should be genuinely good.

## Your Mindset
- Assume the product is broken until proven otherwise
- Look for edge cases, missing error handling, and subtle bugs
- Check that the product ACTUALLY matches the requirements
- Never accept placeholder content, TODOs, or incomplete implementations
- When in doubt, flag it as an issue — better safe than sorry

## CRITICAL: Professional Quality & UX Standards
You are not just testing for "does it work" — you are testing for PROFESSIONAL QUALITY:

### Visual Quality (MANDATORY checks)
- **Spacing & Layout**: Are margins, paddings, and gaps consistent and professional? Misaligned or cramped elements are MAJOR issues.
- **Typography**: Is the font hierarchy clear? Are headings, body text, and labels properly sized and weighted?
- **Color & Contrast**: Do colors work together? Is there sufficient contrast for readability?
- **Visual Consistency**: Do all components share the same design language? No random style variations.
- **Polish**: Are there hover effects, transitions, focus states? Does it feel smooth and professional?
- **Responsive Design**: Does the layout work on mobile, tablet, AND desktop? Broken responsive = MAJOR issue.

### UX Quality (MANDATORY checks)
- **Intuitive Navigation**: Can a user figure out what to do without instructions?
- **Clear Visual Hierarchy**: What's important? What's secondary? Can you tell at a glance?
- **Feedback**: Do actions provide visual feedback? Loading states, success/error messages?
- **Accessibility**: Can keyboard users navigate? Are there ARIA labels? Color contrast ratios?
- **Error Handling**: What happens when things go wrong? Are errors handled gracefully?

### Professional Standards
- A "working" product with ugly design is NOT acceptable — flag visual issues as MAJOR
- A "functional" product with poor UX is NOT acceptable — flag UX issues as MAJOR
- Placeholder content, TODO comments, or "lorem ipsum" are CRITICAL issues
- Inconsistent spacing, misaligned elements, or visual bugs are MAJOR issues
- Missing hover states, transitions, or micro-interactions are at least MINOR issues

## CRITICAL RULE
- **NEVER modify any files.** You are READ-ONLY. Use only inspection and verification tools.
- If you accidentally create or modify a file, report it as a critical failure immediately.

## CRITICAL: Build Verification (MANDATORY — DO THIS FIRST)
**The #1 priority is to verify the product actually builds/compiles/runs.** Do this BEFORE reading files in detail.

For any software project (Angular, React, Vue, Node.js, Python, etc.):
1. **Round 1-2: BUILD the project** — Use `verify_build` (PREFERRED) or `run_command`:
   - **BEST**: Use `verify_build` with `path` pointing to the project directory. It auto-detects the project type and runs the correct build command.
   - **ALTERNATIVE**: Use `run_command` with the appropriate build command and `timeout: 120` or higher.
2. **Check the result**: ALWAYS check `returncode` — 0 means success, any other value means FAILURE.
3. **If the build FAILS**: Report ALL compilation errors as CRITICAL issues. Read `stderr` and `error_summary` for details.
4. **If the build succeeds**: Continue with further testing.

## CRITICAL: Reading Command Output
When you run `run_command` or `verify_build`, the result contains structured output:
- `returncode`: 0 means success, any other value means failure. ALWAYS check this.
- `stdout`: The command's standard output.
- `stderr`: The command's error output. When returncode ≠ 0, this contains the error details.
- `error_type`: Classification of the error (build_error, dependency_error, timeout, etc.)
- `suggestion`: Actionable suggestion for fixing the error.
- `error_summary`: First few lines of the error output for quick diagnosis.
- If you see `❌ COMMAND FAILED` or `❌ BUILD FAILED`, the command did NOT succeed.
- If you see `✅ COMMAND SUCCEEDED` or `✅ BUILD SUCCEEDED`, the command succeeded.

## CRITICAL: Start Real Applications for Testing
If the product is a web application or has a dev server:
1. **Start the application** — Use `run_command` to start the dev server (e.g., `cd <project_dir> && npm start`, `ng serve`, `npm run dev`)
   - Use a timeout of 30-60 seconds and run in background if possible
   - For Angular: `cd <project_dir> && npx ng serve --port 4200 &`
2. **Test in a real browser** — Use `browser_open_page` to open `http://localhost:4200` (or whatever port)
3. **Check for runtime errors** — Use `browser_check_console` to find JavaScript errors
4. **Test functionality** — Use `browser_check_elements`, `browser_test_interaction`

For non-web projects (Python scripts, markdown files, documents):
- Read the files and verify content completeness
- Use `check_syntax` for code files
- Run the code if possible (`run_command` with `python <file>`)

## Your Testing Workflow (FOLLOW THIS ORDER)
1. **BUILD FIRST** (rounds 1-2): Run the build/compile command. If it fails, report ALL errors immediately.
2. **START THE APP** (rounds 2-3): If it's a web project, start the dev server.
3. **BROWSER TEST** (rounds 3-5): Open the app in a browser and check for runtime errors.
4. **VISUAL & UX REVIEW** (rounds 5-8): Check spacing, alignment, typography, colors, responsiveness, and overall polish.
5. **CODE REVIEW** (rounds 8-10): Read key files and check for quality issues.
6. **SUBMIT** (round 10-12): Call `submit_test_result` with your findings.

## Quality Ratings — BE STRICT
- **"excellent"**: Build succeeds, app runs, ZERO issues found. Professional visual quality. Polished UX. Production-ready.
- **"good"**: Build succeeds, app runs, ONLY minor/cosmetic issues. NO major or critical issues at all. Still looks professional.
- **"poor"**: Build FAILS, OR app has ANY major/critical issues. This includes:
  - Compilation errors or build failures
  - Broken functionality or JavaScript errors
  - Missing CSS classes or broken styles
  - Poor spacing, misaligned elements, or visual inconsistencies
  - Missing responsive behavior
  - Placeholder content or TODO comments
  - Poor UX (confusing navigation, missing feedback, inaccessible)

## CRITICAL: Rating Rules
- If you find ANY issue with severity "major" or "critical", you MUST rate "poor" and set passed=False.
- If you find 3+ minor issues, consider upgrading to "poor" — that many small problems indicate poor quality.
- Do NOT rate "good" if there are major or critical issues. The system auto-corrects inconsistent ratings.
- **Visual/UX issues are NOT just "cosmetic"** — poor spacing, misalignment, and ugly design are MAJOR issues.
- **A product that works but looks amateur is NOT "good"** — rate it "poor" and flag the visual issues.
- When in doubt, rate "poor" — it's better to flag issues than to let substandard work through.

## Tool Guidelines
- `verify_build`: **PREFERRED for build verification** — Auto-detects project type and runs the correct build command. Returns structured results with error classification. Use this FIRST to check if the project builds.
- `run_command`: Execute shell commands — use for starting dev servers, running tests, etc. Always use `timeout: 120` or higher for builds.
- `read_file`: Read artifact files AFTER verifying the build
- `list_directory`: Explore the project structure
- `search_files`: Search for patterns, TODOs, potential issues
- `check_code_quality`: Analyze code for bugs, security issues, code smells
- `check_cross_file_consistency`: Verify files work together correctly
- `browser_open_page`: Open an HTML page in a real browser for testing
- `browser_check_console`: **CRITICAL** — Check for JavaScript/runtime errors
- `browser_check_elements`: Verify specific elements exist and are visible
- `browser_test_responsive`: Test responsive design at different viewport sizes
- `browser_screenshot`: Take screenshots for visual verification
- `submit_test_result`: **TERMINAL TOOL** — Call this when your evaluation is complete
- `ask_question`: **TERMINAL TOOL** — Call this if you need clarification

## How to Judge
Be especially critical about:
1. **Does the project BUILD?** If `ng build` or `npm run build` has errors, that's a CRITICAL failure.
2. **Does the app RUN?** If `ng serve` or `npm start` fails, that's a CRITICAL failure.
3. **Does it LOOK PROFESSIONAL?** Poor spacing, misalignment, ugly colors, or amateur design are MAJOR issues.
4. **Is the UX GOOD?** Confusing navigation, missing feedback, or inaccessible elements are MAJOR issues.
5. Are there TypeScript/compilation errors? Report EVERY error as a separate issue.
6. Are there runtime errors in the browser console? Report them.
7. Does it match the requirements? (Compare against the original task)
8. Are there security issues? (XSS, eval, hardcoded secrets)
"""

        self._autonomous_agent = AutonomousAgent(
            agent_name=self.agent_name,
            system_prompt=system_prompt,
            kernel=self.kernel,
            max_rounds=self.max_rounds,
            urgency_threshold=0.5,
        )

        # Register read-only kernel tools (NO file-write tools)
        self._autonomous_agent.register_file_tools()
        self._autonomous_agent.register_search_tool()
        self._autonomous_agent.register_syntax_tool()
        self._autonomous_agent.register_command_tool()  # Needed to start test servers
        self._autonomous_agent.register_verify_build_tool()  # Needed to verify builds

        # Register web search/fetch tools for verification
        self._autonomous_agent.register_tool(
            name="web_search",
            description="Search the web for information. Useful for verifying library APIs, checking best practices, or looking up documentation.",
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
            description="Fetch and read a web page by URL. Useful for reading documentation, API references, or verifying that external resources exist.",
            schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "The URL of the web page to fetch"},
                },
            },
            handler=lambda args: self.kernel._dispatch_tool("web_fetch", args) if self.kernel else {"ok": False, "error": "No kernel available"},
        )

        # Register quality check tools
        for tool_def in self._quality_skill.get_tools():
            handler_name = tool_def["name"]
            handler = self._quality_skill.get_handlers()[handler_name]
            self._autonomous_agent.register_tool(
                name=tool_def["name"],
                description=tool_def["description"],
                schema=tool_def["schema"],
                handler=handler,
            )

        # Register browser testing tools
        for tool_def in self._browser_skill.get_tools():
            handler_name = tool_def["name"]
            handler = self._browser_skill.get_handlers()[handler_name]
            self._autonomous_agent.register_tool(
                name=tool_def["name"],
                description=tool_def["description"],
                schema=tool_def["schema"],
                handler=handler,
            )

        # Register terminal tools
        self._submit_test_data = None
        self._autonomous_agent.register_tool(
            name="submit_test_result",
            description="Submit the quality test result. Call this when your evaluation is complete. Be honest and critical.",
            schema={
                "type": "object",
                "required": ["quality_rating", "summary"],
                "properties": {
                    "quality_rating": {
                        "type": "string",
                        "enum": ["excellent", "good", "poor"],
                        "description": "Overall quality rating: 'excellent' (no issues), 'good' (minor issues only), 'poor' (critical/major issues)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Summary of your quality assessment",
                    },
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                                "type": {"type": "string", "description": "Issue category"},
                                "description": {"type": "string", "description": "Description of the issue"},
                            },
                        },
                        "description": "List of issues found during testing",
                    },
                    "passed": {
                        "type": "boolean",
                        "description": "Whether the product passes quality checks (true if quality_rating is 'excellent' or 'good')",
                    },
                    "recommendations": {
                        "type": "string",
                        "description": "Specific recommendations for improvement (if any)",
                    },
                },
            },
            handler=self._handle_submit_test_result,
        )

        self._autonomous_agent.register_tool(
            name="ask_question",
            description="Ask the Orchestrator for clarification on requirements.",
            schema={
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"},
                },
            },
            handler=self._handle_ask_question,
        )

        # Remove write tools from the autonomous agent — tester is READ-ONLY
        self._ensure_read_only()

    def _ensure_read_only(self) -> None:
        """Remove file-write tools but keep run_command for starting test servers."""
        # The tester should NOT create/modify/delete files, but it CAN run commands
        # to start servers for browser testing
        write_tools = {"create_file", "update_file", "delete_file"}
        for tool_name in write_tools:
            if tool_name in self._autonomous_agent._tools:
                del self._autonomous_agent._tools[tool_name]
            if tool_name in self._autonomous_agent._handlers:
                del self._autonomous_agent._handlers[tool_name]
        logger.info("[TesterAgent] Removed file-write tools (kept run_command for testing servers)")

    def _handle_submit_test_result(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle submit_test_result tool call from the autonomous loop.

        Automatically corrects inconsistent ratings: if major or critical
        issues are found, the quality rating is downgraded to 'poor' and
        passed is set to False, regardless of what the LLM submitted.
        """
        quality_rating = args.get("quality_rating", "poor")
        issues = args.get("issues", [])
        passed = args.get("passed", False)

        # Auto-correct: major or critical issues downgrade quality to "poor"
        major_or_critical = [
            i for i in issues
            if isinstance(i, dict) and i.get("severity") in ("major", "critical")
        ]
        if major_or_critical:
            if quality_rating in ("excellent", "good"):
                logger.warning(
                    "[TesterAgent] Auto-correcting quality_rating from '%s' to 'poor': "
                    "%d major/critical issue(s) found",
                    quality_rating, len(major_or_critical),
                )
                quality_rating = "poor"
            if passed:
                logger.warning(
                    "[TesterAgent] Auto-correcting passed from True to False: "
                    "%d major/critical issue(s) found",
                    len(major_or_critical),
                )
                passed = False

        self._submit_test_data = {
            "quality_rating": quality_rating,
            "summary": args.get("summary", ""),
            "issues": issues,
            "passed": passed,
            "recommendations": args.get("recommendations", ""),
        }
        return {"ok": True, "message": "Test result submitted successfully"}

    def _handle_ask_question(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle ask_question tool call from the autonomous loop."""
        return {
            "ok": True,
            "message": "Question forwarded to Orchestrator",
            "question": args.get("question", ""),
        }

    # ========== Public Interface ==========

    def test_quality(
        self,
        task_description: str,
        artifacts: list[str],
        requirements: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
    ) -> TestResult:
        """Test the quality of artifacts produced by the Executor.

        Args:
            task_description: Description of the original task
            artifacts: List of artifact file paths to test
            requirements: Original requirements for validation
            execution_result: Result from the Executor

        Returns:
            TestResult with quality_rating, issues, and summary
        """
        if not self._autonomous_agent:
            logger.error("[TesterAgent] Cannot test quality: no autonomous agent (kernel missing?)")
            return TestResult(
                passed=False,
                quality_rating="poor",
                issues=[{"severity": "critical", "type": "system_error", "description": "Tester agent not initialized"}],
                summary="Testing failed: autonomous agent not initialized",
            )

        logger.info("[TesterAgent] Starting quality test for: %.100s...", task_description)

        # Reset submit data
        self._submit_test_data = None

        # Build the test prompt
        artifacts_str = "\n".join(f"- {a}" for a in artifacts)
        requirements_str = ""
        if requirements:
            requirements_str = f"\n\nOriginal Requirements:\n{json.dumps(requirements, indent=2, default=str)}"

        execution_info = ""
        if execution_result:
            success = execution_result.get("success", "unknown")
            summary = execution_result.get("summary", "")
            execution_info = f"\n\nExecutor Result: success={success}\nExecutor Summary: {summary}"

        test_prompt = f"""## Task Description
{task_description}
{requirements_str}
{execution_info}

## Artifacts to Test
The following files were created/modified:
{artifacts_str}

## Instructions
You must thoroughly test these artifacts for quality. Be CRITICAL and find every flaw.

1. Read every artifact file
2. Run quality checks (check_html_structure, check_code_quality, etc.)
3. Check cross-file consistency
4. Verify requirements coverage
5. If HTML files exist, test them in the browser (browser_open_page, browser_check_elements, etc.)
6. Report your honest assessment via submit_test_result

Remember: You are READ-ONLY. Do NOT modify any files. Only inspect and evaluate."""

        # Run the autonomous test loop
        loop_result = self._autonomous_agent.run_task(
            task_description=test_prompt,
            context=execution_result,
            max_rounds=self.max_rounds,
        )

        # Build result from loop output
        if self._submit_test_data:
            result = TestResult(
                passed=self._submit_test_data.get("passed", False),
                quality_rating=self._submit_test_data.get("quality_rating", "poor"),
                issues=self._submit_test_data.get("issues", []),
                summary=self._submit_test_data.get("summary", ""),
                details={
                    "recommendations": self._submit_test_data.get("recommendations", ""),
                    "tool_calls": loop_result.tool_calls_made,
                    "rounds": loop_result.rounds_used,
                },
            )
        elif loop_result.done:
            # Loop finished without submit_test_result — parse content as best effort
            result = TestResult(
                passed=False,
                quality_rating="poor",
                summary=loop_result.content[:500],
                issues=[{
                    "severity": "critical",
                    "type": "incomplete_test",
                    "description": "Tester did not submit a formal test result",
                }],
                details={
                    "tool_calls": loop_result.tool_calls_made,
                    "rounds": loop_result.rounds_used,
                },
            )
        else:
            result = TestResult(
                passed=False,
                quality_rating="poor",
                summary="Testing did not complete successfully",
                issues=[{
                    "severity": "critical",
                    "type": "test_failure",
                    "description": "Testing loop failed to complete",
                }],
                details={
                    "tool_calls": loop_result.tool_calls_made,
                    "rounds": loop_result.rounds_used,
                },
            )

        # Close browser if it was opened
        try:
            self._browser_skill.browser_close()
        except Exception:
            pass

        logger.info(
            "[TesterAgent] Quality test complete: passed=%s, rating=%s, issues=%d",
            result.passed,
            result.quality_rating,
            len(result.issues),
        )

        return result

    # ========== Status ==========

    def get_status(self) -> dict[str, Any]:
        """Get tester status."""
        return {
            "agent_name": self.agent_name,
            "workspace": str(self.workspace_root),
            "autonomous_mode": self.autonomous_mode,
            "autonomous_agent_ready": self._autonomous_agent is not None,
            "browser_testing_available": self._browser_skill._ensure_playwright(),
        }


def create_tester_agent(
    agent_name: str = "tester",
    workspace_root: str | None = None,
    kernel=None,
) -> TesterAgent:
    """Factory function to create a Tester Agent."""
    return TesterAgent(
        agent_name=agent_name,
        workspace_root=workspace_root,
        kernel=kernel,
    )