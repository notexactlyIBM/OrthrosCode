"""Every practice and held-out exercise is well formed, and its stub fails.

A stub that already passes its hidden tests would score every version full
marks and prove nothing. The reference solutions are kept outside the
repository; this checks what can be checked without them.
"""

import os
import re
import sys
import tempfile
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import orthros_work as work  # noqa: E402


def folders():
    for base in ("exercises", "evals"):
        path = os.path.join(ROOT, base)
        for name in sorted(os.listdir(path)):
            if os.path.isdir(os.path.join(path, name, "hidden")):
                yield base, name, os.path.join(path, name)


class TestExercises(unittest.TestCase):
    def test_each_has_a_task_a_stub_and_hidden_tests_the_stub_fails(self):
        seen = {}
        for base, name, folder in folders():
            with self.subTest(exercise=name):
                task = work.read(os.path.join(folder, "task.md"))
                first, _, items = task.partition("\n\n")
                self.assertTrue(first.strip())
                self.assertGreaterEqual(len(re.findall(r"^- \[ \] .+Done when:", items, re.M)), 1)
                stubs = [f for f in os.listdir(folder) if f.endswith(".py")]
                self.assertEqual(len(stubs), 1)
                self.assertNotIn(stubs[0][:-3], getattr(sys, "stdlib_module_names", ()))
                with tempfile.TemporaryDirectory() as tmp:
                    shutil.copy(os.path.join(folder, stubs[0]), tmp)
                    passed, total = work.run_tests(tmp, sys.executable,
                                                   os.path.join(folder, "hidden"))
                self.assertGreater(total, 0)
                self.assertEqual(passed, 0)
                self.assertNotIn(name, seen, "%s is in both %s and %s" % (name, seen.get(name), base))
                seen[name] = base

    def test_there_are_enough_held_out_exercises_to_tell_versions_apart(self):
        held_out = [n for b, n, _ in folders() if b == "evals"]
        self.assertGreaterEqual(len(held_out), 8)
        self.assertEqual(work.eval_exercises(), sorted(held_out))

    def test_practice_never_picks_a_held_out_exercise(self):
        self.assertFalse(set(work.exercises()) & set(work.eval_exercises()))


class TestPracticeFailures(unittest.TestCase):
    def test_which_hidden_tests_failed_and_how_but_not_the_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "pangram.py"), "w") as h:
                h.write("def is_pangram(s):\n    return len(set(s.lower())) >= 26\n\n\n"
                        "def missing_letters(s):\n    return ''\n")
            score, failures = work.score_practice_detail(tmp, "pangram", sys.executable)
        self.assertEqual(score[1], 5)
        self.assertIn("test_missing_letters (AssertionError)", failures)
        self.assertFalse(any("defg" in f for f in failures))     # no expected values

    def test_never_for_a_held_out_exercise(self):
        with tempfile.TemporaryDirectory() as tmp:
            score, failures = work.score_practice_detail(
                tmp, work.eval_exercises()[0], sys.executable, held_out=True)
        self.assertEqual(failures, [])
        self.assertEqual(score[0], 0)


class TestContainedRun(unittest.TestCase):
    def test_a_timeout_takes_everything_the_run_started(self):
        import time
        started = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            work.contained_run([sys.executable, "-c",
                                "import subprocess, sys, time; "
                                "subprocess.Popen([sys.executable, '-c', "
                                "'import time; time.sleep(20)']); time.sleep(20)"], 1)
        self.assertLess(time.time() - started, 8)


if __name__ == "__main__":
    unittest.main()
