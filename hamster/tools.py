from __future__ import annotations

import difflib
import os
import re
import shlex
import subprocess
from pathlib import Path

from hamster.ui import (
    confirm,
    render_action_summary,
    render_diff,
    render_files_summary,
    render_security_violation,
    status,
)


class SandboxViolation(ValueError):
    pass


class CommandSecurityViolation(ValueError):
    pass


SANDBOX_ROOT = os.path.abspath(os.path.join(os.getcwd(), "sandbox"))

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
    SANDBOX_ROOT = os.path.abspath(str(root))


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
    absolute_path = os.path.abspath(os.path.join(root, filepath))
    if not _is_inside_sandbox(absolute_path):
        raise SandboxViolation(
            f"Blocked sandbox escape attempt. Requested={filepath!r}; resolved={absolute_path!r}; sandbox={root!r}."
        )
    return absolute_path


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

    if not confirm(f"🐹 Hamster wants to run command '{command}'. Allow? (y/n):"):
        return "User denied run_sandbox_command."

    with status("Running sandbox command..."):
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
    render_files_summary([{"operation": "search", "path": root, "scope": "sandbox"}])
    render_action_summary("search_codebase", {"query": query})
    if not confirm(f"🐹 Hamster wants to search the codebase for '{query}'. Allow? (y/n):"):
        return "User denied search_codebase."

    with status("Searching sandbox with ripgrep..."):
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
        path = _resolve_inside_sandbox(filepath)
    except SandboxViolation as exc:
        return _security_violation(str(exc))

    render_files_summary([{"operation": "read", "path": path, "scope": "sandbox"}])
    if not confirm(f"🐹 Hamster wants to read file '{filepath}'. Allow? (y/n):"):
        return "User denied read_file."

    with status("Reading sandbox file..."):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found inside sandbox: {filepath}")
        return Path(path).read_text(encoding="utf-8")


def edit_file_patch(filepath: str, target_text: str, replacement_text: str) -> str:
    try:
        path = _resolve_inside_sandbox(filepath)
    except SandboxViolation as exc:
        return _security_violation(str(exc))

    render_files_summary([{"operation": "patch", "path": path, "scope": "sandbox"}])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found inside sandbox: {filepath}")

    original = Path(path).read_text(encoding="utf-8")
    if target_text not in original:
        raise ValueError(f"Target text was not found in {filepath}.")

    updated = original.replace(target_text, replacement_text, 1)
    render_diff(filepath, _make_patch_preview(filepath, original, updated))

    if not confirm(f"🐹 Hamster wants to edit '{filepath}'. Allow? (y/n):"):
        return "User denied edit_file_patch."

    with status("Applying sandbox patch..."):
        Path(path).write_text(updated, encoding="utf-8")
    return f"Patched {filepath}: replaced 1 occurrence."


def web_search(query: str) -> str:
    render_action_summary("web_search", {"query": query, "network": "DuckDuckGo documentation lookup"})
    if not confirm(f"🐹 Hamster wants to search the web for '{query}'. Allow? (y/n):"):
        return "User denied web_search."

    with status("Searching technical documentation..."):
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
]

TOOL_FUNCTIONS = {
    "search_codebase": search_codebase,
    "read_file": read_file,
    "edit_file_patch": edit_file_patch,
    "web_search": web_search,
    "run_sandbox_command": run_sandbox_command,
}
