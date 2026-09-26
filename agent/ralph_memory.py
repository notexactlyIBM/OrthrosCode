"""How similar items were done here: past kept rounds, found by BM25.

LESSONS.md holds one line per mistake. What a small model uses best is an
example: a similar item, and the change that was kept for it. ExpeL retrieves
past successes as examples at inference time and reports steady gains with
no training (ORTHROSCODE-IMPROVEMENTS.md, item 6).

Every kept round is a commit whose message names its item ("Item: ..."), so
the folder's own git history is the memory: it survives sessions, rollbacks
keep what was kept before them, and nothing else has to be written. Search is
BM25 over item text and the names in it -- no embedding model, nothing more
on the card -- and the diff is read from git only for the few that are shown.
"""

import math
import re
import subprocess
from collections import Counter

from ralph_common import _env_flag

EXAMPLES = _env_flag("LC_RALPH_EXAMPLES", True)
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
ITEM_LINE = re.compile(r"^Item: (.+)$", re.MULTILINE)
COMMIT_TITLE = "LocalCoder ralph: round"
HISTORY = 400                  # kept rounds read back per session
SHOWN = 2                      # examples per round
DIFF_CHARS = 1500              # per example: two are ~800 tokens of a 32k window
LEAST_SCORE = 2.0              # below this a match is a shared common word, not a similar item


def tokens(text):
    """Words, lower case, with snake_case and CamelCase names also split."""
    out = []
    for word in TOKEN.findall(text or ""):
        out.append(word.lower())
        out += [p.lower() for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", word) if len(p) > 2]
    return out


class Index:
    """BM25 over short documents: [(key, text)]."""

    def __init__(self, docs=()):
        self.keys, self.tf, self.len = [], [], []
        for key, text in docs:
            self.add(key, text)

    def add(self, key, text):
        counts = Counter(tokens(text))
        self.keys.append(key)
        self.tf.append(counts)
        self.len.append(sum(counts.values()))

    def search(self, query, k=SHOWN, k1=1.2, b=0.75):
        """[(score, key)], best first, scores above zero only."""
        n = len(self.keys)
        if not n:
            return []
        avg = sum(self.len) / float(n) or 1.0
        df = Counter(w for counts in self.tf for w in counts)
        scores = []
        for i, counts in enumerate(self.tf):
            s = 0.0
            for w in set(tokens(query)):
                if w in counts:
                    idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                    f = counts[w]
                    s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / avg))
            if s > 0:
                scores.append((s, self.keys[i]))
        return sorted(scores, reverse=True)[:k]


def _git(workspace, *args):
    try:
        proc = subprocess.run(["git", "-C", workspace] + list(args), capture_output=True,
                              text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def git_head(workspace):
    return _git(workspace, "rev-parse", "HEAD").strip()


def kept_rounds(workspace, limit=HISTORY):
    """[(commit, item)] for the kept rounds in the folder's history, newest first."""
    out = _git(workspace, "log", "-n", str(limit), "--grep=^%s" % COMMIT_TITLE,
               "--format=%H%x1f%B%x1e")
    rounds = []
    for record in out.split("\x1e"):
        sha, _, body = record.strip().partition("\x1f")
        item = ITEM_LINE.search(body)
        if sha and item:
            rounds.append((sha, item.group(1).strip()))
    return rounds


def commit_diff(workspace, sha, chars=DIFF_CHARS):
    """The source change a commit made -- not the notes -- trimmed to `chars`."""
    diff = _git(workspace, "show", "--format=", "--unified=2", sha, "--",
                "*.py", "*.js", "*.ts", "*.html", "*.css")
    if len(diff) > chars:
        diff = diff[:chars] + "\n[... cut ...]"
    return diff.strip()


class Memory:
    """The examples a session can show, built once and added to as rounds are kept."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.items = {}
        self.index = Index()
        for sha, item in reversed(kept_rounds(workspace)):
            self.remember(sha, item)

    def remember(self, sha, item):
        if sha and item and sha not in self.items:
            self.items[sha] = item
            self.index.add(sha, item)

    def similar(self, task, k=SHOWN):
        """[(item, diff)] of the most similar kept rounds on other items."""
        found = []
        for score, sha in self.index.search(task, k=k + 3):
            item = self.items[sha]
            if score < LEAST_SCORE or item == task or any(i == item for i, _ in found):
                continue
            diff = commit_diff(self.workspace, sha)
            if diff:
                found.append((item, diff))
            if len(found) >= k:
                break
        return found


def examples_note(examples):
    """The prompt section for them, or ''."""
    if not examples:
        return ""
    fence = "`" * 3
    lines = ["# How similar items were done here", "",
             "Changes kept for items like this one. Examples, not instructions: do this",
             "item, in the code as it is now.", ""]
    for item, diff in examples:
        lines += ["Item: %s" % item, "", fence + "diff", diff, fence, ""]
    return "\n".join(lines)
