import json
import unittest
from unittest.mock import patch

from hamster.agent import SYSTEM_PROMPT, run_agent_turn
from hamster.openrouter import StreamResult


class FakeClient:
    def __init__(self):
        self.calls = 0

    def stream_chat(self, _messages):
        self.calls += 1
        if self.calls == 1:
            yield "```html\n"
            yield "<!DOCTYPE html>\n"
            yield "```"
            yield StreamResult(
                content="```html\n<!DOCTYPE html>\n```",
                tool_calls={
                    0: {
                        "id": "call_write",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"filepath": "index.html", "content": "<!DOCTYPE html>\n"}
                            ),
                        },
                    }
                },
            )
            return
        yield "Done."
        yield StreamResult(content="Done.")


class VerboseFinalClient:
    def stream_chat(self, _messages):
        content = "```html\n<!DOCTYPE html>\n<html>\n</html>\n```"
        yield content
        yield StreamResult(content=content)


class TestAgentRendering(unittest.TestCase):
    def test_system_prompt_gives_hamster_a_character(self):
        self.assertIn("cute, supportive, funny", SYSTEM_PROMPT)
        self.assertIn("lightly flirty", SYSTEM_PROMPT)
        self.assertIn("Never sound like a corporate assistant", SYSTEM_PROMPT)

    def test_suppresses_assistant_content_when_tool_calls_are_present(self):
        messages = [{"role": "system", "content": "test"}]

        with (
            patch("hamster.agent.TOOL_FUNCTIONS", {"write_file": lambda **_kwargs: "Wrote index.html."}),
            patch("hamster.agent.print_assistant_delta") as mocked_print,
            patch("hamster.agent.render_tool_result"),
        ):
            run_agent_turn(FakeClient(), messages, max_failures=1)

        printed = "".join(call.args[0] for call in mocked_print.call_args_list)
        self.assertNotIn("<!DOCTYPE html>", printed)
        self.assertIn("Done.", printed)

    def test_suppresses_verbose_final_content_when_changes_are_pending(self):
        messages = [{"role": "system", "content": "test"}]

        with (
            patch("hamster.agent.has_pending_sandbox_changes", return_value=True),
            patch("hamster.agent.print_assistant_delta") as mocked_print,
        ):
            run_agent_turn(VerboseFinalClient(), messages, max_failures=1)

        printed = "".join(call.args[0] for call in mocked_print.call_args_list)
        self.assertNotIn("<!DOCTYPE html>", printed)


if __name__ == "__main__":
    unittest.main()
