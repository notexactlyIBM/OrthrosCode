import os
import tempfile
import unittest

from ralph_tools import code_search


class TestCodeSearchLimit(unittest.TestCase):
    def test_limit_zero_returns_no_results(self):
        with tempfile.TemporaryDirectory() as workspace:
            path = os.path.join(workspace, "sample.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("needle one\nneedle two\nneedle three\n")
            self.assertEqual(code_search(workspace, "needle", limit=0), [])

    def test_limit_stops_after_requested_matches(self):
        with tempfile.TemporaryDirectory() as workspace:
            path = os.path.join(workspace, "big.txt")
            with open(path, "w", encoding="utf-8") as handle:
                for number in range(1, 1001):
                    handle.write("needle %d\n" % number)
            hits = code_search(workspace, "needle", limit=10)
            self.assertEqual(len(hits), 10)
            self.assertNotIn("big.txt:1000:", "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
