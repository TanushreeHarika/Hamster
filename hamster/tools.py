from __future__ import annotations

import difflib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from src.sandbox import TempSandbox
from src.container import execute_sandboxed
from src.security import assert_sandbox_path, PathSecurityViolation
from hamster.ui import (
    confirm,
    render_security_violation,
    sandbox_status,
    status,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SandboxViolation(ValueError):
    pass


class CommandSecurityViolation(ValueError):
    pass


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

class SessionState:
    """Track approval state across tool calls within a session."""

    def __init__(self) -> None:
        self.read_approved = False
        self.approved_read_scopes: set[str] = set()

    def approve_read(self, scope: str = "sandbox") -> None:
        """Mark read operations as approved for the given scope."""
        self.read_approved = True
        self.approved_read_scopes.add(scope)

    def is_read_approved(self, scope: str = "sandbox") -> bool:
        """Check if read operations are approved for the given scope."""
        return scope in self.approved_read_scopes


# Global session state — initialized by init_session_state()
_session_state: SessionState | None = None

# Active sandbox — set by configure_sandbox()
_sandbox: TempSandbox | None = None


def init_session_state() -> SessionState:
    """Initialize session state for the current session."""
    global _session_state
    _session_state = SessionState()
    return _session_state


def get_session_state() -> SessionState:
    """Return the current session state."""
    if _session_state is None:
        raise RuntimeError("Session not initialized. Call init_session_state() first.")
    return _session_state


def configure_sandbox(sandbox: TempSandbox) -> None:
    """Inject the active TempSandbox into the tool subsystem."""
    global _sandbox
    _sandbox = sandbox


def _get_sandbox() -> TempSandbox:
    """Return the active sandbox, raising if not configured or destroyed."""
    if _sandbox is None:
        raise RuntimeError("Sandbox not configured. Call configure_sandbox() first.")
    _sandbox.assert_alive()
    return _sandbox


# ---------------------------------------------------------------------------
# Internal path helpers
# ---------------------------------------------------------------------------

def _project_root() -> str:
    """Return the project root (cwd at startup)."""
    if _sandbox is not None:
        return str(_sandbox.project_root)
    return str(Path.cwd().resolve())


def _sandbox_root_str() -> str:
    """Return the active workspace root as a string."""
    return str(_get_sandbox().workspace)


def _is_inside_sandbox(absolute_path: str) -> bool:
    root = _sandbox_root_str()
    return absolute_path == root or absolute_path.startswith(root + os.sep)


def _security_violation(message: str) -> str:
    warning = f"SECURITY VIOLATION: {message}"
    render_security_violation(warning)
    return warning


def _resolve_inside_sandbox(filepath: str) -> str:
    """Resolve *filepath* relative to the sandbox root with boundary enforcement.

    The filepath is resolved against the active sandbox workspace. This is used
    only for the security validation step; path construction happens through
    TempSandbox helpers.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.workspace)
    try:
        absolute_path = assert_sandbox_path(filepath, root=root_str)
    except (PathSecurityViolation, Exception) as exc:
        raise SandboxViolation(str(exc)) from exc
    if not _is_inside_sandbox(absolute_path):
        raise SandboxViolation(
            f"Blocked sandbox escape attempt. "
            f"Requested={filepath!r}; resolved={absolute_path!r}; sandbox={root_str!r}."
        )
    return absolute_path


def _stage_file_to_sandbox(filepath: str) -> str:
    """Return the workspace path for a project file."""
    sandbox = _get_sandbox()
    staged = sandbox.workspace_path(filepath)
    if not staged.is_file():
        raise FileNotFoundError(f"File not found in draft workspace: {staged!r}")
    return str(staged)


def _make_patch_preview(filepath: str, original: str, updated: str) -> list[str]:
    return list(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile=f"{filepath} before",
            tofile=f"{filepath} after",
            lineterm="",
        )
    )


# ---------------------------------------------------------------------------
# Terminal command validation
# ---------------------------------------------------------------------------

BLOCKED_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|[;&|]\s*)sudo(\s|$)", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)rm\s+", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)chmod\s+", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)chown\s+", re.IGNORECASE),
    re.compile(r"curl\s+[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
    re.compile(r"wget\s+[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
    re.compile(r"\b(base64|openssl)\b[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
)


def validate_terminal_command(command: str) -> None:
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(command):
            raise CommandSecurityViolation(
                f"Blocked command by blacklist pattern {pattern.pattern!r}: {command!r}"
            )
    parts = shlex.split(command)
    if not parts:
        raise CommandSecurityViolation("Refusing to run an empty terminal command.")


# ---------------------------------------------------------------------------
# Fuzzy patching helper
# ---------------------------------------------------------------------------

def _try_fuzzy_replace(original: str, target_text: str, replacement_text: str) -> str | None:
    """Attempt a whitespace-tolerant text replacement in *original*.

    Strips trailing whitespace per line before comparing so the model can
    match code blocks even when the editor has saved with different trailing
    spaces or line-endings.  Leading whitespace is preserved for indentation
    accuracy.

    Returns the updated string on success, or ``None`` if no fuzzy match is
    found (caller should then return the regular 'not found' error).
    """
    # Normalise line endings first
    original_n = original.replace("\r\n", "\n").replace("\r", "\n")
    target_n = target_text.replace("\r\n", "\n").replace("\r", "\n")

    orig_lines = original_n.splitlines(keepends=True)
    tgt_stripped = [line.rstrip() for line in target_n.splitlines()]
    tgt_len = len(tgt_stripped)

    # Nothing to match against
    if not tgt_stripped or all(s == "" for s in tgt_stripped):
        return None

    for i in range(len(orig_lines) - tgt_len + 1):
        window = [line.rstrip("\r\n").rstrip() for line in orig_lines[i : i + tgt_len]]
        if window == tgt_stripped:
            before = "".join(orig_lines[:i])
            after = "".join(orig_lines[i + tgt_len :])
            rep = replacement_text
            # Ensure the replacement ends with a newline when there is more content
            if after and not rep.endswith("\n"):
                rep += "\n"
            return before + rep + after

    return None


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def run_sandbox_command(command: str) -> str:
    try:
        validate_terminal_command(command)
    except (CommandSecurityViolation, SandboxViolation) as exc:
        return _security_violation(str(exc))

    if not confirm(f"🐹 Run: {command}"):
        return "Denied."

    sandbox = _get_sandbox()
    with sandbox_status("🖥️  Running command..."):
        result = execute_sandboxed(command, cwd=str(sandbox.workspace))
    return (result.stdout + result.stderr).strip() or f"Command exited with {result.returncode}."


def search_codebase(query: str) -> str:
    """Search for *query* across the sandbox workspace."""
    root = str(_get_sandbox().workspace)

    session = get_session_state()
    if not session.is_read_approved("codebase"):
        if not confirm(f"🐹 Search codebase for: {query}"):
            return "Denied."
        session.approve_read("codebase")

    try:
        result_check = subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            timeout=2,
            check=False,
        )
        if result_check.returncode != 0:
            raise FileNotFoundError("ripgrep not available")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (
            "ERROR: ripgrep (rg) is not installed or not in PATH.\n"
            "Install it with: brew install ripgrep\n"
            "Or: cargo install ripgrep"
        )

    with sandbox_status("🔍 Searching codebase..."):
        result = subprocess.run(
            ["rg", "--line-number", "--column", "--", query, root],
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode == 0:
        return result.stdout.strip() or "No matches."
    if result.returncode == 1:
        return "No matches."
    raise RuntimeError(result.stderr.strip() or "rg failed without stderr.")


def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read *filepath* from the draft workspace.

    Args:
        filepath: Project-relative file path (e.g. ``'hamster/agent.py'``).
        start_line: First line to return, 1-indexed inclusive.  ``None`` means
            start from line 1 (reads the whole file from the top).
        end_line: Last line to return, 1-indexed inclusive.  ``None`` means
            read to the end of the file.

    Returns:
        File contents (or a selected line slice prefixed with a range header).
    """
    # Security: validate path won't escape the draft workspace.
    sandbox = _get_sandbox()
    root_str = str(sandbox.workspace)
    try:
        assert_sandbox_path(filepath, root=root_str)
    except PathSecurityViolation as exc:
        return _security_violation(str(exc))

    session = get_session_state()
    if not session.is_read_approved("codebase"):
        if not confirm(f"🐹 Read: {filepath}"):
            return "Denied."
        session.approve_read("codebase")

    try:
        with sandbox_status("📄 Reading file..."):
            staged = _stage_file_to_sandbox(filepath)
            content = Path(staged).read_text(encoding="utf-8")

        # Return full content when no line range is requested
        if start_line is None and end_line is None:
            return content

        lines = content.splitlines(keepends=True)
        total = len(lines)

        # Convert to 0-based slice indices
        s = max(0, (start_line or 1) - 1)
        e = min(total, end_line or total)

        if s >= total:
            return f"start_line {start_line} exceeds file length ({total} lines)."

        header = f"[Lines {s + 1}–{e} of {total}]\n"
        return header + "".join(lines[s:e])

    except FileNotFoundError as exc:
        return f"File not found: {exc}"


def edit_file_patch(filepath: str, target_text: str, replacement_text: str) -> str:
    """Draft a file edit using a text-replacement patch.

    Workflow:
      1. Read the file from the draft workspace.
      2. Apply the text replacement on the draft copy.
      3. The project file is saved only after final task approval.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.workspace)
    try:
        assert_sandbox_path(filepath, root=root_str)
    except PathSecurityViolation as exc:
        return _security_violation(str(exc))

    try:
        with sandbox_status("📋 Opening file..."):
            staged = _stage_file_to_sandbox(filepath)
    except FileNotFoundError:
        return f"File not found: {filepath}"

    original = Path(staged).read_text(encoding="utf-8")

    # --- Exact match (primary path, preserves all existing behaviour) --------
    if target_text in original:
        replaced_count = original.count(target_text)
        updated = original.replace(target_text, replacement_text)
        with sandbox_status("✏️  Updating file..."):
            Path(staged).write_text(updated, encoding="utf-8")
        return f"Updated {filepath}: replaced {replaced_count} occurrence{'s' if replaced_count != 1 else ''}."

    # --- Fuzzy match (trailing-whitespace-tolerant fallback) ------------------
    fuzzy_result = _try_fuzzy_replace(original, target_text, replacement_text)
    if fuzzy_result is not None:
        with sandbox_status("✏️  Updating file (fuzzy match)..."):
            Path(staged).write_text(fuzzy_result, encoding="utf-8")
        return f"Updated {filepath}: 1 occurrence replaced (whitespace-normalised match)."

    return (
        f"Target text was not found in {filepath}. "
        "For broad rewrites, read the current file and use write_file with the full updated content."
    )


def write_file(filepath: str, content: str) -> str:
    """Create or overwrite a draft file."""
    sandbox = _get_sandbox()
    try:
        dest = sandbox.new_path(filepath)
        with sandbox_status("✏️  Writing file..."):
            dest.write_text(content, encoding="utf-8")
        return f"Wrote {filepath}."
    except Exception as e:
        return f"Error creating file {filepath}: {e}"


def delete_file(filepath: str) -> str:
    """Delete a file from the draft workspace using Python's filesystem API.

    This tool NEVER invokes a shell command (``rm`` etc.) — it is exempt from
    the shell-command security blacklist.  Boundary enforcement is handled by
    :func:`src.security.assert_sandbox_path` which resolves symlinks on both
    sides, so it works correctly on macOS where ``/var`` is a symlink to
    ``/private/var``.

    Args:
        filepath: Project-relative path of the file to delete
                  (e.g. ``'login.html'``, ``'src/old_module.py'``).

    Returns:
        A one-line status string.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.workspace)
    try:
        # assert_sandbox_path resolves symlinks on BOTH the root and the
        # candidate, so /var vs /private/var is handled correctly on macOS.
        absolute_path = assert_sandbox_path(filepath, root=root_str)
    except PathSecurityViolation as exc:
        return _security_violation(str(exc))

    staged = Path(absolute_path)
    if not staged.exists():
        return f"File not found in draft workspace: {filepath}"

    if staged.is_dir():
        return (
            f"'{filepath}' is a directory. "
            "Use delete_file only for individual files."
        )

    with sandbox_status(f"🗑️  Deleting {filepath}..."):
        staged.unlink(missing_ok=True)
        # Prune empty parent directories up to (but not including) the workspace root
        workspace = Path(os.path.realpath(root_str))
        parent = staged.parent
        while parent != workspace:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    return f"Deleted {filepath}."


