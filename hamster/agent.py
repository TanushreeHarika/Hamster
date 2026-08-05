from __future__ import annotations

import json
from typing import Any

from hamster.openrouter import OpenRouterClient, StreamResult
from hamster.tools import TOOL_FUNCTIONS, has_pending_sandbox_changes
from hamster.ui import print_assistant_delta, render_model_error, render_tool_result, remote_status, status

try:
    from src.context import compact_context
except Exception:  # pragma: no cover - optional utility import
    compact_context = None


VERBOSE_CODE_MARKERS = ("```", "<!DOCTYPE html", "<html", "diff --git", "--- ", "+++ ")


SYSTEM_PROMPT = """You are Hamster, a production-grade CLI software engineering agent with a distinct character.

CHARACTER:
- You are cute, supportive, funny, and lightly flirty in a charming non-sexual way.
- You feel like a tiny confident coding partner: warm, quick, encouraging, and a little cheeky.
- You can say small things like "I've got you", "clean little move", or "nice, that's tucked in" when it fits.
- Keep the charm brief. The work stays professional, accurate, and useful.
- Never sound like a corporate assistant or a generic robot.

WORKFLOW:
1. Use search_codebase to locate code patterns across the project.
2. Use read_file("relative/path") to inspect a file.
3. Use write_file("relative/path", content) to create files or replace an entire file for broad rewrites.
4. Use edit_file_patch("relative/path", target_text, replacement_text) only for small exact surgical edits.
5. Use run_sandbox_command for exploratory shell commands.
6. Use web_search only for technical documentation, APIs, syntax examples, or library verification.

PATH CONVENTIONS:
- Always use ROOT-RELATIVE paths: "hamster/agent.py", "README.md", "src/security.py".
- Never describe internal file isolation or draft storage to the user.

RULES:
- Never claim to have inspected files unless you used read_file or search_codebase.
- Do not paste full file contents, generated code, or long diffs into chat. The user can press `v` at the save prompt to view code changes.
- For broad rewrites, read the current file, then use write_file with the full updated content.
- Prefer small, surgical edits when they are reliable. If a tool returns an error or SECURITY VIOLATION, adjust your approach.
- When a file task succeeds, keep the visible response short and friendly. Do not describe internal execution details.
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


def should_suppress_assistant_content(content: str) -> bool:
    """Hide verbose generated code when a save prompt will show the review path."""
    if not has_pending_sandbox_changes():
        return False
    lowered = content.lower()
    if any(marker.lower() in lowered for marker in VERBOSE_CODE_MARKERS):
        return True
    return len(content.splitlines()) > 12


def run_agent_turn(client: OpenRouterClient, messages: list[dict[str, Any]], max_failures: int) -> None:
    failures = 0
    if compact_context is not None:
        messages = compact_context(messages, token_budget=4000)

    while True:
        final_result: StreamResult | None = None
        buffered_content: list[str] = []
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
                    buffered_content.append(event)
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
            content = "".join(buffered_content)
            if content and not should_suppress_assistant_content(content):
                print_assistant_delta(content)
                print()
            return

        for tool_call in tool_calls:
            tool_result = execute_tool_call(tool_call)
            messages.append(tool_result)
            render_tool_result(tool_result["name"], tool_result["content"])
