"""Tools a round can ask for, and the loop's memory of what went wrong.

aider cannot call a tool mid-reply, so a round asks by writing one line into
the task list and stopping; the loop answers between rounds, into a file the
next round is sent:

    RESEARCH: <question>   a web search and page fetch   -> RESEARCH.md
    FIND: <text>           every line in the project with it -> FOUND.md
    CALLERS: <function>    every line calling that function -> FOUND.md
    DEF: <name>            the line where a name is defined -> FOUND.md
    OUTLINE: <file>        every class and def line in one file -> FOUND.md
    DOCS: <module or name> the installed library's own help -> FOUND.md
    DIGEST: <file> -- <question>  a file too big for a round, read in parts -> FOUND.md

LESSONS.md is the other half: one dated line each time a round is rolled
back, rejected or parked, and the newest few are put in front of every
round -- so a mistake made at 2am is not made again at 3am.
"""

import os
import re
import subprocess
import time

from ralph_common import DIGEST_PARTS, RESEARCH_ASK, RESEARCH_FILE, read_text, say, write_text
from ralph_digest import DIGEST_ASK, digest, inside, parse_request

FIND_ASK = re.compile(r"^\s*FIND:\s*(.+?)\s*$", re.MULTILINE)
CALLERS_ASK = re.compile(r"^\s*CALLERS:\s*([A-Za-z_][\w.]*)\s*$", re.MULTILINE)
DOCS_ASK = re.compile(r"^\s*DOCS:\s*([A-Za-z_][\w.]*)\s*$", re.MULTILINE)
DEF_ASK = re.compile(r"^\s*DEF:\s*([A-Za-z_][\w.]*)\s*$", re.MULTILINE)
OUTLINE_ASK = re.compile(r"^\s*OUTLINE:\s*(.+?)\s*$", re.MULTILINE)
FOUND_FILE = "FOUND.md"
LESSONS_FILE = "LESSONS.md"
SKILLS_FILE = "SKILLS.md"

SEARCH_EXTS = (".py", ".md", ".cmd", ".bat", ".html", ".txt", ".json", ".toml", ".cfg")
SKIP_DIRS = {"venv", ".git", "__pycache__", "node_modules", "logs", ".venv"}
FIND_LIMIT = 40
DOCS_LINES = 120


# --------------------------------------------------------------------------
# code search and offline docs
# --------------------------------------------------------------------------

def code_search(workspace, text, limit=FIND_LIMIT):
    """Lines containing `text` (case-insensitive), as ['file:line: code']."""
    needle = text.lower()
    hits = []
    for folder, dirs, names in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            if not name.lower().endswith(SEARCH_EXTS) or name == FOUND_FILE:
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, workspace)
            try:
                lines = read_text(path).splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, 1):
                if needle in line.lower():
                    hits.append("%s:%d: %s" % (rel, number, line.strip()[:140]))
                    if len(hits) >= limit:
                        return hits
    return hits


def callers_search(workspace, func_name, limit=FIND_LIMIT):
    """Lines calling `func_name` (containing `func_name(`), excluding its def line."""
    needle = func_name + "("
    def_pat = re.compile(r"\bdef\s+" + re.escape(func_name) + r"\s*\(")
    hits = []
    for folder, dirs, names in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(names):
            if not fname.lower().endswith(SEARCH_EXTS) or fname == FOUND_FILE:
                continue
            path = os.path.join(folder, fname)
            rel = os.path.relpath(path, workspace)
            lines = read_text(path).splitlines()
            def_line = None
            calls = []
            for number, line in enumerate(lines, 1):
                if def_pat.search(line):
                    def_line = number
                elif needle in line:
                    calls.append((number, line))
            for number, line in calls:
                if number != def_line:
                    hits.append("%s:%d: %s" % (rel, number, line.strip()[:140]))
                    if len(hits) >= limit:
                        return hits
    return hits


