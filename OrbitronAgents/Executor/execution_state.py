"""Execution State Management for the Executor Agent.

Tracks created/modified files and provides context for consistent code generation.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Executor.ExecutionState")


@dataclass
class FileRecord:
    """Record of a file operation."""
    path: str
    action: str  # created, modified, deleted
    size_bytes: int
    created_at: datetime = field(default_factory=datetime.now)
    content_hash: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "action": self.action,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }


@dataclass
class StepResult:
    """Result of executing a single plan step."""
    step_id: str
    success: bool
    action: str
    skill: str
    result: Any = None
    error: Optional[str] = None
    artifacts: list[str] = field(default_factory=list)
    executed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "success": self.success,
            "action": self.action,
            "skill": self.skill,
            "result": self.result,
            "error": self.error,
            "artifacts": self.artifacts,
            "executed_at": self.executed_at.isoformat(),
        }


class ExecutionState:
    """Tracks execution state for a task.

    Provides:
    - File operation tracking (created, modified, deleted)
    - Step execution history
    - Context for consistent code generation
    - Artifact collection
    """

    def __init__(
        self,
        task_id: str,
        workspace_root: str,
    ):
        self.task_id = task_id
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        # File tracking
        self.created_files: list[FileRecord] = []
        self.modified_files: list[FileRecord] = []
        self.deleted_files: list[FileRecord] = []

        # Step tracking
        self.step_results: list[StepResult] = []
        self.current_step_index: int = 0

        # Artifacts
        self.artifacts: list[str] = []

        # Metadata
        self.started_at = datetime.now()
        self.completed_at: Optional[datetime] = None
        self.status: str = "running"  # running, completed, failed
        self.error_message: Optional[str] = None

        logger.info("[ExecutionState] Initialized for task %s", task_id)

    # ========== File Tracking ==========

    def record_file_created(
        self,
        path: str,
        size_bytes: int,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record that a file was created."""
        record = FileRecord(
            path=path,
            action="created",
            size_bytes=size_bytes,
            metadata=metadata or {},
        )
        self.created_files.append(record)
        self._add_artifact(path)
        logger.debug("[ExecutionState] File created: %s (%d bytes)", path, size_bytes)

    def record_file_modified(
        self,
        path: str,
        size_bytes: int,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record that a file was modified."""
        record = FileRecord(
            path=path,
            action="modified",
            size_bytes=size_bytes,
            metadata=metadata or {},
        )
        self.modified_files.append(record)
        logger.debug("[ExecutionState] File modified: %s", path)

    def record_file_deleted(self, path: str) -> None:
        """Record that a file was deleted."""
        record = FileRecord(
            path=path,
            action="deleted",
            size_bytes=0,
        )
        self.deleted_files.append(record)
        logger.debug("[ExecutionState] File deleted: %s", path)

    def file_was_created(self, path: str) -> bool:
        """Check if a file was created during this execution."""
        return any(f.path == path for f in self.created_files)

    def file_was_modified(self, path: str) -> bool:
        """Check if a file was modified during this execution."""
        return any(f.path == path for f in self.modified_files)

    def file_exists_in_execution(self, path: str) -> bool:
        """Check if a file exists (was created or existed before)."""
        # Files created during execution
        if self.file_was_created(path):
            return True
        # Files that existed before and weren't deleted
        if any(f.path == path for f in self.deleted_files):
            return False
        # Check filesystem for pre-existing files
        full_path = self.workspace_root / path
        return full_path.exists()

    def get_created_files(self) -> list[str]:
        """Get list of all created file paths."""
        return [f.path for f in self.created_files]

    def get_modified_files(self) -> list[str]:
        """Get list of all modified file paths."""
        return [f.path for f in self.modified_files]

    def get_all_affected_files(self) -> list[str]:
        """Get all files that were created, modified, or deleted."""
        paths = set()
        paths.update(f.path for f in self.created_files)
        paths.update(f.path for f in self.modified_files)
        paths.update(f.path for f in self.deleted_files)
        return sorted(paths)

    # ========== Step Tracking ==========

    def record_step_result(self, result: StepResult) -> None:
        """Record the result of a step execution."""
        self.step_results.append(result)
        self.current_step_index += 1
        logger.debug(
            "[ExecutionState] Step %s: %s",
            result.step_id,
            "success" if result.success else f"failed ({result.error})",
        )

    def get_step_result(self, step_id: str) -> Optional[StepResult]:
        """Get the result of a specific step."""
        for result in self.step_results:
            if result.step_id == step_id:
                return result
        return None

    def get_failed_steps(self) -> list[StepResult]:
        """Get all failed step results."""
        return [r for r in self.step_results if not r.success]

    def get_successful_steps(self) -> list[StepResult]:
        """Get all successful step results."""
        return [r for r in self.step_results if r.success]

    # ========== Artifact Tracking ==========

    def _add_artifact(self, path: str) -> None:
        """Add a file path to artifacts (deduplicated)."""
        if path not in self.artifacts:
            self.artifacts.append(path)

    def add_artifact(self, path: str) -> None:
        """Manually add an artifact path."""
        self._add_artifact(path)

    def add_artifacts(self, paths: list[str]) -> None:
        """Manually add multiple artifact paths."""
        for path in paths:
            self._add_artifact(path)

    def get_artifacts(self) -> list[str]:
        """Get all artifact paths."""
        return self.artifacts.copy()

    # ========== Context for Code Generation ==========

    def get_file_context(self, filename: str) -> Optional[str]:
        """Get the context of a file (for consistency checks).

        Returns file content if it was created/modified during execution,
        None otherwise (caller should read from filesystem).
        """
        # Check if file was created in this execution
        for record in self.created_files:
            if record.path == filename:
                # We don't store content, just signal that it exists
                # Caller should read from workspace
                return self._read_file_content(filename)

        # Check if file was modified in this execution
        for record in self.modified_files:
            if record.path == filename:
                return self._read_file_content(filename)

        # Check filesystem
        full_path = self.workspace_root / filename
        if full_path.exists():
            return self._read_file_content(filename)

        return None

    def _read_file_content(self, filename: str) -> Optional[str]:
        """Read file content from workspace."""
        full_path = self.workspace_root / filename
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("[ExecutionState] Could not read %s: %s", filename, e)
            return None

    def get_related_files(self, filename: str) -> list[str]:
        """Get files related to a given file (same directory, complementary extensions).

        For example, for 'app.html' returns:
        - Other files in same directory
        - Complementary files like 'app.css', 'app.js'
        """
        related: set[str] = set()
        file_path = Path(filename)
        file_dir = str(file_path.parent) if file_path.parent != Path(".") else ""
        file_stem = file_path.stem

        # Files in same directory
        all_files = self.get_all_affected_files()
        for f in all_files:
            f_path = Path(f)
            f_dir = str(f_path.parent) if f_path.parent != Path(".") else ""
            if f_dir == file_dir:
                related.add(f)

        # Complementary files (same name, different extension)
        for f in all_files:
            f_path = Path(f)
            if f_path.stem == file_stem and f_path.suffix != file_path.suffix:
                related.add(f)

        # Common complementary patterns
        if file_path.suffix == ".html":
            # Look for CSS and JS files
            for f in all_files:
                if f.endswith(".css") or f.endswith(".js"):
                    related.add(f)

        return sorted(related)

    def get_execution_context(self) -> dict[str, Any]:
        """Get full execution context for LLM consumption."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_step_index": self.current_step_index,
            "total_steps": len(self.step_results),
            "files_created": self.get_created_files(),
            "files_modified": self.get_modified_files(),
            "artifacts": self.get_artifacts(),
            "failed_steps": [r.to_dict() for r in self.get_failed_steps()],
        }

    def get_related_files_context(self, filename: str, max_files: int = 5, max_content_length: int = 3000) -> str:
        """Get context string of related files for LLM.

        Returns formatted string with file contents for consistency.
        """
        related = self.get_related_files(filename)[:max_files]
        if not related:
            return ""

        lines = ["\n## Already Created Files (for consistency)"]
        for rel_path in related:
            if rel_path == filename:
                continue  # Skip the file itself

            content = self._read_file_content(rel_path)
            if content is None:
                continue

            # Truncate very long files
            if len(content) > max_content_length:
                content = content[:max_content_length] + "\n...[truncated]"

            lines.append(f"\n### {rel_path}")
            lines.append(f"```\n{content}\n```")

        return "\n".join(lines)

    # ========== Lifecycle ==========

    def mark_completed(self, success: bool, error_message: Optional[str] = None) -> None:
        """Mark execution as completed."""
        self.completed_at = datetime.now()
        self.status = "completed" if success else "failed"
        if error_message:
            self.error_message = error_message

        logger.info(
            "[ExecutionState] Execution %s: %d files created, %d artifacts",
            self.status,
            len(self.created_files),
            len(self.artifacts),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "current_step_index": self.current_step_index,
            "step_results": [r.to_dict() for r in self.step_results],
            "created_files": [f.to_dict() for f in self.created_files],
            "modified_files": [f.to_dict() for f in self.modified_files],
            "deleted_files": [f.to_dict() for f in self.deleted_files],
            "artifacts": self.artifacts,
        }

    def get_summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"Execution State for Task: {self.task_id}",
            f"Status: {self.status}",
            f"Steps executed: {len(self.step_results)}",
            f"Files created: {len(self.created_files)}",
            f"Files modified: {len(self.modified_files)}",
            f"Artifacts: {len(self.artifacts)}",
        ]

        failed = self.get_failed_steps()
        if failed:
            lines.append(f"Failed steps: {len(failed)}")
            for f in failed[:3]:
                lines.append(f"  - {f.step_id}: {f.error}")

        return "\n".join(lines)
