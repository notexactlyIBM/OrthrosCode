"""Catch bad edits without asking the model: every check here costs no tokens.

The reviewer is one careful reader with a small window and the same blind
spots as the author. These checks are the other kind of reader -- exact,
tireless and cheap -- run over the whole project after every round:

    lint        pyflakes over every file, compared with before the round, so
                a rename that breaks a caller in another module is caught
    calls       calls to the project's own functions with arguments the
                function does not take -- the usual break after a signature
                change -- also compared with before the round
    lazy edits  "rest of the code unchanged" and its cousins, where the model
                wrote a placeholder instead of the code it was replacing
    markers     merge-conflict lines left in a file
    tests       tests deleted, or assertions taken out, in a test file
    deletions   a file cut by more than half when the item said nothing of it

Each finding is `(kind, message)`: kind "reject" undoes the round like a
rejection by the reviewer, with the message written under the item; kind
"warn" is passed to the reviewer as evidence. Every check prefers missing
something to crying wolf: a false alarm costs a good round.

One slip is put right instead of reported (put_main_last): a test class
added below `if __name__ == "__main__":`.
"""

import ast
import os
import re
import subprocess
import sys

from ralph_common import read_text

# pyflakes messages that mean the code is wrong, not merely untidy.
SERIOUS = ("undefined name", "may be undefined", "referenced before assignment",
           "redefinition of unused", "syntax error", "invalid syntax",
           "import * used", "unexpected indent", "is not defined")

LAZY = re.compile(r"^\+\s*(#|//)\s*(\.\.\.|…)?\s*(the\s+)?(rest|remainder|remaining|existing|other|"
                  r"previous|unchanged|same as before|keep)\b.*\b(code|unchanged|as before|"
                  r"implementation|methods|functions|lines|logic|here|same)\b", re.I)
ELLIPSIS_ONLY = re.compile(r"^\+\s*(\.\.\.|…)\s*$")
MARKER = re.compile(r"^(<{7}|>{7}|={7})( |$)", re.M)


# ---------------------------------------------------------------- lint

def lint(files, python=None):
    """{'file: message'} from pyflakes, without line numbers so they compare
    across edits. None when pyflakes is not available."""
    py = [f for f in files if f.endswith(".py") and os.path.isfile(f)]
    if not py:
        return set()
    try:
        proc = subprocess.run([python or sys.executable, "-m", "pyflakes"] + py,
                              capture_output=True, text=True, timeout=120,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    if "No module named pyflakes" in out:
        return None
    found = set()
    for line in out.splitlines():
        match = re.match(r"(.+?):\d+:(?:\d+:?)?\s*(.+)$", line.strip())
        if match:
            found.add("%s: %s" % (os.path.basename(match.group(1)), match.group(2).strip()))
    return found


# ---------------------------------------------------------------- calls

def _signatures(trees):
    """{function name: (min positional, max positional or None, keyword names or None)}
    for module-level functions defined once in the project."""
    seen, sigs = {}, {}
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen[node.name] = seen.get(node.name, 0) + 1
                args = node.args
                positional = [a.arg for a in args.posonlyargs + args.args]
                required = len(positional) - len(args.defaults)
                most = None if args.vararg else len(positional)
                names = None if args.kwarg else set(positional[len(args.posonlyargs):]
                                                    + [a.arg for a in args.kwonlyargs])
                kw_required = {a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults)
                               if d is None}
                sigs[node.name] = (required, most, names, kw_required)
    return {name: sig for name, sig in sigs.items() if seen[name] == 1}


def call_mismatches(files):
    """{'file: call to f(...) ...'} -- calls that the called function cannot accept."""
    trees = {}
    for path in files:
        if path.endswith(".py") and os.path.isfile(path):
            try:
                trees[path] = ast.parse(read_text(path))
            except (SyntaxError, ValueError):
                continue
    sigs = _signatures(trees)
    modules = {os.path.splitext(os.path.basename(p))[0] for p in trees}
    found = set()
    for path, tree in trees.items():
        # Only names this file defines, or imports from the project itself:
        # a library's `join` is not the project's `join`.
        known = {n.name: n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in modules:
                known.update({a.asname or a.name: a.name for a in node.names})
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in known):
                continue
            sig = sigs.get(known[node.func.id])
            if not sig or any(isinstance(a, ast.Starred) for a in node.args) \
                    or any(k.arg is None for k in node.keywords):
                continue
            required, most, names, kw_required = sig
            given = len(node.args)
            keywords = {k.arg for k in node.keywords}
            where = os.path.basename(path)
            if most is not None and given > most:
                found.add("%s: %s() given %d positional arguments, takes at most %d"
                          % (where, node.func.id, given, most))
            if names is not None:
                for unknown in sorted(keywords - names):
                    found.add("%s: %s() has no argument called %s"
                              % (where, node.func.id, unknown))
            if given + len(keywords) < required:
                found.add("%s: %s() needs %d arguments, given %d"
                          % (where, node.func.id, required, given + len(keywords)))
            for missing in sorted(kw_required - keywords):
                found.add("%s: %s() needs the keyword argument %s"
                          % (where, node.func.id, missing))
    return found


