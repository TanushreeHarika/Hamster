from __future__ import annotations

import os
from pathlib import Path


class PathSecurityViolation(ValueError):
    """Raised when a requested filesystem path escapes the sandbox root."""


def canonicalize_path(filepath: str, *, root: str = "./sandbox") -> str:
    """Return a normalized absolute path after resolving the sandbox root.

    The path must remain rooted under the sandbox root. Any breakout attempt is
    rejected natively instead of being silently normalized.
    """

    root_path = os.path.realpath(root)
    candidate: str

    if os.path.isabs(filepath):
        candidate = os.path.realpath(filepath)
    else:
        trimmed = filepath.strip()
        if trimmed == "" or trimmed in {".", "./"}:
            candidate = root_path
        elif (
            trimmed.startswith(("./sandbox/", "sandbox/", "./sandbox"))
            or trimmed == "sandbox"
        ):
            candidate = os.path.realpath(trimmed)
        else:
            candidate = os.path.realpath(os.path.join(root_path, trimmed))

    if candidate != root_path and not candidate.startswith(root_path + os.sep):
        raise PathSecurityViolation(
            f"Blocked sandbox breakout attempt: requested={filepath!r}, resolved={candidate!r}, root={root_path!r}."
        )
    return candidate


def assert_sandbox_path(filepath: str, *, root: str = "./sandbox") -> str:
    """Compatibility helper that enforces the sandbox boundary contract."""

    return canonicalize_path(filepath, root=root)


def safe_write_text(filepath: str, content: str, *, root: str = "./sandbox") -> str:
    """Write a string to a sandbox-safe path and return the canonical file path."""

    target = assert_sandbox_path(filepath, root=root)
    Path(target).write_text(content, encoding="utf-8")
    return target
