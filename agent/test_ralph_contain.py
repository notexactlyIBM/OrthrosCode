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

    def test_no_limits_off_windows_or_when_they_cannot_be_set(self):
        if os.name != "nt":
            self.assertIsNone(contain._limited_job(4096, 8))
        with mock.patch.object(contain, "_limited_job", return_value=None):
            proc, job = contain.start([sys.executable, "-c", "pass"])
            proc.wait()
            self.assertIsNone(job)

    @unittest.skipUnless(os.name == "nt", "Windows job objects")
    def test_a_test_that_eats_memory_is_stopped(self):
        proc = contain.run([sys.executable, "-c", "x = bytearray(600 * 1024 * 1024)"],
                           memory_mb=256, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MemoryError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