def web_search(query: str) -> str:
    if not confirm(f"🐹 Web search: {query}"):
        return "Denied."

    with status("Searching docs..."):
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:
            raise RuntimeError(
                "duckduckgo-search is not installed. Run `uv pip install -e .`."
            ) from exc

        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=5):
                title = item.get("title", "Untitled")
                href = item.get("href") or item.get("url") or ""
                body = item.get("body", "")
                results.append(f"- {title}\n  {href}\n  {body}")

    return "\n\n".join(results) if results else "No web results found."


def apply_sandbox_to_root(project_root: Path | None = None, verbose: bool = False) -> str:
    """Save drafted changes back to the real project root and destroy the sandbox.

    Diffs the mutable workspace against the pristine baseline, then applies
    only those changes to the project root. If a project file changed since the
    sandbox was created, that path is reported as a conflict and left untouched.

    Returns:
        Status message with sync summary.
    """
    sandbox = _get_sandbox()

    if project_root is None:
        project_root = Path(_project_root())
    else:
        project_root = Path(project_root)

    protected_items = {".env", ".git", ".venv"}
    copied_count = 0
    deleted_count = 0
    conflicts: list[str] = []
    copies: list[tuple[Path, Path]] = []
    deletes: list[Path] = []

    def is_protected(rel: Path) -> bool:
        return bool(rel.parts) and rel.parts[0] in protected_items

    def iter_files(root: Path) -> set[Path]:
        if not root.exists():
            return set()
        return {item.relative_to(root) for item in root.rglob("*") if item.is_file()}

    with sandbox_status("💾 Saving changes..."):
        baseline_files = iter_files(sandbox.baseline)
        workspace_files = iter_files(sandbox.workspace)

        for rel in sorted(baseline_files | workspace_files):
            if is_protected(rel):
                continue

            baseline_path = sandbox.baseline / rel
            workspace_path = sandbox.workspace / rel
            project_path = project_root / rel

            baseline_exists = rel in baseline_files
            workspace_exists = rel in workspace_files

            baseline_bytes = baseline_path.read_bytes() if baseline_exists else None
            workspace_bytes = workspace_path.read_bytes() if workspace_exists else None

            if baseline_exists and workspace_exists and baseline_bytes == workspace_bytes:
                continue

            if not workspace_exists:
                if project_path.exists() and project_path.read_bytes() == baseline_bytes:
                    deletes.append(project_path)
                else:
                    conflicts.append(str(rel))
                continue

            if baseline_exists:
                if not project_path.exists() or project_path.read_bytes() != baseline_bytes:
                    conflicts.append(str(rel))
                    continue
            elif project_path.exists() and project_path.read_bytes() != workspace_bytes:
                conflicts.append(str(rel))
                continue

            copies.append((workspace_path, project_path))

        if not conflicts:
            for project_path in deletes:
                project_path.unlink()
                deleted_count += 1
                parent = project_path.parent
                while parent != project_root:
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent

            for workspace_path, project_path in copies:
                project_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_path, project_path)
                copied_count += 1

    sandbox.destroy()
    if conflicts:
        return (
            f"Could not save because {len(conflicts)} file(s) changed outside Hamster: "
            f"{', '.join(conflicts)}. No drafted changes were saved."
        )
    return f"Saved {copied_count} file(s), removed {deleted_count} file(s)."


