from __future__ import annotations

import difflib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from src.security import assert_sandbox_path
from hamster.ui import (
    confirm,
    render_diff,
    render_security_violation,
    sandbox_status,
    status,
)


class SandboxViolation(ValueError):
    pass


class CommandSecurityViolation(ValueError):
    pass


class SessionState:
    """Track approval state across tool calls within a session."""
    def __init__(self):
        self.read_approved = False
        self.approved_read_scopes: set[str] = set()
    
    def approve_read(self, scope: str = "sandbox") -> None:
        """Mark read operations as approved for the given scope."""
        self.read_approved = True
        self.approved_read_scopes.add(scope)
    
    def is_read_approved(self, scope: str = "sandbox") -> bool:
        """Check if read operations are approved for the given scope."""
        return scope in self.approved_read_scopes


# Global session state initialized in cli.py
_session_state: SessionState | None = None


def init_session_state() -> SessionState:
    """Initialize session state for the current session."""
    global _session_state
    _session_state = SessionState()
    return _session_state


def get_session_state() -> SessionState:
    """Get the current session state."""
    if _session_state is None:
        raise RuntimeError("Session not initialized. Call init_session_state() first.")
    return _session_state


SANDBOX_ROOT = os.path.realpath(os.path.join(os.getcwd(), "sandbox"))


def _project_root() -> str:
    """Return the canonical project root (parent of the sandbox directory)."""
    return str(Path(SANDBOX_ROOT).parent)


def _staged_path(filepath: str) -> str:
    """Map a relative filepath to its mirror location inside the sandbox."""
    return os.path.join(SANDBOX_ROOT, filepath.lstrip("/"))


def _stage_file_to_sandbox(filepath: str) -> str:
    """Lazily copy a single file from the project root into the sandbox.

    If the file is already staged (sandbox copy is up-to-date), this is a
    no-op.  Returns the absolute path of the staged file.

    Raises:
        FileNotFoundError: If the source file does not exist in the project root.
        SandboxViolation:  If the resolved path escapes the sandbox boundary.
    """
    # Security: ensure the target resolves inside sandbox
    staged = _resolve_inside_sandbox(filepath)

    # Source file lives in the project root
    source = os.path.join(_project_root(), filepath.lstrip("/"))
    if not os.path.isfile(source):
        raise FileNotFoundError(
            f"Source file not found in project root: {source!r}"
        )

    # Skip copy if the staged version is already current
    if os.path.isfile(staged):
        return staged

    # Ensure the parent directory exists inside the sandbox
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    shutil.copy2(source, staged)
    return staged


def _apply_patch_to_root(filepath: str, updated_content: str) -> None:
    """Write *updated_content* directly to the project-root copy of *filepath*.

    The diff preview has already been shown and approved by the user before
    this function is called.
    """
    root_path = os.path.join(_project_root(), filepath.lstrip("/"))
    # Ensure parent directories exist (e.g. when a new sub-path is staged)
    os.makedirs(os.path.dirname(root_path), exist_ok=True)
    Path(root_path).write_text(updated_content, encoding="utf-8")


def _cleanup_staged_file(staged_path: str) -> None:
    """Delete the temporary staged copy from the sandbox after patching."""
    try:
        os.unlink(staged_path)
    except FileNotFoundError:
        pass  # already gone — that's fine

