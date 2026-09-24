"""Every way a session can end says why.

A session that ends without a reason reads, in the summary and in Orthros's
field report, like one that finished its work. Two refill branches did
exactly that -- `return False` with no `self.stop(...)` -- and the reports
said "ended: finished" for sessions that had given up half-way.

This reads the loop's source rather than running it: in each method that
returns False to stop, every `return False` must follow a `self.stop(...)`
in the same block, or sit under an `if` that asks another such method (which
is then checked itself). Add a new way to stop and this holds you to it.
"""

import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ("ralph_session.py", "ralph_refill.py", "ralph_outcome.py", "ralph_report.py")


def _calls_self_method(node):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
               for n in ast.walk(node))


def _is_stop(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "stop"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == "self")


def silent_exits(func):
    """Line numbers of `return False` with no reason given before them."""
    found = []

    def walk(stmts, delegated):
        stopped = False
        for stmt in stmts:
            if _is_stop(stmt):
                stopped = True
            if (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is False and not (stopped or delegated)):
                found.append(stmt.lineno)
            if isinstance(stmt, ast.If):
                walk(stmt.body, delegated or _calls_self_method(stmt.test))
                walk(stmt.orelse, delegated)
            elif isinstance(stmt, (ast.For, ast.While, ast.With)):
                walk(stmt.body, delegated)
            elif isinstance(stmt, ast.Try):
                walk(stmt.body, delegated)
                for handler in stmt.handlers:
                    walk(handler.body, delegated)
                walk(stmt.finalbody, delegated)

    walk(func.body, False)
    return found


def stopping_methods(path):
    """Methods whose docstring says they return False to stop."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            doc = ast.get_docstring(node) or ""
            if "False to stop" in doc or node.name in ("step", "work_round"):
                yield node


class TestStopPaths(unittest.TestCase):
    def test_every_stop_says_why(self):
        checked, silent = 0, []
        for name in MODULES:
            for func in stopping_methods(os.path.join(HERE, name)):
                checked += 1
                silent += ["%s:%d in %s" % (name, line, func.name)
                           for line in silent_exits(func)]
        self.assertGreater(checked, 5)
        self.assertEqual(silent, [], "these end a session without self.stop(reason)")

    def test_the_check_catches_a_silent_exit(self):
        func = ast.parse("def f(self):\n    if x:\n        return False\n").body[0]
        self.assertEqual(silent_exits(func), [3])
        func = ast.parse("def f(self):\n    self.stop('why')\n    return False\n").body[0]
        self.assertEqual(silent_exits(func), [])


if __name__ == "__main__":
    unittest.main()