def discard_sandbox_changes() -> str:
    """Discard drafted changes and destroy the active sandbox."""
    cleanup_sandbox()
    return "Discarded drafted changes."


def cleanup_sandbox() -> str:
    """Destroy the active temp sandbox.

    Called on session exit (both normal and abnormal).  The TempSandbox
    atexit hook acts as a secondary safety net.
    """
    if _sandbox is None:
        return "No active sandbox to clean up."
    return _sandbox.destroy()


def list_sandbox_files(pattern: str = "") -> str:
    """List files in the current draft for debugging.

    Args:
        pattern: Optional substring to filter files.

    Returns:
        String listing of draft contents.
    """
    try:
        sandbox = _get_sandbox()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    files = []
    try:
        for item in sorted(sandbox.workspace.rglob("*")):
            if item.is_file():
                rel_path = item.relative_to(sandbox.workspace)
                if not pattern or pattern.lower() in str(rel_path).lower():
                    files.append(str(rel_path))
    except Exception as e:
        return f"ERROR listing draft files: {e}"

    if not files:
        return "Draft workspace is empty."

    header = f"Draft workspace files ({len(files)} total):\n"
    listing = "\n".join(files[:50])
    suffix = f"\n... and {len(files) - 50} more" if len(files) > 50 else ""
    return header + listing + suffix