def baseline(files, python=None):
    """What is already wrong before a round, so only what the round adds counts."""
    return {"lint": lint(files, python), "calls": call_mismatches(files)}


# ---------------------------------------------------------------- the diff

def _files_in_diff(diff):
    """{file: (added lines, removed lines)} from a unified diff."""
    out, current = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[4:].strip()
            current = current[2:] if current.startswith("b/") else current
            out.setdefault(current, ([], []))
        elif line.startswith("NEW FILE "):
            current = None
        elif current and line.startswith("+") and not line.startswith("+++"):
            out[current][0].append(line)
        elif current and line.startswith("-") and not line.startswith("---"):
            out[current][1].append(line)
    return out


def diff_findings(diff, task):
    findings = []
    for name, (added, removed) in _files_in_diff(diff).items():
        base = os.path.basename(name)
        lazy = [l for l in added if LAZY.match(l) or ELLIPSIS_ONLY.match(l)]
        if lazy and removed:
            findings.append(("reject", "%s: a placeholder was written where code was removed "
                             "(%s) -- write the code out in full" % (base, lazy[0][1:].strip()[:60])))
        if base.startswith("test_"):
            lost = (sum(1 for l in removed if re.match(r"-\s*def test_", l))
                    - sum(1 for l in added if re.match(r"\+\s*def test_", l)))
            asserts = (sum(1 for l in removed if re.search(r"\bassert", l))
                       - sum(1 for l in added if re.search(r"\bassert", l)))
            if lost > 0:
                findings.append(("reject", "%s: %d test(s) deleted -- never delete or weaken a "
                                 "test to get a change through" % (base, lost)))
            elif asserts > 0 and not re.search(r"\btest", task or "", re.I):
                findings.append(("reject", "%s: %d assertion(s) taken out of the tests"
                                 % (base, asserts)))
        if len(removed) > 30 and len(removed) > 3 * max(1, len(added)) \
                and base.lower() not in (task or "").lower():
            findings.append(("warn", "%s: %d lines removed and %d added, and the item does not "
                             "name the file" % (base, len(removed), len(added))))
    return findings


def marker_findings(files):
    return [("reject", "%s: a merge-conflict marker is left in the file" % os.path.basename(f))
            for f in files if os.path.isfile(f) and MARKER.search(read_text(f))]


# ---------------------------------------------------------------- main last

DIFF_FILE = re.compile(r"^(?:\+\+\+ b/|NEW FILE )(.+?):?\s*$", re.M)


def _main_guard(node):
    """Is this top-level statement `if __name__ == "__main__":`?"""
    test = getattr(node, "test", None)
    return (isinstance(node, ast.If) and isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def main_block_last(path):
    """Put a file's `if __name__ == "__main__":` block back at its end.

    A class added below the block still runs under `unittest discover`, which
    is how the tests run here, but not when the file is run by hand -- and on
    2026-09-24 the reviewers sent back three rounds for it. Moving the block
    is mechanical, so it is done here for nothing instead of costing a round.
    Extra copies of the block go; blocks that differ are left for a reader.
    Line endings are kept as they were. True if the file changed.
    """
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            body = handle.read()
        tree = ast.parse(body)
    except (OSError, SyntaxError, ValueError):
        return False
    guards = [node for node in tree.body if _main_guard(node)]
    if not guards or (len(guards) == 1 and tree.body[-1] is guards[0]):
        return False
    # Split on "\n" alone, as the parser counts lines: splitlines() also
    # breaks at form feeds and the like, and would cut the wrong lines.
    lines = body.split("\n")
    blocks = ["\n".join(lines[g.lineno - 1:g.end_lineno]).strip() for g in guards]
    if len(set(blocks)) > 1:
        return False
    for guard in reversed(guards):
        del lines[guard.lineno - 1:guard.end_lineno]
    eol = "\r\n" if "\r\n" in body else "\n"
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("\n".join(lines).rstrip() + eol * 3 + blocks[-1] + eol)
    except OSError:
        return False
    return True


def put_main_last(files, diff):
    """main_block_last for each test file this round's diff touches. Returns those moved."""
    touched = {os.path.basename(name) for name in DIFF_FILE.findall(diff or "")}
    return [f for f in files if os.path.basename(f).startswith("test_")
            and os.path.basename(f) in touched and main_block_last(f)]


# ---------------------------------------------------------------- all of it

def scan(files, diff, task, before, python=None):
    """Everything the round broke that the checks can see: [(kind, message)]."""
    findings = marker_findings(files) + diff_findings(diff, task)
    now = lint(files, python)
    if now is not None and before.get("lint") is not None:
        for message in sorted(now - before["lint"]):
            serious = any(s in message.lower() for s in SERIOUS)
            findings.append(("reject" if serious else "warn", "lint: " + message))
    for message in sorted(call_mismatches(files) - (before.get("calls") or set())):
        findings.append(("reject", "call: " + message))
    return findings
