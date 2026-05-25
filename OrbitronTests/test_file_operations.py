"""Unit tests for FileOperations module."""

import os
import tempfile
from pathlib import Path

import pytest

from OrbitronKernel.file_operations import FileOperations


class TestFileOperationsInit:
    """Test FileOperations initialization."""

    def test_creates_workspace_directory(self, tmp_path):
        """FileOperations should create workspace directory if it doesn't exist."""
        workspace = tmp_path / "new_workspace"
        ops = FileOperations(workspace=str(workspace))
        assert workspace.exists()

    def test_default_workspace(self):
        """FileOperations should use default workspace if none specified."""
        ops = FileOperations(workspace=None)
        assert ops.workspace is not None
        assert Path(ops.workspace).exists()

    def test_workspace_root_property(self, tmp_path):
        """workspace_root property should return a Path object."""
        workspace = tmp_path / "ws"
        ops = FileOperations(workspace=str(workspace))
        assert isinstance(ops.workspace_root, Path)
        assert ops.workspace_root == Path(str(workspace))


class TestFileOperationsRead:
    """Test FileOperations read operations."""

    def test_read_file(self, file_ops):
        """read_file should return file content."""
        file_ops.write_file("test_read.txt", "Hello, World!")
        content = file_ops.read_file("test_read.txt")
        assert content == "Hello, World!"

    def test_read_nonexistent_file(self, file_ops):
        """read_file should raise error for nonexistent files."""
        with pytest.raises(FileNotFoundError):
            file_ops.read_file("nonexistent.txt")

    def test_read_file_with_encoding(self, file_ops):
        """read_file should handle different encodings."""
        content = "Ünïcödé tëst: äöü ß"
        file_ops.write_file("unicode.txt", content)
        result = file_ops.read_file("unicode.txt")
        assert result == content

    def test_read_nested_file(self, file_ops):
        """read_file should read files in nested directories."""
        file_ops.write_file("deep/nested/file.txt", "Deep content")
        content = file_ops.read_file("deep/nested/file.txt")
        assert content == "Deep content"


class TestFileOperationsWrite:
    """Test FileOperations write operations."""

    def test_write_file(self, file_ops):
        """write_file should create a file with content."""
        file_ops.write_file("test_write.txt", "Test content")
        assert file_ops.file_exists("test_write.txt")
        assert file_ops.read_file("test_write.txt") == "Test content"

    def test_write_file_creates_directories(self, file_ops):
        """write_file should create parent directories if needed."""
        file_ops.write_file("new/dir/file.txt", "Nested content")
        assert file_ops.file_exists("new/dir/file.txt")

    def test_write_file_overwrite(self, file_ops):
        """write_file should overwrite existing files."""
        file_ops.write_file("overwrite.txt", "Original")
        file_ops.write_file("overwrite.txt", "Updated")
        assert file_ops.read_file("overwrite.txt") == "Updated"

    def test_append_file(self, file_ops):
        """append_file should add content to end of file."""
        file_ops.write_file("append.txt", "Line 1\n")
        file_ops.append_file("append.txt", "Line 2\n")
        content = file_ops.read_file("append.txt")
        assert "Line 1" in content
        assert "Line 2" in content

    def test_append_file_creates_if_missing(self, file_ops):
        """append_file should create file if it doesn't exist."""
        file_ops.append_file("new_append.txt", "First line\n")
        assert file_ops.file_exists("new_append.txt")
        assert file_ops.read_file("new_append.txt") == "First line\n"


class TestFileOperationsDelete:
    """Test FileOperations delete operations."""

    def test_delete_file(self, file_ops):
        """delete_file should remove a file."""
        file_ops.write_file("to_delete.txt", "Delete me")
        assert file_ops.delete_file("to_delete.txt") is True
        assert not file_ops.file_exists("to_delete.txt")

    def test_delete_nonexistent_file(self, file_ops):
        """delete_file should return False for nonexistent files."""
        assert file_ops.delete_file("nonexistent.txt") is False

    def test_delete_directory(self, file_ops):
        """delete_directory should remove a directory and its contents."""
        file_ops.write_file("del_dir/file.txt", "Content")
        assert file_ops.delete_directory("del_dir") is True
        assert not file_ops.directory_exists("del_dir")


class TestFileOperationsDirectory:
    """Test FileOperations directory operations."""

    def test_create_directory(self, file_ops):
        """create_directory should create nested directories."""
        file_ops.create_directory("new/nested/dir")
        assert file_ops.directory_exists("new/nested/dir")

    def test_list_directory(self, file_ops):
        """list_directory should return directory contents."""
        file_ops.write_file("list_dir/file1.txt", "Content 1")
        file_ops.write_file("list_dir/file2.txt", "Content 2")
        items = file_ops.list_directory("list_dir")
        assert "file1.txt" in items
        assert "file2.txt" in items

    def test_list_directory_root(self, file_ops):
        """list_directory with '.' should list workspace root."""
        file_ops.write_file("root_file.txt", "Content")
        items = file_ops.list_directory(".")
        assert "root_file.txt" in items


class TestFileOperationsExistence:
    """Test FileOperations existence checks."""

    def test_file_exists_true(self, file_ops):
        """file_exists should return True for existing files."""
        file_ops.write_file("exists.txt", "Content")
        assert file_ops.file_exists("exists.txt") is True

    def test_file_exists_false(self, file_ops):
        """file_exists should return False for nonexistent files."""
        assert file_ops.file_exists("nonexistent.txt") is False

    def test_directory_exists_true(self, file_ops):
        """directory_exists should return True for existing directories."""
        file_ops.create_directory("test_dir")
        assert file_ops.directory_exists("test_dir") is True

    def test_directory_exists_false(self, file_ops):
        """directory_exists should return False for nonexistent directories."""
        assert file_ops.directory_exists("nonexistent_dir") is False

    def test_get_file_size(self, file_ops):
        """get_file_size should return file size in bytes."""
        content = "A" * 100
        file_ops.write_file("sized.txt", content)
        size = file_ops.get_file_size("sized.txt")
        assert size == 100


class TestFileOperationsPathSecurity:
    """Test FileOperations path traversal protection."""

    def test_rejects_absolute_path(self, file_ops):
        """Should reject absolute paths."""
        with pytest.raises(ValueError, match="Absolute paths"):
            file_ops.read_file("/etc/passwd")

    def test_rejects_path_traversal(self, file_ops):
        """Should reject path traversal attempts."""
        with pytest.raises(ValueError, match="escapes|outside|traversal"):
            file_ops.read_file("../../etc/passwd")

    def test_rejects_empty_path(self, file_ops):
        """Should reject empty paths."""
        with pytest.raises(ValueError, match="non-empty"):
            file_ops.read_file("")

    def test_rejects_non_string_path(self, file_ops):
        """Should reject non-string paths."""
        with pytest.raises(ValueError, match="non-empty"):
            file_ops.read_file(None)

    def test_accepts_valid_relative_path(self, file_ops):
        """Should accept valid relative paths."""
        file_ops.write_file("valid/path.txt", "Content")
        content = file_ops.read_file("valid/path.txt")
        assert content == "Content"

    def test_resolve_path_normal(self, file_ops):
        """_resolve_path should resolve normal relative paths."""
        resolved = file_ops._resolve_path("test.txt")
        assert resolved.endswith("test.txt")
        assert file_ops.workspace in resolved

    def test_resolve_path_nested(self, file_ops):
        """_resolve_path should resolve nested relative paths."""
        resolved = file_ops._resolve_path("sub/dir/file.txt")
        assert resolved.endswith("sub/dir/file.txt")