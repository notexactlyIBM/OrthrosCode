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
            contain.finish(job, proc)
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

    def test_a_check_leaves_nothing_in_temp_not_even_read_only_files(self):
        # git's object files are read-only; rmtree(ignore_errors=True) left
        # 17,884 such repos in temp by 2026-10-18.
        leave = ("import os, stat, tempfile; d = os.path.join(tempfile.gettempdir(), 'repo'); "
                 "os.makedirs(d); p = os.path.join(d, 'obj'); open(p, 'w').close(); "
                 "os.chmod(p, stat.S_IREAD); print(tempfile.gettempdir())")
        proc = contain.run([sys.executable, "-c", leave], text=True, timeout=30)
        temp = proc.stdout.strip()
        self.assertTrue(os.path.basename(temp).startswith(contain.TEMP_PREFIX))
        self.assertFalse(os.path.exists(temp))

    def test_stale_check_temps_are_swept_and_nothing_else(self):
        import tempfile, time
        base = tempfile.mkdtemp()
        self.addCleanup(contain.wipe, base)
        old, new, other = (os.path.join(base, n) for n in
                           (contain.TEMP_PREFIX + "old", contain.TEMP_PREFIX + "new", "tmpkeep"))
        for d in (old, new, other):
            os.makedirs(d)
        long_ago = time.time() - 2 * contain.STALE_TEMP_SECONDS
        os.utime(old, (long_ago, long_ago))
        os.utime(other, (long_ago, long_ago))
        with mock.patch.object(contain.tempfile, "gettempdir", return_value=base):
            contain._sweep_stale_temps()
        self.assertEqual(sorted(os.listdir(base)), sorted([os.path.basename(new), "tmpkeep"]))

    @unittest.skipUnless(os.name == "nt", "Windows job objects")
    def test_a_test_that_eats_memory_is_stopped(self):
        proc = contain.run([sys.executable, "-c", "x = bytearray(600 * 1024 * 1024)"],
                           memory_mb=256, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MemoryError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
