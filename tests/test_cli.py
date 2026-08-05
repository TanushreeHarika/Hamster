import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hamster.cli as cli
import hamster.tools as tools


class TestCLIEndOfTaskSave(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="hamster-cli-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.project, ignore_errors=True))

    def test_accepting_end_of_task_save_does_not_crash(self):
        def draft_change(_client, _messages, _max_failures):
            tools.write_file("index.html", "<!DOCTYPE html>\n")

        with (
            patch("hamster.cli.Path.cwd", return_value=self.project),
            patch("hamster.cli.print_logo"),
            patch("hamster.cli.print_exit_logo"),
            patch("hamster.cli.load_config", return_value=SimpleNamespace(max_failures=1)),
            patch("hamster.cli.OpenRouterClient", return_value=object()),
            patch("hamster.cli.run_agent_turn", side_effect=draft_change),
            patch("hamster.cli.request_save_changes", return_value="accept"),
            patch("hamster.cli.prompt_user", side_effect=["create index", EOFError]),
        ):
            cli.main()

        self.assertEqual((self.project / "index.html").read_text(encoding="utf-8"), "<!DOCTYPE html>\n")


if __name__ == "__main__":
    unittest.main()
