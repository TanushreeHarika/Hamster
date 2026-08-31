from __future__ import annotations

import re
from typing import Any

_TOKEN_PATTERN = re.compile(r"\w+|[\[\]{}()\-.,:;!?/]+")


def lightweight_tokenize(text: str) -> list[str]:
    """A tiny tokenizer that estimates conversational token usage without external deps."""

    return _TOKEN_PATTERN.findall(text or "")


def estimate_tokens(text: str) -> int:
    tokens = lightweight_tokenize(text)
    return max(1, len(tokens))


# ---------------------------------------------------------------------------
# Tokenizer upgrade: use tiktoken BPE when available
# ---------------------------------------------------------------------------
# tiktoken (https://github.com/openai/tiktoken) is an optional dependency.
# When installed it gives an accurate BPE token count (cl100k_base encoding,
# which is used by GPT-4 / Claude-equivalent vocab). When absent, the regex
# tokenizer above is used as a lightweight fallback — no crash, no error.
try:
    import tiktoken as _tiktoken

    _cl100k = _tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:  # type: ignore[misc]
        """Estimate tokens using cl100k_base BPE encoding (tiktoken)."""
        if not text:
            return 1
        return max(1, len(_cl100k.encode(text)))

except ImportError:
    pass  # estimate_tokens already defined above using the regex fallback


class CompactContextManager:
    """Keeps the most important prompts and recent outcomes within a strict token budget."""

    def __init__(self, token_budget: int = 4000) -> None:
        self.token_budget = token_budget

    def compact_messages(
        self, messages: list[dict[str, Any]], *, keep_tail: int = 3
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        estimated = sum(
            estimate_tokens(str(message.get("content", ""))) for message in messages
        )
        if estimated <= self.token_budget:
            return messages

        system_messages = [
            message for message in messages if message.get("role") == "system"
        ]
        tail_messages = messages[-keep_tail:]
        middle_messages = [
            message
            for message in messages
            if message not in system_messages and message not in tail_messages
        ]

        collapsed: list[dict[str, Any]] = []
        collapsed.extend(system_messages)

        for message in middle_messages:
            collapsed.append(self._compress_middle_message(message))

        collapsed.extend(tail_messages)
        return collapsed

    def _compress_middle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Return a compacted copy of a middle-history message.

        Rules:
        - ``tool`` messages must keep ``tool_call_id`` and ``name`` so OpenRouter
          can match them to the originating assistant tool_call.
        - ``assistant`` messages that carry ``tool_calls`` are collapsed to a plain
          summary string; stripping the ``tool_calls`` list avoids dangling-reference
          errors when the paired tool result is also being compacted.
        - All other messages are truncated to 80 tokens with a prefix note.
        """
        role = message.get("role", "assistant")
        content = str(message.get("content") or "")
        tokens = lightweight_tokenize(content)

        # tool messages: always keep required pairing fields
        if role == "tool":
            compressed: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": message.get("tool_call_id", ""),
                "name": message.get("name", ""),
                "content": (
                    content
                    if len(tokens) <= 120
                    else "[condensed] " + " ".join(tokens[:80]) + " ..."
                ),
            }
            return compressed

        # assistant messages with tool_calls: collapse to a plain summary
        if role == "assistant" and message.get("tool_calls"):
            tool_names = ", ".join(
                tc.get("function", {}).get("name", "?")
                for tc in (message.get("tool_calls") or [])
            )
            return {
                "role": "assistant",
                "content": f"[condensed tool call: {tool_names}]",
            }

        # everything else: plain text truncation
        if len(tokens) <= 120:
            return {"role": role, "content": content}
        return {
            "role": role,
            "content": "[condensed history] " + " ".join(tokens[:80]) + " ...",
        }


def compact_context(
    messages: list[dict[str, Any]], *, token_budget: int = 4000
) -> list[dict[str, Any]]:
    return CompactContextManager(token_budget=token_budget).compact_messages(messages)
