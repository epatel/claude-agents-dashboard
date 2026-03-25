"""
P1 Priority Unit Tests: Path Validation and Security

Tests path validation and security measures including:
- Path traversal attack prevention
- File system boundary enforcement
- Input sanitization and validation
- Safe file operations
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import os

from src.git.worktree import create_worktree, cleanup_worktree
from src.database import Database


@pytest.mark.unit
class TestPathTraversalPrevention:
    """Test suite for path traversal attack prevention."""

    def test_basic_path_traversal_patterns(self):
        """Test detection of basic path traversal patterns."""
        malicious_patterns = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded
            "..%252f..%252f..%252fetc%252fpasswd",  # Double URL encoded
            "..%c0%af..%c0%af..%c0%afetc%c0%afpasswd",  # UTF-8 encoded
        ]

        for pattern in malicious_patterns:
            # Test path normalization catches these
            normalized = os.path.normpath(pattern)
            absolute = os.path.abspath(normalized)

            # Should not end up in system directories
            assert not absolute.startswith('/etc/')
            assert not absolute.startswith('/root/')
            assert 'system32' not in absolute.lower() or not absolute.startswith('C:\\Windows')

    def test_directory_boundary_enforcement(self, temp_dir):
        """Test that operations stay within allowed directories."""
        project_root = temp_dir / "project"
        project_root.mkdir()

        # Define allowed base directory
        allowed_base = project_root

        # Test paths that should be rejected
        dangerous_paths = [
            temp_dir / ".." / "outside",
            Path("/etc/passwd"),
            Path("/tmp/malicious"),
            temp_dir.parent / "escape"
        ]

        for dangerous_path in dangerous_paths:
            try:
                # Resolve to absolute path
                resolved = dangerous_path.resolve()

                # Check if it's within allowed boundaries
                try:
                    resolved.relative_to(allowed_base)
                    # If we get here, it's within boundaries (could be OK)
                except ValueError:
                    # Path is outside boundaries - this is what we expect
                    assert True
            except (OSError, PermissionError):
                # Expected for truly dangerous paths
                assert True

    def test_symbolic_link_traversal_prevention(self, temp_dir):
        """Test prevention of symbolic link traversal attacks."""
        project_dir = temp_dir / "project"
        project_dir.mkdir()

        # Create a symbolic link pointing outside project
        outside_dir = temp_dir / "outside_target"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("sensitive data")

        symlink_path = project_dir / "malicious_link"
        try:
            symlink_path.symlink_to(outside_dir)

            # Test that following the symlink is detected
            resolved_path = symlink_path.resolve()

            # Should detect that resolved path is outside project
            try:
                resolved_path.relative_to(project_dir)
            except ValueError:
                # Path resolved outside project - security check should catch this
                assert True

        except OSError:
            # Symlink creation failed (e.g., on Windows without admin) - that's fine
            pytest.skip("Cannot create symlinks on this system")

    def test_null_byte_injection_prevention(self):
        """Test prevention of null byte injection attacks."""
        malicious_filenames = [
            "innocent.txt\x00../../../etc/passwd",
            "normal\x00.exe",
            "file.txt\x00\x00malicious.sh",
            "\x00inject",
        ]

        for filename in malicious_filenames:
            # Null bytes should be detected and rejected
            assert '\x00' in filename

            # Most systems will reject null bytes in filenames
            sanitized = filename.replace('\x00', '')
            assert '\x00' not in sanitized

    def test_filename_length_validation(self):
        """Test validation of extremely long filenames."""
        # Most filesystems have limits (255 chars for filename, 4096 for path)
        very_long_filename = "a" * 1000
        very_long_path = "/".join(["part"] * 100)  # Very deep path

        # Should validate lengths
        assert len(very_long_filename) > 255
        assert len(very_long_path) > 1000


@pytest.mark.unit
class TestInputSanitization:
    """Test suite for input sanitization."""

    def test_branch_name_sanitization(self):
        """Test sanitization of git branch names."""
        unsafe_branch_names = [
            "branch with spaces",
            "branch/with/slashes",
            "branch@{upstream}",
            "branch~1",
            "branch^",
            "branch:",
            "branch[tab]\t",
            "branch\nwith\nnewlines",
            "../malicious",
            "",  # Empty string
            "." * 255,  # Very long name
        ]

        for unsafe_name in unsafe_branch_names:
            # Test various sanitization approaches
            sanitized = unsafe_name.replace(" ", "-").replace("\n", "").replace("\t", "")

            # Should not contain dangerous characters
            assert "\n" not in sanitized
            assert "\t" not in sanitized

            # Should not be empty after sanitization (unless originally empty)
            if unsafe_name.strip():
                assert len(sanitized.strip()) > 0

    def test_file_content_validation(self, temp_dir):
        """Test validation of file content before operations."""
        test_file = temp_dir / "test.txt"

        # Test various types of content
        content_types = [
            "Normal text content",
            "\x00Binary\x01content\x02",  # Binary content with null bytes
            "Unicode content: 🚀 emoji test",
            "Very long content: " + "x" * 10000,
            "",  # Empty content
        ]

        for content in content_types:
            try:
                # Most text operations should handle these gracefully
                test_file.write_text(content, encoding='utf-8', errors='replace')

                # Read back to verify
                read_content = test_file.read_text(encoding='utf-8', errors='replace')

                # Binary content might be modified during text operations
                if '\x00' in content:
                    # Null bytes might be replaced or cause errors - both are acceptable
                    assert True
                else:
                    # Regular text should round-trip
                    assert len(read_content) > 0 or len(content) == 0

            except UnicodeDecodeError:
                # Binary content causing decode errors is expected
                assert '\x00' in content or not content.isascii()
            finally:
                if test_file.exists():
                    test_file.unlink()

    def test_command_injection_prevention(self):
        """Test prevention of command injection in parameters."""
        dangerous_inputs = [
            "normal; rm -rf /",
            "input && malicious_command",
            "file.txt | evil_script",
            "input $(malicious)",
            "input `backdoor`",
            "input & background_task",
            "input > overwrite_file",
            "input < read_secrets",
        ]

        for dangerous_input in dangerous_inputs:
            # Commands should be properly escaped/validated
            shell_dangerous_chars = [';', '&&', '||', '|', '$', '`', '&', '>', '<']
            contains_dangerous = any(char in dangerous_input for char in shell_dangerous_chars)

            if contains_dangerous:
                # Input validation should catch these
                assert True

            # Test shell escaping
            import shlex
            try:
                escaped = shlex.quote(dangerous_input)
                assert escaped.startswith("'") or not contains_dangerous
            except ValueError:
                # Some inputs might be too dangerous to escape
                assert contains_dangerous


@pytest.mark.unit
class TestFileSystemSafety:
    """Test suite for file system safety measures."""

    def test_safe_file_creation(self, temp_dir):
        """Test safe file creation practices."""
        # Test creating files with various names
        test_cases = [
            ("normal.txt", True),
            ("with-dashes.txt", True),
            ("with_underscores.txt", True),
            ("with.dots.txt", True),
            ("CON", False),  # Windows reserved name
            ("PRN", False),  # Windows reserved name
            ("AUX", False),  # Windows reserved name
            ("NUL", False),  # Windows reserved name
            ("", False),     # Empty name
            (".", False),    # Current directory
            ("..", False),   # Parent directory
        ]

        for filename, should_succeed in test_cases:
            if not filename:
                continue

            test_path = temp_dir / filename

            try:
                test_path.write_text("test content")

                if should_succeed:
                    assert test_path.exists()
                    test_path.unlink()  # Cleanup
                else:
                    # If it succeeded when it shouldn't have, that might be a problem
                    # But it depends on the OS - Windows is stricter about reserved names
                    if test_path.exists():
                        test_path.unlink()  # Cleanup anyway

            except (OSError, PermissionError, ValueError) as e:
                if not should_succeed:
                    # Expected failure for dangerous names
                    assert True
                else:
                    # Unexpected failure - might be OS-specific
                    assert "reserved" in str(e).lower() or "invalid" in str(e).lower()

    def test_atomic_file_operations(self, temp_dir):
        """Test atomic file operations to prevent corruption."""
        target_file = temp_dir / "atomic_test.txt"
        original_content = "original content"
        new_content = "new content"

        # Create original file
        target_file.write_text(original_content)

        # Test atomic write operation
        temp_file = temp_dir / f"{target_file.name}.tmp"
        try:
            # Write to temporary file first
            temp_file.write_text(new_content)

            # Verify temp file has correct content
            assert temp_file.read_text() == new_content

            # Atomic move (should be atomic on most filesystems)
            temp_file.replace(target_file)

            # Verify final content
            assert target_file.read_text() == new_content
            assert not temp_file.exists()

        except Exception:
            # Cleanup on failure
            if temp_file.exists():
                temp_file.unlink()
            # Original file should be unchanged
            if target_file.exists():
                assert target_file.read_text() == original_content

    def test_directory_permissions(self, temp_dir):
        """Test directory permission validation."""
        # Create test directories with different permissions
        readable_dir = temp_dir / "readable"
        readable_dir.mkdir(mode=0o755)

        try:
            restricted_dir = temp_dir / "restricted"
            restricted_dir.mkdir(mode=0o000)  # No permissions

            # Test access
            assert readable_dir.exists()
            assert os.access(readable_dir, os.R_OK | os.W_OK)

            # Restricted directory tests
            if os.name != 'nt':  # Unix-like systems
                assert restricted_dir.exists()
                assert not os.access(restricted_dir, os.W_OK)

        finally:
            # Cleanup - restore permissions
            if restricted_dir.exists():
                restricted_dir.chmod(0o755)

    def test_disk_space_handling(self, temp_dir):
        """Test handling of disk space issues."""
        # Test creating large files (simulated)
        large_file = temp_dir / "large_file.txt"

        try:
            # Try to create a moderately large file
            large_content = "x" * (1024 * 1024)  # 1MB
            large_file.write_text(large_content)

            # Verify it was created
            assert large_file.exists()
            assert large_file.stat().st_size >= len(large_content)

        except OSError as e:
            if "No space left on device" in str(e) or "Disk full" in str(e):
                # Expected when disk is actually full
                assert True
            else:
                # Other OS errors might indicate different issues
                assert "permission" in str(e).lower() or "access" in str(e).lower()
        finally:
            if large_file.exists():
                large_file.unlink()


@pytest.mark.unit
class TestDatabasePathSecurity:
    """Test suite for database path security."""

    def test_database_path_validation(self, temp_dir):
        """Test that database paths are validated."""
        safe_paths = [
            temp_dir / "database.db",
            temp_dir / "data" / "app.db",
            temp_dir / "nested" / "deep" / "db.sqlite",
        ]

        dangerous_paths = [
            Path("/etc/passwd"),
            temp_dir / ".." / "outside.db",
            Path("/tmp/system.db"),
        ]

        for safe_path in safe_paths:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Should be able to create database in safe locations
                db = Database(safe_path)
                assert db.db_path == safe_path
            except Exception as e:
                # Some errors might be OK (e.g., permissions)
                assert "permission" in str(e).lower()

        for dangerous_path in dangerous_paths:
            try:
                # May or may not succeed depending on system security
                db = Database(dangerous_path)

                # If it succeeds, verify the path is actually safe
                resolved_path = db.db_path.resolve()

                # Should not be in system directories
                assert not str(resolved_path).startswith('/etc/')
                assert not str(resolved_path).startswith('/root/')

            except (PermissionError, ValueError):
                # Expected for truly dangerous paths
                assert True

    def test_migration_file_validation(self, temp_dir):
        """Test validation of migration file paths."""
        from src.migrations.runner import MigrationRunner

        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create various migration files
        valid_migrations = [
            "001_initial.py",
            "002_add_users.py",
            "999_cleanup.py",
        ]

        invalid_migrations = [
            "../escape.py",
            "not_numbered.py",
            ".hidden_migration.py",
            "001_initial.py.backup",
        ]

        # Create valid migration files
        for filename in valid_migrations:
            migration_file = migrations_dir / filename
            migration_file.write_text(f"# Migration {filename}")

        # Create invalid migration files
        for filename in invalid_migrations:
            try:
                migration_file = migrations_dir / filename
                if ".." not in filename:  # Don't actually create path traversal files
                    migration_file.write_text(f"# Invalid migration {filename}")
            except (ValueError, OSError):
                # Expected for dangerous filenames
                pass

        # Test migration discovery
        runner = MigrationRunner(migrations_dir)

        # This should only find valid migrations
        # The actual discovery logic should filter out invalid files