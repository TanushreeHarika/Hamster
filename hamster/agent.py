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
Your file tools are physically restricted to ./sandbox/ and security violations are non-negotiable.
You may run terminal commands only through run_sandbox_command, which is restricted to ./sandbox/ and blocks destructive syntax before approval.
You may use web_search only for technical documentation, API specifications, syntax examples, or library verification.
Never claim to have inspected files unless you used read_file or search_codebase.
Prefer small, surgical edits through edit_file_patch. If a tool returns an error or SECURITY VIOLATION, adjust your next step.
Note: search_codebase requires ripgrep (rg) to be installed. If missing, install with: brew install ripgrep

CRITICAL — YOUR WORKING DIRECTORY:
- You are already running INSIDE ./sandbox/. Do NOT reference "sandbox/" in paths.
- To list all files: run_sandbox_command("ls -la") or run_sandbox_command("find . -type f")
- NEVER use "ls ./sandbox/" — that tries to enter a non-existent nested sandbox directory.
- NEVER use "ls ./sandbox" as a path argument to read_file or search_codebase.
- Correct file access: read_file("README.md") or read_file("hamster/agent.py")
- Wrong file access: read_file("sandbox/README.md") — this will FAIL.
- If a tool returns "No files found" or "directory not found", use run_sandbox_command("find . -type f | head -30") to verify what exists."""


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
