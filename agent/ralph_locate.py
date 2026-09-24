"""Find the files an item is about when it does not say.

Agentless (Xia et al., 2024) localizes before it repairs: file, then function,
then line, each step a small prompt. A round here is sent the files its item
names in backticks. An item that names nothing findable in a project bigger
than the window used to be sent no source at all, and the model guessed.
Now one short request first: the item and an outline of every module --
names only, a few thousand tokens -- and the model says which files to open.
"""

import os
import re

from ralph_common import read_text

LOCATE_PROMPT = """Choose the source files a small change needs.

The change:

    %s

The project's modules, each with the functions and classes it defines:

%s

Reply with the file names to open, most important first, one per line, at
most %d. Nothing else."""

DEFINES = re.compile(r"^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+(\w+)", re.MULTILINE)
FILE_NAME = re.compile(r"[\w.-]+\.py\b")


def outline(files, per_file=40):
    """One line per module: its name and the names it defines."""
    lines = []
    for path in files:
        names = DEFINES.findall(read_text(path))
        more = " ..." if len(names) > per_file else ""
        lines.append("%s: %s%s" % (os.path.basename(path), ", ".join(names[:per_file]), more))
    return "\n".join(lines)


def locate(task, files, ask, most=3, budget=12000):
    """The files `ask` picks for `task`, within `budget` tokens. [] if it cannot say."""
    if not ask or len(files) < 2:
        return []
    try:
        reply = ask(LOCATE_PROMPT % (task, outline(files), most)) or ""
    except Exception:
        return []
    by_name = {os.path.basename(f).lower(): f for f in files}
    picked = []
    for word in FILE_NAME.findall(reply):
        path = by_name.get(word.lower())
        if path and path not in picked:
            picked.append(path)
    out, spent = [], 0
    for path in picked[:most]:
        try:
            cost = os.path.getsize(path) // 4
        except OSError:
            continue
        if out and spent + cost > budget:
            continue
        out.append(path)
        spent += cost
    return out
