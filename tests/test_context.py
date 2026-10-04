from __future__ import annotations

import unittest

from src.context import CompactContextManager, estimate_tokens


class TestCompactContext(unittest.TestCase):
    def test_accounts_for_tool_schemas_and_preserves_system_prompt(self) -> None:
        system = {"role": "system", "content": "Important system instructions"}
        history = [
            system,
            {"role": "user", "content": "old request " * 100},
            {"role": "assistant", "content": "old response " * 100},
            {"role": "user", "content": "current request"},
        ]
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": "large_tool",
                    "description": "schema details " * 100,
                },
            }
        ]
        budget = (
            CompactContextManager(token_budget=10_000, tool_schemas=schemas)
            ._token_cost([system, history[-1]])
            + 10
        )
        compacted = CompactContextManager(
            token_budget=budget, tool_schemas=schemas
        ).compact_messages(history, keep_tail=1)

        self.assertEqual(compacted[0], system)
        self.assertEqual(compacted[-1]["content"], "current request")
        self.assertNotIn("old request " * 100, str(compacted))

    def test_keeps_tool_call_and_all_results_together(self) -> None:
        assistant_call = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"filepath":"a"}'},
                },
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"filepath":"b"}'},
                },
            ],
        }
        results = [
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": "read_file",
                "content": f"result-{call_id} " * 100,
            }
            for call_id in ("call_a", "call_b")
        ]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old request " * 100},
            {"role": "assistant", "content": "old response " * 100},
            assistant_call,
            *results,
            {"role": "user", "content": "current request"},
        ]

        compacted = CompactContextManager(token_budget=500).compact_messages(
            messages, keep_tail=2
        )
        kept_call = next(msg for msg in compacted if msg.get("tool_calls"))
        kept_results = [msg for msg in compacted if msg.get("role") == "tool"]

        self.assertEqual(kept_call, assistant_call)
        self.assertEqual(
            {call["id"] for call in kept_call["tool_calls"]},
            {result["tool_call_id"] for result in kept_results},
        )

    def test_schema_tokens_contribute_to_budget(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "current"},
        ]
        schemas = [{"description": "tool schema " * 30}]
        no_tools_cost = CompactContextManager(token_budget=10_000)._token_cost(
            messages
        )
        with_tools_cost = CompactContextManager(
            token_budget=10_000, tool_schemas=schemas
        )._token_cost(messages)

        self.assertGreater(with_tools_cost, no_tools_cost)


if __name__ == "__main__":
    unittest.main()
