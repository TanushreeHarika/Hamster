"""Tests for the /undo pathway and the delete_file tool.

Key invariants verified:
- delete_file() removes a workspace file using Python's filesystem API, never
  invoking a shell command and therefore never triggering the security blacklist.
- restore_checkpoint() removes extra files from the workspace using Path.unlink()
  directly, also never going through the shell runner.
- Neither path raises a SECURITY VIOLATION for patterns like ``rm <file>``.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hamster.checkpoint import CheckpointStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ckpt(tmp: str) -> CheckpointStore:
    return CheckpointStore(base=Path(tmp) / "checkpoints")


def _write(root: Path, rel: str, content: str = "content") -> Path:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# 1. delete_file tool — no shell invocation
# ---------------------------------------------------------------------------

class TestDeleteFileTool(unittest.TestCase):
    """delete_file() must use Python filesystem ops, never shell commands."""

    def _make_sandbox(self, workspace: Path):
        """Return a minimal TempSandbox-like mock for injecting into tools._sandbox."""
        class DummySandbox:
            def __init__(self, ws: Path):
                self.workspace = ws.resolve()
                self.project_root = ws.resolve()
            def assert_alive(self):
                pass
            def new_path(self, p: str) -> Path:
                return self.workspace / p

        return DummySandbox(workspace)

    def test_delete_file_removes_file_via_python(self) -> None:
        """delete_file deletes the target file without any shell invocation."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            target = _write(workspace, "login.html", "<html/>")
            self.assertTrue(target.exists())

            sandbox = self._make_sandbox(workspace)

            # Patch _sandbox and session state
            with (
                patch("hamster.tools._sandbox", sandbox),
                patch("hamster.tools._session_state", MagicMock()),
                # Ensure validate_terminal_command is NEVER called
                patch("hamster.tools.validate_terminal_command") as mock_validate,
            ):
                from hamster.tools import delete_file
                result = delete_file("login.html")

            # File is gone
            self.assertFalse(target.exists(), f"Expected login.html to be deleted, got: {result}")
            self.assertIn("Deleted", result)
            # Shell security validator was never invoked
            mock_validate.assert_not_called()

    def test_delete_file_returns_error_for_missing_file(self) -> None:
        """delete_file returns a clear message when the file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            sandbox = self._make_sandbox(workspace)

            with (
                patch("hamster.tools._sandbox", sandbox),
                patch("hamster.tools._session_state", MagicMock()),
            ):
                from hamster.tools import delete_file
                result = delete_file("nonexistent.txt")

            self.assertIn("not found", result.lower())

    def test_delete_file_rejects_directory(self) -> None:
        """delete_file refuses to remove directories."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "subdir").mkdir()
            sandbox = self._make_sandbox(workspace)

            with (
                patch("hamster.tools._sandbox", sandbox),
                patch("hamster.tools._session_state", MagicMock()),
            ):
                from hamster.tools import delete_file
                result = delete_file("subdir")

            self.assertIn("directory", result.lower())
            self.assertTrue((workspace / "subdir").exists())

    def test_delete_file_blocks_path_traversal(self) -> None:
        """delete_file must reject paths that try to escape the sandbox."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            sandbox = self._make_sandbox(workspace)

            with (
                patch("hamster.tools._sandbox", sandbox),
                patch("hamster.tools._session_state", MagicMock()),
            ):
                from hamster.tools import delete_file
                result = delete_file("../../etc/passwd")

            self.assertIn("SECURITY", result)

    def test_delete_file_cleans_empty_parent_directories(self) -> None:
        """delete_file prunes empty parent directories after removal."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            target = _write(workspace, "deep/nested/file.txt")
            sandbox = self._make_sandbox(workspace)

            with (
                patch("hamster.tools._sandbox", sandbox),
                patch("hamster.tools._session_state", MagicMock()),
            ):
                from hamster.tools import delete_file
                delete_file("deep/nested/file.txt")

            # File and its now-empty ancestors should be removed
            self.assertFalse(target.exists())
            self.assertFalse((workspace / "deep").exists())


# ---------------------------------------------------------------------------
# 2. restore_checkpoint — no shell invocation
# ---------------------------------------------------------------------------

class TestRestoreCheckpointNoShell(unittest.TestCase):
    """restore_checkpoint() must never call validate_terminal_command."""

    def test_restore_removes_extra_file_without_shell(self) -> None:
        """A file added after the checkpoint is deleted on restore via Path.unlink()."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()

            # Checkpoint with no files
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            # Add a file after the checkpoint
            extra = _write(workspace, "login.html", "<html>login</html>")
            self.assertTrue(extra.exists())

            # Patch validate_terminal_command to fail if called
            with patch("hamster.tools.validate_terminal_command") as mock_validate:
                result = store.restore_checkpoint(ckpt_id, workspace)

            # File must be gone
            self.assertFalse(extra.exists(), "login.html should have been removed by restore")
            self.assertEqual(result["removed"], 1)
            # Shell validator was never touched
            mock_validate.assert_not_called()

    def test_restore_restores_deleted_file_without_shell(self) -> None:
        """A file deleted after the checkpoint is recreated on restore via Path.write_bytes()."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()

            original = _write(workspace, "app.py", "x = 1")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            # Delete the file
            original.unlink()
            self.assertFalse(original.exists())

            with patch("hamster.tools.validate_terminal_command") as mock_validate:
                result = store.restore_checkpoint(ckpt_id, workspace)

            self.assertTrue(original.exists())
            self.assertEqual(original.read_text(), "x = 1")
            self.assertEqual(result["restored"], 1)
            mock_validate.assert_not_called()


# ---------------------------------------------------------------------------
# 3. No SECURITY VIOLATION string emitted during undo flow
# ---------------------------------------------------------------------------

class TestNoSecurityViolationDuringUndo(unittest.TestCase):
    """End-to-end: undo flow must never produce a SECURITY VIOLATION string."""

    def test_full_undo_flow_emits_no_security_violation(self) -> None:
        """Simulate a complete /undo cycle and assert no security strings are raised."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()

            # State before agent turn: empty workspace
            ckpt_id = store.create_checkpoint(workspace, session_id="sess", turn_index=0)

            # Agent adds a file (simulated)
            _write(workspace, "login.html", "<html>login</html>")

            # /undo: restore to empty
            security_violations: list[str] = []
            original_violation = None

            # Intercept render_security_violation to catch any accidental security hits
            with patch("hamster.tools.render_security_violation") as mock_render:
                mock_render.side_effect = lambda msg: security_violations.append(msg)
                result = store.restore_checkpoint(ckpt_id, workspace)

            self.assertFalse(
                (workspace / "login.html").exists(),
                "login.html should have been removed by undo",
            )
            self.assertEqual(result["removed"], 1)
            self.assertEqual(
                security_violations,
                [],
                f"Expected no security violations but got: {security_violations}",
            )


if __name__ == "__main__":
    unittest.main()
