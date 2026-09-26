"""Checks run the model's code inside limits; the same results without them."""

import os
import subprocess
import sys
import unittest
from unittest import mock

import ralph_contain as contain


class TestRun(unittest.TestCase):
    def test_same_result_as_subprocess_run(self):
        proc = contain.run([sys.executable, "-c", "import sys; print('out'); "
                            "print('err', file=sys.stderr); sys.exit(3)"],
                           text=True, capture_output=True, timeout=30)
        self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr.strip()),
                         (3, "out", "err"))

    def test_a_timeout_raises_as_before(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            contain.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)

    def test_a_timeout_does_not_wait_for_a_child_left_holding_the_pipe(self):
        import time
        started = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            contain.run([sys.executable, "-c",
                         "import subprocess, sys, time; "
                         "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); "
                         "time.sleep(20)"], timeout=1)
        self.assertLess(time.time() - started, 8)

    def test_a_bad_memory_setting_falls_back(self):
        import importlib
        with mock.patch.dict(os.environ, {"LC_CHECK_MEMORY_MB": "4G"}):
            self.assertEqual(importlib.reload(contain).CHECK_MEMORY_MB, 4096)
        importlib.reload(contain)

    def test_no_limits_off_windows_or_when_they_cannot_be_set(self):
        if os.name != "nt":
            self.assertIsNone(contain._limited_job(4096, 8))
        with mock.patch.object(contain, "_limited_job", return_value=None):
            proc, job = contain.start([sys.executable, "-c", "pass"])
            proc.wait()
            self.assertIsNone(job)

    def test_the_code_checked_gets_nothing_of_the_harness(self):
        show = [sys.executable, "-c", "import os; print(*(os.environ.get(k, '-') for k in "
                "('ORTHROS_LEDGER', 'LC_WORKSPACE', 'LC_QUICK_TESTS', 'KEEP')))"]
        harness = {"ORTHROS_LEDGER": "shared.sqlite", "LC_WORKSPACE": "twin", "LC_QUICK_TESTS": "1"}
        with mock.patch.dict(os.environ, harness):
            inherited = contain.run(show, text=True, timeout=30).stdout.split()
            given = contain.run(show, text=True, timeout=30,
                                env=dict(os.environ, KEEP="1")).stdout.split()
            self.assertEqual(os.environ["ORTHROS_LEDGER"], "shared.sqlite")   # ours is untouched
        self.assertEqual(inherited, ["-", "-", "1", "-"])      # the quick switch gets through
        self.assertEqual(given, ["-", "-", "1", "1"])

    @unittest.skipUnless(os.name == "nt", "Windows job objects")
    def test_a_test_that_eats_memory_is_stopped(self):
        proc = contain.run([sys.executable, "-c", "x = bytearray(600 * 1024 * 1024)"],
                           memory_mb=256, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MemoryError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
