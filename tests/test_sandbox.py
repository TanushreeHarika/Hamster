import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamster.tools import (
    TOOL_FUNCTIONS,
    TOOL_SCHEMAS,
    _get_sandbox,
    apply_sandbox_to_root,
    cleanup_sandbox,
    configure_sandbox,
    edit_file_patch,
    init_session_state,
    read_file,
    write_file,
)
from src.sandbox import TempSandbox


class TestSandbox(unittest.TestCase):
    def setUp(self):
        # Create a temporary project root for testing
        self.test_project = Path(tempfile.mkdtemp(prefix="hamster-test-project-"))
        self.addCleanup(lambda: shutil.rmtree(self.test_project, ignore_errors=True))

        # Create a mock file in the project
        self.mock_file = self.test_project / "mock_config.py"
        self.mock_file.write_text('APP_NAME = "hamster-legacy"\n', encoding="utf-8")

        # Patch read/command prompts to automatically approve everything
        self.patcher1 = patch("hamster.tools.confirm", return_value=True)
        self.patcher1.start()

        # Patch the tools._project_root to point to our test project
        self.patcher3 = patch(
            "hamster.tools._project_root", return_value=str(self.test_project)
        )
        self.patcher3.start()

        # Initialize session state for tools
        init_session_state()

        # Initialize the TempSandbox
        self.sandbox = TempSandbox(project_root=self.test_project)
        configure_sandbox(self.sandbox)

    def tearDown(self):
        self.patcher1.stop()
        self.patcher3.stop()
        self.sandbox.destroy()

    def test_sandbox_creation(self):
        # Sandbox should be created in /tmp or system temp dir
        self.assertTrue(self.sandbox.root.exists())
        self.assertTrue(self.sandbox.workspace.exists())
        self.assertTrue(self.sandbox.baseline.exists())
        self.assertTrue((self.sandbox.workspace / "mock_config.py").exists())
        # Should not be in the project dir
        self.assertFalse(str(self.sandbox.root).startswith(str(self.test_project)))

    def test_workspace_reading(self):
        # Reading a file should read from the draft workspace
        content = read_file("mock_config.py")
        self.assertIn("hamster-legacy", content)

        workspace_path = self.sandbox.workspace / "mock_config.py"
        self.assertTrue(workspace_path.exists())
        self.assertEqual(
            workspace_path.read_text(encoding="utf-8"), 'APP_NAME = "hamster-legacy"\n'
        )

    def test_editing(self):
        # Editing should only affect the draft workspace, not the real project
        res = edit_file_patch(
            "mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"'
        )
        self.assertIn("Updated mock_config.py", res)

        workspace_path = self.sandbox.workspace / "mock_config.py"
        self.assertEqual(
            workspace_path.read_text(encoding="utf-8"), 'APP_NAME = "hamster"\n'
        )

        # Real project file remains unchanged
        self.assertEqual(
            self.mock_file.read_text(encoding="utf-8"), 'APP_NAME = "hamster-legacy"\n'
        )

    def test_editing_does_not_prompt_per_change(self):
        with patch("hamster.tools.confirm") as mocked_confirm:
            res = edit_file_patch(
                "mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"'
            )

        self.assertIn("Updated mock_config.py", res)
        mocked_confirm.assert_not_called()

    def test_missing_patch_target_is_recoverable_tool_result(self):
        res = edit_file_patch("mock_config.py", "DOES_NOT_EXIST", "replacement")

        self.assertIn("Target text was not found", res)
        self.assertIn("use write_file", res)
        self.assertFalse(res.startswith("ERROR"))

    def test_new_file_creation(self):
        # Creating a new file should put it in the workspace
        res = write_file("new_folder/new_file.txt", "Hello World")
        self.assertIn("Wrote new_folder/new_file.txt", res)

        new_path = self.sandbox.workspace / "new_folder" / "new_file.txt"
        self.assertTrue(new_path.exists())
        self.assertEqual(new_path.read_text(encoding="utf-8"), "Hello World")

        # Real project doesn't have it yet
        self.assertFalse((self.test_project / "new_folder" / "new_file.txt").exists())

    def test_write_file_does_not_prompt_per_change(self):
        with patch("hamster.tools.confirm") as mocked_confirm:
            res = write_file("new_folder/quiet.txt", "Hello")

        self.assertIn("Wrote new_folder/quiet.txt", res)
        mocked_confirm.assert_not_called()

    def test_model_cannot_apply_changes_directly(self):
        tool_names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        self.assertNotIn("apply_sandbox_to_root", tool_names)
        self.assertNotIn("apply_sandbox_to_root", TOOL_FUNCTIONS)

    def test_apply_sandbox_to_root(self):
        # Stage an edit
        edit_file_patch(
            "mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"'
        )
        # Create a new file
        write_file("new_folder/new_file.txt", "Hello World")

        # Apply
        res = apply_sandbox_to_root(project_root=self.test_project)
        self.assertIn("Saved", res)

        # Project should now be updated
        self.assertEqual(
            self.mock_file.read_text(encoding="utf-8"), 'APP_NAME = "hamster"\n'
        )
        self.assertTrue((self.test_project / "new_folder" / "new_file.txt").exists())

        # Sandbox should be cleaned up after apply
        self.assertTrue(self.sandbox.is_destroyed)
        self.assertFalse(self.sandbox.root.exists())

    def test_apply_deletes_removed_workspace_files(self):
        (self.sandbox.workspace / "mock_config.py").unlink()

        res = apply_sandbox_to_root(project_root=self.test_project)
        self.assertIn("removed 1 file", res)
        self.assertFalse(self.mock_file.exists())

    def test_apply_skips_concurrent_project_changes(self):
        edit_file_patch(
            "mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"'
        )
        self.mock_file.write_text('APP_NAME = "user-change"\n', encoding="utf-8")

        res = apply_sandbox_to_root(project_root=self.test_project)
        self.assertIn("Could not save", res)
        self.assertEqual(
            self.mock_file.read_text(encoding="utf-8"), 'APP_NAME = "user-change"\n'
        )

    def test_idempotent_destroy(self):
        # First destroy
        msg1 = self.sandbox.destroy()
        self.assertIn("Temp sandbox destroyed", msg1)
        self.assertFalse(self.sandbox.root.exists())
        self.assertTrue(self.sandbox.is_destroyed)

        # Second destroy should be safe
        msg2 = self.sandbox.destroy()
        self.assertIn("Sandbox already destroyed", msg2)

    def test_cleanup_sandbox(self):
        res = cleanup_sandbox()
        self.assertIn("Temp sandbox destroyed", res)
        self.assertFalse(self.sandbox.root.exists())

        # Further operations should raise RuntimeError
        with self.assertRaises(RuntimeError):
            _get_sandbox()


if __name__ == "__main__":
    unittest.main()