BLOCKED_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|[;&|]\s*)sudo(\s|$)", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)rm\s+", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)chmod\s+", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)chown\s+", re.IGNORECASE),
    re.compile(r"curl\s+[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
    re.compile(r"wget\s+[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
    re.compile(r"\b(base64|openssl)\b[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
)


def configure_sandbox(root: Path) -> None:
    global SANDBOX_ROOT
    SANDBOX_ROOT = os.path.realpath(str(root))


def _sandbox_root() -> str:
    return SANDBOX_ROOT


def _is_inside_sandbox(absolute_path: str) -> bool:
    root = _sandbox_root()
    return absolute_path == root or absolute_path.startswith(root + os.sep)


def _security_violation(message: str) -> str:
    warning = f"SECURITY VIOLATION: {message}"
    render_security_violation(warning)
    return warning


def _resolve_inside_sandbox(filepath: str) -> str:
    """Resolve *filepath* relative to the sandbox root with boundary enforcement."""
    root = _sandbox_root()
    try:
        absolute_path = assert_sandbox_path(filepath, root=root)
    except Exception as exc:
        raise SandboxViolation(str(exc)) from exc
    if not _is_inside_sandbox(absolute_path):
        raise SandboxViolation(
            f"Blocked sandbox escape attempt. Requested={filepath!r}; resolved={absolute_path!r}; sandbox={root!r}."
        )
    return absolute_path


def _resolve_file_with_fallback(filepath: str) -> str:
    """Resolve a file path with case-insensitive fallback.
    
    If the exact path doesn't exist, tries to find a case-insensitive match
    in the same directory before raising FileNotFoundError.
    """
    try:
        resolved = _resolve_inside_sandbox(filepath)
    except SandboxViolation:
        raise
    
    # If exact path exists, return it
    if os.path.isfile(resolved):
        return resolved
    
    # Try case-insensitive fallback
    parent_dir = os.path.dirname(resolved)
    filename = os.path.basename(resolved)
    
    if not os.path.isdir(parent_dir):
        raise FileNotFoundError(f"Parent directory not found: {parent_dir}")
    
    # List all files in parent directory and try case-insensitive match
    try:
        entries = os.listdir(parent_dir)
    except (OSError, PermissionError) as e:
        raise FileNotFoundError(f"Cannot access directory {parent_dir}: {e}") from e
    
    # Case-insensitive match
    for entry in entries:
        if entry.lower() == filename.lower():
            fallback_path = os.path.join(parent_dir, entry)
            if os.path.isfile(fallback_path):
                return fallback_path
    
    # No match found
    raise FileNotFoundError(f"File not found (case-sensitive or case-insensitive): {filepath}")


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


def validate_terminal_command(command: str) -> None:
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(command):
            raise CommandSecurityViolation(
                f"Blocked command by blacklist pattern {pattern.pattern!r}: {command!r}"
            )

    parts = shlex.split(command)
    if not parts:
        raise CommandSecurityViolation("Refusing to run an empty terminal command.")

    if parts[0] == "mv" and len(parts) >= 3:
        source = _resolve_inside_sandbox(parts[-2])
        destination = _resolve_inside_sandbox(parts[-1])
        if not (_is_inside_sandbox(source) and _is_inside_sandbox(destination)):
            raise CommandSecurityViolation(f"Blocked mv outside sandbox: {command!r}")


def run_sandbox_command(command: str) -> str:
    try:
        validate_terminal_command(command)
    except (CommandSecurityViolation, SandboxViolation) as exc:
        return _security_violation(str(exc))

    if not confirm(f"🐹 Run: {command}"):
        return "Denied."

    with sandbox_status("🖥️  Running command..."):
        result = subprocess.run(
            shlex.split(command),
            cwd=_sandbox_root(),
            text=True,
            capture_output=True,
            check=False,
        )
    return (result.stdout + result.stderr).strip() or f"Command exited with {result.returncode}."


def search_codebase(query: str) -> str:
    """Search for *query* across the **project root** (not the sandbox).

    Searches are always read-only and fast because they target the real
    repository on disk rather than staged copies.
    """
    # Search the real project root so the index is always complete.
    root = _project_root()

    session = get_session_state()
    if not session.is_read_approved("codebase"):
        if not confirm(f"🐹 Search codebase for: {query}"):
            return "Denied."
        session.approve_read("codebase")

    # Check if ripgrep is installed
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

    The staged copy is kept alive so that a subsequent ``edit_file_patch`` call
    on the same file can skip the re-copy.
    """
    # Security gate — validates the path resolves inside the sandbox boundary
    try:
        _resolve_inside_sandbox(filepath)
    except SandboxViolation as exc:
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
      1. Lazily stage the file from the project root into ./sandbox/.
      2. Apply the text replacement on the *staged* copy.
      3. Show a unified diff and ask for approval.
      4. On approval: write the updated content back to the **project root** file,
         then delete the temporary staged copy from the sandbox.
    """
    # Security gate
    try:
        _resolve_inside_sandbox(filepath)
    except SandboxViolation as exc:
        return _security_violation(str(exc))

    # --- Stage the file on demand ---
    try:
        with sandbox_status("📋 Staging file..."):
            staged = _stage_file_to_sandbox(filepath)
    except FileNotFoundError:
        return f"File not found in project root: {filepath}"

    # --- Apply the text replacement on the staged copy ---
    original = Path(staged).read_text(encoding="utf-8")
    if target_text not in original:
        raise ValueError(f"Target text was not found in {filepath}.")

    updated = original.replace(target_text, replacement_text, 1)
    render_diff(filepath, _make_patch_preview(filepath, original, updated))

    if not confirm(f"🐹 Edit: {filepath}"):
        # Leave staged file so the agent can retry; it will be cleaned at session end
        return "Denied."

    with sandbox_status("✏️  Patching root file..."):
        # 1. Write updated content to the staged copy
        Path(staged).write_text(updated, encoding="utf-8")
        # 2. Apply the patch to the actual project root file
        _apply_patch_to_root(filepath, updated)
        # 3. Clean up the temporary staged copy
        _cleanup_staged_file(staged)

    return f"Patched {filepath}: replaced 1 occurrence (root file updated, staged copy removed)."


def web_search(query: str) -> str:
    if not confirm(f"🐹 Web search: {query}"):
        return "Denied."

    with status("Searching docs..."):
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:
            raise RuntimeError("duckduckgo-search is not installed. Run `uv pip install -e .`.") from exc

        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=5):
                title = item.get("title", "Untitled")
                href = item.get("href") or item.get("url") or ""
                body = item.get("body", "")
                results.append(f"- {title}\n  {href}\n  {body}")

    return "\n\n".join(results) if results else "No web results found."


def sync_workspace_to_sandbox(project_root: Path | None = None, verbose: bool = False) -> str:
    """No-op stub retained for API compatibility.

    The demand-based lazy-copy model stages individual files on demand via
    ``_stage_file_to_sandbox``.  Bulk startup syncing is no longer performed.

    Returns:
        Informational message explaining the new behaviour.
    """
    return "Lazy-copy mode active: files are staged on demand. No bulk sync needed."


def cleanup_sandbox() -> str:
    """Remove all synced files from the sandbox at the end of a session.

    Deletes every item inside the sandbox directory (preserving the directory
    itself) so no stale copies linger after the agent exits.

    Returns:
        Status message describing what was removed.
    """
    import shutil

    sandbox_root = Path(_sandbox_root())
    if not sandbox_root.exists():
        return "Sandbox directory does not exist — nothing to clean."

    removed = []
    errors = []
    for item in list(sandbox_root.iterdir()):
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed.append(item.name)
        except Exception as exc:  # pragma: no cover
            errors.append(f"{item.name}: {exc}")

    msg = f"🧹 Sandbox cleaned — removed {len(removed)} item(s)."
    if errors:
        msg += f" Errors: {'; '.join(errors)}"
    return msg


def list_sandbox_files(pattern: str = "") -> str:
    """List files in the sandbox directory for debugging.
    
    Args:
        pattern: Optional substring to filter files.
    
    Returns:
        String listing of sandbox contents.
    """
    sandbox_root = Path(_sandbox_root())
    
    if not sandbox_root.exists():
        return f"ERROR: Sandbox not found at {sandbox_root}"
    
    files = []
    try:
        for item in sorted(sandbox_root.rglob("*")):
            if item.is_file():
                rel_path = item.relative_to(sandbox_root)
                if not pattern or pattern.lower() in str(rel_path).lower():
                    files.append(str(rel_path))
    except Exception as e:
        return f"ERROR listing sandbox: {e}"
    
    if not files:
        return f"Sandbox is empty. Path: {sandbox_root}"
    
    return f"Files in sandbox ({len(files)} total):\n" + "\n".join(files[:50]) + (
        f"\n... and {len(files) - 50} more" if len(files) > 50 else ""
    )


def apply_sandbox_to_root(project_root: Path | None = None, verbose: bool = False) -> str:
    """Deprecated: bulk apply sandbox → root.

    In the demand-based lazy-copy model, each approved ``edit_file_patch`` call
    writes the updated content directly to the project root file and removes the
    staged sandbox copy.  A bulk apply is therefore no longer needed.

    This function is retained as an emergency fallback only.  It will copy any
    remaining staged files in the sandbox back to the project root, skipping
    protected paths.

    Returns:
        Status message with sync summary.
    """
    sandbox_root = Path(_sandbox_root())

    if project_root is None:
        project_root = sandbox_root.parent
    else:
        project_root = Path(project_root)

    protected_items = {".env", ".git", ".gitignore", ".venv", "sandbox"}
    copied_count = 0

    with sandbox_status("🔄 Emergency apply: sandbox → root..."):
        for item in sandbox_root.rglob("*"):
            if not item.is_file():
                continue
            # Skip protected top-level names
            rel = item.relative_to(sandbox_root)
            if rel.parts[0] in protected_items:
                continue
            dest = project_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied_count += 1

    return f"Emergency apply: copied {copied_count} staged file(s) to project root."


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
                "The file is lazily staged into ./sandbox/ on demand before reading. "
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
                "The file is lazily staged into ./sandbox/, the replacement is applied to "
                "the staged copy, a diff is shown for approval, and — on approval — the "
                "patch is written directly to the project root file and the staged copy is "
                "removed. Use relative paths like 'hamster/tools.py'. Never prefix with 'sandbox/'."
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
                "Run a non-destructive terminal command inside ./sandbox/ after security "
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
    "web_search": web_search,
    "run_sandbox_command": run_sandbox_command,
}
