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


class CompactContextManager:
    """Keeps the most important prompts and recent outcomes within a strict token budget."""

    def __init__(self, token_budget: int = 4000) -> None:
        self.token_budget = token_budget

    def compact_messages(self, messages: list[dict[str, Any]], *, keep_tail: int = 3) -> list[dict[str, Any]]:
        if not messages:
            return []

        estimated = sum(estimate_tokens(str(message.get("content", ""))) for message in messages)
        if estimated <= self.token_budget:
            return messages

        system_messages = [message for message in messages if message.get("role") == "system"]
        tail_messages = messages[-keep_tail:]
        middle_messages = [message for message in messages if message not in system_messages and message not in tail_messages]

        collapsed: list[dict[str, Any]] = []
        collapsed.extend(system_messages)

        for message in middle_messages:
            collapsed.append(
                {
                    "role": message.get("role", "assistant"),
                    "content": self._compress_middle_message(message),
                }
            )

        collapsed.extend(tail_messages)
        return collapsed

    def _compress_middle_message(self, message: dict[str, Any]) -> str:
        content = str(message.get("content", ""))
        tokens = lightweight_tokenize(content)
        if len(tokens) <= 120:
            return content
        return "[condensed history] " + " ".join(tokens[:80]) + " ..."


def compact_context(messages: list[dict[str, Any]], *, token_budget: int = 4000) -> list[dict[str, Any]]:
    return CompactContextManager(token_budget=token_budget).compact_messages(messages)
