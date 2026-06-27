from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import requests

from hamster.config import Config
from hamster.tools import TOOL_SCHEMAS


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class StreamResult:
    content: str = ""
    tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)

    def assistant_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.get("id", f"call_{idx}"),
                    "type": "function",
                    "function": {
                        "name": call["function"].get("name", ""),
                        "arguments": call["function"].get("arguments", ""),
                    },
                }
                for idx, call in sorted(self.tool_calls.items())
            ]
        return message


class OpenRouterClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def stream_chat(self, messages: list[dict[str, Any]]) -> Iterator[str | StreamResult]:
        if not self.config.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is empty in .env.")

        headers = {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/hamster",
            "X-Title": "Hamster",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }

        response = requests.post(
            OPENROUTER_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=120,
            stream=True,
        )
        response.raise_for_status()

        result = StreamResult()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data: "):
                continue
            data = raw_line.removeprefix("data: ").strip()
            if data == "[DONE]":
                break

            chunk = json.loads(data)
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                result.content += content
                yield content

            for call_delta in delta.get("tool_calls", []) or []:
                index = call_delta["index"]
                call = result.tool_calls.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if call_delta.get("id"):
                    call["id"] = call_delta["id"]
                function_delta = call_delta.get("function", {})
                if function_delta.get("name"):
                    call["function"]["name"] += function_delta["name"]
                if function_delta.get("arguments"):
                    call["function"]["arguments"] += function_delta["arguments"]

        yield result
