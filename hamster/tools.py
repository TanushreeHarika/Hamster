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
    # The project root is the working directory when hamster was launched.
    # We derive it from __file__ so it never changes even if cwd drifts.
    return str(Path(__file__).parent.parent.resolve())


def _sandbox_root_str() -> str:
    """Return the sandbox root as a string (for legacy callers)."""
    return str(_get_sandbox().root)


def _is_inside_sandbox(absolute_path: str) -> bool:
    root = _sandbox_root_str()
    return absolute_path == root or absolute_path.startswith(root + os.sep)


def _security_violation(message: str) -> str:
    warning = f"SECURITY VIOLATION: {message}"
    render_security_violation(warning)
    return warning


def _resolve_inside_sandbox(filepath: str) -> str:
    """Resolve *filepath* relative to the sandbox root with boundary enforcement.

    The filepath is resolved against the full sandbox root (which includes the
    mirror/ and new/ subtrees).  This is used only for the security validation
    step; the actual staging helpers use mirror_path / new_path directly.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.root)
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
    """Lazily copy a project file into the sandbox mirror/ on first access.

    Returns the absolute path of the staged file.  If the mirror copy already
    exists it is returned immediately (no re-copy).
    """
    sandbox = _get_sandbox()
    staged = sandbox.mirror_path(filepath)

    if staged.is_file():
        return str(staged)

    source = Path(_project_root()) / filepath.lstrip("/")
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found in project root: {source!r}")

    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, staged)
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
            cwd=str(sandbox.root),
            text=True,
            capture_output=True,
            check=False,
        )
    return (result.stdout + result.stderr).strip() or f"Command exited with {result.returncode}."


def search_codebase(query: str) -> str:
    """Search for *query* across the real project root (not the sandbox).

    Searches are always read-only and fast because they target the real
    repository on disk rather than staged copies.
    """
    root = _project_root()

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
    """Stage *filepath* from the project root into the sandbox on demand, then read it.

    The staged copy lives in ``mirror/`` inside the temp sandbox so subsequent
    ``edit_file_patch`` calls can skip the re-copy.
    """
    # Security: validate path won't escape sandbox
    sandbox = _get_sandbox()
    root_str = str(sandbox.root)
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
      1. Lazily stage the file from the project root into sandbox ``mirror/``.
      2. Apply the text replacement on the staged copy.
      3. Ask for approval before applying; show diff only when requested.
      4. On approval: write the updated content back to the staged copy only.
         The real project file remains untouched until apply_sandbox_to_root.
    """
    sandbox = _get_sandbox()
    root_str = str(sandbox.root)
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

    return f"Patched {filepath}: replaced 1 occurrence (staged in sandbox)."


def write_file(filepath: str, content: str) -> str:
    """Create or overwrite a file inside the sandbox ``new/`` subtree.

    New files are isolated in ``new/`` so apply_sandbox_to_root can
    distinguish them from lazily staged project files.
    """
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
    """Copy verified edits from the sandbox back to the real project root.

    Copies staged files from ``mirror/`` and new files from ``new/`` into
    the project root.  The sandbox is NOT destroyed after apply so the
    session can continue making further edits.

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

    with sandbox_status("🔄 Syncing sandbox → project root..."):
        for subtree in (sandbox.root / "mirror", sandbox.root / "new"):
            if not subtree.exists():
                continue
            for item in subtree.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(subtree)
                if rel.parts[0] in protected_items:
                    continue
                dest = project_root / rel
                if dest.exists() and item.read_bytes() == dest.read_bytes():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                copied_count += 1

    return f"Applied {copied_count} staged file(s) to project root."


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
        for item in sorted(sandbox.root.rglob("*")):
            if item.is_file():
                rel_path = item.relative_to(sandbox.root)
                if not pattern or pattern.lower() in str(rel_path).lower():
                    files.append(str(rel_path))
    except Exception as e:
        return f"ERROR listing sandbox: {e}"

    if not files:
        return f"Sandbox is empty. Path: {sandbox.root}"

    header = f"Sandbox: {sandbox.root}\nFiles ({len(files)} total):\n"
    listing = "\n".join(files[:50])
    suffix = f"\n... and {len(files) - 50} more" if len(files) > 50 else ""
    return header + listing + suffix


def review_changes() -> str:
    """Summarize pending staged sandbox changes for user review."""
    try:
        sandbox = _get_sandbox()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    pending = []
    mirror_dir = sandbox.root / "mirror"
    new_dir = sandbox.root / "new"

    if mirror_dir.exists():
        for item in sorted(mirror_dir.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(sandbox.root)
            project_path = Path(_project_root()) / rel
            if not project_path.exists():
                pending.append(f"NEW (staged): {rel}")
                continue
            original = project_path.read_text(encoding="utf-8")
            updated = item.read_text(encoding="utf-8")
            if original != updated:
                pending.append(f"MODIFIED: {rel}")

    if new_dir.exists():
        for item in sorted(new_dir.rglob("*")):
            if item.is_file():
                rel = item.relative_to(sandbox.root)
                pending.append(f"NEW: {rel}")

    if not pending:
        return "No staged sandbox changes pending review."

    summary = [f"Pending staged sandbox changes ({len(pending)} files):"]
    summary.extend(f"  - {line}" for line in pending)
    summary.append("\nUse /apply to commit staged changes to the project root.")
    summary.append("Use /files to inspect sandbox contents.")
    return "\n".join(summary)


def sync_workspace_to_sandbox(project_root: Path | None = None, verbose: bool = False) -> str:
    """No-op stub retained for API compatibility.

    The demand-based lazy-copy model stages individual files on demand via
    ``_stage_file_to_sandbox``.  Bulk startup syncing is no longer performed.
    """
    return "Lazy-copy mode active: files are staged on demand. No bulk sync needed."


# ---------------------------------------------------------------------------
# Tool schema definitions for OpenRouter
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": (
                "Search the project root codebase for string matches using ripgrep. "
                "Searches the real repository — not the sandbox staging area. "
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
                "Read a file from the project repository by its relative path "
                "(e.g. 'hamster/agent.py', 'README.md'). "
                "The file is lazily staged into the OS temp sandbox on demand before reading. "
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
                "The file is lazily staged into the OS temp sandbox, the replacement is applied to "
                "the staged copy, and a diff is shown for approval. On approval, the "
                "patch is written to the sandbox copy only. Use relative paths like 'hamster/tools.py'."
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
                "Create or overwrite a new file inside the OS temp sandbox, automatically scaffolding "
                "missing parent directories. Does not write to the project root. "
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
                "Copy all verified edits from the OS temp sandbox back to the real project root. "
                "Use this after making changes and the user wants to keep them. "
                "The sandbox stays active after apply for further edits."
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
                "filtering and user approval. Use for exploratory commands on staged files."
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