def review_changes() -> str:
    """Summarize pending drafted changes for user review."""
    try:
        sandbox = _get_sandbox()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    pending = _pending_sandbox_changes(sandbox)

    if not pending:
        return "No drafted changes pending review."

    summary = [f"Pending drafted changes ({len(pending)} files):"]
    summary.extend(f"  - {line}" for line in pending)
    summary.append("\nUse /apply to save changes.")
    return "\n".join(summary)


def sync_workspace_to_sandbox(project_root: Path | None = None, verbose: bool = False) -> str:
    """No-op stub retained for API compatibility."""
    return "Draft workspace is initialized at task start. No manual sync needed."


def _pending_sandbox_changes(sandbox: TempSandbox | None = None) -> list[str]:
    sandbox = sandbox or _get_sandbox()

    def iter_files(root: Path) -> set[Path]:
        return {item.relative_to(root) for item in root.rglob("*") if item.is_file()}

    pending: list[str] = []
    baseline_files = iter_files(sandbox.baseline)
    workspace_files = iter_files(sandbox.workspace)
    for rel in sorted(baseline_files | workspace_files):
        baseline_path = sandbox.baseline / rel
        workspace_path = sandbox.workspace / rel
        if rel not in baseline_files:
            pending.append(f"NEW: {rel}")
        elif rel not in workspace_files:
            pending.append(f"DELETED: {rel}")
        elif baseline_path.read_bytes() != workspace_path.read_bytes():
            pending.append(f"MODIFIED: {rel}")
    return pending


