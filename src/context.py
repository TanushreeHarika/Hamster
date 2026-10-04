from __future__ import annotations

import json
import re
from typing import Any

_TOKEN_PATTERN = re.compile(r"\w+|[\[\]{}()\-.,:;!?/]+")
_REQUEST_OVERHEAD_TOKENS = 16


def lightweight_tokenize(text: str) -> list[str]:
    """Estimate conversational token usage without external dependencies."""
    return _TOKEN_PATTERN.findall(text or "")


def estimate_tokens(text: str) -> int:
    return max(1, len(lightweight_tokenize(text)))


try:
    import tiktoken as _tiktoken

    _cl100k = _tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:  # type: ignore[misc]
        """Estimate tokens with cl100k_base when the optional package is installed."""
        if not text:
            return 1
        return max(1, len(_cl100k.encode(text)))

except ImportError:
    pass


class CompactContextManager:
    """Compact request history while preserving tool-call/result groups."""

    def __init__(
        self,
        token_budget: int = 4000,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.tool_schemas = tool_schemas or []

    def _token_cost(self, messages: list[dict[str, Any]]) -> int:
        serialized_messages = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        serialized_tools = json.dumps(
            self.tool_schemas, ensure_ascii=False, separators=(",", ":")
        )
        return (
            estimate_tokens(serialized_messages)
            + (estimate_tokens(serialized_tools) if self.tool_schemas else 0)
            + _REQUEST_OVERHEAD_TOKENS
        )

    @staticmethod
    def _group_history(
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        history = [msg for msg in messages if msg.get("role") != "system"]
        groups: list[list[dict[str, Any]]] = []
        index = 0

        while index < len(history):
            message = history[index]
            group = [message]
            index += 1
            calls = message.get("tool_calls") if message.get("role") == "assistant" else None
            if calls:
                pending_ids = {
                    call.get("id") for call in calls if call.get("id") is not None
                }
                while pending_ids and index < len(history):
                    result = history[index]
                    if (
                        result.get("role") != "tool"
                        or result.get("tool_call_id") not in pending_ids
                    ):
                        break
                    group.append(result)
                    pending_ids.remove(result["tool_call_id"])
                    index += 1
            groups.append(group)

        return system_messages, groups

    @staticmethod
    def _shorten_message(
        message: dict[str, Any], limit: int, *, preserve: bool = False
    ) -> dict[str, Any]:
        if preserve or message.get("tool_calls"):
            return message

        content = message.get("content")
        if not isinstance(content, str):
            return message
        tokens = lightweight_tokenize(content)
        if len(tokens) <= limit:
            return message

        shortened = " ".join(tokens[:limit])
        if len(tokens) > limit:
            shortened += " ..."
        compacted = dict(message)
        compacted["content"] = "[condensed] " + shortened
        return compacted

    def _compact_group(
        self,
        group: list[dict[str, Any]],
        limit: int,
        *,
        preserve_user: bool,
    ) -> list[dict[str, Any]]:
        return [
            self._shorten_message(
                message,
                limit,
                preserve=preserve_user and message.get("role") == "user",
            )
            for message in group
        ]

    def compact_messages(
        self, messages: list[dict[str, Any]], *, keep_tail: int = 3
    ) -> list[dict[str, Any]]:
        if not messages:
            return []
        if self._token_cost(messages) <= self.token_budget:
            return messages

        system_messages, groups = self._group_history(messages)
        if not groups:
            if self._token_cost(system_messages) > self.token_budget:
                raise ValueError("System prompt and tool schemas exceed the context budget.")
            return system_messages

        latest_user_group = next(
            (
                index
                for index in range(len(groups) - 1, -1, -1)
                if any(msg.get("role") == "user" for msg in groups[index])
            ),
            len(groups) - 1,
        )
        protected = set(range(max(0, len(groups) - keep_tail), len(groups)))
        protected.add(latest_user_group)

        compacted_groups = [
            self._compact_group(
                group,
                80,
                preserve_user=index == latest_user_group,
            )
            for index, group in enumerate(groups)
        ]

        def assemble() -> list[dict[str, Any]]:
            return system_messages + [
                message for group in compacted_groups for message in group
            ]

        result = assemble()
        for index in range(len(compacted_groups)):
            if self._token_cost(result) <= self.token_budget:
                return result
            if index in protected:
                continue
            compacted_groups[index] = []
            result = assemble()

        if self._token_cost(result) <= self.token_budget:
            return result

        for limit in (40, 20, 10, 1, 0):
            for index in sorted(protected):
                compacted_groups[index] = self._compact_group(
                    compacted_groups[index],
                    limit,
                    preserve_user=index == latest_user_group,
                )
            result = assemble()
            if self._token_cost(result) <= self.token_budget:
                return result

        raise ValueError(
            "Current user request, system prompt, and tool schemas exceed the context budget."
        )


def compact_context(
    messages: list[dict[str, Any]],
    *,
    token_budget: int = 4000,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return CompactContextManager(token_budget, tool_schemas).compact_messages(messages)
