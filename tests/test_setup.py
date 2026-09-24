"""Tests for picking the right Python when setting the agents up."""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import orthros_setup as setup  # noqa: E402


class TestPythons(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = setup.SHARED
        setup.SHARED = self.dir

    def tearDown(self):
        setup.SHARED = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def cfg(self, text):
        with open(os.path.join(self.dir, "pyvenv.cfg"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_reads_the_version_a_venv_was_made_with(self):
        self.cfg("home = C:\\Python312\ninclude-system-site-packages = false\nversion = 3.12.4\n")
        self.assertEqual(setup.version_of(self.dir), "3.12")

    def test_the_agents_use_the_interpreter_shared_venv_was_made_with(self):
        self.cfg("home = /nowhere\nversion = %d.%d.0\nexecutable = %s\n"
                 % (sys.version_info[0], sys.version_info[1], sys.executable))
        self.assertEqual(setup.shared_python(), sys.executable)

    def test_no_shared_venv_means_no_answer(self):
        self.assertEqual(setup.version_of(self.dir), "")
        self.assertEqual(setup.venv_config(self.dir), {})

    def test_a_python_aider_supports_is_used_as_is(self):
        if sys.version_info[:2] in setup.AIDER_PYTHONS:
            self.assertEqual(setup.python_for_aider(), sys.executable)


if __name__ == "__main__":
    unittest.main()
