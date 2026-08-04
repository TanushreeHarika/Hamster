from __future__ import annotations

import difflib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from src.sandbox import TempSandbox
from src.security import assert_sandbox_path, PathSecurityViolation
from hamster.ui import (
    confirm,
    render_diff,
    render_security_violation,
    request_approval,
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
        self.low_risk_actions_approved = False

    def approve_read(self, scope: str = "sandbox") -> None:
        """Mark read operations as approved for the given scope."""
        self.read_approved = True
        self.approved_read_scopes.add(scope)

    def is_read_approved(self, scope: str = "sandbox") -> bool:
        """Check if read operations are approved for the given scope."""
        return scope in self.approved_read_scopes

    def approve_low_risk_actions(self) -> None:
        """Mark low-risk tool actions as approved for the current session."""
        self.low_risk_actions_approved = True

    def is_low_risk_actions_approved(self) -> bool:
        return self.low_risk_actions_approved


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
        raise FileNotFoundError(f"File not found in sandbox workspace: {staged!r}")
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
        result = subprocess.run(
            shlex.split(command),
            cwd=str(sandbox.workspace),
            text=True,
            capture_output=True,
            check=False,
        )
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


def read_file(filepath: str) -> str:
    """Read *filepath* from the sandbox workspace."""
    # Security: validate path won't escape sandbox
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
        with sandbox_status("📄 Staging & reading..."):
            staged = _stage_file_to_sandbox(filepath)
            return Path(staged).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        return f"File not found: {exc}"


def edit_file_patch(filepath: str, target_text: str, replacement_text: str) -> str:
    """Edit a file using a text-replacement patch with user approval.

    Workflow:
      1. Read the file from the sandbox workspace.
      2. Apply the text replacement on the workspace copy.
      3. Ask for approval before applying; show diff only when requested.
      4. On approval: write the updated content back to the workspace copy only.
         The real project file remains untouched until apply_sandbox_to_root.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.workspace)
    try:
        assert_sandbox_path(filepath, root=root_str)
    except PathSecurityViolation as exc:
        return _security_violation(str(exc))

    try:
        with sandbox_status("📋 Staging file..."):
            staged = _stage_file_to_sandbox(filepath)
    except FileNotFoundError:
        return f"File not found in project root: {filepath}"

    original = Path(staged).read_text(encoding="utf-8")
    if target_text not in original:
        raise ValueError(f"Target text was not found in {filepath}.")

    replaced_count = original.count(target_text)
    if replaced_count == 0:
        raise ValueError(f"Target text was not found in {filepath}.")

    updated = original.replace(target_text, replacement_text)
    diff_lines = _make_patch_preview(filepath, original, updated)
    additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++ "))
    deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("--- "))

    session = get_session_state()
    if not session.is_low_risk_actions_approved():
        while True:
            action = request_approval(
                f"Edit {filepath}: replace {replaced_count} occurrence{'s' if replaced_count != 1 else ''}",
                filepath=filepath,
                additions=additions,
                deletions=deletions,
            )
            if action == "view":
                render_diff(filepath, diff_lines)
                continue
            if action == "no":
                return "Denied."
            if action == "all":
                session.approve_low_risk_actions()
            break

    with sandbox_status("✏️  Patching sandbox copy..."):
        Path(staged).write_text(updated, encoding="utf-8")

    return f"Patched {filepath}: replaced 1 occurrence in sandbox workspace."


def write_file(filepath: str, content: str) -> str:
    """Create or overwrite a file inside the sandbox workspace."""
    sandbox = _get_sandbox()
    try:
        dest = sandbox.new_path(filepath)
        original = dest.read_text(encoding="utf-8") if dest.exists() else ""
        diff_lines = _make_patch_preview(filepath, original, content)
        additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++ "))
        deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("--- "))
        session = get_session_state()
        if not session.is_low_risk_actions_approved():
            while True:
                action = request_approval(f"Create file: {filepath}", filepath=filepath, additions=additions, deletions=deletions)
                if action == "view":
                    render_diff(filepath, diff_lines)
                    continue
                if action == "no":
                    return "File creation denied by user."
                if action == "all":
                    session.approve_low_risk_actions()
                break
        with sandbox_status("✏️  Writing to sandbox..."):
            dest.write_text(content, encoding="utf-8")
        return f"Successfully created file in sandbox: {filepath}"
    except Exception as e:
        return f"Error creating file {filepath}: {e}"


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
    """Apply workspace changes back to the real project root and destroy the sandbox.

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

    with sandbox_status("🔄 Syncing sandbox → project root..."):
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

    cleanup_message = sandbox.destroy()
    summary = f"Applied {copied_count} file(s), deleted {deleted_count} file(s). {cleanup_message}"
    if conflicts:
        summary += f" Skipped {len(conflicts)} conflict(s): {', '.join(conflicts)}."
    return summary


def cleanup_sandbox() -> str:
    """Destroy the active temp sandbox.

    Called on session exit (both normal and abnormal).  The TempSandbox
    atexit hook acts as a secondary safety net.
    """
    if _sandbox is None:
        return "No active sandbox to clean up."
    return _sandbox.destroy()


def list_sandbox_files(pattern: str = "") -> str:
    """List files in the sandbox for debugging.

    Args:
        pattern: Optional substring to filter files.

    Returns:
        String listing of sandbox contents.
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
        return f"ERROR listing sandbox: {e}"

    if not files:
        return "Sandbox workspace is empty."

    header = f"Sandbox workspace files ({len(files)} total):\n"
    listing = "\n".join(files[:50])
    suffix = f"\n... and {len(files) - 50} more" if len(files) > 50 else ""
    return header + listing + suffix


def review_changes() -> str:
    """Summarize pending sandbox changes for user review."""
    try:
        sandbox = _get_sandbox()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    pending = _pending_sandbox_changes(sandbox)

    if not pending:
        return "No sandbox changes pending review."

    summary = [f"Pending sandbox changes ({len(pending)} files):"]
    summary.extend(f"  - {line}" for line in pending)
    summary.append("\nUse /apply to apply changes to the project root.")
    return "\n".join(summary)


def sync_workspace_to_sandbox(project_root: Path | None = None, verbose: bool = False) -> str:
    """No-op stub retained for API compatibility."""
    return "Sandbox workspace is initialized at session start. No manual sync needed."


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


# ---------------------------------------------------------------------------
# Tool schema definitions for OpenRouter
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": (
                "Search the hidden sandbox workspace for string matches using ripgrep. "
                "Use relative paths like 'hamster/agent.py', never 'sandbox/...'."
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
                "Read a file from the hidden sandbox workspace by its project-relative path "
                "(e.g. 'hamster/agent.py', 'README.md'). "
                "Never prefix paths with 'sandbox/'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
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
                "Replace one exact target text block in a project file. "
                "The replacement is applied to the hidden sandbox workspace after approval. "
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
                "Create or overwrite a file inside the hidden sandbox workspace, automatically "
                "scaffolding missing parent directories. Does not write to the project root. "
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
            "name": "apply_sandbox_to_root",
            "description": (
                "Apply verified hidden sandbox workspace changes back to the real project root, "
                "then destroy the temporary sandbox."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
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
            "name": "run_sandbox_command",
            "description": (
                "Run a non-destructive terminal command inside the OS temp sandbox after security "
                "filtering and user approval. Use for exploratory commands on workspace files."
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
    "web_search": web_search,
    "run_sandbox_command": run_sandbox_command,
    "apply_sandbox_to_root": apply_sandbox_to_root,
}
