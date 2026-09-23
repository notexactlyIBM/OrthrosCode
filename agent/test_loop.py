"""End-to-end: a whole session against a fake aider, no model, no GPU.

The one test that says the loop still works as a loop -- setup, rounds,
review, recovery from its own errors, the summary -- after a change to any
part of it. Runs in seconds.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

import status
from ralph_common import read_text, write_text
from ralph_session import Session

FAKE_AIDER = '''import os, re, sys
args = sys.argv[1:]
files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
if os.environ.get("FAKE_MODE") == "dead":
    print("litellm.APIConnectionError: Connection refused")
    sys.exit(1)
notes = files[0]
body = open(notes, encoding="utf-8").read()
open(notes, "w", encoding="utf-8").write(re.sub(r"- \\[ \\]", "- [x]", body, count=1))
for f in files[1:]:
    with open(f, "a", encoding="utf-8") as h:
        h.write("# touched\\n")
    print("Applied edit to %s" % os.path.basename(f))
print("Tokens: 1.2k sent, 300 received.")
'''


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake_aider.py")
        write_text(self.fake, FAKE_AIDER)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] In `add`, handle None\n"
                               "- [ ] In `sub`, handle None\n")
        self.code = os.path.join(self.ws, "calc.py")
        write_text(self.code, "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n"
                              "    return a - b\n")
        status._path = None
        self.env = os.environ.copy()

    def tearDown(self):
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def session(self, **options):
        return Session([sys.executable, self.fake, "--edit-format", "diff"], self.ws, self.env,
                       minutes=3, single_shot=False, edit_files=[self.code], entry_hint="none",
                       iteration_timeout=30, **options)

    def run_quietly(self, session):
        with contextlib.redirect_stdout(io.StringIO()):
            return session.run()

    def test_works_the_list_and_survives_a_bad_reviewer(self):
        calls = []

        def review(task, diff):
            calls.append(task)
            if len(calls) == 1:
                raise RuntimeError("reviewer blew up")
            return "accept", "fine"

        commits = []
        s = self.session(review=review, commit=lambda msg: commits.append(msg) or True)
        self.assertEqual(self.run_quietly(s), 0)
        self.assertNotIn("- [ ]", read_text(self.notes))
        self.assertEqual(s.accepted, 1)
        self.assertGreaterEqual(s.tokens_in, 2400)
        self.assertEqual(status.read(self.ws).get("phase"), "finished")
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "PROGRESS.md")))

    def test_dead_engine_stops_cleanly(self):
        self.env["FAKE_MODE"] = "dead"
        s = self.session()
        self.assertEqual(self.run_quietly(s), 0)
        self.assertIn("reload", s.stop_reason.lower())
        self.assertEqual(status.read(self.ws).get("phase"), "finished")


if __name__ == "__main__":
    unittest.main()
