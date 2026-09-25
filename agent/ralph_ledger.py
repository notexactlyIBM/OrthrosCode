"""One row per round, in SQLite: the evidence every decision here should rest on.

Until 2026-09-25 what a round did was spread across the loop's log, aider's
transcript, PROGRESS.md, FIELD_REPORT.md and LESSONS.md, in prose. "How many
rejections were sound?" and "does a warmer retry ever win?" took hours of
reading logs by hand. Here each is one query (ORTHROSCODE-IMPROVEMENTS.md, 0).

Orthros points both agents at one file, ORTHROS_LEDGER, next to the agents'
folders. On its own a session writes into the folder it works on.
"""

import hashlib
import os
import sqlite3
import time

LEDGER_FILE = ".localcoder-ledger.sqlite"

COLUMNS = (
    ("at", "REAL"),            # time.time()
    ("agent", "TEXT"),         # 'A' or 'B', who ran; '' outside Orthros
    ("workspace", "TEXT"),     # folder name: 'OrthrosCode B', a task, a practice
    ("kind", "TEXT"),          # 'self' | 'task' | 'practice'
    ("item", "TEXT"),
    ("attempt", "INTEGER"),    # rounds already spent on this item
    ("temperature", "REAL"),
    ("tokens_in", "INTEGER"),
    ("tokens_out", "INTEGER"),
    ("seconds", "REAL"),
    ("symptom", "TEXT"),       # '', 'context', 'enginedied', 'crashed', ...
    ("applied", "INTEGER"),    # edits applied
    ("failed", "INTEGER"),     # edits that did not match
    ("touched", "INTEGER"),    # code changed, after any undo
    ("broken", "TEXT"),        # first check failure, '' if none
    ("caught", "TEXT"),        # automatic-check rejection, '' if none
    ("verdict", "TEXT"),       # 'accept' | 'reject' | 'unclear' | 'skipped'
    ("reason", "TEXT"),
    ("ticked", "INTEGER"),
    ("kept", "INTEGER"),       # 1 if committed
    ("diff_sha", "TEXT"),      # sha1 of the diff, to find it again
)
SCHEMA = "CREATE TABLE IF NOT EXISTS rounds (id INTEGER PRIMARY KEY, %s)" % ", ".join(
    "%s %s" % pair for pair in COLUMNS)
NAMES = set(name for name, _ in COLUMNS)


def ledger_path(folder):
    return os.environ.get("ORTHROS_LEDGER") or os.path.join(folder, LEDGER_FILE)


def record(folder, **row):
    """Write one round. Never raises: a ledger must not be what stops a run.

    `folder` is where the ledger goes without ORTHROS_LEDGER; the row's own
    `workspace` column is just a name.
    """
    row.setdefault("at", time.time())
    diff = row.pop("diff", None)
    if diff:
        row["diff_sha"] = hashlib.sha1(diff.encode("utf-8", "replace")).hexdigest()
    keys = sorted(k for k in row if k in NAMES)
    try:
        db = sqlite3.connect(ledger_path(folder), timeout=10)
        try:
            with db:
                db.execute(SCHEMA)
                db.execute("INSERT INTO rounds (%s) VALUES (%s)"
                           % (", ".join(keys), ", ".join("?" * len(keys))),
                           [row[k] for k in keys])
        finally:
            db.close()           # `with db` commits but does not close; Windows keeps the lock
        return True
    except (sqlite3.Error, OSError):
        return False


# Where rounds go: one outcome per round, first match wins.
OUTCOMES = """SELECT CASE
         WHEN symptom != '' THEN 'lost: ' || symptom
         WHEN failed > 0 AND applied = 0 THEN 'edit did not apply'
         WHEN broken != '' THEN 'broke a check'
         WHEN caught != '' THEN 'caught by a check'
         WHEN verdict = 'reject' THEN 'rejected by reviewer'
         WHEN kept = 1 THEN 'kept'
         ELSE 'no change'
       END AS outcome, COUNT(*) AS n
FROM rounds WHERE at > ? GROUP BY outcome ORDER BY n DESC, outcome"""


def outcomes(path, since):
    """[(outcome, count)] for rounds after `since`, most common first. [] if none."""
    if not os.path.isfile(path):
        return []
    try:
        db = sqlite3.connect(path, timeout=10)
        try:
            return [tuple(r) for r in db.execute(OUTCOMES, (since,))]
        finally:
            db.close()
    except sqlite3.Error:
        return []
