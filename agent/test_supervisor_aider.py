import unittest
from unittest.mock import patch

from supervisor_aider import build_aider_command


class TestBuildAiderCommand(unittest.TestCase):

    def _build(self, **kwargs):
        with patch("supervisor_aider.venv_python", return_value="python.exe"), \
             patch("supervisor_aider.module_available", return_value=True), \
             patch("supervisor_aider.write_model_settings", return_value="/tmp/s.yml"), \
             patch("supervisor_aider.find_linter", return_value=""), \
             patch("supervisor_aider.find_test_cmd", return_value=""):
            return build_aider_command("test-model", "/tmp/meta.json",
                                       use_git=True, ui="terminal", **kwargs)

    def test_starts_with_m_aider(self):
        cmd = self._build(loop_mode=True)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "aider")

    def test_includes_no_suggest_shell_commands(self):
        cmd = self._build(loop_mode=True)
        self.assertIsNotNone(cmd)
        self.assertIn("--no-suggest-shell-commands", cmd)

    def test_includes_message_file(self):
        cmd = self._build(loop_mode=True, prompt_path="/tmp/prompt.md")
        self.assertIsNotNone(cmd)
        self.assertIn("--message-file", cmd)
        self.assertEqual(cmd[cmd.index("--message-file") + 1], "/tmp/prompt.md")


if __name__ == "__main__":
    unittest.main()
