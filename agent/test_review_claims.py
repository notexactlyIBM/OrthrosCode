"""Reviewers who must cite what they object to (ORTHROSCODE-IMPROVEMENTS.md, 2).

No model: the reviewer's replies are scripted, and the loop's own checks
decide which of its claims stand.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import importlib.util
import unittest

import status
import supervisor_aider
from ralph_common import read_text, write_text
from ralph_scan import check_claims, lint
from ralph_session import Session

# A bug in the loop fails the test instead of being logged and survived: that
# is how a crash in the refill hid behind a passing suite on 2026-09-26.
os.environ.setdefault("LC_RALPH_RAISE", "1")

LIB = "import re\n\n\ndef words(text):\n    return re.findall(r\"\\w+\", text)\n"
DIFF = "+def words(text):\n+    return re.findall(r\"\\w+\", text)\n"

HAS_PYFLAKES = importlib.util.find_spec("pyflakes") is not None


def fault(kind, line, why):
    return {"kind": kind, "line": line, "why": why}


class TestParseFaults(unittest.TestCase):
    def setUp(self):
        self.real = supervisor_aider._chat

    def tearDown(self):
        supervisor_aider._chat = self.real

    def test_a_rejection_hands_back_its_cited_faults(self):
        reply = ("VERDICT: REJECT\nREASON: re is not imported\n"
                 "FAULT: undefined-name | `return re.findall(r\"\\w+\", text)` | `re` is undefined\n"
                 "\n(thinking) FAULT: undefined-name | return re.findall(r\"\\w+\", text) | again")
        supervisor_aider._chat = lambda prompt, max_tokens, timeout, temperature=0.1: (reply, "stop")
        faults = []
        verdict, _ = supervisor_aider.review_change("count words", DIFF, faults=faults)
        self.assertEqual(verdict, "reject")
        self.assertEqual(faults, [fault("undefined-name", 'return re.findall(r"\\w+", text)',
                                        "`re` is undefined")])

    def test_the_prompt_lists_the_kinds(self):
        self.assertIn("undefined-name", supervisor_aider.REVIEW_PROMPT)
        self.assertNotIn("KINDS", supervisor_aider.REVIEW_PROMPT)


class TestCheckClaims(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.lib = os.path.join(self.dir, "lib.py")
        write_text(self.lib, LIB)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def check(self, *faults, lint_now=frozenset()):
        return check_claims(list(faults), "count words\n" + DIFF, [self.lib], lint_now)

    def test_a_name_imported_above_the_diff_is_not_undefined(self):
        kept, dropped = self.check(fault("undefined-name", 'return re.findall(r"\\w+", text)',
                                         "`re` is never imported"))
        self.assertEqual(kept, [])
        self.assertIn("`re` is defined", dropped[0][1])

    def test_a_name_pyflakes_also_calls_undefined_stands(self):
        claim = fault("undefined-name", 'return re.findall(r"\\w+", text)', "`re` is undefined")
        kept, _ = self.check(claim, lint_now={"lib.py: undefined name 're'"})
        self.assertEqual(kept, [claim])

    def test_a_quote_that_is_not_there_is_dropped(self):
        kept, dropped = self.check(fault("logic-error", "return len(text.split())",
                                         "counts spaces"))
        self.assertEqual(kept, [])
        self.assertIn("not in the change", dropped[0][1])

    def test_what_cannot_be_checked_is_kept(self):
        short = fault("does-not-do-the-item", "re", "it does not count")
        unchecked = fault("undefined-name", 'return re.findall(r"\\w+", text)', "`re`")
        self.assertEqual(self.check(short)[0], [short])
        self.assertEqual(self.check(unchecked, lint_now=None)[0], [unchecked])

    @unittest.skipIf(lint([__file__]) is None, "pyflakes is not installed")
    def test_real_pyflakes_output_confirms_a_real_undefined_name(self):
        write_text(self.lib, "def words(text):\n    return re.findall(r\"\\w+\", text)\n")
        claim = fault("undefined-name", 'return re.findall(r"\\w+", text)', "`re` is undefined")
        self.assertEqual(self.check(claim, lint_now=lint([self.lib]))[0], [claim])


FAKE = r'''import sys
args = sys.argv[1:]
files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
body = open(files[0]).read()
open(files[0], "w").write(body.replace("- [ ]", "- [x]", 1))
for f in files[1:]:
    if f.endswith(".py"):
        open(f, "a").write("\n\ndef count(text):\n    return len(words(text))\n")
print("Tokens: 1k sent, 100 received.")
'''


class TestTheLoopWeighsClaims(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.join(self.dir, "ws")
        os.makedirs(self.ws)
        self.fake = os.path.join(self.dir, "fake.py")
        write_text(self.fake, FAKE)
        self.notes = os.path.join(self.ws, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] In `count` (lib.py), count the words\n")
        self.lib = os.path.join(self.ws, "lib.py")
        write_text(self.lib, LIB)
        status._path = None

    def tearDown(self):
        status._path = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_with(self, faults, why="bad"):
        def review(task, diff, context="", notes=(), faults=None):
            faults.extend(cited)
            return "reject", why
        cited = faults
        s = Session([sys.executable, self.fake], self.ws, os.environ.copy(), minutes=3,
                    single_shot=True, edit_files=[self.lib], entry_hint="none",
                    iteration_timeout=30, review=review, rollback=lambda: True)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run()
        return s

    @unittest.skipUnless(HAS_PYFLAKES, "the lint checks need pyflakes (it comes with flake8)")
    def test_a_rejection_on_refuted_claims_keeps_the_change(self):
        s = self.run_with([fault("undefined-name", "return len(words(text))",
                                 "`words` is not defined")])
        self.assertEqual((s.accepted, s.rejected), (1, 0))
        self.assertIn("reviewer's claim dropped", read_text(
            os.path.join(self.ws, ".localcoder-ralph.log")))

    def test_a_rejection_that_cites_nothing_still_stands(self):
        s = self.run_with([])
        self.assertEqual((s.accepted, s.rejected), (0, 1))

    def test_a_cited_fault_that_holds_rejects_with_the_quote(self):
        s = self.run_with([fault("logic-error", "return len(words(text))",
                                 "counts words twice")])
        self.assertEqual(s.rejected, 1)
        self.assertIn("Reviewer rejected it: logic-error -- `return len(words(text))`",
                      read_text(os.path.join(self.ws, ".localcoder-ralph.log")))


if __name__ == "__main__":
    unittest.main()