def define_search(workspace, name, limit=FIND_LIMIT):
    """Lines defining `name` as a function or class, as ['file:line: code']."""
    pat = re.compile(r"^\s*(?:def|class)\s+" + re.escape(name) + r"\b")
    hits = []
    for folder, dirs, names in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(names):
            if not fname.lower().endswith(SEARCH_EXTS) or fname == FOUND_FILE:
                continue
            path = os.path.join(folder, fname)
            rel = os.path.relpath(path, workspace)
            for number, line in enumerate(read_text(path).splitlines(), 1):
                if pat.search(line):
                    hits.append("%s:%d: %s" % (rel, number, line.strip()[:140]))
                    if len(hits) >= limit:
                        return hits
    return hits


def outline_file(workspace, filename):
    """Every class and def line in one file, with line numbers, no limit."""
    filename = filename.strip().strip("`\"'").replace("\\", "/")
    path = filename if os.path.isabs(filename) else os.path.join(workspace, filename)
    if not os.path.isfile(path):
        return []
    rel = os.path.relpath(path, workspace)
    pat = re.compile(r"^\s*(?:async\s+)?(?:class|def)\s+\w+")
    return ["%s:%d: %s" % (rel, number, line.strip()[:140])
            for number, line in enumerate(read_text(path).splitlines(), 1)
            if pat.search(line)]


