from __future__ import annotations

import difflib
import os
import re
import shlex
import subprocess
from pathlib import Path

from src.security import assert_sandbox_path
from src.transactions import TransactionManager
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
    root = _sandbox_root()
    os.makedirs(root, exist_ok=True)
    
    session = get_session_state()
    if not session.is_read_approved("sandbox"):
        if not confirm(f"🐹 Search sandbox for: {query}"):
            return "Denied."
        session.approve_read("sandbox")
    
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
    
    with sandbox_status("🔍 Searching..."):
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
    try:
        path = _resolve_file_with_fallback(filepath)
    except SandboxViolation as exc:
        return _security_violation(str(exc))
    except FileNotFoundError as exc:
        return f"File not found: {exc}"

    session = get_session_state()
    if not session.is_read_approved("sandbox"):
        if not confirm(f"🐹 Read: {filepath}"):
            return "Denied."
        session.approve_read("sandbox")

    with sandbox_status("📄 Reading..."):
        return Path(path).read_text(encoding="utf-8")


def edit_file_patch(filepath: str, target_text: str, replacement_text: str) -> str:
    try:
        path = _resolve_inside_sandbox(filepath)
    except SandboxViolation as exc:
        return _security_violation(str(exc))

    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found inside sandbox: {filepath}")

    original = Path(path).read_text(encoding="utf-8")
    if target_text not in original:
        raise ValueError(f"Target text was not found in {filepath}.")

    updated = original.replace(target_text, replacement_text, 1)
    render_diff(filepath, _make_patch_preview(filepath, original, updated))

    if not confirm(f"🐹 Edit: {filepath}"):
        return "Denied."

    transaction = TransactionManager([path])
    try:
        with sandbox_status("✏️  Patching..."):
            Path(path).write_text(updated, encoding="utf-8")
    except Exception:
        transaction.rollback()
        raise
    return f"Patched {filepath}: replaced 1 occurrence."


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
    """Sync project files from root to sandbox on startup.
    
    Copies all files from project root (except .git, .venv, __pycache__, sandbox/, .env)
    into the isolated sandbox directory. This ensures the agent works with a clean,
    isolated copy of the codebase.
    
    Args:
        project_root: Project root directory. If None, infers from SANDBOX_ROOT parent.
        verbose: If True, print detailed sync information.
    
    Returns:
        Status message with sync summary.
    """
    import shutil
    
    sandbox_root = Path(_sandbox_root())
    
    # Infer project root from sandbox parent if not provided
    if project_root is None:
        project_root = sandbox_root.parent
    else:
        project_root = Path(project_root)
    
    # Verify paths exist
    if not project_root.exists():
        return f"ERROR: Project root not found: {project_root}"
    
    if not sandbox_root.exists():
        return f"ERROR: Sandbox root not found: {sandbox_root}"
    
    # Excluded patterns during sync
    exclude_patterns = {".git", ".venv", "__pycache__", "sandbox", ".env", ".DS_Store"}
    
    copied_count = 0
    skipped_count = 0
    failed_items = []
    
    with sandbox_status("🔄 Syncing workspace..."):
        try:
            for item in project_root.iterdir():
                # Skip excluded items
                if item.name in exclude_patterns:
                    skipped_count += 1
                    continue
                
                # Skip hidden files/dirs except those we might want
                if item.name.startswith("."):
                    skipped_count += 1
                    continue
                
                dest = sandbox_root / item.name
                
                try:
                    if item.is_dir():
                        # Remove existing directory before copying
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                        copied_count += 1
                    elif item.is_file():
                        shutil.copy2(item, dest)
                        copied_count += 1
                except Exception as e:
                    failed_items.append((item.name, str(e)))
                    if verbose:
                        print(f"⚠️  Failed to sync {item.name}: {e}")
        except Exception as e:
            return f"ERROR during sync: {e}"
    
    summary = f"Synced {copied_count} items to sandbox"
    
    if failed_items:
        errors = "; ".join([f"{name}({err})" for name, err in failed_items])
        summary += f" ({len(failed_items)} failed: {errors})"
    
    if copied_count == 0:
        return f"WARNING: No files copied to sandbox. Project root: {project_root}, Sandbox: {sandbox_root}"
    
    return summary


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
    """Sync verified edits from sandbox back to project root.
    
    Copies modified files from the isolated sandbox directory back to the
    project root, allowing verified changes to be committed to the repository.
    
    Args:
        project_root: Project root directory. If None, infers from SANDBOX_ROOT parent.
        verbose: If True, print detailed sync information.
    
    Returns:
        Status message with sync summary.
    """
    import shutil
    
    sandbox_root = Path(_sandbox_root())
    
    # Infer project root from sandbox parent if not provided
    if project_root is None:
        project_root = sandbox_root.parent
    else:
        project_root = Path(project_root)
    
    # Never overwrite .env, .git, or other sensitive files
    protected_items = {".env", ".git", ".gitignore", ".venv", "sandbox"}
    
    copied_count = 0
    skipped_count = 0
    
    with sandbox_status("🔄 Applying sandbox changes to root..."):
        for item in sandbox_root.iterdir():
            # Skip protected items
            if item.name in protected_items:
                skipped_count += 1
                continue
            
            dest = project_root / item.name
            
            try:
                if item.is_dir():
                    # Remove existing directory before copying back
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                    copied_count += 1
                elif item.is_file():
                    shutil.copy2(item, dest)
                    copied_count += 1
            except Exception as e:
                if verbose:
                    print(f"⚠️  Failed to apply {item.name}: {e}")
    
    summary = f"Applied {copied_count} items from sandbox to root"
    return summary


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": "Search for string matches inside the ./sandbox/ directory only.",
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
            "description": "Read a specific file inside the ./sandbox/ directory only.",
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
            "description": "Replace one exact target text block in a file inside ./sandbox/ only.",
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
            "description": "Run a non-destructive terminal command inside ./sandbox/ only after security filtering and user approval.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_sandbox_to_root",
            "description": "Sync verified edits from ./sandbox/ back to the project root. Use after testing changes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
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
    "apply_sandbox_to_root": apply_sandbox_to_root,
}
