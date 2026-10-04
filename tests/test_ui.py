import unittest
from unittest.mock import patch

from rich.console import Console

from hamster.ui import request_save_changes


class TestSavePrompt(unittest.TestCase):
    def test_save_prompt_uses_clear_shortcuts(self):
        prompts: list[str] = []

        def answer(prompt: str) -> str:
            prompts.append(prompt)
            return "a"

        with patch("hamster.ui.prompt_user", side_effect=answer):
            result = request_save_changes(["MODIFIED: README.md"], [])

        self.assertEqual(result, "accept")
        self.assertIn("Choice", prompts[0])
        self.assertIn("[green]a[/]/[red]r[/]/[yellow]v[/]", prompts[0])
        self.assertNotIn("a[/]ccept", prompts[0])

    def test_save_prompt_accepts_a_truthful_validation_status(self):
        test_console = Console(record=True, width=120)
        with patch("hamster.ui.prompt_user", return_value="r"), patch(
            "hamster.ui.console", test_console
        ):
            result = request_save_changes(
                ["NEW: index.html"],
                [],
                validation_status="Validation needs attention: billing prices do not change.",
            )

        self.assertEqual(result, "reject")
        self.assertIn("billing prices do not change", test_console.export_text())


if __name__ == "__main__":
    unittest.main()