def library_docs(workspace, name, python, lines=DOCS_LINES):
    """`pydoc` for an installed module or name, trimmed. Offline, no model."""
    try:
        proc = subprocess.run([python, "-m", "pydoc", name], cwd=workspace,
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "pydoc failed: %s" % exc
    text = (proc.stdout or proc.stderr or "").replace("\x08", "")
    # pydoc bolds with backspaces; what is left is plain text.
    kept = [l.rstrip() for l in text.splitlines()][:lines]
    return "\n".join(kept) or "no documentation found for %s" % name


def handle_tool_requests(workspace, notes_path, python, ask=None):
    """Answer every RESEARCH:, FIND:, CALLERS:, DEF:, OUTLINE: and DOCS: line.

    Each request is replaced in the task list by a note saying where its
    answer is, so it is answered once. FIND, CALLERS, DEF, OUTLINE and DOCS
    share FOUND.md, newest first, rewritten each time so it never grows past
    one round's worth.
    """
    handled = []
    query = handle_research(workspace, notes_path)
    if query:
        handled.append("RESEARCH")
    body = read_text(notes_path)
    sections = []
    for match in list(FIND_ASK.finditer(body)):
        text = match.group(1).strip().strip("`\"'")
        hits = code_search(workspace, text) if text else []
        sections.append("## FIND: %s\n\n%s\n\n    %d match(es)\n" % (
            text, "\n".join("    " + h for h in hits) if hits else "    (nothing matches)", len(hits)))
        body = body.replace(match.group(0), "  - *Searched*: %s (see %s)" % (text, FOUND_FILE), 1)
        say("    code search: %s (%d hit(s))" % (text[:50], len(hits)))
        handled.append("FIND")
    for match in list(CALLERS_ASK.finditer(body)):
        func = match.group(1)
        hits = callers_search(workspace, func)
        sections.append("## CALLERS: %s\n\n%s\n\n    %d match(es)\n" % (
            func, "\n".join("    " + h for h in hits) if hits else "    (no callers found)", len(hits)))
        body = body.replace(match.group(0), "  - *Callers*: %s (see %s)" % (func, FOUND_FILE), 1)
        say("    callers: %s (%d hit(s))" % (func, len(hits)))
        handled.append("CALLERS")
    for match in list(DEF_ASK.finditer(body)):
        name = match.group(1)
        hits = define_search(workspace, name)
        sections.append("## DEF: %s\n\n%s\n" % (
            name, "\n".join("    " + h for h in hits) if hits else "    (no definition found)"))
        body = body.replace(match.group(0), "  - *Defined*: %s (see %s)" % (name, FOUND_FILE), 1)
        say("    definition: %s (%d hit(s))" % (name, len(hits)))
        handled.append("DEF")
    for match in list(OUTLINE_ASK.finditer(body)):
        filename = match.group(1).strip().strip("`\"'")
        lines = outline_file(workspace, filename)
        sections.append("## OUTLINE: %s\n\n%s\n" % (
            filename, "\n".join("    " + line for line in lines) if lines
            else "    (no class or def lines found)"))
        body = body.replace(match.group(0), "  - *Outlined*: %s (see %s)" % (filename, FOUND_FILE), 1)
        say("    outline: %s (%d line(s))" % (filename, len(lines)))
        handled.append("OUTLINE")
    for match in list(DOCS_ASK.finditer(body)):
        name = match.group(1)
        sections.append("## DOCS: %s\n\n%s\n" % (name, library_docs(workspace, name, python)))
        body = body.replace(match.group(0), "  - *Looked up*: %s (see %s)" % (name, FOUND_FILE), 1)
        say("    docs: %s" % name)
        handled.append("DOCS")
    for match in list(DIGEST_ASK.finditer(body)):
        name, question = parse_request(match.group(1))
        path = inside(workspace, name)
        if not path:
            answer, note = "(no such file in this folder)", "not found"
        elif not ask:
            answer, note = "(reading in parts needs the model, which is not available here)", "skipped"
        else:
            say("    reading %s in parts: %s" % (name, question[:50]))
            answer, parts, whole = digest(path, question, ask, DIGEST_PARTS)
            note = "%d part(s)%s" % (parts, "" if whole else ", only the start of it")
        sections.append("## DIGEST: %s -- %s\n\n%s\n\n    read %s\n" % (name, question, answer, note))
        body = body.replace(match.group(0), "  - *Digested*: %s (see %s)" % (name, FOUND_FILE), 1)
        handled.append("DIGEST")
    if sections:
        write_text(notes_path, body)
        write_text(os.path.join(workspace, FOUND_FILE),
                   "# Answers to FIND:, CALLERS: and DOCS: requests\n\n" + "\n".join(sections))
    return handled


def handle_research(workspace, notes_path):
    """Answer a `RESEARCH:` line with a web search. Returns the query, or ''."""
    body = read_text(notes_path)
    match = RESEARCH_ASK.search(body)
    if not match or not match.group(1).strip():
        return ""
    query = match.group(1).strip()
    say("    it asked for research: %s" % query[:66])
    here = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(workspace, RESEARCH_FILE)
    try:
        proc = subprocess.run(
            [os.path.join(here, "venv", "Scripts", "python.exe"),
             os.path.join(here, "research.py"), "--query", query, "--out", out_path],
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        ok = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok = False
        say("    research failed: %s" % exc)
    # Marked answered either way, so the loop does not ask forever.
    body = body.replace(match.group(0), "  - *Researched*: %s (see %s)"
                        % (query, RESEARCH_FILE), 1)
    write_text(notes_path, body)
    if ok:
        say("    wrote %s" % RESEARCH_FILE)
    return query


# --------------------------------------------------------------------------
# lessons
# --------------------------------------------------------------------------

def lessons_path(workspace):
    return os.path.join(workspace, LESSONS_FILE)


def record_lesson(workspace, text):
    """Append one dated line to LESSONS.md, unless the same lesson is recent.

    Kept to one line and 200 characters: these are read back into every round,
    and a paragraph per mistake would soon cost more than the mistakes.
    """
    text = " ".join(str(text).split())[:200]
    if not text:
        return False
    path = lessons_path(workspace)
    body = read_text(path)
    recent = [l.split(" ", 2)[-1] for l in body.splitlines()[-20:] if l.startswith("- ")]
    if text in recent:
        return False
    if not body:
        body = ("# Lessons\n\nOne line per mistake the loop caught: rolled back, rejected "
                "or parked. The newest are read back into every round.\n\n")
    return write_text(path, body.rstrip("\n") + "\n- %s %s\n"
                      % (time.strftime("%Y-%m-%d"), text))


def recent_lessons(workspace, count=8, task=None):
    """The newest lesson lines, oldest first.

    With `task`, lessons sharing the most words with it come first,
    newest first among equals.
    """
    lines = [l for l in read_text(lessons_path(workspace)).splitlines() if l.startswith("- ")]
    if not task:
        return lines[-count:]
    task_words = set(w.lower() for w in task.split())
    def score(line):
        return len(set(w.lower() for w in line.split()) & task_words)
    indexed = list(enumerate(lines))
    indexed.sort(key=lambda pair: (-score(pair[1]), -pair[0]))
    return [line for _, line in indexed[:count]]
