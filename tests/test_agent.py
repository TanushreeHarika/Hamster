import json
import unittest
from unittest.mock import patch

from hamster.agent import SYSTEM_PROMPT, run_agent_turn
from hamster.openrouter import StreamResult
from hamster.quality import DraftQualityReport


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
                                {
                                    "filepath": "index.html",
                                    "content": "<!DOCTYPE html>\n",
                                }
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


class QualityRepairClient:
    def __init__(self):
        self.calls = 0
        self.messages = []

    def stream_chat(self, messages):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            yield StreamResult(
                tool_calls={
                    0: {
                        "id": "call_write",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {"filepath": "index.html", "content": "draft"}
                            ),
                        },
                    }
                }
            )
            return
        yield StreamResult(content="Fixed and complete.")


class ImplementationReminderClient:
    def __init__(self):
        self.calls = 0
        self.messages = []

    def stream_chat(self, messages):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            yield StreamResult(content="I will make those changes next.")
            return
        yield StreamResult(content="I could not make changes because the file is unavailable.")


class TestAgentRendering(unittest.TestCase):
    def test_system_prompt_gives_hamster_a_character(self):
        self.assertIn("cute, supportive, funny", SYSTEM_PROMPT)
        self.assertIn("lightly flirty", SYSTEM_PROMPT)
        self.assertIn("Never sound like a corporate assistant", SYSTEM_PROMPT)

    def test_suppresses_assistant_content_when_tool_calls_are_present(self):
        messages = [{"role": "system", "content": "test"}]

        with (
            patch(
                "hamster.agent.TOOL_FUNCTIONS",
                {"write_file": lambda **_kwargs: "Wrote index.html."},
            ),
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

    def test_compacted_messages_replace_history_used_by_caller(self):
        original = [{"role": "system", "content": "old"}]
        compacted = [
            {"role": "system", "content": "new"},
            {"role": "user", "content": "current request"},
        ]

        class CapturingClient:
            def stream_chat(self, messages):
                self.messages = messages
                yield StreamResult(content="Done.")

        client = CapturingClient()
        with (
            patch("hamster.agent.compact_context", return_value=compacted),
            patch("hamster.agent.print_assistant_delta"),
        ):
            run_agent_turn(client, original, max_failures=1)

        self.assertIs(client.messages, original)
        self.assertEqual(original[:2], compacted)
        self.assertEqual(original[-1], {"role": "assistant", "content": "Done."})

    def test_context_overflow_is_reported_without_calling_model(self):
        messages = [{"role": "system", "content": "system"}]
        with (
            patch(
                "hamster.agent.compact_context",
                side_effect=ValueError("request exceeds token budget"),
            ),
            patch("hamster.agent.render_model_error") as report_error,
        ):
            run_agent_turn(FakeClient(), messages, max_failures=1)

        report_error.assert_called_once()
        self.assertIn("Unable to fit conversation", report_error.call_args.args[0])
        self.assertEqual(messages, [{"role": "system", "content": "system"}])

    def test_quality_failure_is_sent_back_for_an_automatic_repair(self):
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "Build it"}]
        client = QualityRepairClient()
        failed_report = DraftQualityReport(
            ("index.html",), (), ("index.html: requested interaction is missing",)
        )

        with (
            patch(
                "hamster.agent.TOOL_FUNCTIONS",
                {"write_file": lambda **_kwargs: "Wrote index.html."},
            ),
            patch("hamster.agent.evaluate_pending_draft", return_value=failed_report),
            patch("hamster.agent.print_assistant_delta"),
            patch("hamster.agent.render_tool_result"),
        ):
            outcome = run_agent_turn(client, messages, max_failures=1)

        self.assertGreaterEqual(client.calls, 2)
        self.assertTrue(
            any(
                "AUTOMATED QUALITY CHECK FAILED" in message.get("content", "")
                for message in client.messages
                if message.get("role") == "user"
            )
        )
        self.assertEqual(outcome.quality_report, failed_report)
        self.assertTrue(outcome.validation_blocked)

    def test_implementation_request_is_retried_without_plan_markers(self):
        messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "Fix the broken button."},
        ]
        client = ImplementationReminderClient()

        with patch("hamster.agent.print_assistant_delta"):
            run_agent_turn(client, messages, max_failures=1)

        self.assertEqual(client.calls, 2)
        self.assertIn(
            "This is an implementation request",
            client.messages[-2]["content"],
        )


if __name__ == "__main__":
    unittest.main()
