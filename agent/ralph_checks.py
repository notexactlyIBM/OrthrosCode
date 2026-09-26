"""Did the round break anything? Parse it, import it, start it, look at it.

The checks for invented attributes are in ralph_inventions.py.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess

import status
from ralph_ledger import LEDGER_FILE
from ralph_common import (FILE_TOKEN_CAP, LOG_FILE, ROUND_FILE,
    TRANSCRIPT_FILE, read_text, write_text)


def health_check(files):
    """Parse every Python file we may edit. Returns [(file, error)].

    Done in memory rather than with py_compile: pointing that at os.devnull to
    avoid littering .pyc files quietly swallows the very errors we are looking
    for on Windows.
    """
    broken = []
    node = None
    for path in files:
        if not os.path.isfile(path):
            continue
        low = path.lower()
        # JavaScript gets the same first check Python does: will it parse.
        # Node ships a syntax-only mode, so this costs nothing to install and
        # runs nothing -- which is what lets the rest of the loop be pointed
        # at a JS project without every round passing on faith.
        if low.endswith((".js", ".mjs", ".cjs")):
            node = node or shutil.which("node")
            if not node:
                continue
            try:
                proc = subprocess.run([node, "--check", path], capture_output=True,
                                      text=True, timeout=30, encoding="utf-8",
                                      errors="replace")
            except (OSError, subprocess.TimeoutExpired):
                continue
            if proc.returncode != 0:
                detail = [l for l in (proc.stderr or "").splitlines() if l.strip()]
                broken.append((path, " / ".join(detail[:3])[:200] or "does not parse"))
            continue
        if not low.endswith(".py"):
            continue
        try:
            compile(read_text(path), path, "exec")
        except SyntaxError as exc:
            broken.append((path, "line %s: %s" % (exc.lineno or "?", exc.msg)))
        except ValueError as exc:
            broken.append((path, str(exc)))
    return broken


def find_entry_point(workspace, files, configured=""):
    """The script that actually starts the thing being built."""
    if configured:
        path = configured if os.path.isabs(configured) else os.path.join(workspace, configured)
        return path if os.path.isfile(path) else ""
    for path in files:
        if path.lower().endswith(".py") and "__main__" in read_text(path):
            return path
    return ""


def find_project_python(workspace):
    """The project's own interpreter if it has one, so its packages are there."""
    local = os.path.join(workspace, "venv", "Scripts", "python.exe")
    if os.path.isfile(local):
        return local
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "venv", "Scripts", "python.exe")


