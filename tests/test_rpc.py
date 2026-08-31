import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hamster.rpc import RPCGateway, SessionManager
from hamster.tools import cleanup_sandbox, configure_sandbox, init_session_state
from src.sandbox import TempSandbox


class TestRPCGateway(unittest.TestCase):
    def setUp(self):
        self.test_project = Path(tempfile.mkdtemp(prefix="hamster-test-project-"))
        self.addCleanup(lambda: shutil.rmtree(self.test_project, ignore_errors=True))

        # create a sample file
        self.mock_file = self.test_project / "sample.txt"
        self.mock_file.write_text("original content\n", encoding="utf-8")

        # patch tools to avoid interactive prompts
        self.p1 = patch("hamster.tools.confirm", return_value=True)
        self.p2 = patch(
            "hamster.tools._project_root", return_value=str(self.test_project)
        )
        self.p1.start()
        self.p2.start()

        init_session_state()
        self.sandbox = TempSandbox(project_root=self.test_project)
        configure_sandbox(self.sandbox)

        self.sessions = SessionManager()
        self.gateway = RPCGateway(self.sessions)

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()
        cleanup_sandbox()

    def test_session_and_exec(self):
        sid = self.gateway.open_session("tester")
        # grant exec capability in policy so execution is allowed
        self.gateway.policy.allow("tester", "exec")
        res = self.gateway.execute_command(sid, "echo hello_rpc")
        self.assertIn("ALLOWED_AUTO", res.get("policy_decision"))
        self.assertIn("hello_rpc", res.get("output", ""))

    def test_checkpoint_and_restore(self):
        sid = self.gateway.open_session("tester")
        # snapshot the absolute file path
        snap_res = self.gateway.create_checkpoint(sid, [str(self.mock_file)])
        snapshot = snap_res.get("snapshot")
        self.assertIsNotNone(snapshot)

        # modify the file
        self.mock_file.write_text("modified content\n", encoding="utf-8")
        self.assertEqual(
            self.mock_file.read_text(encoding="utf-8"), "modified content\n"
        )

        # restore
        restore_res = self.gateway.restore_checkpoint(sid, snapshot)
        self.assertIn("restored", restore_res)
        # file should be back to original
        self.assertEqual(
            self.mock_file.read_text(encoding="utf-8"), "original content\n"
        )


if __name__ == "__main__":
    unittest.main()