def has_pending_sandbox_changes() -> bool:
    try:
        return bool(_pending_sandbox_changes())
    except RuntimeError:
        return False


def pending_change_summary() -> list[str]:
    return _pending_sandbox_changes()


def pending_change_diff() -> list[str]:
    sandbox = _get_sandbox()

    def iter_files(root: Path) -> set[Path]:
        return {item.relative_to(root) for item in root.rglob("*") if item.is_file()}

    lines: list[str] = []
    baseline_files = iter_files(sandbox.baseline)
    workspace_files = iter_files(sandbox.workspace)
    for rel in sorted(baseline_files | workspace_files):
        baseline_path = sandbox.baseline / rel
        workspace_path = sandbox.workspace / rel
        before = baseline_path.read_text(encoding="utf-8", errors="replace") if rel in baseline_files else ""
        after = workspace_path.read_text(encoding="utf-8", errors="replace") if rel in workspace_files else ""
        if before == after:
            continue
        lines.extend(_make_patch_preview(str(rel), before, after))
    return lines

def undo_workspace(
    steps: int,
    session_id: str,
    store: "SessionStore",  # type: ignore[name-defined]  # imported at call site
) -> tuple[bool, str]:
    """Restore the sandbox workspace to the state *steps* turns ago.

    This function DOES NOT modify the messages list — conversation history
    is always preserved.  Only workspace files are rolled back.

    Args:
        steps:      How many turns back to restore (1 = most recent checkpoint).
        session_id: The active session ID from the session store.
        store:      The :class:`~hamster.session_store.SessionStore` instance.

    Returns:
        ``(success, message)`` — *success* is False when no checkpoint exists
        at the requested depth.
    """
    from hamster.checkpoint import CheckpointStore

    if steps < 1:
        return False, "Steps must be at least 1."

    checkpoint_id = store.get_checkpoint_at_turn(session_id, turn_offset=steps)
    if checkpoint_id is None:
        available = len(store.list_checkpoints_for_session(session_id))
        return (
            False,
            f"No checkpoint found {steps} turn{'s' if steps != 1 else ''} ago. "
            f"Only {available} checkpoint{'s are' if available != 1 else ' is'} available.",
        )

    try:
        sandbox = _get_sandbox()
    except RuntimeError as exc:
        return False, f"No active sandbox: {exc}"

    ckpt_store = CheckpointStore()
    result = ckpt_store.restore_checkpoint(checkpoint_id, sandbox.workspace)

    n = steps
    parts: list[str] = []
    if result["restored"]:
        parts.append(f"restored {result['restored']} file{'s' if result['restored'] != 1 else ''}")
    if result["removed"]:
        parts.append(f"removed {result['removed']} file{'s' if result['removed'] != 1 else ''}")
    if result["unchanged"]:
        parts.append(f"{result['unchanged']} unchanged")

    detail = ", ".join(parts) if parts else "no changes needed"
    msg = f"Reverted {n} turn{'s' if n != 1 else ''}: {detail}."
    return True, msg


