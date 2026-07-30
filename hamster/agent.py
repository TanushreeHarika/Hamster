from __future__ import annotations

import json
from typing import Any

from hamster.openrouter import OpenRouterClient, StreamResult
from hamster.tools import TOOL_FUNCTIONS
from hamster.ui import print_assistant_delta, render_model_error, render_tool_result, remote_status, status

try:
    from src.context import compact_context
except Exception:  # pragma: no cover - optional utility import
    compact_context = None


SYSTEM_PROMPT = """You are Hamster, a production-grade CLI software engineering agent.

ARCHITECTURE — STRICT SANDBOX ISOLATION:
- All file creations, edits, and terminal commands are STRICTLY jailed inside `./sandbox/`.
- The real project root is NEVER modified directly by file tools.
- read_file and edit_file_patch automatically stage the target file from the project root into ./sandbox/ on first access.
- write_file creates new files directly inside the sandbox, auto-creating parent directories.
- search_codebase scans the REAL project root on disk for complete, up-to-date results.
- When you approve an edit or creation, it is applied ONLY to the sandbox copy.
- To promote sandbox changes back to the real repository, you MUST call apply_sandbox_to_root.

PATH CONVENTIONS:
- Always use ROOT-RELATIVE paths: "hamster/agent.py", "README.md", "src/security.py".
- NEVER prefix paths with "sandbox/" — that will FAIL (e.g., do NOT use "sandbox/README.md").

WORKFLOW:
1. Use search_codebase to locate code patterns across the real codebase.
2. Use read_file("relative/path") to inspect a file — it will be staged transparently.
3. Use write_file("new_file.py", content) to create new files in the sandbox.
4. Use edit_file_patch("relative/path", target_text, replacement_text) to make surgical edits (applied to sandbox).
5. Use run_sandbox_command for exploratory shell commands inside the staged sandbox area.
6. When your changes are complete and verified, call apply_sandbox_to_root to sync them to the real project root.
7. Use web_search only for technical documentation, APIs, syntax examples, or library verification.

RULES:
- Never claim to have inspected files unless you used read_file or search_codebase.
- Prefer small, surgical edits. If a tool returns an error or SECURITY VIOLATION, adjust your approach.
- ripgrep (rg) must be installed for search_codebase. Install with: brew install ripgrep"""


def initial_messages() -> list[dict[str, Any]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def execute_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    name = tool_call["function"]["name"]
    raw_arguments = tool_call["function"].get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments)
        if name not in TOOL_FUNCTIONS:
            raise ValueError(f"Unknown tool: {name}")
        output = TOOL_FUNCTIONS[name](**arguments)
    except Exception as exc:
        output = f"ERROR: {type(exc).__name__}: {exc}"

    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id", f"call_{name}"),
        "name": name,
        "content": output,
    }


def run_agent_turn(client: OpenRouterClient, messages: list[dict[str, Any]], max_failures: int) -> None:
    failures = 0
    if compact_context is not None:
        messages = compact_context(messages, token_budget=4000)

    while True:
        final_result: StreamResult | None = None
        waiting = remote_status("⏳ Waiting on OpenRouter model response...")
        waiting_active = False
        try:
            waiting.__enter__()
            waiting_active = True
            for event in client.stream_chat(messages):
                if waiting_active:
                    waiting.__exit__(None, None, None)
                    waiting_active = False
                if isinstance(event, StreamResult):
                    final_result = event
                else:
                    print_assistant_delta(event)
            print()
        except Exception as exc:
            if waiting_active:
                waiting.__exit__(None, None, None)
                waiting_active = False
            failures += 1
            render_model_error(f"OpenRouter error: {type(exc).__name__}: {exc}")
            if failures >= max_failures:
                render_model_error("Failure limit reached for this turn.")
                return
            messages.append(
                {
                    "role": "user",
                    "content": f"The previous model call failed with: {type(exc).__name__}: {exc}",
                }
            )
            continue
        finally:
            if waiting_active:
                waiting.__exit__(None, None, None)

        if final_result is None:
            return

        assistant_message = final_result.assistant_message()
        messages.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            return

        for tool_call in tool_calls:
            tool_result = execute_tool_call(tool_call)
            messages.append(tool_result)
            render_tool_result(tool_result["name"], tool_result["content"])
