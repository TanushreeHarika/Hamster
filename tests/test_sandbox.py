import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sandbox import TempSandbox
from hamster.tools import (
    configure_sandbox,
    init_session_state,
    read_file,
    edit_file_patch,
    write_file,
    apply_sandbox_to_root,
    cleanup_sandbox,
    _get_sandbox,
)


class TestSandbox(unittest.TestCase):
    def setUp(self):
        # Create a temporary project root for testing
        self.test_project = Path(tempfile.mkdtemp(prefix="hamster-test-project-"))
        self.addCleanup(lambda: shutil.rmtree(self.test_project, ignore_errors=True))
        
        # Create a mock file in the project
        self.mock_file = self.test_project / "mock_config.py"
        self.mock_file.write_text('APP_NAME = "hamster-legacy"\n', encoding="utf-8")
        
        # Patch the UI prompts to automatically approve everything
        self.patcher1 = patch("hamster.tools.confirm", return_value=True)
        self.patcher2 = patch("hamster.tools.render_diff")
        self.patcher1.start()
        self.patcher2.start()
        
        # Patch the tools._project_root to point to our test project
        self.patcher3 = patch("hamster.tools._project_root", return_value=str(self.test_project))
        self.patcher3.start()
        
        # Initialize session state for tools
        init_session_state()

        # Initialize the TempSandbox
        self.sandbox = TempSandbox()
        configure_sandbox(self.sandbox)

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.sandbox.destroy()

    def test_sandbox_creation(self):
        # Sandbox should be created in /tmp or system temp dir
        self.assertTrue(self.sandbox.root.exists())
        self.assertTrue((self.sandbox.root / "mirror").exists())
        self.assertTrue((self.sandbox.root / "new").exists())
        # Should not be in the project dir
        self.assertFalse(str(self.sandbox.root).startswith(str(self.test_project)))

    def test_lazy_staging_and_reading(self):
        # Reading a file should stage it in the mirror
        content = read_file("mock_config.py")
        self.assertIn("hamster-legacy", content)
        
        mirror_path = self.sandbox.root / "mirror" / "mock_config.py"
        self.assertTrue(mirror_path.exists())
        self.assertEqual(mirror_path.read_text(encoding="utf-8"), 'APP_NAME = "hamster-legacy"\n')

    def test_editing(self):
        # Editing should only affect the sandbox mirror, not the real project
        res = edit_file_patch("mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"')
        self.assertIn("Patched mock_config.py", res)
        
        mirror_path = self.sandbox.root / "mirror" / "mock_config.py"
        self.assertEqual(mirror_path.read_text(encoding="utf-8"), 'APP_NAME = "hamster"\n')
        
        # Real project file remains unchanged
        self.assertEqual(self.mock_file.read_text(encoding="utf-8"), 'APP_NAME = "hamster-legacy"\n')

    def test_new_file_creation(self):
        # Creating a new file should put it in the new/ folder
        res = write_file("new_folder/new_file.txt", "Hello World")
        self.assertIn("Successfully created", res)
        
        new_path = self.sandbox.root / "new" / "new_folder" / "new_file.txt"
        self.assertTrue(new_path.exists())
        self.assertEqual(new_path.read_text(encoding="utf-8"), "Hello World")
        
        # Real project doesn't have it yet
        self.assertFalse((self.test_project / "new_folder" / "new_file.txt").exists())

    def test_apply_sandbox_to_root(self):
        # Stage an edit
        edit_file_patch("mock_config.py", 'APP_NAME = "hamster-legacy"', 'APP_NAME = "hamster"')
        # Create a new file
        write_file("new_folder/new_file.txt", "Hello World")
        
        # Apply
        res = apply_sandbox_to_root(project_root=self.test_project)
        self.assertIn("Applied", res)
        
        # Project should now be updated
        self.assertEqual(self.mock_file.read_text(encoding="utf-8"), 'APP_NAME = "hamster"\n')
        self.assertTrue((self.test_project / "new_folder" / "new_file.txt").exists())
        
        # Sandbox should still be alive after apply (for further edits)
        self.assertFalse(self.sandbox.is_destroyed)
        self.assertTrue(self.sandbox.root.exists())

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
