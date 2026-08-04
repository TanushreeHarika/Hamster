"""OS-level temporary sandbox for Hamster.

Creates an isolated, session-scoped directory under the OS temp root
(e.g. /tmp/hamster-sandbox-<hex>/). The real project directory is copied
into the sandbox before work begins, and the original project is never
touched during the draft phase.

Layout::

    <temp>/
        baseline/   <- pristine copy used to compute deltas
        workspace/  <- mutable project copy used by all tools
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import uuid
from pathlib import Path


class TempSandbox:
    """Session-scoped, OS-managed temporary sandbox.

    Usage::

        sandbox = TempSandbox()
        configure_sandbox(sandbox)
        try:
            run_cli()
        finally:
            sandbox.destroy()
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        prefix = f"hamster-sandbox-{uuid.uuid4().hex[:8]}-"
        self._root = Path(tempfile.mkdtemp(prefix=prefix))
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self._baseline = self._root / "baseline"
        self._workspace = self._root / "workspace"
        self._copy_project(self.project_root, self._workspace)
        self._copy_project(self._workspace, self._baseline)
        self._destroyed = False
        atexit.register(self._cleanup_on_exit)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        """Absolute path to the temp sandbox root directory."""
        return self._root

    @property
    def workspace(self) -> Path:
        """Mutable project copy used as the agent working directory."""
        return self._workspace

    @property
    def baseline(self) -> Path:
        """Pristine project copy used to compute changes at apply time."""
        return self._baseline

    @property
    def is_destroyed(self) -> bool:
        """True after destroy() has been called."""
        return self._destroyed

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def workspace_path(self, relative: str) -> Path:
        """Absolute path inside the mutable sandbox workspace."""
        dest = (self._workspace / relative.lstrip("/")).resolve()
        workspace = self._workspace.resolve()
        if dest != workspace and workspace not in dest.parents:
            raise ValueError(f"Path escapes sandbox workspace: {relative!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def mirror_path(self, relative: str) -> Path:
        """Compatibility alias for older callers."""
        return self.workspace_path(relative)

    def new_path(self, relative: str) -> Path:
        """Compatibility alias for older callers."""
        return self.workspace_path(relative)

    # ------------------------------------------------------------------
    # Copy helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ignore_project_entries(_directory: str, names: list[str]) -> set[str]:
        ignored = {
            ".git",
            ".hg",
            ".svn",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "dist",
            "build",
            "sandbox",
        }
        return {name for name in names if name in ignored}

    def _copy_project(self, source: Path, dest: Path) -> None:
        shutil.copytree(
            source,
            dest,
            symlinks=True,
            ignore=self._ignore_project_entries,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def destroy(self) -> str:
        """Remove the temp sandbox directory tree.

        Safe to call multiple times (idempotent).  Returns a status
        message for display.
        """
        if self._destroyed:
            return f"Sandbox already destroyed: {self._root}"
        self._destroyed = True
        if self._root.exists():
            shutil.rmtree(self._root, ignore_errors=True)
        return f"Temp sandbox destroyed: {self._root}"

    def _cleanup_on_exit(self) -> None:
        """Best-effort atexit hook -- calls destroy() silently."""
        self.destroy()

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    def assert_alive(self) -> None:
        """Raise RuntimeError if the sandbox has been destroyed."""
        if self._destroyed:
            raise RuntimeError(
                f"Sandbox has been destroyed ({self._root}). "
                "Start a new session to continue editing."
            )

    def __repr__(self) -> str:
        state = "destroyed" if self._destroyed else "active"
        return f"TempSandbox(root={self._root!r}, state={state!r})"
