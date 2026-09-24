"""A short summary of every module, kept current: the planner's view of the whole.

ReadAgent (Lee et al., Google DeepMind, 2024) reads a long text page by page,
keeps a short gist of each page, and works from the gists -- opening a page in
full only when it needs the detail. Here a page is a module. A planning round
used to be sent whatever source fitted in 8,000 tokens, which on a project of
thirty modules is a few of them; now it also gets GISTS.md, a few lines on
every module, about 2,000 tokens for the lot.

Gists are written by the model, a few per refill (each is a request, and a
refill is already the slowest part of a session). Until a module's turn comes
its gist is the first paragraph of its docstring, marked provisional. A gist
is redone whenever its module changes.
"""

import ast
import hashlib
import os
import re

from ralph_common import read_text, write_text

GISTS_FILE = "GISTS.md"
MAX_CHARS = 24000            # of a module sent for its gist, about 6,000 tokens

GIST_PROMPT = """Below is one module of a Python project. In at most three short
lines, say what it is for, its main functions or classes, and what it works
with. Plain words. No preamble, no code.

File: %s

%s
"""

ENTRY = re.compile(r"^## (\S+)  (~?)([0-9a-f]{12})\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def fingerprint(path):
    return hashlib.sha1(read_text(path).encode("utf-8", "replace")).hexdigest()[:12]


def read_gists(path):
    """{module: (fingerprint, provisional, text)}"""
    return {m.group(1): (m.group(3), bool(m.group(2)), m.group(4).strip())
            for m in ENTRY.finditer(read_text(path))}


def docstring_gist(path):
    """The module docstring's first paragraph: a gist that costs no request."""
    try:
        doc = ast.get_docstring(ast.parse(read_text(path))) or ""
    except (SyntaxError, ValueError):
        doc = ""
    first = doc.strip().split("\n\n")[0]
    return " ".join(first.split())[:300] or "(no summary yet)"


def refresh_gists(workspace, files, ask=None, limit=6):
    """Bring GISTS.md up to date. Returns (written by the model, still provisional)."""
    path = os.path.join(workspace, GISTS_FILE)
    gists = read_gists(path)
    names = {os.path.basename(f): f for f in files if f.endswith(".py")}
    changed = False
    asked = 0
    for name in sorted(names):
        source = names[name]
        fp = fingerprint(source)
        old = gists.get(name)
        if old and old[0] == fp and not old[1]:
            continue
        text = ""
        if ask and asked < limit:
            body = read_text(source)
            if len(body) > MAX_CHARS:
                body = body[:MAX_CHARS] + "\n[... the rest of the module is not shown ...]"
            try:
                text = ask(GIST_PROMPT % (name, body)) or ""
            except Exception:
                text = ""
            asked += 1
        lines = [" ".join(l.split()) for l in text.strip().splitlines() if l.strip()][:3]
        if lines:
            gists[name] = (fp, False, "\n".join(lines))
            changed = True
        elif not old or old[0] != fp:
            gists[name] = (fp, True, docstring_gist(source))
            changed = True
    for name in [n for n in gists if n not in names]:
        del gists[name]
        changed = True
    if changed:
        body = ["# Gists: every module in a few lines", "",
                "Kept by the loop, for planning. `~` marks one not yet written by the "
                "model. Open the module itself for the detail.", ""]
        for name in sorted(gists):
            fp, provisional, text = gists[name]
            body += ["## %s  %s%s" % (name, "~" if provisional else "", fp), text, ""]
        write_text(path, "\n".join(body))
    written = sum(1 for n in names if n in gists and not gists[n][1])
    return written, len(names) - written
