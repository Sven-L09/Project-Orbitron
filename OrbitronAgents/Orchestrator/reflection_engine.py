"""Reflection Engine for the Orbitron Orchestrator.

Provides self-reflection capabilities for continuous learning from task outcomes.
Analyzes what went well, what could be improved, and stores learnings for future tasks.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Orchestrator.ReflectionEngine")


@dataclass
class ReflectionEntry:
    """A single reflection entry with learnings."""
    task_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True

    # What went well
    positives: list[str] = field(default_factory=list)

    # What could be improved
    improvements: list[str] = field(default_factory=list)

    # Lessons learned for future tasks
    learnings: list[str] = field(default_factory=list)

    # Patterns detected
    patterns: list[str] = field(default_factory=list)

    # Recommendations for next similar task
    recommendations: list[str] = field(default_factory=list)

    # Metadata
    task_type: str = "unknown"
    duration_seconds: float = 0.0
    planning_iterations: int = 0
    execution_steps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "positives": self.positives,
            "improvements": self.improvements,
            "learnings": self.learnings,
            "patterns": self.patterns,
            "recommendations": self.recommendations,
            "task_type": self.task_type,
            "duration_seconds": self.duration_seconds,
            "planning_iterations": self.planning_iterations,
            "execution_steps": self.execution_steps,
        }


class ReflectionEngine:
    """Engine for self-reflection and continuous learning.

    After each task completion, the ReflectionEngine:
    1. Analyzes what went well and what didn't
    2. Identifies patterns across tasks
    3. Extracts learnings for future tasks
    4. Updates USER.md with new preferences (optional)
    5. Provides recommendations for similar future tasks

    This creates a feedback loop that makes the system smarter over time.
    """

    def __init__(
        self,
        workspace_root: str,
        reflections_dir: Optional[str] = None,
        max_reflections: int = 100,
    ):
        self.workspace_root = Path(workspace_root)
        self.reflections_dir = Path(reflections_dir) if reflections_dir else self.workspace_root / ".orbitron" / "reflections"
        self.reflections_dir.mkdir(parents=True, exist_ok=True)

        self._reflections: list[ReflectionEntry] = []
        self._max_reflections = max_reflections

        # Load existing reflections
        self._load_reflections()

        logger.info("[ReflectionEngine] Initialized at %s", self.reflections_dir)

    # ========== Reflection Creation ==========

    def reflect_on_task(
        self,
        task_id: str,
        result: dict[str, Any],
        duration_seconds: float = 0.0,
    ) -> ReflectionEntry:
        """Create a reflection entry after task completion.

        Args:
            task_id: ID of the completed task
            result: Task result dictionary
            duration_seconds: Total task duration

        Returns:
            ReflectionEntry with analysis
        """
        success = result.get("success", False)
        plan = result.get("plan", {})
        execution = result.get("execution", {})
        validation = result.get("validation", {})

        # Extract metadata
        planning_iterations = result.get("iterations", 1) or 1
        execution_steps = execution.get("steps_executed", 0) if isinstance(execution, dict) else 0
        task_type = plan.get("plan_type", "unknown") if isinstance(plan, dict) else "unknown"

        # Create reflection entry
        entry = ReflectionEntry(
            task_id=task_id,
            success=success,
            task_type=task_type,
            duration_seconds=duration_seconds,
            planning_iterations=planning_iterations,
            execution_steps=execution_steps,
        )

        # Analyze positives
        entry.positives = self._identify_positives(result, planning_iterations, execution_steps)

        # Analyze improvements
        entry.improvements = self._identify_improvements(result, planning_iterations, execution_steps)

        # Extract learnings
        entry.learnings = self._extract_learnings(entry)

        # Detect patterns
        entry.patterns = self._detect_patterns(entry)

        # Generate recommendations
        entry.recommendations = self._generate_recommendations(entry)

        # Store reflection
        self._reflections.append(entry)
        self._trim_reflections()
        self._save_reflections()

        logger.info(
            "[ReflectionEngine] Reflected on task %s: %d positives, %d improvements, %d learnings",
            task_id,
            len(entry.positives),
            len(entry.improvements),
            len(entry.learnings),
        )

        return entry

    def _identify_positives(
        self,
        result: dict[str, Any],
        planning_iterations: int,
        execution_steps: int,
    ) -> list[str]:
        """Identify what went well in the task."""
        positives = []

        # Task completed successfully
        if result.get("success"):
            positives.append("Task completed successfully")

        # Plan approved on first iteration
        if planning_iterations == 1:
            positives.append("Plan approved on first iteration (high quality)")

        # All steps executed successfully
        exec_result = result.get("execution", {}).get("execution_result", {}) if isinstance(result.get("execution"), dict) else {}
        steps_failed = exec_result.get("steps_failed", 0) if isinstance(exec_result, dict) else 0
        if steps_failed == 0 and execution_steps > 0:
            positives.append("All execution steps completed without errors")

        # Validation passed on first try
        validation = result.get("validation", {})
        if isinstance(validation, dict) and validation.get("iterations", 1) <= 1:
            positives.append("Execution validation passed on first iteration")

        # Fast completion
        duration = result.get("duration_seconds", 0)
        if duration > 0 and duration < 60:  # Under 1 minute
            positives.append(f"Task completed quickly ({duration:.1f}s)")

        return positives

    def _identify_improvements(
        self,
        result: dict[str, Any],
        planning_iterations: int,
        execution_steps: int,
    ) -> list[str]:
        """Identify areas for improvement."""
        improvements = []

        # Multiple planning iterations needed
        if planning_iterations > 1:
            improvements.append(
                f"Plan required {planning_iterations} iterations - consider improving initial plan quality"
            )

        # Task failed
        if not result.get("success"):
            error = result.get("error", "Unknown error")
            improvements.append(f"Task failed: {error}")

        # Execution failures
        exec_result = result.get("execution", {}).get("execution_result", {}) if isinstance(result.get("execution"), dict) else {}
        if isinstance(exec_result, dict):
            steps_failed = exec_result.get("steps_failed", 0)
            if steps_failed > 0:
                improvements.append(f"{steps_failed} execution step(s) failed")

            errors = exec_result.get("errors", [])
            if errors:
                for err in errors[:3]:  # Top 3 errors
                    if isinstance(err, dict):
                        step_id = err.get("step_id", "unknown")
                        err_msg = err.get("error", "Unknown")
                        improvements.append(f"Step {step_id}: {err_msg}")

        # Validation required multiple iterations
        validation = result.get("validation", {})
        if isinstance(validation, dict):
            val_iterations = validation.get("iterations", 1)
            if val_iterations > 1:
                improvements.append(
                    f"Validation required {val_iterations} iterations - improve execution quality"
                )

        # Long duration
        duration = result.get("duration_seconds", 0)
        if duration > 300:  # Over 5 minutes
            improvements.append(f"Task took {duration:.1f}s - consider optimization")

        return improvements

    def _extract_learnings(self, entry: ReflectionEntry) -> list[str]:
        """Extract generalizable learnings from the reflection."""
        learnings = []

        # Success-based learnings
        if entry.success:
            if entry.planning_iterations == 1:
                learnings.append("Clear initial requirements lead to faster plan approval")
            if entry.execution_steps > 0:
                learnings.append(f"Execution of {entry.execution_steps} steps completed successfully")

        # Failure-based learnings
        if not entry.success:
            learnings.append("Review failure patterns to prevent recurrence")
            if entry.planning_iterations >= 3:
                learnings.append("Complex planning may indicate unclear task requirements")

        # Pattern-based learnings
        if entry.task_type == "execution":
            learnings.append("Execution tasks benefit from detailed artifact specifications")
        elif entry.task_type == "experience":
            learnings.append("Experience tasks require comprehensive risk assessment")

        return learnings

    def _detect_patterns(self, entry: ReflectionEntry) -> list[str]:
        """Detect patterns across reflections."""
        patterns = []

        # Look at recent reflections
        recent = self._reflections[-10:] if len(self._reflections) >= 10 else self._reflections

        # Pattern: Multiple iterations common
        avg_iterations = sum(r.planning_iterations for r in recent) / len(recent) if recent else 0
        if avg_iterations > 2:
            patterns.append(f"Recent tasks average {avg_iterations:.1f} planning iterations")

        # Pattern: Task type frequency
        type_counts: dict[str, int] = {}
        for r in recent:
            type_counts[r.task_type] = type_counts.get(r.task_type, 0) + 1
        for task_type, count in type_counts.items():
            if count >= 5:
                patterns.append(f"Frequent task type: {task_type} ({count} times)")

        # Pattern: Success rate trend
        recent_successes = sum(1 for r in recent if r.success)
        success_rate = recent_successes / len(recent) if recent else 0
        if success_rate < 0.5:
            patterns.append(f"Low recent success rate: {success_rate:.0%}")
        elif success_rate > 0.9:
            patterns.append(f"High recent success rate: {success_rate:.0%}")

        return patterns

    def _generate_recommendations(self, entry: ReflectionEntry) -> list[str]:
        """Generate recommendations for similar future tasks."""
        recommendations = []

        # Based on task type
        if entry.task_type == "execution":
            recommendations.append("For code tasks: specify expected file structure upfront")
            recommendations.append("Include acceptance criteria for each artifact")
        elif entry.task_type == "experience":
            recommendations.append("For experience tasks: provide detailed constraints")
            recommendations.append("Consider weather and seasonal factors")

        # Based on iteration count
        if entry.planning_iterations >= 2:
            recommendations.append("Provide more detailed initial requirements to reduce planning iterations")

        # Based on success/failure
        if entry.success:
            recommendations.append("Apply similar approach to future tasks of this type")
        else:
            recommendations.append("Break complex tasks into smaller subtasks")
            recommendations.append("Request intermediate validation checkpoints")

        return recommendations

    # ========== Persistence ==========

    def _load_reflections(self) -> None:
        """Load reflections from disk."""
        reflections_file = self.reflections_dir / "reflections.json"
        if not reflections_file.exists():
            return

        try:
            with open(reflections_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for entry_data in data:
                self._reflections.append(ReflectionEntry(
                    task_id=entry_data.get("task_id", ""),
                    timestamp=datetime.fromisoformat(entry_data.get("timestamp", datetime.now().isoformat())),
                    success=entry_data.get("success", True),
                    positives=entry_data.get("positives", []),
                    improvements=entry_data.get("improvements", []),
                    learnings=entry_data.get("learnings", []),
                    patterns=entry_data.get("patterns", []),
                    recommendations=entry_data.get("recommendations", []),
                    task_type=entry_data.get("task_type", "unknown"),
                    duration_seconds=entry_data.get("duration_seconds", 0.0),
                    planning_iterations=entry_data.get("planning_iterations", 0),
                    execution_steps=entry_data.get("execution_steps", 0),
                ))

            logger.info("[ReflectionEngine] Loaded %d reflections", len(self._reflections))
        except Exception as e:
            logger.warning("[ReflectionEngine] Failed to load reflections: %s", e)

    def _save_reflections(self) -> None:
        """Save reflections to disk."""
        reflections_file = self.reflections_dir / "reflections.json"

        data = [entry.to_dict() for entry in self._reflections]

        try:
            with open(reflections_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[ReflectionEngine] Failed to save reflections: %s", e)

    def _trim_reflections(self) -> None:
        """Trim reflections to max count."""
        if len(self._reflections) > self._max_reflections:
            self._reflections = self._reflections[-self._max_reflections:]

    # ========== Query & Analysis ==========

    def get_reflections(
        self,
        limit: int = 10,
        success_only: bool = False,
        task_type: Optional[str] = None,
    ) -> list[ReflectionEntry]:
        """Get reflections with optional filtering."""
        filtered = self._reflections

        if success_only:
            filtered = [r for r in filtered if r.success]

        if task_type:
            filtered = [r for r in filtered if r.task_type == task_type]

        return filtered[-limit:]

    def get_learnings(self, limit: int = 10) -> list[str]:
        """Get recent learnings."""
        learnings = []
        for entry in reversed(self._reflections[-limit * 2:]):
            learnings.extend(entry.learnings)
            if len(learnings) >= limit:
                break
        return learnings[:limit]

    def get_recommendations_for_type(self, task_type: str) -> list[str]:
        """Get recommendations for a specific task type."""
        recommendations = []
        for entry in reversed(self._reflections):
            if entry.task_type == task_type:
                recommendations.extend(entry.recommendations)
                if len(recommendations) >= 5:
                    break
        return recommendations[:5]

    def get_success_rate(self, window: int = 10) -> float:
        """Get success rate for recent tasks."""
        recent = self._reflections[-window:]
        if not recent:
            return 0.0
        return sum(1 for r in recent if r.success) / len(recent)

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        if not self._reflections:
            return {
                "total_reflections": 0,
                "success_rate": 0.0,
                "avg_planning_iterations": 0.0,
                "avg_duration_seconds": 0.0,
            }

        return {
            "total_reflections": len(self._reflections),
            "success_rate": self.get_success_rate(),
            "avg_planning_iterations": sum(r.planning_iterations for r in self._reflections) / len(self._reflections),
            "avg_duration_seconds": sum(r.duration_seconds for r in self._reflections) / len(self._reflections),
            "task_types": list(set(r.task_type for r in self._reflections)),
        }

    def update_user_profile(self, user_md_path: Optional[str] = None) -> None:
        """Update USER.md with learned preferences.

        This method analyzes reflections and adds new preferences
        to the user profile file.
        """
        user_path = Path(user_md_path) if user_md_path else self.workspace_root / "USER.md"

        if not user_path.exists():
            logger.warning("[ReflectionEngine] USER.md not found at %s", user_path)
            return

        try:
            content = user_path.read_text(encoding="utf-8")

            # Find or create "Gesprächsverlauf & Erinnerungen" section
            section_marker = "## Gesprächsverlauf & Erinnerungen"
            if section_marker not in content:
                # Add section before the last line
                lines = content.split("\n")
                insert_pos = len(lines) - 1
                lines.insert(insert_pos, f"\n{section_marker}\n")
                content = "\n".join(lines)

            # Generate new entry
            summary = self.get_summary()
            timestamp = datetime.now().strftime("%Y-%m-%d")

            new_entry = f"""
- {timestamp}: System-Lernungen aus {summary['total_reflections']} Reflexionen
  - Erfolgsrate: {summary['success_rate']:.0%}
  - Durchschnittliche Planungs-Iterationen: {summary['avg_planning_iterations']:.1f}
  - Learnings: {', '.join(self.get_learnings(3)) or 'Keine spezifischen Learnings'}
"""

            # Insert after section marker
            content = content.replace(
                section_marker,
                f"{section_marker}\n{new_entry}",
                1,
            )

            user_path.write_text(content, encoding="utf-8")
            logger.info("[ReflectionEngine] Updated USER.md with new learnings")

        except Exception as e:
            logger.error("[ReflectionEngine] Failed to update USER.md: %s", e)
