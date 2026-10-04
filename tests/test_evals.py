from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evals import (
    SYSTEM_PROMPT,
    TOOL_SCHEMAS,
    _check_application_quality,
    _execute_quality_tool,
)
from hamster.agent import SYSTEM_PROMPT as AGENT_SYSTEM_PROMPT
from hamster.tools import TOOL_SCHEMAS as AGENT_TOOL_SCHEMAS


class TestQualityEvaluation(unittest.TestCase):
    def test_evals_use_the_production_prompt_and_tool_schemas(self) -> None:
        self.assertEqual(SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT)
        self.assertEqual(TOOL_SCHEMAS, AGENT_TOOL_SCHEMAS)

    def test_full_turn_quality_checks_generated_app_build_and_tool_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "index.html").write_text(
                """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css">
<script src="app.js" defer></script>
</head><body><main><h1>Focus timer</h1>
<button type="button">Start</button><button type="button">Pause</button>
<button type="button">Reset</button>
</main></body></html>""",
                encoding="utf-8",
            )
            (workspace / "styles.css").write_text(
                "main { max-width: 40rem; margin: auto; }\n"
                "@media (max-width: 600px) { main { padding: 1rem; } }\n",
                encoding="utf-8",
            )
            (workspace / "app.js").write_text(
                "const totalSeconds = 25 * 60;\nlet intervalId;\n"
                "button.addEventListener('click', () => {\n"
                "  intervalId = setInterval(() => {}, 1000);\n"
                "  clearInterval(intervalId);\n"
                "  localStorage.setItem('timer', 'running');\n"
                "});\n",
                encoding="utf-8",
            )
            messages = [
                {"role": "system", "content": "System instructions"},
                {"role": "user", "content": "Build the app"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call_build"}],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_build",
                    "name": "run_sandbox_command",
                    "content": "Build verification passed: node --check app.js.",
                },
            ]

            passed, detail = _check_application_quality(
                workspace, messages, build_verified=True
            )

        self.assertTrue(passed, detail)

    def test_quality_check_fails_without_build_or_complete_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "index.html").write_text("<main><h1>App</h1></main>")
            (workspace / "styles.css").write_text("main { color: red; }")
            (workspace / "app.js").write_text("localStorage.getItem('x');")

            passed, detail = _check_application_quality(
                workspace,
                [
                    {
                        "role": "assistant",
                        "tool_calls": [{"id": "call_missing"}],
                    }
                ],
                build_verified=False,
            )

        self.assertFalse(passed)
        self.assertIn("build verification", detail)
        self.assertIn("history is incomplete", detail)
        self.assertIn("responsive CSS", detail)

    def test_quality_tool_rejects_shell_commands_other_than_node_check(self) -> None:
        tool_call = {
            "id": "call_unsafe",
            "function": {
                "name": "run_sandbox_command",
                "arguments": '{"command":"node app.js"}',
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            message, build_verified = _execute_quality_tool(tool_call, Path(tmp))

        self.assertFalse(build_verified)
        self.assertTrue(message["content"].startswith("ERROR:"))

    def test_quality_tool_runs_only_node_syntax_check(self) -> None:
        tool_call = {
            "id": "call_build",
            "function": {
                "name": "run_sandbox_command",
                "arguments": '{"command":"node --check app.js"}',
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "evals.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run:
                message, build_verified = _execute_quality_tool(
                    tool_call, Path(tmp)
                )

        self.assertTrue(build_verified)
        self.assertIn("Build verification passed", message["content"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0:2], ["node", "--check"])


if __name__ == "__main__":
    unittest.main()
