"""File operations module for Orbitron Kernel."""

import os
import shutil
from pathlib import Path
from typing import Optional


class FileOperations:
    """File operations handler for Orbitron."""
    
    def __init__(self, workspace: str | None = None):
        """Initialize file operations."""
        self.workspace = str(Path(workspace or (Path.home() / ".orbitron" / "workspace")).resolve())
        os.makedirs(self.workspace, exist_ok=True)
    
    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """Read file content."""
        full_path = self._resolve_path(path)
        with open(full_path, "r", encoding=encoding) as f:
            return f.read()
    
    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """Write content to file."""
        full_path = self._resolve_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding=encoding) as f:
            f.write(content)
    
    def append_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """Append content to file."""
        full_path = self._resolve_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "a", encoding=encoding) as f:
            f.write(content)
    
    def delete_file(self, path: str) -> bool:
        """Delete file."""
        full_path = self._resolve_path(path)
        if os.path.exists(full_path):
            os.remove(full_path)
            return True
        return False
    
    def create_file(self, path: str, content: str = "", encoding: str = "utf-8") -> None:
        """Create new file."""
        full_path = self._resolve_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding=encoding) as f:
            f.write(content)
    
    def list_directory(self, path: str = ".") -> list[str]:
        """List directory contents."""
        full_path = self._resolve_path(path)
        return os.listdir(full_path)
    
    def create_directory(self, path: str) -> None:
        """Create directory."""
        full_path = self._resolve_path(path)
        os.makedirs(full_path, exist_ok=True)
    
    def delete_directory(self, path: str) -> bool:
        """Delete directory and all contents."""
        full_path = self._resolve_path(path)
        if os.path.exists(full_path):
            shutil.rmtree(full_path)
            return True
        return False
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists."""
        full_path = self._resolve_path(path)
        return os.path.isfile(full_path)
    
    def directory_exists(self, path: str) -> bool:
        """Check if directory exists."""
        full_path = self._resolve_path(path)
        return os.path.isdir(full_path)
    
    def get_file_size(self, path: str) -> int:
        """Get file size in bytes."""
        full_path = self._resolve_path(path)
        return os.path.getsize(full_path)
    
    def _resolve_path(self, path: str) -> str:
        """Resolve relative path against workspace."""
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Path must be a non-empty string")

        p = Path(path)
        if p.is_absolute():
            raise ValueError("Absolute paths are not allowed")

        workspace_root = Path(self.workspace)
        resolved = (workspace_root / p).resolve()

        try:
            resolved.relative_to(workspace_root)
        except ValueError as e:
            raise ValueError("Path escapes workspace") from e

        return str(resolved)
