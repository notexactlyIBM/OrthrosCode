"""Run one failing test and print the values at the point it failed.

Run as: python ralph_explain.py test_mod.Class.test_name, from the project's
folder. When a round breaks a test, the next round was told only the error
line -- "AssertionError: 3 != 4". Self-Debugging (Chen et al., 2023) found
models fix code far better when shown what the code did: the values, not
only the message. The standard library can print every local in every frame
of a traceback, so this is free (ORTHROSCODE-IMPROVEMENTS.md, item 9).
"""

import os
import sys
import traceback
import unittest

MOST = 2500          # characters: under a thousand tokens in the next prompt
WIDEST = 160         # a local's repr can be a whole list; its line is cut here
UNITTEST = os.path.dirname(os.path.abspath(unittest.__file__))


class LocalsResult(unittest.TestResult):
    explained = ""

    def _explain(self, err):
        if not self.explained:
            tbe = traceback.TracebackException(*err, capture_locals=True)
            # The project's frames only -- the test and the code it called --
            # and the three innermost of those. unittest's own frames are
            # half the text and none of the answer.
            ours = [f for f in tbe.stack if UNITTEST not in os.path.abspath(f.filename)]
            tbe.stack = traceback.StackSummary.from_list(ours[-3:])
            lines = "".join(tbe.format()).splitlines()
            self.explained = "\n".join(l if len(l) <= WIDEST else l[:WIDEST] + " ..."
                                       for l in lines)[-MOST:]

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._explain(err)

    def addError(self, test, err):
        super().addError(test, err)
        self._explain(err)


def explain(test_id):
    """The failure with its values, or '' if the test passes or cannot be loaded."""
    sys.path.insert(0, os.getcwd())      # the project, not this file's folder
    result = LocalsResult()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    except Exception as exc:              # a module that will not import says so itself
        return "%s: %s" % (type(exc).__name__, exc)
    suite.run(result)
    return result.explained


def main(argv):
    text = explain(argv[1]) if len(argv) > 1 else ""
    print(text or "passed")
    return 1 if text else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
