"""OS-level temporary sandbox for Hamster.

Creates an isolated, session-scoped directory under the OS temp root
(e.g. /tmp/hamster-sandbox-<hex>/).  The real project directory is
never touched during the draft phase; changes are promoted to the
project root only via an explicit apply operation.

Layout::

    <temp>/
        mirror/   <- lazy copies of existing project files
        new/      <- brand-new files created by write_file
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

    def __init__(self) -> None:
        prefix = f"hamster-sandbox-{uuid.uuid4().hex[:8]}-"
        self._root = Path(tempfile.mkdtemp(prefix=prefix))
        (self._root / "mirror").mkdir(parents=True, exist_ok=True)
        (self._root / "new").mkdir(parents=True, exist_ok=True)
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
    def is_destroyed(self) -> bool:
        """True after destroy() has been called."""
        return self._destroyed

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def mirror_path(self, relative: str) -> Path:
        """Absolute path inside ``mirror/`` for a real-project file.

        The path is constructed from *relative* (a project-root-relative
        path such as ``"hamster/agent.py"`` or ``"README.md"``).
        Parent directories are created automatically.
        """
        dest = self._root / "mirror" / relative.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def new_path(self, relative: str) -> Path:
        """Absolute path inside ``new/`` for a brand-new file.

        Use this for files that do not exist in the project root yet.
        Parent directories are created automatically.
        """
        dest = self._root / "new" / relative.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

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
