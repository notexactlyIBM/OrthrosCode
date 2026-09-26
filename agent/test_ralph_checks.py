"""Tests for ralph_checks.smoke_run."""

import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


class TestSmokeRun(unittest.TestCase):
    def test_a_quiet_clean_exit_is_healthy(self):
        """doctest.testmod() prints nothing when every example passes."""
        from ralph_checks import smoke_run
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "quiet.py")
            with open(script, "w") as f:
                f.write('def add(a, b):\n    """\n    >>> add(1, 2)\n    3\n    """\n'
                        '    return a + b\n\n\nif __name__ == "__main__":\n'
                        '    import doctest\n    doctest.testmod()\n')
            with mock.patch("ralph_checks.find_project_python", return_value=sys.executable):
                ok, msg = smoke_run(tmp, script, seconds=5)
            self.assertTrue(ok, msg)

    def test_a_traceback_is_a_crash(self):
        from ralph_checks import smoke_run
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "broken.py")
            with open(script, "w") as f:
                f.write("undefined_name()\n")
            with mock.patch("ralph_checks.find_project_python", return_value=sys.executable):
                ok, msg = smoke_run(tmp, script, seconds=5)
            self.assertFalse(ok)
            self.assertIn("NameError", msg)

    def test_normal_exit_is_healthy(self):
        """A script that exits 0 and prints something is healthy."""
        from ralph_checks import smoke_run
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "hello.py")
            with open(script, "w") as f:
                f.write("print('hello')\n")
            with mock.patch("ralph_checks.find_project_python", return_value=sys.executable):
                ok, msg = smoke_run(tmp, script, seconds=5)
            self.assertTrue(ok)


import subprocess

import ralph_checks


class TestImportCheckSingleCall(unittest.TestCase):
    def test_three_files_one_subprocess(self):
        """Three files in the same folder produce exactly one subprocess.run call."""
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name in ("alpha.py", "beta.py", "gamma.py"):
                path = os.path.join(tmp, name)
                with open(path, "w") as f:
                    f.write("x = 1\n")
                files.append(path)

            # Reset the cache so the fingerprint check does not short-circuit.
            ralph_checks._IMPORT_CACHE["fingerprint"] = None

            fake_result = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='@@IMPORTS@@{}\n', stderr="")

            with mock.patch("ralph_checks.contain.run", return_value=fake_result) as mock_run:
                ralph_checks.import_check(tmp, files)

            self.assertEqual(mock_run.call_count, 1,
                             "expected exactly 1 subprocess.run call for 3 same-folder files")


class TestFailuresExplained(unittest.TestCase):
    def test_the_values_at_the_failure_come_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "calc.py"), "w") as f:
                f.write("def total(prices):\n    subtotal = sum(prices)\n"
                        "    discount = subtotal // 10\n    return subtotal - discount\n")
            with open(os.path.join(tmp, "test_calc.py"), "w") as f:
                f.write("import unittest\nfrom calc import total\n\n\n"
                        "class TestTotal(unittest.TestCase):\n"
                        "    def test_total(self):\n"
                        "        basket = [30, 45, 25]\n"
                        "        self.assertEqual(total(basket), 100)\n")
            with mock.patch("ralph_checks.find_project_python", return_value=sys.executable):
                broken = ralph_checks.test_check(tmp)
        self.assertEqual(broken[0][0], "tests")
        self.assertIn("90 != 100", broken[0][1])
        where, values = broken[1]
        self.assertIn("basket = [30, 45, 25]", values)

    def test_a_passing_suite_explains_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "test_ok.py"), "w") as f:
                f.write("import unittest\n\n\nclass T(unittest.TestCase):\n"
                        "    def test_ok(self):\n        pass\n")
            with mock.patch("ralph_checks.find_project_python", return_value=sys.executable):
                self.assertEqual(ralph_checks.test_check(tmp), [])

    def test_test_ids_from_both_pythons(self):
        self.assertEqual(ralph_checks.failing_test_id(
            "FAIL: test_add (test_calc.TestCalc.test_add)"), "test_calc.TestCalc.test_add")
        self.assertEqual(ralph_checks.failing_test_id(
            "ERROR: test_add (test_calc.TestCalc)"), "test_calc.TestCalc.test_add")
        self.assertEqual(ralph_checks.failing_test_id("nonsense"), "")
        self.assertEqual(ralph_checks.failing_test_id(
            "ERROR: test_calc (unittest.loader._FailedTest.test_calc)"), "")

    def test_any_exception_line_is_the_detail(self):
        for line in ("Exception: bad input", "ZeroDivisionError: x", "KeyError: 'a'",
                     "calc.PriceError: negative"):
            self.assertTrue(ralph_checks.EXCEPTION_LINE.match(line), line)
        for line in ("Errors are bad", "FAILED (errors=1)", "Traceback (most recent call last):"):
            self.assertFalse(ralph_checks.EXCEPTION_LINE.match(line), line)


if __name__ == "__main__":
    unittest.main()