# ---------------------------------------------------------------------------
# Tool schema definitions for OpenRouter
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": (
                "Search project files for string matches using ripgrep. "
                "Use relative paths like 'hamster/agent.py'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file by its project-relative path "
                "(e.g. 'hamster/agent.py', 'README.md'). "
                "Use start_line and end_line (1-indexed, inclusive) to read only "
                "a specific line range and avoid exhausting the context window on "
                "large files. Omit both to read the entire file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "start_line": {
                        "type": "integer",
                        "description": "First line to return (1-indexed, inclusive). Omit to start from line 1.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to return (1-indexed, inclusive). Omit to read to end of file.",
                    },
                },
                "required": ["filepath"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file_patch",
            "description": (
                "Replace one exact target text block in a project file. Use this for small surgical edits only; "
                "for broad rewrites, use write_file with the full updated file content. "
                "Use relative paths like 'hamster/tools.py'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "target_text": {"type": "string"},
                    "replacement_text": {"type": "string"},
                },
                "required": ["filepath", "target_text", "replacement_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a project file, automatically scaffolding missing parent directories. "
                "Use this for new files and broad whole-file rewrites. "
                "Use relative paths like 'hamster/new_file.py'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filepath", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Permission-gated DuckDuckGo lookup for technical documentation, APIs, syntax, and libraries.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Delete a file from the draft workspace without invoking any shell command. "
                "Use this instead of run_sandbox_command('rm ...') — it bypasses the shell "
                "security blacklist and operates safely via Python's filesystem API. "
                "Use project-relative paths like 'login.html' or 'src/old_module.py'. "
                "The file is removed from the draft only; the real project is unchanged until /apply."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                },
                "required": ["filepath"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sandbox_command",
            "description": (
                "Run a non-destructive terminal command after security filtering and user approval. "
                "Do NOT use this for file deletion — use delete_file instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "search_codebase": search_codebase,
    "read_file": read_file,
    "edit_file_patch": edit_file_patch,
    "write_file": write_file,
    "delete_file": delete_file,
    "web_search": web_search,
    "run_sandbox_command": run_sandbox_command,
}
