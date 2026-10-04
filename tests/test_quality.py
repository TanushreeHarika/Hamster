import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamster.quality import evaluate_pending_draft
from hamster.tools import configure_sandbox, init_session_state, write_file
from src.sandbox import TempSandbox


class TestDraftQualityChecks(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="hamster-quality-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.project, ignore_errors=True))
        init_session_state()
        self.sandbox = TempSandbox(project_root=self.project)
        configure_sandbox(self.sandbox)
        self.addCleanup(self.sandbox.destroy)

    def test_rejects_billing_toggle_that_only_changes_theme(self):
        write_file(
            "index.html",
            """<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width\">
            <style>body[data-theme='dark'] { background: #111; }</style></head><body>
            <label>Monthly <input id=\"billing\" class=\"hidden\" type=\"checkbox\"> Yearly</label>
            <p>$10/month</p><script>billing.addEventListener('change', () => {
            document.body.dataset.theme = billing.checked ? 'dark' : ''; });</script></body></html>""",
        )

        report = evaluate_pending_draft(
            "Build a responsive pricing card with a Monthly/Yearly toggle and full dark mode support."
        )

        self.assertFalse(report.passed)
        summary = report.summary()
        self.assertIn("billing control does not update", summary)
        self.assertIn("changing the theme", summary)

    def test_accepts_a_billing_control_that_updates_the_price(self):
        write_file(
            "index.html",
            """<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width\">
            <style>[data-theme='dark'] .card { background: #111; color: white; }
            [data-theme='dark'] .button { color: white; }</style></head><body><main class=\"card\">
            <label for=\"billing\">Yearly billing</label><input id=\"billing\" type=\"checkbox\">
            <p id=\"price\">$10/month</p></main><script>const billing = document.querySelector('#billing');
            const price = document.querySelector('#price'); billing.addEventListener('change', () => {
            price.textContent = billing.checked ? '$100/year' : '$10/month'; });</script></body></html>""",
        )

        report = evaluate_pending_draft(
            "Build a responsive pricing card with a Monthly/Yearly toggle and full dark mode support."
        )

        self.assertTrue(report.passed, report.summary())

    def test_python_changes_require_the_project_test_command(self):
        (self.sandbox.workspace / "tests").mkdir()
        write_file("feature.py", "def enabled():\n    return True\n")

        pending = evaluate_pending_draft("Add a Python feature")
        verified = evaluate_pending_draft(
            "Add a Python feature", completed_commands={"pytest -q"}
        )

        self.assertIn("pytest -q", pending.required_commands)
        self.assertIn("run verification command: pytest -q", pending.summary())
        self.assertTrue(verified.passed, verified.summary())


if __name__ == "__main__":
    unittest.main()
