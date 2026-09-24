"""Read a file too big for one window, in parts: `DIGEST: <file> -- <question>`.

Chain-of-Agents (Zhang et al., Google, 2024): workers read a long input one
chunk at a time, each passing its notes to the next, and a manager answers
from the last notes. One request at a time, so it suits one card; slow, but
nothing is too long to read. Used for transcripts, logs, big modules --
anything a round needs to know about and cannot be sent whole.

Recursive Language Models (Zhang, Kraska and Khattab, 2025) go further, having
the model write code to search the text; that means running code the model
wrote, which the unattended loop does not do.
"""

import os
import re

from ralph_common import read_text

DIGEST_ASK = re.compile(r"^\s*DIGEST:\s*(.+?)\s*$", re.MULTILINE)
PART_CHARS = 20000           # about 5,000 tokens a part, with room for the notes
MAX_PART_CHARS = 28000

WORKER = """You are reading a long file in parts to answer a question.

Question: %s

Notes so far, from the parts before this one:
%s

Part %d of %d of %s:
----
%s
----

Rewrite the notes: keep what helps answer the question, add what this part
adds, drop the rest. Quote exact names, numbers and error messages. At most
250 words. Reply with the notes only."""

MANAGER = """Question: %s

Notes taken while reading all of %s, part by part:
%s

Answer the question from the notes in at most 200 words. If the notes do not
hold the answer, say so plainly."""


def parse_request(text):
    """('file', 'question') from 'file -- question' or 'file | question'."""
    for sep in (" -- ", " | "):
        if sep in text:
            name, question = text.split(sep, 1)
            return name.strip().strip("`\"'"), question.strip()
    return text.strip().strip("`\"'"), "What does this contain that matters here?"


def inside(workspace, name):
    """The file's path if it is inside the workspace, else ''."""
    root = os.path.realpath(workspace)
    path = os.path.realpath(os.path.join(root, name))
    return path if path.startswith(root + os.sep) and os.path.isfile(path) else ""


def split_parts(text, most, size=PART_CHARS):
    """Whole lines, in parts of about `size` characters -- fewer, larger ones
    if there would be more than `most`. Returns (parts, whether it all fitted)."""
    size = min(MAX_PART_CHARS, max(size, len(text) // max(1, most) + 1))
    parts, current = [], []
    length = 0
    for line in text.splitlines(True):
        if current and length + len(line) > size:
            parts.append("".join(current))
            current, length = [], 0
        current.append(line[:size])
        length += len(current[-1])
    if current:
        parts.append("".join(current))
    return parts[:most], len(parts) <= most


def digest(path, question, ask, most=12):
    """(answer, parts read, whether the whole file was read)."""
    parts, whole = split_parts(read_text(path), most)
    name = os.path.basename(path)
    notes = "(none yet)"
    for number, part in enumerate(parts, 1):
        try:
            notes = (ask(WORKER % (question, notes, number, len(parts), name, part))
                     or notes).strip()
        except Exception:
            continue
    try:
        answer = (ask(MANAGER % (question, name, notes)) or "").strip()
    except Exception:
        answer = ""
    return answer or notes, len(parts), whole