def smoke_run(workspace, entry, seconds=6):
    """Actually start it and see whether it stays up. Returns (ok, traceback).

    Parsing a file only proves it is grammatical. A game that calls a method
    that does not exist, or reads an attribute set nowhere, parses perfectly
    and dies the moment you double-click it -- which is the failure that
    matters and the one a syntax check waves straight through.

    Run with the dummy SDL drivers so no window opens and no sound plays.
    Surviving the whole window counts as healthy; exiting inside it does not,
    because a game loop that returns on its own has fallen over.
    """
    if not entry:
        return True, ""
    env = os.environ.copy()
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    try:
        proc = subprocess.Popen(
            [find_project_python(workspace), os.path.basename(entry)],
            cwd=os.path.dirname(entry) or workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return True, ""  # cannot test it; do not claim it is broken
    try:
        out, _ = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return True, ""
    # A clean exit with nothing printed is healthy too. Failing it (tried
    # 2026-09-24) flags every `if __name__ == "__main__": doctest.testmod()`
    # or quiet batch script as crashing on startup, and rolls back each round.
    if proc.returncode == 0:
        return True, ""
    # A non-zero exit is not the same as a crash, and treating it as one only
    # ever worked because the only program this had checked was a game, which
    # never exits by itself. A command-line tool started with no arguments
    # exits 2 and prints its usage; a script that needs an input file says so
    # and exits 1. Both are healthy, and both would have had every round
    # rolled back. What an actual startup crash always leaves is a traceback.
    if "Traceback (most recent call last)" not in (out or ""):
        return True, ""
    lines = [l for l in (out or "").splitlines() if l.strip()]
    return False, "\n".join(lines[-6:])


def code_fingerprint(files):
    """Hash of the files being worked on.

    Line counts are not good enough to tell whether a round did anything: a
    rewritten line, a renamed variable and a whole reworked function all leave
    the count untouched, and the round gets wrongly written off as dead.
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(read_text(path).encode("utf-8", "replace") if os.path.isfile(path) else b"")
    return digest.hexdigest()


def code_lines(files):
    """Total lines, for reporting how much the code grew or shrank."""
    return sum(read_text(p).count("\n") for p in files if os.path.isfile(p))


IMPORT_PROBE = r"""
import importlib, json, sys, traceback
failed = {}
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except BaseException as exc:  # SystemExit too: exiting on import is broken
        lines = traceback.format_exception_only(type(exc), exc)
        failed[name] = (lines[-1].strip() if lines else repr(exc))[:300]
print("@@IMPORTS@@" + json.dumps(failed))
"""


def _import_env():
    env = os.environ.copy()
    env.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy",
               PYGAME_HIDE_SUPPORT_PROMPT="1", MPLBACKEND="Agg")
    return env


_IMPORT_CACHE = {"fingerprint": None, "result": []}


def import_check(workspace, files, seconds=20):
    """Import every module. Returns [(file, error)] for those that fail.

    The runtime check for a project with nothing to run -- a library, a set of
    helpers, a package. Importing each module catches the failures that only
    exist when code is loaded: a missing dependency, a name imported from a
    module that does not have it, a circular import, an error in top-level code.

    One interpreter per folder, importing every module in a single -c
    expression, rather than one per module: this runs after every round, and
    starting a dozen Pythons that each load the same dependencies was most of
    what the check cost. If that one process hangs or dies without reporting,
    each module is tried on its own instead, and one that runs something long
    when imported is given the benefit of the doubt, the same as a program
    that keeps running.
    """
    fingerprint = code_fingerprint(files)
    if _IMPORT_CACHE["fingerprint"] == fingerprint:
        return list(_IMPORT_CACHE["result"])
    python = find_project_python(workspace)
    by_folder = {}
    for path in files:
        if path.endswith(".py") and not os.path.basename(path).startswith("test_")                 and os.path.isfile(path):
            folder = os.path.dirname(path) or workspace
            by_folder.setdefault(folder, []).append(path)
    broken = []
    for folder, paths in by_folder.items():
        names = {os.path.splitext(os.path.basename(p))[0]: p for p in paths}
        try:
            proc = subprocess.run([python, "-c", IMPORT_PROBE] + list(names),
                                  cwd=folder, env=_import_env(), capture_output=True,
                                  text=True, timeout=seconds + 5 * len(names),
                                  encoding="utf-8", errors="replace")
            marker = [l for l in (proc.stdout or "").splitlines() if l.startswith("@@IMPORTS@@")]
            failed = json.loads(marker[-1][len("@@IMPORTS@@"):]) if marker else None
        except (subprocess.TimeoutExpired, ValueError):
            failed = None
        except OSError:
            return []
        if failed is None:
            broken += _import_each(python, folder, paths, seconds)
            continue
        broken += [(names[n], "fails on import: " + why) for n, why in failed.items()
                   if n in names]
    _IMPORT_CACHE["fingerprint"] = fingerprint
    _IMPORT_CACHE["result"] = broken
    return broken


def _import_each(python, folder, paths, seconds):
    """The slow way, one module per interpreter, for when the fast way hung."""
    broken = []
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            proc = subprocess.run([python, "-c", "import %s" % name],
                                  cwd=folder, env=_import_env(),
                                  capture_output=True, text=True, timeout=seconds,
                                  encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            return broken
        if proc.returncode != 0 and "Traceback" in (proc.stderr or ""):
            last = [l for l in proc.stderr.splitlines() if l.strip()][-1:]
            broken.append((path, "fails on import: " + (last[0] if last else "?")))
    return broken


def full_check(workspace, files, entry, seconds=6):
    """Does it parse, and then: does it actually run? Returns [(where, what)].

    Parsing first because it is instant and a syntax error makes the run
    pointless. Only a file that parses is worth starting.
    """
    broken = health_check(files)
    if broken:
        return broken
    if not entry:
        # Nothing to start: a library. Loading every module is the runtime
        # check it has, and until now it had none.
        broken = import_check(workspace, files)
        if broken:
            return broken
    else:
        ok, trace = smoke_run(workspace, entry, seconds)
        if not ok:
            broken = [(entry or "the program", "crashes on startup:\n" + trace)]
    return broken or test_check(workspace)


def test_check(workspace, seconds=240):
    """Run the project's unittest tests. Returns [("tests", what failed)] or [].

    aider already runs them after every edit and shows the model what failed,
    inside the round -- but a round can still end with them failing, and
    nothing noticed. Here a failing test counts the same as a failing start:
    the round that caused it is rolled back.

    unittest rather than pytest because it ships with Python, and an
    unattended round cannot install anything. Only test_*.py at the top level.
    """
    try:
        names = [n for n in os.listdir(workspace) if n.startswith("test_") and n.endswith(".py")]
    except OSError:
        return []
    if not names:
        return []
    try:
        proc = subprocess.run([find_project_python(workspace), "-m", "unittest", "discover",
                               "-s", ".", "-p", "test_*.py", "-q"],
                              cwd=workspace, capture_output=True, text=True, timeout=seconds,
                              encoding="utf-8", errors="replace", env=_import_env())
    except subprocess.TimeoutExpired:
        return [("tests", "the tests did not finish in %d seconds" % seconds)]
    except OSError:
        return []
    if proc.returncode == 0:
        return []
    out = [l for l in ((proc.stderr or "") + (proc.stdout or "")).splitlines() if l.strip()]
    failing = [l for l in out if l.startswith(("FAIL:", "ERROR:"))]
    detail = ""
    test_name = ""
    if failing:
        # "FAIL: test_add (test_calc.TestCalc)" -- the method name is the
        # second token, before the parenthesised class.
        tokens = failing[0].split()
        if len(tokens) >= 2:
            test_name = tokens[1].split("(")[0].strip()
        start = out.index(failing[0])
        block = out[start + 1:]
        for line in block:
            if line.startswith(("FAIL:", "ERROR:")):
                break
            # Any exception's own line: the list of names this used to check
            # missed ZeroDivisionError, NameError and the rest.
            if EXCEPTION_LINE.match(line):
                detail = line
                break
        if not detail:
            for line in reversed(block):
                if line.startswith(("FAIL:", "ERROR:")):
                    break
                if (line and not line.startswith(("Traceback (most recent call last):", "File ",
                                                  "  File", "    File")) and not set(line) <= set("-")):
                    detail = line
                    break
    parts = []
    if test_name:
        parts.append(test_name)
    if failing:
        parts.append(failing[0])
    else:
        parts.extend(out[-3:])
    if detail:
        parts.append(detail)
    if len(failing) > 1:
        parts.append("%d more" % (len(failing) - 1))
    broken = [("tests", "tests fail: " + "; ".join(parts)[:300])]
    values = explain_failure(workspace, failing[0] if failing else "", seconds)
    if values:
        broken.append(("the values where it failed", "\n" + values))
    return broken


EXCEPTION_LINE = re.compile(
    r"^(?:[A-Za-z_][\w.]*)?(?:Error|Exception|Exit|Interrupt|Warning)\b(:|$)")
EXPLAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ralph_explain.py")


def failing_test_id(line):
    """'test_calc.TestCalc.test_add' from unittest's FAIL:/ERROR: line, or ''.

    Python 3.11 writes "FAIL: test_add (test_calc.TestCalc.test_add)"; older
    ones "FAIL: test_add (test_calc.TestCalc)".
    """
    match = re.match(r"^(?:FAIL|ERROR):\s+(\w+)\s+\(([\w.]+)\)", line or "")
    if not match:
        return ""
    method, where = match.groups()
    if where.startswith("unittest."):
        # "ERROR: test_calc (unittest.loader._FailedTest.test_calc)": the
        # module would not import. Run alone it only fails inside unittest;
        # the ImportError itself is already in the failure's own lines.
        return ""
    return where if where.endswith("." + method) else "%s.%s" % (where, method)


def explain_failure(workspace, line, seconds=60):
    """The first failing test run again alone, with the values at the failure. '' if none."""
    test_id = failing_test_id(line)
    if not test_id or not os.path.isfile(EXPLAIN):
        return ""
    try:
        proc = subprocess.run([find_project_python(workspace), EXPLAIN, test_id],
                              cwd=workspace, capture_output=True, text=True,
                              timeout=min(seconds, 60), encoding="utf-8", errors="replace",
                              env=_import_env())
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = (proc.stdout or "").strip()
    return "" if proc.returncode == 0 or not out else out


def keep_files_small(workspace, edit_files, entry, run_seconds=6):
    """Move a class out of any file that has grown too big. Returns [messages].

    The same housekeeping as trimming the task list, applied to the source.
    A file the model cannot fit alongside its own reply is a file no round can
    finish work in, and splitting it is the only cure -- on 2026-08-10 the
    prompt was taking 73% of the window and seven rounds in fourteen ran out
    of room to answer.

    Asking the model to do the move is what made it hard. The move is
    mechanical: which lines are the class, which imports it needs, what has to
    be imported back. A parser knows all of it exactly and cannot stop
    halfway. See split.py, which refuses anything it cannot prove safe and
    puts both files back if the result will not run.
    """
    try:
        import split
    except ImportError:
        return []

    def verify():
        here = [os.path.join(workspace, f) for f in os.listdir(workspace)
                if f.endswith(".py")]
        if health_check(here):
            return False
        ok, _ = smoke_run(workspace, entry, run_seconds)
        return ok

    done = []
    for path in list(edit_files):
        if not os.path.isfile(path) or not path.endswith(".py"):
            continue
        for _ in range(4):              # a few per session, not a rewrite
            if len(read_text(path)) // 4 <= FILE_TOKEN_CAP:
                break
            # Moving a file's only class, or moving a class into the file it is
            # already in, only relocates the problem. That leaves methods.
            here = os.path.splitext(os.path.basename(path))[0]
            picks = split.candidates(path)
            if len(picks) <= 1:
                picks = [p for p in picks if split._snake(p[0]) != here
                         and len(split.candidates(path)) > 1]
            if not picks:
                # Nothing can leave without dragging something with it. The
                # usual reason is settings still sitting beside the classes.
                ok, msg = split.extract_constants(path, verify=verify)
                if ok:
                    done.append(msg)
                    continue
                # Then it is one class too big on its own. Its methods can
                # still go, one at a time, each leaving a one-line stub.
                methods = split.method_candidates(path)
                if not methods:
                    done.append("%s is over %d tokens and nothing in it can move "
                                "safely -- it needs splitting by hand"
                                % (os.path.basename(path), FILE_TOKEN_CAP))
                    break
                klass, method, _ = methods[0]
                ok, msg = split.extract_method(path, klass, method, verify=verify)
                done.append(msg)
                if ok:
                    # The new module is a file to edit like any other.
                    fresh = os.path.join(os.path.dirname(path),
                                         "%s_%s.py" % (split._snake(klass), method.strip("_")))
                    if fresh not in edit_files:
                        edit_files.append(fresh)
                    continue
                break
            ok, msg = split.extract(path, picks[0][0], verify=verify)
            done.append(msg)
            if not ok:
                break
    return done


def ensure_ignored(workspace):
    """Keep our own scratch files, and the project's venv, out of the commits.

    The venv matters more than it looks. Committed, it made this workspace a
    2,243-file repo that aider itself warns about, and every round paid for
    scanning it -- for eleven files of actual project.
    """
    path = os.path.join(workspace, ".gitignore")
    body = read_text(path)
    wanted = (ROUND_FILE, LOG_FILE, TRANSCRIPT_FILE, "*.tmp",
              status.STATUS_FILE, status.STOP_FILE,
              TRANSCRIPT_FILE + ".1", "venv/", "__pycache__/", LEDGER_FILE + "*")
    missing = [p for p in wanted if p not in body]
    if not missing:
        return
    if body and not body.endswith("\n"):
        body += "\n"
    write_text(path, body + "\n".join(missing) + "\n")
