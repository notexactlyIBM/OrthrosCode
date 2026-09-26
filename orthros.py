"""Orthros -- two coders, each improving the other, taking turns on one GPU.

    OrthrosCode A works on B's source.  Then B works on A's.  Forever.

One model, one card, so only one of them runs at a time. Between turns Orthros
hands the model over: the finished agent shuts down and unloads it, anything it
left running is killed, and only then is the other one started.

What makes it safe to leave running:

    rollback   If an agent will not start after the other has worked on it,
               it goes back to the last version that did, and the reason is
               written onto the task list the other one reads.
    proof      An agent that starts and works well has proven the changes the
               other made to it. Those are then carried into the other agent
               as well, so a good idea ends up in both.
    balance    Turns alternate, and each turn's length leans towards evening
               out the time and tokens the two have had.

Standard library only, so it keeps working whatever the agents do to their
own code and their own venvs.

    python orthros.py              the orchestrator and its page (port 8770)
    python orthros.py --simulate   the same, on two fake agents in a temp folder
"""

import argparse
import ctypes
import http.server
import json
import math
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser

import orthros_tune as tune
import orthros_work as work

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ("A", "B")
PEER = {"A": "B", "B": "A"}

DEFAULTS = {
    "session_minutes": 60,       # a turn's length before balancing nudges it
    "first": "A",                # who goes first on a fresh start
    "port": 8770,
    "launch_minutes": 20,        # to get from starting to its first round
    "grace_minutes": 30,         # past the planned end before asking it to stop
    "pause_after_idle": 4,       # sessions in a row with nothing kept; 0 = never
    # Install an agent's changed requirements.txt into its own venv layer
    # before its turn. Off by default: it downloads from PyPI whatever the
    # other agent wrote there, and a small model can invent package names
    # that someone has registered maliciously. The shared base and the twin
    # are never touched either way.
    "install_requirements": False,
    # Windows counts every byte a program may need -- including the system
    # memory the driver commits to back video memory -- against one limit. A
    # 27B model can put that limit within reach on 32 GB, and when it is
    # reached Windows kills whatever asks next: the engine, an agent, or
    # Orthros itself. So: do not start a turn with less than this much of the
    # limit free, and end a turn early rather than be killed during one.
    "min_free_mb": 4096,
    "critical_free_mb": 1536,
    # Load orthros_guard\sitecustomize.py into the agents' Pythons: aider may
    # not pull files into a round past what the window holds, nor send a
    # prompt the window cannot take. See that file for why.
    "aider_guard": True,
    # Turns in a row that end on the same item without progress before
    # Orthros parks that item (`- [!]`), so the next turn does not die on it
    # too. 0 = never.
    "park_after_tries": 2,
    # A start that fails because of the machine -- LM Studio not up, the card
    # busy -- is tried again after these many minutes before Orthros gives up.
    "env_retry_minutes": [2, 5, 15],
    # Do not start a turn with less free disk than this (logs, git, models).
    "min_free_disk_mb": 2048,
    "keep_logs": 300,            # turn logs kept in logs\, newest first
    "gpu_telemetry": True,       # poll nvidia-smi for the page's GPU view
    # In self-improvement mode, every this many turns of an agent's, one is a
    # practice exercise instead: a small job it has never seen, scored by
    # tests it never sees, so "better" is measured on coding in general.
    # 0 = never.
    "practice_every": 4,
    "practice_minutes": 20,
    # Proof by score (ORTHROSCODE-IMPROVEMENTS.md, item 3). Starting and doing
    # some work proves a version is not broken, not that it is better. Every
    # `eval_every` good turns, an agent's version works through the first
    # `eval_count` held-out exercises in evals\, `eval_minutes` each, and is
    # compared exercise by exercise with the last version that passed. Until
    # it passes, the changes in it do not reach the twin; if it does worse,
    # it goes back to that version. 8 exercises at 8 minutes is about an
    # hour and a half with model loads, every 4 good turns.
    "prove_by_score": True,
    "eval_every": 4,
    "eval_count": 8,
    "eval_minutes": 8,
    # Fit context and timeouts to the machine, from what each turn measures
    # (see orthros_tune.py). The agents' config.cmd holds the starting point.
    "auto_tune": True,
}
# Files an agent may edit in a task or a practice: any project, not just Python.
PROJECT_FILES = "*.py;*.js;*.mjs;*.cjs;*.ts;*.tsx;*.jsx;*.html;*.css"

GUARD_DIR = os.path.join(HERE, "orthros_guard")
# Written when Orthros gives up and needs a person; removed on Start. The
# page shows it too, and Windows beeps: a surrender nobody hears is a night
# of a machine doing nothing.
ALERT_FILE = "ORTHROS-NEEDS-YOU.txt"
LOG_CAP = 20 * 1024 * 1024           # orthros.log is rotated past this
GUARD_REFUSED = "Orthros guard: prompt too big"

# The task list, plan and ledger an agent keeps about the one it works on.
# They live in the folder being worked on but belong to the worker, so a
# rollback of the code keeps them, and they are never carried across.
# STOPS.md was missing and the 2026-09-25 export copied one into agent\;
# LESSONS.summary.md is written by fold_old_lessons from that day on.
MEMORY_FILES = ("orthros_tasks.md", "janus_tasks.md", "PLAN.md", "PROGRESS.md", "PROGRESS.old.md", "DONE.md",
                "BRIEF.md", "CONVENTIONS.md", "RALPH_PROMPT.md", "RESEARCH.md",
                "LESSONS.md", "LESSONS.summary.md", "STOPS.md", "FOUND.md", "FIELD_REPORT.md",
                "ROLLBACK.md", "GISTS.md")
FIELD_REPORT = "FIELD_REPORT.md"
# One row per round from both agents (agent/ralph_ledger.py). Read here with
# its own query, not by importing the agents' code, which they rewrite.
LEDGER = "ledger.sqlite"
ROUND_OUTCOMES = """SELECT CASE
         WHEN symptom != '' THEN 'lost: ' || symptom
         WHEN failed > 0 AND applied = 0 THEN 'edit did not apply'
         WHEN broken != '' THEN 'broke a check'
         WHEN caught != '' THEN 'caught by a check'
         WHEN verdict = 'reject' THEN 'rejected by reviewer'
         WHEN kept = 1 THEN 'kept'
         ELSE 'no change'
       END AS outcome, COUNT(*) AS n
FROM rounds WHERE agent = ? AND at >= ? GROUP BY outcome ORDER BY n DESC, outcome"""
ROLLBACK_NOTE = "ROLLBACK.md"
DIFF_NOTE_CHARS = 8000               # of the undone diff written into ROLLBACK.md

# How a turn ends when nothing went wrong. Anything else, well short of its
# time, is an early stop -- and becomes the twin's first job.
NORMAL_ENDS = ("Time is up", "Stopped from the dashboard", "Stopped by hand",
               "Single round", "Every item is ticked")
PROVEN_KEPT = 20                     # proven versions remembered per agent

# Start-up failures that are the machine's fault, not the code's. Stepping
# back through proven versions cannot fix these, so Orthros pauses instead.
ENV_SIGNS = ("Could not find LM Studio", "server never came up", "card is shared",
             "Could not load '", "No model is loaded", "The model did not answer",
             "aider is not installed")

# Every module must import before a turn is worth a model load.
PREFLIGHT_IMPORTS = r'''import glob, importlib, os, sys
bad = []
for path in sorted(glob.glob("*.py")):
    name = os.path.splitext(path)[0]
    if name.startswith("test_"):
        continue
    try:
        importlib.import_module(name)
    except BaseException as exc:
        bad.append("%s: %s: %s" % (name, type(exc).__name__, exc))
print("\n".join(bad))
sys.exit(1 if bad else 0)
'''

# What the field report counts in a turn's output: (label, phrase).
FIELD_SIGNS = (
    ("unexpected errors in the loop", "LocalCoder hit an unexpected error"),
    ("rounds lost to the engine", "engine stopped answering"),
    ("edits that did not apply", "did not match the file"),
    ("replies cut off", "was cut off at the ceiling"),
    ("replies that outgrew the window", "outgrew the context window"),
    ("prompts too big to answer", "prompt alone is taking most of the window"),
    ("rounds that broke start-up", "That round broke it"),
    ("items parked", "Parked"),
    ("invented attributes caught", "Invented "),
    # A prompt the window cannot hold comes back from LM Studio as a 400 that
    # aider words as a connection error, so it was counted above as the
    # engine dying -- and the twin went looking for an engine problem.
    ("requests refused as too big for the window (aider retries each)",
     "exceeds the available context size"),
    ("files pulled into a round because a reply named them",
     "it's best to only add files that need changes"),
    ("prompts the guard kept from being sent", GUARD_REFUSED),
    ("files the guard kept out of a round", "Orthros guard: not adding"),
    ("bad edits stopped by the automatic checks", "An automatic check rejected it"),
    ("changes a second look at the diff found a bug in", "a second look found"),
)
OVERSIZE = re.compile(r"request \((\d+) tokens\) exceeds the available context size "
                      r"\((\d+) tokens\)")
NOTES_FILES = ("orthros_tasks.md", "janus_tasks.md")


def notes_file(folder):
    """The task list an agent keeps about this folder, under either name."""
    for name in NOTES_FILES:
        if os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return os.path.join(folder, NOTES_FILES[0])


OPEN_ITEM = re.compile(r"^[ \t]*[-*][ \t]*\[ \][ \t]*(.+?)[ \t]*$", re.MULTILINE)
DONE_ITEM = re.compile(r"^[ \t]*[-*][ \t]*\[[xX]\][ \t]*(.+?)[ \t]*$", re.MULTILINE)
PARKED_ITEM = re.compile(r"^[ \t]*[-*][ \t]*\[!\]", re.MULTILINE)
TASKS_HEADING = re.compile(r"^##[ \t]+Tasks[ \t]*\n", re.MULTILINE)


def park_item(path, item, reason):
    """Mark one open item `- [!]`, the way the agents park their own. True if it was there."""
    body = read_text(path)
    match = re.search(r"^([ \t]*[-*][ \t]*)\[ \]([ \t]*%s[ \t]*)$" % re.escape(item), body,
                      re.MULTILINE)
    if not match:
        return False
    body = (body[:match.start()] + match.group(1) + "[!]" + match.group(2)
            + "\n  - *Parked by Orthros*: " + reason + body[match.end():])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return True


def add_first(path, text):
    """Put one open item at the top of the `## Tasks` section -- the next round takes it.

    The end of the list when there is no such heading. Nothing when there is
    no task list at all: an agent that keeps none is not one to steer.
    """
    body = read_text(path)
    if not body:
        return False
    line = "- [ ] %s\n" % " ".join(text.split())
    match = TASKS_HEADING.search(body)
    if match:
        spot = match.end()
        while body[spot:spot + 1] == "\n":
            spot += 1
        body = body[:spot] + line + ("\n" if body[spot:spot + 1] not in ("-", "*") else "") \
            + body[spot:]
    else:
        body = body.rstrip() + "\n\n" + line
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return True


STATUS_FILE = ".localcoder-status.json"
STOP_FILE = ".localcoder-stop"
MANAGED_MARKER = ".localcoder-managed"
LAUNCHED = {"ready", "planning", "researching", "working", "checking", "reviewing",
            "engine down", "finished", "locating", "summarising"}

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def adopt_old_name(root, new, old):
    """Keep using what is already there: a machine set up under the old name
    has its state and settings in files called janus*, and losing them would
    mean losing which versions have proven themselves."""
    fresh, stale = os.path.join(root, new), os.path.join(root, old)
    if not os.path.isfile(fresh) and os.path.isfile(stale):
        try:
            os.replace(stale, fresh)
        except OSError:
            return stale
    return fresh


def agent_folder(root, name):
    """An agent's folder. New setups are OrthrosCode A and B; a machine set up
    when the project was called JanusCoder keeps those folder names."""
    for pattern in ("OrthrosCode %s", "JanusCoder %s"):
        folder = os.path.join(root, pattern % name)
        if os.path.isdir(folder):
            return folder
    return os.path.join(root, "OrthrosCode %s" % name)


def now():
    return time.time()


def clock_left(seconds):
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def clock(ts=None):
    return time.strftime("%H:%M", time.localtime(ts or now()))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def tail(path, lines=40):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 64 * 1024))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [l.rstrip() for l in text.splitlines() if l.strip()][-lines:]


# --------------------------------------------------------------------------
# processes
# --------------------------------------------------------------------------

_k32 = ctypes.windll.kernel32 if os.name == "nt" else None


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    """(free commit MiB, free RAM MiB, % in use), or None off Windows.

    Free commit is the number that matters: it is what Windows refuses new
    allocations against, and llama.cpp's "bad allocation" is what a refusal
    looks like from inside the engine.
    """
    if _k32 is None:
        return None
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not _k32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return (int(status.ullAvailPageFile / 1048576), int(status.ullAvailPhys / 1048576),
            int(status.dwMemoryLoad))


def pid_alive(pid):
    if not pid:
        return False
    if _k32 is None:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = _k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = _k32.GetExitCodeProcess(handle, ctypes.byref(code))
    _k32.CloseHandle(handle)
    return bool(ok) and code.value == 259                  # STILL_ACTIVE


GPU_QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def gpu_reading():
    """The first card's state from nvidia-smi, or None. Only numbers it reports.

    utilization.gpu is the share of the last sample period in which a kernel
    was running -- how busy the card is, not a count of cores in use; no
    tool reports that per core.
    """
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=" + GPU_QUERY,
                               "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    cells = [c.strip() for c in proc.stdout.strip().splitlines()[0].split(",")]

    def num(text):
        try:
            return float(text)
        except ValueError:
            return None

    if len(cells) < 6:
        return None
    return {"name": cells[0], "util": num(cells[1]), "mem_used": num(cells[2]),
            "mem_total": num(cells[3]), "temp": num(cells[4]), "power": num(cells[5])}


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def read_from(path, offset, limit=65536):
    """(text, next offset) from byte `offset`, whole lines only, escapes removed."""
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read(limit)
    except OSError:
        return "", offset
    if len(chunk) == limit and b"\n" in chunk:
        chunk = chunk[:chunk.rindex(b"\n") + 1]
    text = ANSI.sub("", chunk.decode("utf-8", "replace")).replace("\r", "")
    return text, offset + len(chunk)


def kill_tree(pid):
    if not pid or not pid_alive(pid):
        return
    if os.name != "nt":
        # Off Windows there is no taskkill; --simulate runs there, and a force
        # stop used to take Orthros down with FileNotFoundError.
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                   capture_output=True, timeout=60)


def processes_under(folder):
    """PIDs of Python and aider processes whose command line names this folder.

    Only those images: an editor or a file browser open on the folder is the
    operator's, and killing it would be a poor way to free a GPU.
    """
    if os.name != "nt":
        return []
    needle = os.path.normcase(os.path.abspath(folder))
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe' "
              "or Name='aider.exe'\" | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=60,
                             encoding="utf-8", errors="replace").stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        pid, _, cmd = line.partition("\t")
        if pid.strip().isdigit() and needle in os.path.normcase(cmd) \
                and int(pid) != os.getpid():
            found.append(int(pid))
    return found


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def git(folder, *args, timeout=300):
    try:
        proc = subprocess.run(["git", "-C", folder, "-c", "user.name=Orthros",
                               "-c", "user.email=orthros@localhost"] + list(args),
                              capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, ((proc.stdout or "") + (proc.stderr or "")).strip()


def head(folder):
    ok, out = git(folder, "rev-parse", "HEAD")
    return out.strip() if ok else ""


def commit_all(folder, message):
    """Commit everything and return HEAD. A clean tree just returns HEAD."""
    git(folder, "add", "-A")
    ok, out = git(folder, "status", "--porcelain")
    if ok and out.strip():
        git(folder, "commit", "-q", "-m", message)
    return head(folder)


def short(sha):
    return (sha or "")[:7]


def sign_test(wins, losses):
    """One-sided p-value that `wins` against `losses` (ties dropped) is chance."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2.0 ** n


def compare_scores(child, parent, alpha=0.2):
    """(wins, losses, not_worse) of `child` against `parent`, both
    {exercise: [passed, total]}, on the exercises both were scored on.

    Paired and by exercise, because one exercise is a large share of so few:
    a win is a larger share of its hidden tests passed. "Not worse" is the bar
    for proof, and deliberately loose -- to stop real regressions, not to
    demand significance from a handful of samples. Four losses and no wins in
    eight is a regression; two and none is not yet.
    """
    def share(score):
        return score[0] / float(score[1]) if score and score[1] else 0.0
    common = [e for e in child if e in parent]
    wins = sum(1 for e in common if share(child[e]) > share(parent[e]))
    losses = sum(1 for e in common if share(child[e]) < share(parent[e]))
    return wins, losses, losses <= wins or sign_test(losses, wins) > alpha


def score_totals(scores):
    """(exercises fully passed, exercises, hidden tests passed, hidden tests)."""
    full = sum(1 for p, t in scores.values() if t and p == t)
    return (full, len(scores), sum(p for p, _ in scores.values()),
            sum(t for _, t in scores.values()))


# --------------------------------------------------------------------------
# the orchestrator
# --------------------------------------------------------------------------

class Orthros:

    def __init__(self, root, simulate=False):
        self.root = root
        self.simulate = simulate
        self.folders = {n: agent_folder(root, n) for n in NAMES}
        self.logs = os.path.join(root, "logs")
        os.makedirs(self.logs, exist_ok=True)
        self.state_path = adopt_old_name(root, ".orthros-state.json", ".janus-state.json")
        self.settings_path = adopt_old_name(root, "orthros.json", "janus.json")
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.settings = dict(DEFAULTS)
        self.settings.update(read_json(self.settings_path, {}) or {})
        if not os.path.isfile(self.settings_path):
            write_json(self.settings_path, self.settings)
        self.state = read_json(self.state_path) or {}
        self.state.setdefault("agents", {})
        for n in NAMES:
            a = self.state["agents"].setdefault(n, {})
            for key, value in (("practice", []), ("tasks", []), ("since_practice", 0),
                               ("good", ""), ("goods", []), ("good_failures", 0),
                               ("pending", []), ("seconds", 0), ("tokens", 0),
                               ("sessions", 0), ("kept", 0), ("launch_failures", 0),
                               ("rollbacks", 0), ("carried_in", 0), ("weak_streak", 0),
                               ("last", {}), ("scored", {}), ("scored_good", ""),
                               ("since_eval", 0), ("proven_pending", [])):
                a.setdefault(key, value)
        for n in NAMES:
            a = self.state["agents"][n]
            if a["good"] and not a["goods"]:
                a["goods"] = [a["good"]]
        self.state.setdefault("events", [])
        self.state.setdefault("next", self.settings["first"])
        self.state.setdefault("idle_streak", 0)
        self.state.setdefault("tries", {})       # "<folder>|<item>": turns that died on it
        self.state.setdefault("directions", [])  # the operator's, waiting for a safe moment
        self.state.setdefault("chat", [])
        self.state.setdefault("mode", "self")    # "self": improve itself; "task": a project
        self.state.setdefault("task", "")        # the task's key under tasks\
        self.state["paused"] = True          # never resume unattended on restart
        self.state.setdefault("running", None)
        stale = self.state["running"]
        if stale and not pid_alive(stale.get("pid")):
            # It finished while Orthros was not looking; its peer is next. The
            # turn itself is judged when Orthros is started -- dropping it here
            # used to lose its proof, and the changes it made never carried over.
            self.state["unjudged"] = stale
            self.state["running"] = None
            self.state["next"] = PEER[stale["agent"]]
        self.phase, self.message = "idle", ""
        self.stop_mode = ""                  # "", "pause", "now", "force"
        self.proc = None
        self.backoff_until = 0               # a machine failure's wait before retrying
        self.gpu = None                      # the latest nvidia-smi reading, for the page
        self.tuner = tune.Tuner(root)
        self.gpu_history = []

    # ---------------------------------------------------------------- state

    def save(self):
        with self.lock:
            write_json(self.state_path, self.state)

    def event(self, text, kind="info"):
        with self.lock:
            self.state["events"] = (self.state["events"] + [[now(), text, kind]])[-60:]
            self.save()
        line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
        path = os.path.join(self.root, "orthros.log")
        try:
            if os.path.getsize(path) > LOG_CAP:
                os.replace(path, path + ".1")
        except OSError:
            pass
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass
        print(line, end="", flush=True)

    def set_phase(self, phase, message=""):
        self.phase, self.message = phase, message

    def agent(self, name):
        return self.state["agents"][name]

    # ---------------------------------------------------------------- setup

    def prepare_folders(self):
        """Both agents must exist, be git repos, and let the other commit."""
        for n in NAMES:
            folder = self.folders[n]
            if not os.path.isdir(os.path.join(folder, ".git")):
                raise RuntimeError("%s is not a git repository" % folder)
            marker = os.path.join(folder, MANAGED_MARKER)
            if not os.path.isfile(marker):
                with open(marker, "w", encoding="utf-8") as handle:
                    handle.write("Looked after by Orthros: the other agent commits and rolls back "
                                 "here.\n")
            work.ensure_better(folder)       # the mission says what "better" is measured by
            sha = commit_all(folder, "Orthros: snapshot before orchestration")
            if not self.agent(n)["goods"]:
                # The baseline: the version everything started from, kept for
                # good as the last place to retreat to.
                self.agent(n)["goods"] = [sha]
                self.agent(n)["good"] = sha
                git(folder, "tag", "-f", "orthros/baseline", sha)
        self.save()

    def agent_env(self, name, workspace=None, kind="self", tuned=True):
        folder, target = self.folders[name], workspace or self.folders[PEER[name]]
        env = os.environ.copy()
        for line in read_text(os.path.join(folder, "config.cmd")).splitlines():
            match = re.match(r'\s*set\s+"([A-Z0-9_]+)=(.*)"\s*$', line, re.I)
            if match:
                value = match.group(2).replace("%~dp0", folder + os.sep)
                env[match.group(1)] = os.path.normpath(os.path.expandvars(value)) \
                    if "%~dp0" in match.group(2) else os.path.expandvars(value)
        env.update(LC_WORKSPACE=target, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   LC_UNLOAD_ON_EXIT="1", LC_STOP_SERVER_ON_EXIT="1",
                   ORTHROS_LEDGER=os.path.join(self.root, LEDGER), ORTHROS_AGENT=name,
                   ORTHROS_KIND=kind)
        if tuned and self.settings.get("auto_tune", True):
            env.update({k: str(v) for k, v in self.tuner.settings().items() if k.startswith("LC_")})
        if kind != "self":
            # Someone else's project: whatever it is written in, and started
            # after each round if it has an entry point.
            env.update(LC_RALPH_FILES=PROJECT_FILES, LC_RALPH_RUN="")
        if self.settings.get("aider_guard", True) and os.path.isdir(GUARD_DIR):
            env["PYTHONPATH"] = os.pathsep.join(p for p in (GUARD_DIR, env.get("PYTHONPATH"))
                                                if p)
            env["ORTHROS_AIDER_GUARD"] = "1"
        return env

    @staticmethod
    def is_mine(status, running):
        """Is this status file from the session Orthros started?

        By the token Orthros hands the session, or failing that by its start
        time. Not by process id: a venv's python.exe is a small launcher that
        runs the real interpreter as a child, so the id the agent reports is
        never the one Orthros started.
        """
        if not status or not running:
            return False
        if running.get("token") and status.get("session") == running["token"]:
            return True
        return (status.get("started") or 0) >= running.get("started", 0) - 2

    def python_for(self, name):
        path = os.path.join(self.folders[name], "venv", "Scripts", "python.exe")
        return path if os.path.isfile(path) else sys.executable

    # ---------------------------------------------------------------- one turn

    def plan_minutes(self, name):
        """This turn's length: the setting, leaning towards a 50/50 split.

        Time behind the other is added (or time ahead taken off), and the
        result is scaled by how the two compare in tokens. Held within half
        and one and a half times the setting, so balancing is a nudge and a
        turn is never trivially short or unreasonably long.
        """
        base = float(self.settings["session_minutes"])
        me, other = self.agent(name), self.agent(PEER[name])
        minutes = base + (other["seconds"] - me["seconds"]) / 60.0
        if me["tokens"] and other["tokens"]:
            minutes *= max(0.75, min(1.25, other["tokens"] / float(me["tokens"])))
        return int(max(base * 0.5, min(base * 1.5, minutes)))

    def prune_logs(self):
        """Keep the newest turn logs; a run of weeks would otherwise fill the disk."""
        keep = int(self.settings.get("keep_logs") or 0)
        try:
            names = sorted(f for f in os.listdir(self.logs) if f.endswith(".log"))
        except OSError:
            return
        for name in (names[:-keep] if keep else []):
            try:
                os.remove(os.path.join(self.logs, name))
            except OSError:
                pass

    def configured(self):
        """The agents' own settings, before any tuning: the starting point."""
        env = self.agent_env("A", tuned=False)
        return {k: env[k] for k in ("LC_CONTEXT", "LC_RALPH_MAX_OUTPUT", "LC_RALPH_API_TIMEOUT",
                                    "LC_RALPH_ITER_TIMEOUT", "LC_MODEL_KEY") if env.get(k)}

    def maybe_look(self, force=""):
        """Look at the hardware if there is a reason to: see orthros_tune.py."""
        if not self.settings.get("auto_tune", True) or self.simulate:
            return
        card = (self.gpu.get("name"), int(self.gpu.get("mem_total") or 0)) if self.gpu else None
        reason = force or self.tuner.due(card)
        if not reason:
            return
        current = self.configured()
        why = self.tuner.look(self.find_lms("A"), current.get("LC_MODEL_KEY", ""), current)
        look = self.tuner.data["look"]
        self.event("looked at the hardware (%s): %s, %d GB of video memory, %d GB of memory%s"
                   % (reason, look.get("gpu") or "no NVIDIA card found",
                      (look.get("vram_mb") or 0) // 1024, (look.get("ram_mb") or 0) // 1024,
                      ("; " + "; ".join(why)) if why else ""))

    def tune_after(self, result):
        if not self.settings.get("auto_tune", True) or self.simulate:
            return
        note = self.tuner.after_turn(read_text(result.get("log") or ""), result["launched"],
                                     self.configured())
        if note:
            self.event("settings: " + note)

    def next_work(self, name):
        """What this turn is for: {kind, folder, label, exercise}.

        Task mode: the chosen task, for both agents in turn. Self mode: the
        twin's code -- except every `practice_every` turns, a practice.
        """
        if self.state.get("mode") == "task":
            folder = work.task_folder(self.root, self.state.get("task"))
            if folder:
                return {"kind": "task", "folder": folder, "label": self.state["task"]}
        me = self.agent(name)
        every = int(self.settings.get("practice_every") or 0)
        if every and me.get("since_practice", 0) >= every:
            exercise = work.next_exercise(me.get("practice") or [])
            if exercise:
                return {"kind": "practice", "exercise": exercise, "label": exercise,
                        "folder": work.start_practice(self.root, name, exercise)}
        return {"kind": "self", "folder": self.folders[PEER[name]], "label": PEER[name]}

    @staticmethod
    def describe(work_):
        return {"task": "the task %s" % work_["label"],
                "practice": "the practice exercise %s" % work_["label"],
                "eval": "held-out exercise %s, to score its version" % work_["label"]}.get(
                    work_["kind"], "%s's code" % work_["label"])

    def launch(self, name, minutes, token, work_=None):
        self.prune_logs()
        folder = self.folders[name]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = os.path.join(self.logs, "%s-%s.log" % (stamp, name))
        if self.simulate:
            cmd = [sys.executable, os.path.abspath(__file__), "--fake-agent",
                   "--minutes", str(minutes)]
        else:
            cmd = [self.python_for(name), "supervisor.py", "--loop", "--minutes", str(minutes)]
        work_ = work_ or {}
        env = self.agent_env(name, work_.get("folder"), work_.get("kind", "self"))
        env["ORTHROS_SESSION"] = env["JANUS_SESSION"] = token
        log = open(log_path, "ab")
        try:
            proc = subprocess.Popen(cmd, cwd=folder, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
                                    if os.name == "nt" else 0)
        finally:
            log.close()
        return proc, log_path

    def run_turn(self, name, work_=None):
        """One agent's session -- on its twin, a task or a practice -- from launch
        to handover. Returns the result dict it also records."""
        for n in NAMES:                      # whatever either agent did to its config
            self.fix_workspace_line(n)
        self.apply_directions(from_loop=True)   # before the commits, so they are kept
        work_ = work_ or self.next_work(name)
        peer = work_["folder"]
        own_sha = commit_all(self.folders[name], "Orthros: %s as it starts its turn" % name)
        pre = commit_all(peer, "Orthros: before %s works on it" % name)
        self.install_requirements(name)
        for leftover in (STOP_FILE,):
            try:
                os.remove(os.path.join(peer, leftover))
            except OSError:
                pass
        minutes = (int(self.settings.get("practice_minutes") or 20) if work_["kind"] == "practice"
                   else int(self.settings.get("eval_minutes") or 8) if work_["kind"] == "eval"
                   else self.plan_minutes(name))
        token = "%s-%d" % (name, int(now() * 1000))
        started = now()
        proc, log_path = self.launch(name, minutes, token, work_)
        self.proc = proc
        running = {"agent": name, "pid": proc.pid, "started": started, "minutes": minutes,
                   "log": log_path, "own": own_sha, "pre": pre, "token": token,
                   "workspace": peer, "kind": work_["kind"], "label": work_["label"],
                   "exercise": work_.get("exercise", "")}
        with self.lock:
            self.state["running"] = running
            self.save()
        self.set_phase("running", "%s is working on %s" % (name, self.describe(work_)))
        self.event("%s started: %d minutes on %s (version %s)"
                   % (name, minutes, self.describe(work_), short(own_sha)), "start")

        launched, stop_sent = False, False
        speed = 20.0 if self.simulate else 1.0          # simulated minutes pass fast
        critical = int(self.settings.get("critical_free_mb") or 0)
        starved, lowest = 0, None
        while proc.poll() is None:
            st = read_json(os.path.join(peer, STATUS_FILE), {}) or {}
            if self.is_mine(st, running) and st.get("phase") in LAUNCHED:
                if not launched:
                    self.event("%s is up and working" % name, "good")
                launched = True
            elapsed = (now() - started) * speed / 60.0
            if not launched and elapsed > self.settings["launch_minutes"]:
                self.event("%s did not reach its first round in %d minutes"
                           % (name, self.settings["launch_minutes"]), "bad")
                kill_tree(proc.pid)
                break
            reading = None if self.simulate else memory()
            if reading:
                lowest = reading[0] if lowest is None else min(lowest, reading[0])
                starved = starved + 1 if critical and reading[0] < critical else 0
                if starved == 3 and not stop_sent:
                    self.event("only %d MB of memory left; asking %s to stop after this round "
                               "before Windows starts killing things" % (reading[0], name), "bad")
                    self.request_stop(peer)
                    stop_sent = True
            late = elapsed > minutes + self.settings["grace_minutes"]
            if (self.stop_mode in ("now", "force") or late) and not stop_sent:
                self.request_stop(peer)
                stop_sent = True
                if late:
                    self.event("%s is past its time; asked it to stop after this round" % name)
            if self.stop_mode == "force" or elapsed > minutes + self.settings["grace_minutes"] + 20:
                kill_tree(proc.pid)
                break
            self.wake.wait(2)
            self.wake.clear()
        code = proc.poll()
        seconds = now() - started
        st = read_json(os.path.join(peer, STATUS_FILE), {}) or {}
        if not self.is_mine(st, running):
            st = {}
        self.set_phase("handover", "releasing the model")
        self.release(name)
        post = commit_all(peer, "Orthros: after %s's turn" % name)
        score = None
        failures = []
        if work_["kind"] in ("practice", "eval"):
            score, failures = work.score_practice_detail(peer, work_["exercise"],
                                                         self.python_for(name),
                                                         held_out=work_["kind"] == "eval")
        elif work_["kind"] == "task":
            score = work.run_tests(peer, self.python_for(name))
        result = {
            "agent": name, "started": started, "seconds": int(seconds), "exit": code,
            "lowest_free_mb": lowest,
            "launched": launched, "rounds": st.get("rounds", 0) or 0,
            "ticked": st.get("ticked", 0) or 0, "kept": st.get("accepted", 0) or 0,
            "sent_back": st.get("rejected", 0) or 0,
            "tokens": (st.get("tokens_in", 0) or 0) + (st.get("tokens_out", 0) or 0),
            "reason": st.get("ended_reason") or "", "log": log_path,
            "own": own_sha, "pre": pre, "post": post,
            "item": st.get("item") or "", "minutes": minutes,
            "kind": work_["kind"], "label": work_["label"], "folder": peer,
            "exercise": work_.get("exercise", ""),
            "score": list(score) if score else None, "failures": failures,
        }
        with self.lock:
            self.state["running"] = None
            self.save()
        self.proc = None
        return result

    def install_requirements(self, name):
        """If the twin changed this agent's requirements.txt, install it -- into
        this agent's own venv layer only. See "install_requirements" above."""
        if self.simulate or not self.settings.get("install_requirements"):
            return
        req = os.path.join(self.folders[name], "requirements.txt")
        body = read_text(req)
        me = self.agent(name)
        if not body or body == me.get("requirements", ""):
            return
        try:
            proc = subprocess.run([self.python_for(name), "-m", "pip", "install", "-q",
                                   "--disable-pip-version-check", "-r", req],
                                  cwd=self.folders[name], capture_output=True, text=True,
                                  timeout=900, encoding="utf-8", errors="replace")
            ok = proc.returncode == 0
            out = (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok, out = False, str(exc)
        if ok:
            me["requirements"] = body
            self.event("installed %s's changed requirements into its own venv" % name, "good")
        else:
            self.event("could not install %s's requirements: %s"
                       % (name, " ".join(out.split())[-160:]), "bad")
        self.save()

    def request_stop(self, folder):
        try:
            with open(os.path.join(folder, STOP_FILE), "w", encoding="utf-8") as handle:
                handle.write("stop requested by Orthros at %s\n" % time.ctime())
        except OSError:
            pass

    def release(self, name):
        """Free the model and the card for the other agent.

        The agent's own shutdown already unloads the model and stops the
        server. This does it again from outside, because the agent that just
        ran may have been left broken by the other -- and a model still
        resident is the one thing that guarantees the next start fails.
        """
        folder = self.folders[name]
        if not self.simulate:
            try:
                subprocess.run([self.python_for(name), "supervisor.py", "--stop"], cwd=folder,
                               env=self.agent_env(name), capture_output=True, timeout=240,
                               stdin=subprocess.DEVNULL,
                               creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            except (OSError, subprocess.TimeoutExpired):
                pass
            lms = self.find_lms(name)
            if lms:
                for args in (["unload", "--all"], ["server", "stop"]):
                    try:
                        subprocess.run([lms] + args, capture_output=True, timeout=120)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        leftovers = processes_under(folder)
        for pid in leftovers:
            kill_tree(pid)
        if leftovers:
            self.event("killed %d process(es) %s left behind" % (len(leftovers), name))
        if not self.simulate:
            time.sleep(8)          # let the driver hand the memory back
        self.event("model released; the card is free", "handover")

    def find_lms(self, name):
        configured = self.agent_env(name).get("LC_LMS_PATH", "")
        tail = os.path.join("resources", "app", ".webpack", "lms.exe")
        candidates = [configured, os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe"),
                      os.path.expandvars(os.path.join(r"%LOCALAPPDATA%\Programs\LM Studio", tail)),
                      os.path.expandvars(os.path.join(r"%ProgramFiles%\LM Studio", tail))]
        candidates += [os.path.join("%s:\\" % d, "LM Studio", tail) for d in "CDEFGH"]
        for path in candidates:
            if path and os.path.isfile(path):
                return path
        return shutil.which("lms")

    # ---------------------------------------------------------------- preflight and reports

    def preflight(self, name):
        """Import every module and run the tests, with the agent's own Python.

        Seconds, where a failed launch costs minutes of model loading first.
        Returns a list of problems; empty means fit to launch. Orthros's own
        check, so an agent cannot switch it off by editing itself -- though
        the tests it runs are the agent's.
        """
        folder, python = self.folders[name], self.python_for(name)
        env = self.agent_env(name)
        flags = CREATE_NO_WINDOW if os.name == "nt" else 0
        problems = []
        try:
            proc = subprocess.run([python, "-c", PREFLIGHT_IMPORTS], cwd=folder, env=env,
                                  capture_output=True, text=True, timeout=180,
                                  encoding="utf-8", errors="replace", creationflags=flags)
            if proc.returncode != 0:
                problems.append("modules do not import: " + " | ".join(
                    ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-4:]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append("could not run the import check: %s" % exc)
        tests = [f for f in os.listdir(folder) if f.startswith("test_") and f.endswith(".py")]
        if not problems and tests:
            try:
                proc = subprocess.run([python, "-m", "unittest", "discover", "-s", ".", "-p",
                                       "test_*.py", "-q"], cwd=folder, env=env,
                                      capture_output=True, text=True, timeout=600,
                                      encoding="utf-8", errors="replace", creationflags=flags)
                if proc.returncode != 0:
                    out = ((proc.stderr or "") + (proc.stdout or "")).splitlines()
                    failing = [l for l in out if l.startswith(("FAIL:", "ERROR:"))]
                    problems.append("tests fail: " + " | ".join(failing[:4] or out[-4:]))
            except (OSError, subprocess.TimeoutExpired) as exc:
                problems.append("the tests did not finish: %s" % exc)
        return problems

    def memory_is_free_enough(self, name):
        """Wait for room before loading a model. False means Orthros paused.

        Starting a turn into a machine that is already full is how the engine
        dies at "bad allocation" a minute later, and how everything else on
        the machine gets killed with it.
        """
        disk = int(self.settings.get("min_free_disk_mb") or 0)
        try:
            free_disk = shutil.disk_usage(self.root).free // 1048576
        except OSError:
            free_disk = None
        if disk and free_disk is not None and free_disk < disk:
            self.pause("Only %d MB of disk left where Orthros keeps its logs and the agents' "
                       "history; a turn needs %d MB. Free some space, then press Start."
                       % (free_disk, disk), error=True)
            return False
        want = int(self.settings.get("min_free_mb") or 0)
        if not want or self.simulate:
            return True
        waited = 0
        while True:
            reading = memory()
            if not reading or reading[0] >= want:
                return True
            free, phys, load = reading
            if waited == 0:
                self.event("waiting for memory: %d MB of the commit limit free, %d MB needed. "
                           "Close what you can -- browsers and Electron apps are the usual "
                           "culprits." % (free, want))
                self.set_phase("handover", "waiting for memory before starting %s" % name)
            if waited >= 600:
                self.pause(loud=True, message="Still only %d MB of memory free after ten minutes, and a turn "
                           "needs %d MB. Close some programs, or give Windows a bigger page "
                           "file, then press Start." % (free, want))
                return False
            self.wake.wait(30)
            self.wake.clear()
            if self.state["paused"]:
                return False
            waited += 30

    def cleared_for_launch(self, name):
        """Preflight, rolling back first if needed. False means paused."""
        self.set_phase("handover", "checking %s before launch" % name)
        problems = self.preflight(name)
        while problems:
            # Imports and tests do not depend on LM Studio, so a failure here
            # is the code's -- safe to step back for, as far as it takes.
            self.event("%s failed its pre-launch checks: %s" % (name, problems[0][:140]), "bad")
            self.field_note(name, "Failed the pre-launch checks, so it was rolled back: %s"
                            % "; ".join(problems)[:300])
            if not self.retreat(name, "it failed the checks before launch: "
                                + "; ".join(problems)):
                self.pause("%s fails its pre-launch checks even on its baseline version: %s"
                           % (name, "; ".join(problems)), error=True)
                return False
            problems = self.preflight(name)
        self.event("%s passed its pre-launch checks" % name)
        return True

    def field_report(self, result):
        """How the agent that just ran actually did, written into its folder --
        where its twin, which made the changes, reads it when planning.

        The only way the improver sees what its improvements did in practice:
        the turn's own numbers, and a count of the things that go wrong.
        """
        name = result["agent"]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(result["started"]))
        if not result["launched"]:
            self.field_note(name, "Failed to start (exit %s). Last output: %s"
                            % (result["exit"], " | ".join(tail(result["log"], 6))[:400]), when)
            return
        text = read_text(result["log"])
        lines = []
        kind, score = result.get("kind", "self"), result.get("score")
        if kind == "practice":
            lines.append("**Practice** on %s: %s of the hidden tests passed."
                         % (result["label"], "%d of %d" % tuple(score) if score else "none"))
            if result.get("failures"):
                lines.append("Hidden tests it failed: %s." % ", ".join(result["failures"]))
        elif kind == "task":
            lines.append("**Task** %s%s." % (result["label"], ": its own tests, %d of %d passing"
                                               % tuple(score) if score and score[1] else ""))
        lines += ["%d min, %d rounds, %d items ticked, %d changes kept, %d sent back, "
                 "%s tokens. Ended: %s" % (result["seconds"] // 60, result["rounds"],
                                           result["ticked"], result["kept"],
                                           result["sent_back"],
                                           "{:,}".format(result["tokens"]),
                                           result["reason"] or "?")]
        counts = ["%s: %d" % (label, text.count(phrase)) for label, phrase in FIELD_SIGNS
                  if text.count(phrase)]
        if result.get("lowest_free_mb") is not None:
            lines.append("Least memory free during the turn: %d MB." % result["lowest_free_mb"])
        if counts:
            lines.append("Trouble: " + "; ".join(counts) + ".")
        sizes = [(int(a), int(b)) for a, b in OVERSIZE.findall(text)]
        if sizes:
            lines.append("Diagnosis: LM Studio refused prompts of up to %s tokens against a "
                         "%s-token window. The engine did not die -- the rounds sent more "
                         "than the window holds (often files aider added because a reply "
                         "named them). Fix what a round sends, not the engine handling."
                         % ("{:,}".format(max(a for a, _ in sizes)),
                            "{:,}".format(sizes[0][1])))
        went = self.round_outcomes(name, result["started"])
        if went:
            lines.append("Where the rounds went: %s." % ", ".join("%s %d" % o for o in went))
        rates = [float(m) for m in re.findall(r"([\d.]+) tok/sec", text)]
        if rates:
            lines.append("Typical speed: %.0f tok/sec." % sorted(rates)[len(rates) // 2])
        reasons = re.findall(r"Reviewer rejected it: (.+)", text)[-3:]
        lines += ["Rejected: %s" % r.strip()[:160] for r in reasons]
        errors = re.findall(r"LocalCoder hit an unexpected error: (.+)", text)[-2:]
        lines += ["Error: %s" % e.strip()[:160] for e in errors]
        record = self.coding_record(name)
        if record:
            lines.append("General coding lately: " + record)
        self.field_note(name, "\n".join("- " + l for l in lines), when, bullets=True)

    def round_outcomes(self, name, since):
        """[(outcome, rounds)] for one agent's rounds since `since`, from the ledger."""
        path = os.path.join(self.root, LEDGER)
        if not os.path.isfile(path):
            return []
        try:
            db = sqlite3.connect(path, timeout=10)
            try:
                return [tuple(r) for r in db.execute(ROUND_OUTCOMES, (name, since))]
            finally:
                db.close()
        except sqlite3.Error:
            return []

    def recent_outcomes(self, name):
        """round_outcomes for the last day, for the page -- read at most once a minute."""
        cache = getattr(self, "_outcomes", {})
        at, value = cache.get(name, (0, []))
        if now() - at > 60:
            value = self.round_outcomes(name, now() - 86400)
            cache[name] = (now(), value)
            self._outcomes = cache
        return value

    def coding_record(self, name):
        """The measure that matters: practice scores and task turns, newest last."""
        me = self.agent(name)
        bits = ["practice %s %d/%d" % (p[1], p[2], p[3]) for p in (me.get("practice") or [])[-4:]]
        bits += ["task %s %d kept" % (t[1], t[4]) for t in (me.get("tasks") or [])[-2:]]
        return ", ".join(bits)

    def field_note(self, name, text, when=None, bullets=False):
        """Put a dated entry at the top of FIELD_REPORT.md; keep the newest five."""
        path = os.path.join(self.folders[name], FIELD_REPORT)
        head_text = ("# Field report: how OrthrosCode %s did in its turns\n\n"
                     "Written by Orthros after each turn, newest first. These are the results "
                     "of the changes made to it.\n" % name)
        old = read_text(path).split("\n## ")[1:5]
        entry = "## %s\n\n%s\n" % (when or time.strftime("%Y-%m-%d %H:%M"),
                                   text if bullets else "- " + text)
        body = head_text + "\n" + entry + "".join("\n## " + e for e in old)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body.rstrip() + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- judging

    @staticmethod
    def effective(result):
        """Did the session do real work? Started, ran rounds, kept something,
        and was not ended by its own errors."""
        return (result["launched"] and result["rounds"] >= 1
                and (result["kept"] + result["ticked"]) >= 1
                and "unexpected error" not in result["reason"])

    def judge(self, result):
        name = result["agent"]
        me = self.agent(name)
        peer_name = PEER[name]
        me["last"] = {k: result[k] for k in ("started", "seconds", "rounds", "ticked", "kept",
                                              "sent_back", "tokens", "reason", "launched")}
        if not result["launched"]:
            return self.launch_failed(name, result)
        me["good_failures"] = 0
        me["env_failures"] = 0

        me["sessions"] += 1
        me["seconds"] += result["seconds"]
        me["tokens"] += result["tokens"]
        me["kept"] += result["kept"]
        good = self.effective(result)
        self.event("%s finished: %d min, %d rounds, %d kept, %d sent back, %s tokens%s"
                   % (name, result["seconds"] // 60, result["rounds"], result["kept"],
                      result["sent_back"], "{:,}".format(result["tokens"]),
                      "" if good else " -- nothing useful kept"), "good" if good else "info")
        if good:
            self.state["idle_streak"] = 0
            me["weak_streak"] = 0
            me["spared"] = False
            self.prove(name, result["own"])    # this version has proven itself
            if self.score_gated(name):
                # Proven to work, not yet to be better: its changes wait for
                # the held-out score before they reach the twin.
                me["proven_pending"] = me["proven_pending"] + me["pending"]
                me["pending"] = []
                if not self.same_code(name, result["own"], me["scored_good"]):
                    me["since_eval"] += 1
            else:
                if self.state.get("mode") != "task" and self.settings.get("prove_by_score") \
                        and work.eval_exercises() and result.get("kind", "self") == "self":
                    me["since_eval"] += 1          # towards the first, baseline score
                self.carry_over(name)
        else:
            self.state["idle_streak"] += 1
            if self.is_good(name, result["own"]):
                # A weak turn on a proven version says nothing about changes
                # made after it. On 2026-09-24 B idled once on its proven
                # version and once on the changes A had just made to it, and
                # those changes were rolled back for "two sessions in a row".
                me["weak_streak"] = 0
            else:
                me["weak_streak"] += 1
            if me["weak_streak"] >= 2 and not self.is_good(name):
                trouble = self.outside_trouble(result)
                if trouble and not me.get("spared"):
                    # On 2026-09-23 A was rolled back for two idle turns that
                    # were lost to oversized prompts built from B's task list.
                    # The rollback undid B's work and changed nothing: the
                    # proven version failed the same way. One more turn first,
                    # with the item it died on parked (count_tries).
                    me["spared"] = True
                    me["weak_streak"] = 0
                    self.event("not rolling %s back yet: its last turns were lost to %s, "
                               "which may not be its code's doing" % (name, trouble))
                else:
                    me["spared"] = False
                    self.rollback(name, "two sessions in a row did no useful work since the "
                                        "last changes to it")
        self.count_tries(name, result, good)
        self.note_early_stop(name, result)
        kind, score = result.get("kind", "self"), result.get("score")
        if kind == "practice":
            me["since_practice"] = 0
            me["practice"] = (me["practice"] + [[result["started"], result["label"],
                                                 score[0] if score else 0,
                                                 score[1] if score else 0]])[-40:]
            self.event("%s's practice on %s: %s hidden tests passed" % (
                name, result["label"], "%d of %d" % tuple(score) if score else "no"),
                "good" if score and score[1] and score[0] == score[1] else "info")
        elif kind == "task":
            me["tasks"] = (me["tasks"] + [[result["started"], result["label"],
                                           score[0] if score else 0, score[1] if score else 0,
                                           result["kept"], result["ticked"]]])[-40:]
        else:
            me["since_practice"] = me.get("since_practice", 0) + 1
        if kind == "self" and result["post"] != result["pre"]:
            self.agent(peer_name)["pending"].append([result["pre"], result["post"]])
        self.state["next"] = peer_name
        self.save()
        for folder in self.folders.values():
            git(folder, "gc", "--auto", "--quiet", timeout=600)   # weeks of commits add up
        limit = int(self.settings.get("pause_after_idle") or 0)
        if limit and self.state["idle_streak"] >= limit:
            self.pause(loud=True, message="%d sessions in a row kept nothing. Paused -- look at the logs "
                       "before starting again." % self.state["idle_streak"])

    def launch_failed(self, name, result):
        """It never reached its first round. Get it back to something that runs.

        Changed since its last proven version: roll back to that. Already on a
        proven version: try once more (a first failure there is as likely to
        be the machine), then step back to the proven version before it --
        which is what saves both agents when a change that looked good, and
        was copied into both, turns out to be fatal. Nothing left, or a
        failure the machine is plainly to blame for: pause.
        """
        me = self.agent(name)
        me["launch_failures"] += 1
        why = "\n".join(tail(result["log"], 12)) or "no output"
        self.event("%s failed to start (exit %s)" % (name, result["exit"]), "bad")
        self.state["next"] = name                # its turn still, once it can run
        if any(sign in why for sign in ENV_SIGNS):
            # The machine, not the code -- and machines recover: LM Studio
            # finishes updating, a game closes, a driver comes back. Wait and
            # try again a few times, longer each time, before giving up.
            waits = list(self.settings.get("env_retry_minutes") or [])
            me["env_failures"] = me.get("env_failures", 0) + 1
            if me["env_failures"] <= len(waits):
                wait = int(waits[me["env_failures"] - 1])
                self.backoff_until = now() + wait * 60
                self.event("%s could not start because of the machine; trying again in %d "
                           "minute(s) (%d of %d): %s" % (name, wait, me["env_failures"],
                                                         len(waits), why.splitlines()[-1][:120]),
                           "bad")
            else:
                me["env_failures"] = 0
                self.pause("%s could not start, %d times now, and the output says the machine "
                           "is the problem, not the code:\n%s"
                           % (name, len(waits) + 1, why), error=True)
        elif not self.is_good(name):
            self.retreat(name, "it failed to start:\n" + why)
        elif me["good_failures"] < 1:
            me["good_failures"] += 1
            self.event("%s failed on a proven version; trying it once more" % name)
        elif not self.retreat(name, "it failed to start twice on a version that had "
                                    "worked:\n" + why):
            self.pause("%s failed to start on every version that has ever worked for it. "
                       "This is LM Studio or the machine. Last output:\n%s" % (name, why),
                       error=True)
        self.save()

    @staticmethod
    def outside_trouble(result):
        """What, other than the agent's code, a weak turn was lost to. '' if nothing."""
        text = read_text(result.get("log") or "")
        if OVERSIZE.search(text) or GUARD_REFUSED in text:
            return "prompts too big for the context window"
        if "engine" in (result.get("reason") or "").lower():
            return "the engine"
        return ""

    def count_tries(self, name, result, good):
        """NR_OF_TRIES: park an item that turn after turn dies on.

        After fstandhartinger/ralph-wiggum, which counts the attempts on each
        spec and flags it as stuck past a limit. The agents park an item
        within a turn; nothing counted across turns. So on 2026-09-23 the
        same top item on B's list ended two of A's turns in a row, identically,
        and would have ended every one after -- the rounds that could have
        parked it were never charged to it.
        """
        limit = int(self.settings.get("park_after_tries") or 0)
        path = result.get("folder") or self.folders[PEER[name]]
        folder = os.path.basename(path)
        tries = self.state.setdefault("tries", {})
        mine = [k for k in tries if k.startswith(folder + "|")]
        if good or not result["launched"]:
            for k in mine:
                del tries[k]
            return
        item = (result.get("item") or "").strip()
        if not limit or not item or item not in OPEN_ITEM.findall(read_text(notes_file(path))):
            return
        key = "%s|%s" % (folder, item)
        for k in mine:
            if k != key:
                del tries[k]                 # a different item: the count starts again
        tries[key] = tries.get(key, 0) + 1
        if tries[key] < limit:
            return
        why = ("%d turns in a row ended on this item without progress (last: %s). "
               "Split it smaller, or rewrite it so one round can finish it."
               % (tries[key], (result.get("reason") or "?")[:120]))
        if park_item(notes_file(path), item, why):
            self.event("parked the item %s's turns keep dying on: %s" % (name, item[:70]), "bad")
        del tries[key]

    def note_early_stop(self, name, result):
        """A turn that ended itself early becomes the twin's first job.

        The field report already says how the turn ended, but as one line
        among many, read only when planning. An early stop is the most
        expensive thing that happens here -- the rest of the turn is thrown
        away -- so its cause goes to the top of the list the twin works from,
        with the words to search for.
        """
        reason = " ".join((result.get("reason") or "").split())
        planned = (result.get("minutes") or 0) * 60
        # A practice that ends early has usually finished the exercise, and
        # its hidden-test score already says how it went. Made a to-do for
        # the twin, it asks for a fix to the loop for doing its job.
        if result.get("kind") == "practice":
            return
        if (not result["launched"] or not reason or reason.startswith(NORMAL_ENDS)
                or (planned and result["seconds"] >= planned * 0.8)):
            return
        path = notes_file(self.folders[name])
        signature = reason[:60]
        if any(signature in item for item in OPEN_ITEM.findall(read_text(path))):
            return                           # already on the list, not yet done
        trouble = self.outside_trouble(result)
        hint = (" The log shows prompts refused as too big for the window, so look at what "
                "a round sends before looking at the engine." if trouble.startswith("prompts")
                else "")
        words = " ".join(reason.split()[:4]).strip(" .-")
        text = ("Found by Orthros: %s's last turn stopped itself after %d of %d minutes, "
                "ending with \"%s\".%s Find the code that says that (FIND: %s), work out why "
                "it fired, and make the loop recover and carry on there instead -- with a "
                "test that the session keeps going."
                % (name, result["seconds"] // 60, planned // 60, reason[:160], hint, words))
        if add_first(path, text):
            self.event("%s stopped early; that is now first on %s's list for %s"
                       % (name, name, PEER[name]))

    # ---------------------------------------------------------------- rollback and carry-over

    def good(self, name):
        """The newest proven version of an agent."""
        goods = self.agent(name)["goods"]
        return goods[-1] if goods else self.agent(name)["good"]

    def is_good(self, name, sha=None):
        """Is the agent's code (not its twin's notes about it) a proven version?"""
        folder = self.folders[name]
        excludes = [":(exclude)%s" % f for f in MEMORY_FILES]
        ok, _ = git(folder, "diff", "--quiet", self.good(name), sha or "HEAD", "--", ".",
                    *excludes)
        return ok

    def prove(self, name, sha):
        me = self.agent(name)
        if not self.is_good(name, sha):
            me["goods"].append(sha)
            git(self.folders[name], "tag", "-f", "orthros/proven-%d" % len(me["goods"]), sha)
            # Keep the baseline, and the newest few after it.
            if len(me["goods"]) > PROVEN_KEPT:
                me["goods"] = me["goods"][:1] + me["goods"][-(PROVEN_KEPT - 1):]
        me["good"] = self.good(name)

    def retreat(self, name, why):
        """Back to the newest proven version -- or, if the agent is already on
        it, past it to the one before. Returns False when there is nowhere
        left to go."""
        me = self.agent(name)
        if self.is_good(name):
            if len(me["goods"]) <= 1:
                return False
            dropped = me["goods"].pop()
            git(self.folders[name], "tag", "-f", "orthros/withdrawn-%s" % short(dropped), dropped)
            self.event("%s's proven version %s failed after all; withdrawing it"
                       % (name, short(dropped)), "bad")
            me["proven_pending"] = []    # what they held may be what failed
            why += " -- on a version that had been proven, so that proof is withdrawn"
        me["good"] = self.good(name)
        me["good_failures"] = 0
        self.rollback(name, why)
        return True

    def rollback(self, name, why):
        """Put an agent back to its last proven version, keeping the notes the
        other agent keeps about it, and telling it what happened."""
        folder = self.folders[name]
        me = self.agent(name)
        bad = commit_all(folder, "Orthros: state before rollback")
        tag = "orthros/failed-%d" % (me["rollbacks"] + 1)
        git(folder, "tag", "-f", tag, bad)
        saved = {f: read_text(os.path.join(folder, f)) for f in MEMORY_FILES
                 if os.path.isfile(os.path.join(folder, f))}
        git(folder, "reset", "--hard", "-q", self.good(name))
        git(folder, "clean", "-fdq")
        for f, body in saved.items():
            with open(os.path.join(folder, f), "w", encoding="utf-8") as handle:
                handle.write(body)
        detail = " ".join(why.split())[:400]
        self.write_rollback_note(folder, bad, tag, detail)
        # The item used to say where the diff was -- `git diff ...` -- to a
        # round that cannot run git. On 2026-09-23 B spent eight rounds and a
        # whole turn writing notes about the diff it could not see. Now the
        # diff is in the folder, and the item says what to do if it is not the
        # culprit (the turns may have been lost to something else entirely).
        self.add_item(folder, "Found by Orthros: the last changes were rolled back",
                      "The changes from %s's last turn were undone because %s. What was "
                      "undone is in %s, as a diff -- there is no git command to run. Read it "
                      "and make the useful part of that change again, smaller and safely. If "
                      "nothing in it can have caused the problem, tick this item with a note "
                      "saying so." % (PEER[name], detail, ROLLBACK_NOTE))
        commit_all(folder, "Orthros: rolled %s back to %s" % (name, short(self.good(name))))
        me["rollbacks"] += 1
        me["pending"] = []
        me["weak_streak"] = 0
        self.event("rolled %s back to %s (the failed version is tag %s)"
                   % (name, short(self.good(name)), tag), "bad")

    def write_rollback_note(self, folder, bad, tag, why):
        """ROLLBACK.md: the undone change, readable by a round that cannot run git."""
        excludes = [":(exclude)%s" % f for f in MEMORY_FILES]
        good = head(folder)                  # just reset to the proven version
        _, stat = git(folder, "diff", "--stat", good, bad, "--", ".", *excludes)
        _, diff = git(folder, "diff", "--unified=2", good, bad, "--", ".", *excludes)
        if len(diff) > DIFF_NOTE_CHARS:
            diff = diff[:DIFF_NOTE_CHARS] + "\n[... cut at %d characters ...]" % DIFF_NOTE_CHARS
        body = ("# What the last rollback undid\n\nWritten by Orthros. It was undone because "
                "%s.\nKept in full in git tag `%s`.\n\n```\n%s\n```\n\n```diff\n%s\n```\n"
                % (why, tag, stat.strip() or "(no source changes)", diff.strip()))
        try:
            with open(os.path.join(folder, ROLLBACK_NOTE), "w", encoding="utf-8") as handle:
                handle.write(body)
        except OSError:
            pass

    def add_item(self, folder, heading, text):
        path = notes_file(folder)
        body = read_text(path)
        if not body:
            return
        block = "\n\n### %s\n\n- [ ] %s\n" % (heading, text)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body.rstrip() + block)

    def carry_over(self, name, ranges=None):
        """The agent just proved the changes its peer made to it; copy them into
        the peer as well, so both agents have them."""
        me = self.agent(name)
        src, dst = self.folders[name], self.folders[PEER[name]]
        if ranges is None:
            ranges, me["pending"] = me["pending"], []
        if not ranges:
            return
        ok, out = git(dst, "fetch", "-q", "--no-tags", src, "+HEAD:refs/orthros/peer")
        if not ok:
            self.event("could not read %s's history to carry changes over: %s"
                       % (name, out[:120]), "bad")
            return
        excludes = [":(exclude)%s" % f for f in MEMORY_FILES]
        carried = skipped = 0
        for pre, post in ranges:
            ok, patch = git(src, "diff", "--binary", pre, post, "--", ".", *excludes)
            if not ok or not patch.strip():
                continue
            fd, patch_path = tempfile.mkstemp(suffix=".patch")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(patch + "\n")
            ok, out = git(dst, "apply", "--3way", "--whitespace=nowarn", patch_path)
            os.remove(patch_path)
            if not ok:
                git(dst, "reset", "--hard", "-q")
                git(dst, "clean", "-fdq")
                skipped += 1
                continue
            self.fix_workspace_line(PEER[name])
            commit_all(dst, "Orthros: carried over %s..%s, proven in %s"
                       % (short(pre), short(post), name))
            carried += 1
        if carried:
            self.agent(PEER[name])["carried_in"] += carried
            self.event("carried %d proven change set(s) from %s into %s"
                       % (carried, name, PEER[name]), "good")
        if skipped:
            self.event("%d change set(s) from %s did not apply cleanly to %s; left out"
                       % (skipped, name, PEER[name]))

    # ---------------------------------------------------------------- proof by score

    def score_gated(self, name):
        """Do this agent's changes wait for a held-out score before carrying over?"""
        return bool(self.settings.get("prove_by_score") and self.state.get("mode") != "task"
                    and work.eval_exercises() and self.agent(name).get("scored_good"))

    def same_code(self, name, a, b):
        """Same code in the agent's folder at `a` and `b`, notes aside."""
        if not a or not b:
            return False
        # Compiled files too: the pre-launch import check writes them, and in a
        # folder that does not ignore them they would make every version new.
        excludes = [":(exclude)%s" % f for f in MEMORY_FILES] + [
            ":(exclude)*.pyc", ":(exclude)**/__pycache__/**"]
        ok, _ = git(self.folders[name], "diff", "--quiet", a, b, "--", ".", *excludes)
        return ok

    def maybe_start_eval(self, name):
        """The evaluation under way, or a new one for `name` if its version is due."""
        if self.state.get("evaluating"):
            return self.state["evaluating"]
        me = self.agent(name)
        exercises = work.eval_exercises()[:max(1, int(self.settings.get("eval_count") or 8))]
        if (not self.settings.get("prove_by_score") or self.state.get("mode") == "task"
                or not work.eval_exercises()
                or me["since_eval"] < max(1, int(self.settings.get("eval_every") or 4))):
            return None
        sha = commit_all(self.folders[name], "Orthros: %s's version, to be scored" % name)
        if self.same_code(name, sha, me["scored_good"]):
            me["since_eval"] = 0
            return None
        ev = {"agent": name, "sha": sha, "parent": me["scored_good"], "todo": exercises,
              "scores": {}, "resume": self.state["next"], "started": now()}
        with self.lock:
            self.state["evaluating"] = ev
            self.save()
        self.event("scoring %s's version %s on %d held-out exercises%s"
                   % (name, short(sha), len(exercises),
                      " against %s" % short(ev["parent"]) if ev["parent"] else
                      " -- the first score, which later versions are held to"), "start")
        return ev

    def eval_work(self, ev):
        exercise = ev["todo"][0]
        return {"kind": "eval", "exercise": exercise,
                "label": "%d of %d" % (len(ev["scores"]) + 1, len(ev["scores"]) + len(ev["todo"])),
                "folder": work.start_practice(self.root, ev["agent"], exercise, held_out=True)}

    def judge_eval(self, result):
        """One held-out exercise done: record it, and decide when all are."""
        ev = self.state.get("evaluating")
        name = result["agent"]
        if not ev or ev["agent"] != name:
            return
        if not result["launched"]:
            # Cannot even start: that is the launch-failure path's to handle,
            # and the score waits for a version that runs.
            self.event("scoring %s stopped: it did not start" % name, "bad")
            self.state.pop("evaluating", None)
            self.judge(dict(result, kind="self"))
            self.state["next"] = ev.get("resume") or self.state["next"]
            self.save()
            return
        exercise = result.get("exercise") or ev["todo"][0]
        score = result.get("score") or [0, 0]
        ev["scores"][exercise] = [int(score[0]), int(score[1])]
        ev["todo"] = [e for e in ev["todo"] if e != exercise]
        self.event("%s scored %d of %d on held-out exercise %d of %d"
                   % (name, score[0], score[1], len(ev["scores"]),
                      len(ev["scores"]) + len(ev["todo"])))
        self.save()
        if not ev["todo"]:
            self.decide_eval(ev)

    def decide_eval(self, ev):
        """Prove the version by its score, or send it back to the last that passed."""
        name, me = ev["agent"], self.agent(ev["agent"])
        self.state.pop("evaluating", None)
        self.state["next"] = ev.get("resume") or PEER[name]
        me["since_eval"] = 0
        parent = me["scored"].get(ev["parent"], {}).get("scores", {}) if ev["parent"] else {}
        wins, losses, not_worse = compare_scores(ev["scores"], parent)
        # Each step "not clearly worse than the last" can still walk downhill
        # a little at a time. So the best version so far is a second bar,
        # stricter, since it may have been a lucky run: five exercises worse
        # and none better in eight.
        best = self.best_scored(name, ev["scores"])
        if parent and best and best != ev["parent"]:
            _, best_losses, not_worse_than_best = compare_scores(
                ev["scores"], me["scored"][best]["scores"], alpha=0.05)
            if not not_worse_than_best:
                not_worse = False
                losses = max(losses, best_losses)
        full, count, passed, total = score_totals(ev["scores"])
        mine = "%d of %d held-out exercises fully passed, %d of %d hidden tests" % (
            full, count, passed, total)
        if parent:
            p_full, p_count, p_passed, p_total = score_totals(
                {e: s for e, s in parent.items() if e in ev["scores"]})
            theirs = "the version before it: %d of %d, %d of %d hidden tests" % (
                p_full, p_count, p_passed, p_total)
        verdict = "baseline" if not parent else "kept" if not_worse else "rolled back"
        me["scored"][ev["sha"]] = {"scores": ev["scores"], "parent": ev["parent"], "at": now(),
                                   "verdict": verdict, "wins": wins, "losses": losses}
        if len(me["scored"]) > 40:
            for old in sorted(me["scored"], key=lambda s: me["scored"][s]["at"])[:-40]:
                if old != me["scored_good"]:
                    me["scored"].pop(old)
        self.warn_if_gamed(name)
        if not parent:
            me["scored_good"] = ev["sha"]
            self.prove(name, ev["sha"])        # it ran every exercise: it works
            self.carry_over(name, me["proven_pending"] + me["pending"])
            me["proven_pending"], me["pending"] = [], []
            self.event("%s's first held-out score: %s. Later versions are held to it."
                       % (name, mine), "good")
            self.field_note(name, "**Held-out score** of this version: %s. The first score; "
                            "later versions must not do worse." % mine)
        elif not_worse:
            me["scored_good"] = ev["sha"]
            self.prove(name, ev["sha"])
            ranges = me["proven_pending"] + me["pending"]
            me["proven_pending"], me["pending"] = [], []
            self.carry_over(name, ranges)
            self.event("%s's version %s proven by score: %s (%s; %d better, %d worse)"
                       % (name, short(ev["sha"]), mine, theirs, wins, losses), "good")
            self.field_note(name, "**Held-out score** of this version: %s -- %s. %d exercises "
                            "went better and %d worse, so the changes were kept and copied "
                            "into %s." % (mine, theirs, wins, losses, PEER[name]))
        else:
            why = ("its held-out score fell: %s -- %s; %d exercises went worse and only %d "
                   "better" % (mine, theirs, losses, wins))
            self.field_note(name, "**Held-out score** of this version: %s -- %s. That is worse, "
                            "so it was rolled back to the version that scored better." % (
                                mine, theirs))
            self.rollback_to_scored(name, why)
        self.save()

    def best_scored(self, name, scores):
        """The passed version with the most hidden tests passed on these exercises."""
        me = self.agent(name)
        passed = [(sum(s[0] for e, s in entry["scores"].items() if e in scores), sha)
                  for sha, entry in me["scored"].items()
                  if entry.get("verdict") in ("baseline", "kept")]
        return max(passed)[1] if passed else ""

    def rollback_to_scored(self, name, why):
        """Back to the last version that passed its score: newer proofs withdrawn."""
        me = self.agent(name)
        target = me["scored_good"]
        goods = me["goods"]
        if target in goods:
            me["goods"] = goods[:goods.index(target) + 1]
        else:
            me["goods"] = goods + [target]
        me["good"] = self.good(name)
        me["proven_pending"] = []
        self.rollback(name, why)

    def warn_if_gamed(self, name):
        """The held-out exercises' names should never turn up in an agent's code.

        Only the distinctive ones, `phone_number` and the like: "clock" in an
        agent's code is no evidence of anything.
        """
        names = [e for e in work.eval_exercises() if "_" in e]
        folder = self.folders[name]
        for root_, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith((".", "venv", "__pycache__"))]
            for f in files:
                if not f.endswith(".py"):
                    continue
                body = read_text(os.path.join(root_, f))
                hit = next((e for e in names if e in body), "")
                if hit:
                    self.event("warning: %s's %s mentions a held-out exercise (%s); its "
                               "score may not mean what it seems" % (name, f, hit), "bad")
                    return True
        return False

    def fix_workspace_line(self, name):
        """Keep an agent's config pointing at its peer, whatever was carried over."""
        path = os.path.join(self.folders[name], "config.cmd")
        body = read_text(path)
        want = 'set "LC_WORKSPACE=%%~dp0..\\OrthrosCode %s"' % PEER[name]
        fixed = re.sub(r'^set "LC_WORKSPACE=.*"$', lambda m: want, body, flags=re.M)
        if fixed != body:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(fixed)

    # ---------------------------------------------------------------- the loop

    def loop(self):
        while True:
            if self.state["paused"]:
                if self.phase not in ("error",):
                    self.set_phase("paused" if self.state["events"] else "idle", self.message
                                   if self.phase == "paused" else "")
                self.wake.wait(5)
                self.wake.clear()
                continue
            if now() < self.backoff_until:
                self.set_phase("handover", "the machine was not ready; trying again in %s"
                               % clock_left(self.backoff_until - now()))
                self.wake.wait(5)
                self.wake.clear()
                continue
            try:
                self.adopt_orphan()
                if self.state["paused"]:
                    continue                 # judging that turn paused Orthros
                # Read after adopting: judging an adopted turn decides who is next,
                # and reading it before meant the same agent ran twice in a row.
                name = self.state["next"]
                ev = self.maybe_start_eval(name)
                if ev:
                    name = ev["agent"]
                if not self.memory_is_free_enough(name) or not self.cleared_for_launch(name):
                    continue
                if ev and not self.same_code(name, ev["sha"], head(self.folders[name])):
                    # The pre-launch checks rolled it back: that version is gone.
                    self.event("scoring %s dropped: its version changed before it was scored"
                               % name)
                    self.state.pop("evaluating", None)
                    self.state["next"] = ev.get("resume") or self.state["next"]
                    self.save()
                    continue
                self.maybe_look()            # cheap unless there is a reason to look
                result = self.run_turn(name, self.eval_work(ev) if ev else None)
                if self.stop_mode and not result["launched"]:
                    # Stopped by hand before it got going: not the code's fault.
                    self.event("%s was stopped before it started working" % name)
                elif ev and self.stop_mode in ("now", "force"):
                    # Cut short by hand: a part-done exercise would score the
                    # stop, not the version. It is done again on the restart.
                    self.event("scoring %s interrupted; that exercise will be done again" % name)
                elif ev:
                    self.judge_eval(result)
                    self.tune_after(result)
                else:
                    self.field_report(result)
                    self.judge(result)
                    self.tune_after(result)
            except Exception as exc:
                self.event("Orthros error: %s" % exc, "bad")
                traceback.print_exc()
                self.pause("Orthros hit an error: %s" % exc, error=True)
                continue
            if self.stop_mode:
                reason = {"pause": "Paused after the session, as asked.",
                          "now": "Stopped after the round, as asked.",
                          "force": "Stopped by force."}.get(self.stop_mode, "Paused.")
                self.stop_mode = ""
                self.pause(reason)
            elif not self.state["paused"]:
                self.set_phase("handover", "starting %s" % self.state["next"])
                self.event("handing over to %s" % self.state["next"], "handover")

    def finish_orphan(self, running):
        """Judge a turn that finished while Orthros was not running.

        Orthros can be killed -- by the operator, or by Windows when memory runs
        out -- while the agent it started carries on and ends normally. Its
        work is committed and its status file is complete; all that is missing
        is the judgement. Without this, that turn is silently lost.
        """
        agent = running["agent"]
        peer = running.get("workspace") or self.folders[PEER[agent]]
        st = read_json(os.path.join(peer, STATUS_FILE), {}) or {}
        self.release(agent)
        self.state["next"] = PEER[agent]
        if not self.is_mine(st, running):
            self.save()
            return
        self.event("%s's turn finished while Orthros was not running; taking it into account now"
                   % agent)
        post = commit_all(peer, "Orthros: after %s's turn" % agent)
        result = {
            "agent": agent, "started": running["started"],
            "seconds": int(max(0, (st.get("ended") or now()) - running["started"])),
            "exit": None, "launched": st.get("phase") in LAUNCHED,
            "rounds": st.get("rounds", 0) or 0, "ticked": st.get("ticked", 0) or 0,
            "kept": st.get("accepted", 0) or 0, "sent_back": st.get("rejected", 0) or 0,
            "tokens": (st.get("tokens_in", 0) or 0) + (st.get("tokens_out", 0) or 0),
            "reason": st.get("ended_reason") or "Orthros was not running at the end",
            "log": running["log"], "own": running["own"], "pre": running["pre"], "post": post,
            "lowest_free_mb": None, "item": st.get("item") or "",
            "minutes": running.get("minutes") or 0,
            "kind": running.get("kind", "self"), "label": running.get("label", ""),
            "exercise": running.get("exercise", ""), "folder": peer, "score": None,
        }
        if result["kind"] in ("practice", "eval") and result["exercise"]:
            score = work.score_practice(peer, result["exercise"], self.python_for(agent),
                                        held_out=result["kind"] == "eval")
            result["score"] = list(score) if score else None
        if result["kind"] == "eval":
            self.judge_eval(result)
            self.save()
            return
        self.field_report(result)
        self.judge(result)
        self.save()

    def adopt_orphan(self):
        """A turn from before a restart: wait it out if it is still going, then judge it.

        The wait is bounded. Windows reuses process ids, and waiting on one
        that now belongs to something else would hold Orthros for ever.
        """
        running = self.state.get("running")
        if running:
            pid = running.get("pid")
            if pid_alive(pid):
                self.set_phase("running", "waiting for %s's session from before a restart"
                               % running["agent"])
                self.event("found %s still running from before; waiting for it"
                           % running["agent"])
                limit = running.get("started", now()) + 60 * (
                    (running.get("minutes") or self.settings["session_minutes"])
                    + self.settings["grace_minutes"] + 25)
                while pid_alive(pid) and not self.stop_mode:
                    if now() > limit:
                        if pid in processes_under(self.folders[running["agent"]]):
                            kill_tree(pid)
                        else:
                            self.event("stopped waiting for process %s: well past its time, "
                                       "and it is no longer %s's" % (pid, running["agent"]))
                        break
                    time.sleep(5)
                if self.stop_mode == "force":
                    kill_tree(pid)
            self.state["running"] = None
            self.state["unjudged"] = running
            self.save()
        orphan = self.state.pop("unjudged", None)
        if orphan:
            self.finish_orphan(orphan)

    def pause(self, message, error=False, loud=False):
        """Stop handing over. An error, or `loud`, means a person is needed:
        see surrender()."""
        with self.lock:
            self.state["paused"] = True
            self.state["wanted"] = False     # --resume brings back only a run that died
            self.save()
        self.set_phase("error" if error else "paused", message)
        self.event(message.splitlines()[0], "bad" if (error or loud) else "info")
        if error or loud:
            self.surrender(message)

    def surrender(self, message):
        """Give up out loud. Everything Orthros can do by itself has been tried.

        A file at the top of the folder, which a person looking at it cannot
        miss; the page turns red, retitles its tab and raises a desktop
        notification if it was allowed to; and Windows beeps. Cleared on Start.
        """
        body = ("Orthros stopped at %s and needs you.\n\n%s\n\nThe page "
                "(http://127.0.0.1:%s/) and orthros.log have the rest. Press Start when it is "
                "dealt with; this file goes away then.\n"
                % (time.strftime("%Y-%m-%d %H:%M"), message.strip(), self.settings.get("port")))
        try:
            with open(os.path.join(self.root, ALERT_FILE), "w", encoding="utf-8") as handle:
                handle.write(body)
        except OSError:
            pass
        with self.lock:
            self.state["alert"] = [now(), message.strip()[:600]]
            self.save()
        if self.simulate:
            return
        try:
            import winsound
            for _ in range(3):
                winsound.MessageBeep(0x30)          # MB_ICONEXCLAMATION
                time.sleep(0.4)
        except Exception:
            print("\a", end="", flush=True)

    # ---------------------------------------------------------------- controls

    def start(self, first=None, minutes=None):
        with self.lock:
            if not self.state["paused"]:
                return "already running"
            if minutes:
                self.settings["session_minutes"] = max(5, min(480, int(minutes)))
                write_json(self.settings_path, self.settings)
            if first in NAMES:
                self.state["next"] = first
            self.prepare_folders()
            self.state["paused"] = False
            self.state["alert"] = None
            self.backoff_until = 0
            try:
                os.remove(os.path.join(self.root, ALERT_FILE))
            except OSError:
                pass
            self.stop_mode = ""
            self.state["wanted"] = True
            self.save()
        self.set_phase("handover", "starting %s" % self.state["next"])
        self.event("Orthros started; %s goes first" % self.state["next"], "start")
        self.wake.set()
        return "ok"

    def stop(self, mode):
        """pause: finish this session, then stop. now: stop after the current
        round. force: kill it now."""
        if self.state["paused"] and not self.state.get("running"):
            return "not running"
        self.stop_mode = mode
        with self.lock:
            self.state["paused"] = True     # no handover once it ends
            self.state["wanted"] = False    # stopped by hand: --resume must not undo it
            self.save()
        if mode == "now" and self.state.get("running"):
            self.request_stop(self.workspace_of(self.state["running"]))
        self.event({"pause": "will pause when this session ends",
                    "now": "asked the running agent to stop after this round",
                    "force": "force-stopping the running agent"}[mode])
        self.wake.set()
        return "ok"

    # ---------------------------------------------------------------- telemetry

    def watch_gpu(self):
        """Poll the card for the page. Slows right down when there is no card to read."""
        tick = 0
        while True:
            if self.simulate:
                busy = bool(self.state.get("running")) and self.phase == "running"
                wobble = (tick % 7) * 1.5
                self.gpu = {"name": "simulated card", "util": (86 + wobble) if busy else 3.0,
                            "mem_used": 17600.0 if busy else 900.0, "mem_total": 24576.0,
                            "temp": 71.0 if busy else 38.0, "power": 310.0 if busy else 24.0}
            else:
                self.gpu = gpu_reading()
            if self.gpu:
                self.gpu_history = (self.gpu_history + [self.gpu.get("util") or 0])[-90:]
            tick += 1
            time.sleep(2 if self.gpu else 30)

    def tail_log(self, agent, name, offset):
        """New raw output of an agent's newest turn log, for the page's terminal."""
        running = self.state.get("running") or {}
        path = running.get("log") if running.get("agent") == agent else ""
        if not path:
            try:
                names = sorted(f for f in os.listdir(self.logs)
                               if f.endswith("-%s.log" % agent))
            except OSError:
                names = []
            path = os.path.join(self.logs, names[-1]) if names else ""
        if not path or not os.path.isfile(path):
            return {"file": "", "offset": 0, "text": "", "reset": True}
        size = os.path.getsize(path)
        reset = name != os.path.basename(path) or offset < 0 or offset > size
        if reset:
            offset = max(0, size - 24000)
        start = offset
        text, offset = read_from(path, offset)
        if reset and start and "\n" in text:
            text = text[text.index("\n") + 1:]      # started mid-file: begin on a whole line
        return {"file": os.path.basename(path), "offset": offset, "text": text,
                "reset": reset, "live": running.get("agent") == agent}

    # ---------------------------------------------------------------- modes

    def set_mode(self, mode, task=None):
        """Switch between improving itself and working a task. Takes effect
        at the next handover; the turn in flight finishes as it began."""
        if mode not in ("self", "task"):
            return "unknown mode"
        if task is not None:
            if task and not work.task_folder(self.root, task):
                return "no such task"
            self.state["task"] = work.slug(task) if task else ""
        if mode == "task" and not work.task_folder(self.root, self.state.get("task")):
            return "choose or create a task first"
        with self.lock:
            changed = self.state.get("mode") != mode
            self.state["mode"] = mode
            self.save()
        if changed or task:
            self.event("mode: %s" % ("working on the task %s" % self.state["task"]
                                     if mode == "task" else "improving itself"), "start")
        self.wake.set()
        return "ok"

    def new_task(self, name, brief):
        key, error = work.create_task(self.root, name, brief)
        if error:
            return {"error": error}
        self.event("new task %s" % key, "start")
        return {"result": "ok", "key": key}

    # ---------------------------------------------------------------- the operator's chat

    def chat(self, text, kind="ask", target="both"):
        """One message from the page's chat box. Returns the reply.

        `ask`: a question about how things stand, answered in a few plain
        sentences from Orthros's own records -- which are exact, and need no
        model: the card belongs to the agent that is running.

        `direct`: new direction for the work. It becomes the first item on the
        task list of the agent it is about (the twin works through that list),
        and waits for the end of the running turn if that list is in use: the
        agent rewrites it between rounds, and a rollback could lose it.
        """
        text = " ".join(str(text or "").split())[:600]
        if not text:
            return "Say something first."
        if kind == "direct":
            names = (target,) if target in NAMES + ("task",) else NAMES
            if target == "task" and not self.direction_folder("task"):
                return "There is no task chosen. Pick or create one first."
            with self.lock:
                for n in names:
                    self.state["directions"].append({"agent": n, "text": text, "at": now()})
                applied = self.apply_directions()
            where = " and ".join("the task" if n == "task" else n for n in names)
            if applied == len(names):
                reply = ("Added to the top of %s's list. The next round on it starts "
                         "there." % where)
            else:
                reply = ("Queued for %s's list. The list is in use by the running turn, "
                         "so it goes in, at the top, as soon as that turn ends." % where)
            self.event("operator direction for %s: %s" % (where, text[:80]), "start")
        else:
            reply = self.answer(text)
        with self.lock:
            self.state["chat"] = (self.state["chat"] + [[now(), "you", text],
                                                        [now(), "orthros", reply]])[-40:]
            self.save()
        return reply

    def workspace_of(self, running):
        return running.get("workspace") or self.folders[PEER[running["agent"]]]

    def direction_folder(self, target):
        """Where a direction for `target` goes: an agent's list (its twin works it) or the task's."""
        if target == "task":
            return work.task_folder(self.root, self.state.get("task"))
        return self.folders.get(target, "")

    def apply_directions(self, from_loop=False):
        """Write queued directions into lists no turn is using. Returns how many went in.

        From the loop, just before a turn's commits, every list is free. From
        the page, the list a turn is using -- or is about to, between turns --
        is not: an uncommitted line there can be lost to the agent's rollback.
        """
        done = 0
        with self.lock:
            running = self.state.get("running")
            if from_loop:
                busy = None
            elif running:
                busy = self.workspace_of(running)
            elif self.state["paused"]:
                busy = None
            else:
                busy = self.next_folder()
            waiting = []
            for d in self.state.get("directions", []):
                folder = self.direction_folder(d["agent"])
                if not folder:
                    continue
                if busy and os.path.normcase(folder) == os.path.normcase(busy):
                    waiting.append(d)
                    continue
                if add_first(notes_file(folder), "From the operator: %s" % d["text"]):
                    done += 1
            self.state["directions"] = waiting
            self.save()
        return done

    def next_folder(self):
        """The folder the next turn will work in, without setting up a practice."""
        if self.state.get("mode") == "task":
            return work.task_folder(self.root, self.state.get("task"))
        return self.folders[PEER[self.state["next"]]]

    def answer(self, question):
        """A few plain sentences on how things stand, picked by what was asked."""
        q = question.lower()
        head_line = self.status_line()
        topics = (
            (("temperature", "temp", "creative", "brainstorm", "precise"), self.say_temperature),
            (("next", "plan", "todo", "to do", "queue", "upcoming", "going to"), self.say_next),
            (("wrong", "problem", "error", "fail", "stuck", "why", "stop", "broke", "idle",
              "trouble", "park"), self.say_trouble),
            (("done", "did", "changed", "progress", "kept", "improv", "today", "so far",
              "learn", "better"), self.say_progress),
        )
        for words, say in topics:
            if any(w in q for w in words):
                return head_line + "\n" + say()
        return head_line + "\n" + self.say_progress(brief=True)

    def status_line(self):
        v = self.view()
        run, live = v["running"], v["live"]
        if run:
            gone = int((live.get("elapsed") or 0) // 60)
            item = (live.get("item") or live.get("detail") or "").strip()
            what = self.describe({"kind": run.get("kind", "self"),
                                  "label": run.get("label") or PEER[run["agent"]]})
            return ("%s is working on %s: %s, round %s, %s kept and %s sent back so far, %d of "
                    "%d minutes gone.%s" % (
                        run["agent"], what, live.get("phase") or "starting",
                        live.get("round") or 0, live.get("accepted") or 0,
                        live.get("rejected") or 0, gone, run["minutes"],
                        (" Current item: %s" % item[:140]) if item else ""))
        if v["phase"] == "error":
            return "Orthros has stopped and needs you: %s" % (v["message"].splitlines() or ["?"])[0]
        if v["paused"]:
            why = (v["message"].splitlines() or [""])[0]
            return "Orthros is paused%s. Press Start to carry on; %s goes next." % (
                (": " + why) if why else "", v["next"])
        return "Orthros is between turns (%s); %s goes next." % (v["message"] or v["phase"],
                                                                v["next"])

    def say_progress(self, brief=False):
        out = []
        for n in NAMES:
            record = self.coding_record(n)
            if record:
                out.append("%s on coding in general: %s." % (n, record))
        for n in NAMES:
            a = self.agent(n)
            last = a.get("last") or {}
            line = ("%s has had %s, kept %s, and has %s"
                    % (n, plural(a["sessions"], "turn"), plural(a["kept"], "change"),
                       plural(len(a["goods"]), "proven version")))
            if a["rollbacks"]:
                line += ", %d rolled back" % a["rollbacks"]
            if last.get("started"):
                line += ". Last turn: %d rounds, %d kept, ended \"%s\"" % (
                    last.get("rounds") or 0, last.get("kept") or 0,
                    (last.get("reason") or "?")[:90])
            out.append(line + ".")
            if not brief:
                done = DONE_ITEM.findall(read_text(notes_file(self.folders[n])))[-3:]
                if done:
                    out.append("  Lately finished on %s: %s." % (
                        n, "; ".join(d[:90] for d in done)))
        return "\n".join(out)

    def say_next(self):
        out = []
        if self.state.get("mode") == "task":
            folder = work.task_folder(self.root, self.state.get("task"))
            items = OPEN_ITEM.findall(read_text(notes_file(folder))) if folder else []
            out.append("The task %s: %d open, next up: %s." % (
                self.state.get("task"), len(items), "; ".join(i[:90] for i in items[:3]) or
                "nothing -- the next round plans more"))
        for n in NAMES:
            folder = self.folders[n]
            items = OPEN_ITEM.findall(read_text(notes_file(folder)))
            plan = re.findall(r"^##\s*\[ \]\s*(.+?)\s*$", read_text(os.path.join(folder, "PLAN.md")),
                              re.MULTILINE)
            line = "%s's list (%s works on it): " % (n, PEER[n])
            line += ("%d open, next up: %s" % (len(items), "; ".join(i[:90] for i in items[:3]))
                     if items else "empty, so the next round plans more work")
            if plan:
                line += ". Next milestone: %s" % plan[0][:80]
            out.append(line + ".")
        waiting = self.state.get("directions") or []
        if waiting:
            out.append("%d direction(s) from you are waiting for the running turn to end."
                       % len(waiting))
        return "\n".join(out)

    def say_trouble(self):
        out = []
        v = self.view()
        if v["phase"] in ("error", "paused") and v["message"]:
            out.append("Why it stopped: %s" % v["message"].splitlines()[0][:200])
        for n in NAMES:
            last = self.agent(n).get("last") or {}
            parked = len(PARKED_ITEM.findall(read_text(notes_file(self.folders[n]))))
            bits = []
            if last.get("reason"):
                bits.append("last turn ended \"%s\"" % last["reason"][:100])
            if parked:
                bits.append("%d item(s) parked for a human on its list" % parked)
            if bits:
                out.append("%s: %s." % (n, "; ".join(bits)))
        for key, count in (self.state.get("tries") or {}).items():
            folder, _, item = key.partition("|")
            out.append("%s's item \"%s\" has ended %d turn(s) in a row; it is parked "
                       "after %s."
                       % (folder, item[:70], count, self.settings.get("park_after_tries")))
        bad = [e[1] for e in self.state["events"] if e[2] == "bad"][-3:]
        if bad:
            out.append("Recent problems: " + " | ".join(b[:110] for b in bad))
        return "\n".join(out) or "Nothing is wrong that Orthros knows of."

    def say_temperature(self):
        env = self.agent_env("A")
        code = env.get("LC_TEMP_CODE") or "0.2"
        idea = env.get("LC_TEMP_BRAINSTORM") or "0.85"
        split = "refill_temperature" in read_text(os.path.join(self.folders["A"],
                                                                 "ralph_refill.py"))
        return ("Yes, there is that lever. Rounds that write code run cold, at %s, for exact "
                "edits. Rounds that plan or invent the next work run warm, at %s, for range. "
                "%sThe reviewer runs at 0.1. Both numbers are LC_TEMP_CODE and "
                "LC_TEMP_BRAINSTORM in each agent's config.cmd."
                % (code, idea, "Of the planning rounds, checking finished work runs cold and "
                   "breaking a milestone down runs in between. " if split else ""))

    # ---------------------------------------------------------------- the page's view

    def view(self):
        with self.lock:
            st = json.loads(json.dumps(self.state))
        running = st.get("running")
        live = {}
        if running:
            peer = self.workspace_of(running)
            s = read_json(os.path.join(peer, STATUS_FILE), {}) or {}
            if self.is_mine(s, running):
                live = {k: s.get(k) for k in ("phase", "detail", "item", "round", "rounds",
                                              "ticked", "accepted", "rejected", "tokens_in",
                                              "tokens_out", "vram_free", "tok_per_sec",
                                              "attempt", "budget", "files", "files_total",
                                              "prompt_tokens", "edits_applied", "edits_failed",
                                              "symptom", "review", "outcome",
                                              "last_round_seconds", "last_in", "last_out")}
                live["log"] = (s.get("log") or [])[-6:]
            else:
                live = {"phase": "starting", "log": tail(running["log"], 6)}
            live["elapsed"] = int(now() - running["started"])
        agents = {}
        for n in NAMES:
            a = st["agents"][n]
            agents[n] = {k: a.get(k) for k in ("seconds", "tokens", "sessions", "kept",
                                               "launch_failures", "rollbacks", "carried_in",
                                               "last", "since_practice")}
            agents[n]["practice"] = (a.get("practice") or [])[-6:]
            agents[n]["version"] = short(head(self.folders[n]))
            agents[n]["proven"] = short((a.get("goods") or [a.get("good")])[-1])
            agents[n]["proven_count"] = len(a.get("goods") or [])
            agents[n]["unproven"] = len(a.get("pending") or [])
            agents[n]["unscored"] = len(a.get("proven_pending") or [])
            best = (a.get("scored") or {}).get(a.get("scored_good") or "")
            agents[n]["held_out"] = list(score_totals(best["scores"])) if best else None
            agents[n]["scores"] = [[e["at"]] + list(score_totals(e["scores"])) + [e["verdict"]]
                                   for e in sorted((a.get("scored") or {}).values(),
                                                   key=lambda e: e["at"])][-6:]
            agents[n]["rounds_24h"] = self.recent_outcomes(n)
        return {"phase": self.phase, "message": self.message, "paused": st["paused"],
                "next": st["next"], "running": running, "live": live, "agents": agents,
                "events": st["events"][-12:][::-1], "settings": self.settings,
                "simulate": self.simulate, "stop_mode": self.stop_mode,
                "chat": st.get("chat", [])[-20:], "directions": len(st.get("directions") or []),
                "alert": st.get("alert"), "gpu": self.gpu, "gpu_history": self.gpu_history[-60:],
                "backoff": max(0, int(self.backoff_until - now())),
                "mode": st.get("mode", "self"), "task": st.get("task", ""),
                "tasks": [{k: t[k] for k in ("key", "name", "folder", "open", "done", "parked")}
                          for t in work.list_tasks(self.root)],
                "exercises": work.exercises(),
                "evaluating": ({k: (st["evaluating"] or {}).get(k) for k in ("agent", "sha")}
                               if st.get("evaluating") else None),
                "hardware": {"look": self.tuner.data.get("look", {}),
                             "good": self.tuner.data.get("good", {}),
                             "trial": self.tuner.data.get("trial", {}),
                             "why": self.tuner.data.get("why", []),
                             "auto": bool(self.settings.get("auto_tune", True)),
                             "configured": self.configured()},
                "planned": {n: self.plan_minutes(n) for n in NAMES}}


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------

def serve(orthros, port):
    page = os.path.join(HERE, "orthros.html")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else (
                body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode())
            self.send_response(code)
            self.send_header("Content-Type", kind + ("; charset=utf-8" if "text" in kind or
                                                      "json" in kind else ""))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/":
                self.send(200, read_text(page), "text/html")
            elif url.path == "/api/state":
                self.send(200, orthros.view())
            elif url.path == "/api/tail":
                try:
                    offset = int(q.get("offset", "-1"))
                except ValueError:
                    offset = -1
                self.send(200, orthros.tail_log(q.get("agent", "A"), q.get("file", ""), offset))
            elif url.path == "/api/log":
                running = orthros.state.get("running") or {}
                path = running.get("log") if running.get("agent") == q.get("agent") else ""
                if not path:
                    names = sorted(f for f in os.listdir(orthros.logs)
                                   if f.endswith("-%s.log" % q.get("agent", "")))
                    path = os.path.join(orthros.logs, names[-1]) if names else ""
                self.send(200, "\n".join(tail(path, 300)) if path else "(no log yet)",
                          "text/plain")
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            try:
                if url.path == "/api/start":
                    self.send(200, {"result": orthros.start(body.get("first"), body.get("minutes"))})
                elif url.path in ("/api/pause", "/api/stop", "/api/force"):
                    mode = {"/api/pause": "pause", "/api/stop": "now", "/api/force": "force"}
                    self.send(200, {"result": orthros.stop(mode[url.path])})
                elif url.path == "/api/hardware":
                    orthros.maybe_look(force="asked from the page")
                    self.send(200, {"result": "ok"})
                elif url.path == "/api/mode":
                    self.send(200, {"result": orthros.set_mode(body.get("mode") or "self",
                                                               body.get("task"))})
                elif url.path == "/api/task":
                    self.send(200, orthros.new_task(body.get("name") or "", body.get("brief") or ""))
                elif url.path == "/api/chat":
                    reply = orthros.chat(body.get("text"), body.get("kind") or "ask",
                                         body.get("target") or "both")
                    self.send(200, {"reply": reply, "chat": orthros.state["chat"][-20:]})
                elif url.path == "/api/settings":
                    if "session_minutes" in body:
                        orthros.settings["session_minutes"] = max(5, min(480, int(
                            body["session_minutes"])))
                    if "practice_every" in body:
                        orthros.settings["practice_every"] = max(0, min(50, int(
                            body["practice_every"])))
                    write_json(orthros.settings_path, orthros.settings)
                    self.send(200, {"result": "ok"})
                else:
                    self.send(404, {"error": "not found"})
            except Exception as exc:
                self.send(500, {"error": str(exc)})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --------------------------------------------------------------------------
# simulation: two fake agents, for trying the page and the handover logic
# --------------------------------------------------------------------------

def make_sandbox():
    root = os.path.join(tempfile.gettempdir(), "orthros-sim")

    def writable(func, path, _):
        os.chmod(path, 0o666)       # git marks its objects read-only on Windows
        func(path)

    if os.path.isdir(root):
        shutil.rmtree(root, onerror=writable)
    for n in NAMES:
        folder = os.path.join(root, "OrthrosCode %s" % n)
        os.makedirs(folder)
        with open(os.path.join(folder, "agent.py"), "w") as handle:
            handle.write("# agent %s\n" % n)
        with open(os.path.join(folder, NOTES_FILES[0]), "w") as handle:
            handle.write("# Tasks\n\n- [ ] improve something\n")
        with open(os.path.join(folder, ".gitignore"), "w") as handle:
            handle.write(".localcoder*\n")
        with open(os.path.join(folder, "config.cmd"), "w") as handle:
            handle.write('set "LC_WORKSPACE=%s"\n'
                         % os.path.join(root, "OrthrosCode %s" % PEER[n]))
        git(folder, "init", "-q")
        commit_all(folder, "sim: start")
    with open(os.path.join(root, "orthros.json"), "w") as handle:
        json.dump(dict(DEFAULTS, session_minutes=2, port=8771), handle)
    return root


def fake_agent(minutes):
    """Pretend to be supervisor.py --loop: write status, edit the peer, exit."""
    own = os.getcwd()
    target = os.environ["LC_WORKSPACE"]
    if os.path.isfile(os.path.join(own, "BROKEN")):
        print("Traceback (most recent call last):\n  ImportError: simulated breakage")
        sys.exit(1)
    status_path = os.path.join(target, STATUS_FILE)
    state = {"pid": os.getpid(), "session": os.environ.get("ORTHROS_SESSION", ""),
             "started": now(), "phase": "starting", "rounds": 0, "ticked": 0,
             "accepted": 0, "rejected": 0, "tokens_in": 0, "tokens_out": 0, "log": []}
    write_json(status_path, state)
    time.sleep(2)
    end = now() + minutes * 3            # a simulated minute is three seconds
    rng = random.Random()
    while now() < end:
        if os.path.isfile(os.path.join(target, STOP_FILE)):
            os.remove(os.path.join(target, STOP_FILE))
            break
        state["rounds"] += 1
        state["round"] = state["rounds"]
        state["item"] = "improve something (%d)" % state["rounds"]
        state.update(files=["agent.py"], files_total=3, prompt_tokens=3100,
                     attempt=1, budget=2, review=None, outcome=None,
                     last_round_seconds=42, last_in=12000, last_out=2200, tok_per_sec=31.4,
                     edits_applied=1, edits_failed=0)
        # What a real turn's log carries, so the page's raw-output view has
        # something to show in a simulation.
        print("Round %d  |  %s" % (state["rounds"], state["item"]))
        print("Model: openai/localcoder with diff edit format")
        print("I'll make the smallest change that does this, in agent.py.")
        print("agent.py\n<<<<<<< SEARCH\n# agent\n=======\n# agent, improved\n>>>>>>> REPLACE")
        print("Tokens: 12k sent, 2.2k received.")
        print("Applied edit to agent.py", flush=True)
        for phase in ("working", "checking", "reviewing"):
            state["phase"] = phase
            write_json(status_path, state)
            time.sleep(0.7)
        state["review"] = "kept: it does what the item asked"
        state["outcome"] = "ticked 1 item(s)"
        if rng.random() < 0.7:
            state["accepted"] += 1
            state["ticked"] += 1
            with open(os.path.join(target, "agent.py"), "a") as handle:
                handle.write("# improvement %d\n" % rng.randint(1, 10 ** 6))
            git(target, "add", "-A")
            git(target, "commit", "-q", "-m", "round %d" % state["rounds"])
        else:
            state["rejected"] += 1
        state["tokens_in"] += 12000
        state["tokens_out"] += 2500
        state["log"] = (state["log"] + ["Round %d done" % state["rounds"]])[-80:]
        write_json(status_path, state)
    if rng.random() < 0.2:                     # sometimes leave the peer unable to start
        open(os.path.join(target, "BROKEN"), "w").close()
    state.update(phase="finished", ended_reason="Time is up.")
    write_json(status_path, state)


# --------------------------------------------------------------------------

def export(root, name):
    """Copy an agent's newest proven version into agent\\ -- the template a
    fresh copy of OrthrosCode is set up from, and what gets published.

    The proven version, not the working tree: what is in agent\\ has been
    through the other agent's hands and then run well on its own.
    """
    folder = os.path.join(root, "OrthrosCode %s" % name)
    state = read_json(os.path.join(root, ".orthros-state.json"), {}) or {}
    goods = ((state.get("agents") or {}).get(name) or {}).get("goods") or []
    if not goods:
        _, dirty = git(folder, "status", "--porcelain")
        if dirty.strip():
            print("OrthrosCode %s has changes that are not committed and no proven version "
                  "yet. Start Orthros once (it commits a baseline), then export." % name)
            return 1
    sha = goods[-1] if goods else head(folder)
    ok, listing = git(folder, "ls-tree", "-r", "--name-only", sha)
    if not ok:
        print("Could not read %s's history: %s" % (name, listing))
        return 1
    out = os.path.join(root, "agent")

    def writable(func, path, _):
        os.chmod(path, 0o666)
        func(path)

    if os.path.isdir(out):
        shutil.rmtree(out, onerror=writable)
    count = 0
    for rel in listing.splitlines():
        base = os.path.basename(rel)
        if base in MEMORY_FILES or base.startswith((".localcoder", ".aider")):
            continue
        data = subprocess.run(["git", "-C", folder, "show", "%s:%s" % (sha, rel)],
                              capture_output=True).stdout
        target = os.path.join(out, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        count += 1
    print("Exported %d files of OrthrosCode %s, version %s, into agent\\"
          % (count, name, short(sha)))
    write_evolution(root, state)
    return 0


def port_in_use(port):
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def split_patch(text):
    """[(path, one file's part of the patch)], from `git diff` output."""
    parts = re.split(r"(?m)^(?=diff --git )", text)
    out = []
    for part in parts:
        match = re.match(r"diff --git a/(\S+) b/(\S+)", part)
        if match:
            out.append((match.group(2), part if part.endswith("\n") else part + "\n"))
    return out


def match_line_endings(part, target):
    """Give a patch's hunk lines CRLF endings when the file it patches has them.

    A `git diff` is written with LF. The agents keep their .cmd files in CRLF
    -- cmd.exe misreads labels without it -- and their repositories have no
    rule to convert, so an LF patch does not match a CRLF file at all.
    """
    try:
        with open(target, "rb") as handle:
            crlf = b"\r\n" in handle.read(65536)
    except OSError:
        return part
    if not crlf or "\n@@" not in part:
        return part
    head, body = part.split("\n@@", 1)
    lines = ("@@" + body).split("\n")
    fixed = [l if (not l or l.endswith("\r") or l.startswith(("@@", "\\"))) else l + "\r"
             for l in lines]
    return head + "\n" + "\n".join(fixed)


def apply_patch(root, patch_path):
    """Put the operator's own change into both live agents, and count it as proven.

    agent\\ is only the template the agents were made from, and `--export`
    overwrites it with an agent's code -- so a fix made there never reaches
    the agents that are running. This applies a `git diff` of agent\\ (made
    with --relative=agent) to each, file by file with a three-way merge. What
    applies is checked with the same pre-launch checks Orthros uses, committed,
    and recorded as the agent's newest proven version: the operator vouches
    for it, and if it then fails to start, the usual retreat undoes it. What
    does not apply is left out and listed.
    """
    settings = dict(DEFAULTS, **(read_json(os.path.join(root, "orthros.json"), {}) or {}))
    if port_in_use(int(settings.get("port") or 8770)):
        print("Orthros is running. Close its window first: it keeps its own copy of which "
              "versions are proven, and would overwrite this.")
        return 1
    parts = split_patch(read_text(patch_path))
    if not parts:
        print("%s holds no file changes." % patch_path)
        return 1
    orthros = Orthros(root)
    status = 0
    for n in NAMES:
        folder = orthros.folders[n]
        if not os.path.isdir(os.path.join(folder, ".git")):
            print("%s: not set up; skipped." % n)
            continue
        before = commit_all(folder, "Orthros: before the operator's patch")
        applied, missed = [], []
        for rel, part in parts:
            ok, out = False, ""
            # Exact first, in the file's own line endings; then forgiving of
            # whitespace (a file an editor left with mixed endings); then a
            # three-way merge, which needs the patch's base in the history.
            for text, how in ((match_line_endings(part, os.path.join(folder, rel)), []),
                              (part, ["--ignore-whitespace"]), (part, ["--3way"])):
                fd, tmp = tempfile.mkstemp(suffix=".patch")
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                ok, out = git(folder, "apply", "--whitespace=nowarn", *how, tmp)
                os.remove(tmp)
                if ok:
                    break
                # A failed 3-way leaves markers in this file: put it alone
                # back. This was `checkout -- .`, which put back every file
                # applied before it as well -- in each patch up to 2026-09-24,
                # README.md and SKILLS.md, undone by config.cmd's clash with the
                # agents' own settings and reported as applied all the same.
                git(folder, "reset", "-q", "--", rel)
                git(folder, "checkout", "-q", "--", rel)
            if ok:
                applied.append(rel)
                continue
            missed.append("%s (%s)" % (rel, " ".join(out.split())[:100]))
            git(folder, "reset", "-q", "--", rel)
            if git(folder, "cat-file", "-e", "HEAD:%s" % rel)[0]:
                git(folder, "checkout", "HEAD", "--", rel)
            else:
                try:
                    os.remove(os.path.join(folder, rel))
                except OSError:
                    pass
        if not applied:
            print("%s: nothing applied. Left out: %s" % (n, "; ".join(missed)))
            status = 1
            continue
        problems = orthros.preflight(n)
        if problems:
            git(folder, "reset", "--hard", "-q", before)
            git(folder, "clean", "-fdq")
            print("%s: the patched version fails its checks, so it was put back as it was: %s"
                  % (n, "; ".join(problems)[:600]))
            if missed:
                print("   Left out because they did not fit %s's code: %s"
                      % (n, "; ".join(m.split(" (")[0] for m in missed)))
                print("   Most likely %s's code has moved on from the version this patch was "
                      "made against, so tests arrived without the code they test." % n)
            status = 1
            continue
        sha = commit_all(folder, "Orthros: operator patch %s" % os.path.basename(patch_path))
        me = orthros.agent(n)
        if sha not in me["goods"]:
            me["goods"].append(sha)
            git(folder, "tag", "-f", "orthros/proven-%d" % len(me["goods"]), sha)
        me["good"], me["pending"], me["weak_streak"] = sha, [], 0
        print("%s: applied %d file(s), passed its checks, now proven at %s.%s"
              % (n, len(applied), short(sha),
                 (" Left out: " + "; ".join(missed)) if missed else ""))
        if missed:
            status = 1
    orthros.save()
    return status


def write_evolution(root, state):
    """EVOLUTION.md: the story so far, for anyone following the project."""
    agents = state.get("agents") or {}
    lines = ["# Evolution", "",
             "Written by `orthros.py --export`. Each agent's totals, then the most recent "
             "events, newest first.", "",
             "| agent | turns | hours | tokens | changes kept | proven versions | rolled back "
             "| carried in |", "|---|---|---|---|---|---|---|---|"]
    for n in NAMES:
        a = agents.get(n) or {}
        lines.append("| %s | %d | %.1f | %s | %d | %d | %d | %d |" % (
            n, a.get("sessions", 0), a.get("seconds", 0) / 3600.0,
            "{:,}".format(a.get("tokens", 0)), a.get("kept", 0), len(a.get("goods") or []),
            a.get("rollbacks", 0), a.get("carried_in", 0)))
    lines += ["", "## Recent events", ""]
    for ts, text, _ in reversed((state.get("events") or [])[-40:]):
        lines.append("- %s  %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)), text))
    with open(os.path.join(root, "EVOLUTION.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def open_window(url):
    """The page in a window of its own: no tabs, no address bar.

    Edge ships with Windows 10 and 11 and, like Chrome, opens a bare app
    window with --app. Nothing to install. Falls back to an ordinary tab.
    """
    env = os.environ.get
    candidates = [os.path.join(base, *tail) for base in
                  (env("ProgramFiles(x86)", ""), env("ProgramFiles", ""), env("LOCALAPPDATA", ""))
                  if base for tail in (("Microsoft", "Edge", "Application", "msedge.exe"),
                                       ("Google", "Chrome", "Application", "chrome.exe"))]
    candidates += [shutil.which(n) or "" for n in ("msedge", "chrome", "chromium")]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                subprocess.Popen([path, "--app=" + url, "--window-size=1240,1000"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
                return
            except OSError:
                continue
    webbrowser.open(url)


# The memory hog --doctor runs inside an agent's own check limits: it must end
# in a MemoryError, not in the machine running short.
DOCTOR_HOG = r"""import sys
import ralph_contain as contain
proc = contain.run([sys.executable, "-c", "x = bytearray(3 * 1024 ** 3)"], memory_mb=512,
                   text=True, capture_output=True, timeout=120)
print("CONTAINED" if "MemoryError" in (proc.stderr or "") else "NOT CONTAINED rc=%s" % proc.returncode)
"""


def doctor(root, out=print):
    """Check what can only be checked on this machine. Returns how many FAILs.

    Read-only: it starts no turn and changes nothing. Most of the setup
    trouble so far -- a Python 3.14 venv, a page file too small -- would have
    been one line of this; and several of the loop's parts (the limits on the
    model's code, the test suite's time against its 240-second gate) can only
    be tried on the machine that runs them.
    """
    fails = [0]

    def say(level, text):
        if level == "FAIL":
            fails[0] += 1
        out("%-4s  %s" % (level, text))

    say("OK" if sys.version_info >= (3, 8) else "FAIL",
        "Orthros's Python: %s" % sys.version.split()[0])
    try:
        free_disk = shutil.disk_usage(root).free // 1048576
        say("OK" if free_disk > 10240 else "WARN", "free disk: %d GB" % (free_disk // 1024))
    except OSError:
        pass
    reading = memory()
    if reading:
        say("OK" if reading[0] > 8192 else "WARN",
            "free commit (RAM + page file) now: %d GB -- a 27B model needs a lot of it"
            % (reading[0] // 1024))
    say("OK" if len(work.eval_exercises()) >= 8 else "FAIL",
        "%d held-out exercises, %d to practise on" % (len(work.eval_exercises()),
                                                     len(work.exercises())))
    settings = dict(DEFAULTS, **(read_json(os.path.join(root, "orthros.json"), {}) or {}))
    say("OK", "proof by score %s (every %s good turns, %s exercises at %s min); practice every %s"
        % ("on" if settings.get("prove_by_score") else "OFF", settings.get("eval_every"),
           settings.get("eval_count"), settings.get("eval_minutes"),
           settings.get("practice_every")))
    lms = shutil.which("lms") or next((p for p in (
        os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe"),) if os.path.isfile(p)), "")
    say("OK" if lms else "WARN", "LM Studio's lms: %s" % (lms or "not found on PATH"))
    for name in NAMES:
        folder = agent_folder(root, name)
        if not os.path.isdir(os.path.join(folder, ".git")):
            say("FAIL", "%s: no agent at %s -- run SETUP.bat" % (name, folder))
            continue
        python = os.path.join(folder, "venv", "Scripts", "python.exe")
        python = python if os.path.isfile(python) else sys.executable
        try:
            proc = subprocess.run([python, "--version"], capture_output=True, text=True,
                                  timeout=60)
            version = (proc.stdout or proc.stderr).strip()
        except (OSError, subprocess.TimeoutExpired):
            version = ""
        say("OK" if version else "FAIL", "%s's Python: %s" % (name, version or "does not run"))
        started = now()
        try:
            proc = subprocess.run([python, "-m", "unittest", "discover", "-s", ".", "-p",
                                   "test_*.py", "-q"], cwd=folder, capture_output=True,
                                  text=True, timeout=600, encoding="utf-8", errors="replace")
            took = now() - started
            tail_ = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-1:]
            if proc.returncode == 5 or "Ran 0 tests" in " ".join(tail_) + (proc.stderr or ""):
                say("WARN", "%s has no tests" % name)
            elif proc.returncode != 0:
                say("FAIL", "%s's tests fail: %s" % (name, " ".join(tail_)))
            else:
                say("OK" if took < 120 else "WARN",
                    "%s's tests pass in %d s%s" % (name, took, "" if took < 120 else
                                                  " -- rounds are failed past 240 s; find the "
                                                  "slow ones"))
        except subprocess.TimeoutExpired:
            say("FAIL", "%s's tests did not finish in 10 minutes" % name)
        except OSError as exc:
            say("FAIL", "%s's tests could not run: %s" % (name, exc))
        if os.name != "nt":
            say("WARN", "%s: the limits on the model's code apply on Windows only" % name)
        elif os.path.isfile(os.path.join(folder, "ralph_contain.py")):
            try:
                proc = subprocess.run([python, "-c", DOCTOR_HOG], cwd=folder,
                                      capture_output=True, text=True, timeout=180)
                verdict = (proc.stdout or proc.stderr or "").strip().splitlines()[-1:] or [""]
            except (OSError, subprocess.TimeoutExpired) as exc:
                verdict = [str(exc)]
            ok = verdict[0] == "CONTAINED"
            say("OK" if ok else "FAIL", "%s: the model's code runs inside memory limits%s" % (
                name, "" if ok else " -- it does not (%s)" % verdict[0][:120]))
        else:
            say("WARN", "%s has no ralph_contain.py yet: apply the latest patch" % name)
    out("")
    out("%s" % ("All clear." if not fails[0] else
                "%d problem(s) to fix before an unattended run." % fails[0]))
    return fails[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--fake-agent", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--minutes", type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--export", nargs="?", const="A", choices=NAMES,
                        help="copy an agent's newest proven version into agent\\ and exit")
    parser.add_argument("--probe", action="store_true",
                        help="look at the hardware now and put fitting settings on trial")
    parser.add_argument("--doctor", action="store_true",
                        help="check this machine and both agents, change nothing, and say "
                             "what to fix")
    parser.add_argument("--resume", action="store_true",
                        help="start straight away if Orthros was running when it last "
                             "stopped -- killed, or the machine restarted -- and not paused")
    parser.add_argument("--apply-patch", metavar="PATCH",
                        help="apply a `git diff --relative=agent` of agent\\ to both live "
                             "agents, check it, and count it as proven")
    args = parser.parse_args()
    if args.fake_agent:
        return fake_agent(args.minutes)
    if args.export:
        return export(HERE, args.export)
    if args.apply_patch:
        return apply_patch(HERE, args.apply_patch)
    if args.doctor:
        return 1 if doctor(HERE) else 0
    if args.probe:
        orthros = Orthros(HERE)
        orthros.event = lambda text, kind="info": print(text)
        orthros.maybe_look(force="asked")
        print("On trial for the next turn: %s" % (tune.describe(orthros.tuner.data["trial"])
                                                   or "nothing -- the current settings fit"))
        return 0
    if not args.simulate and not all(os.path.isdir(os.path.join(HERE, "OrthrosCode %s" % n, ".git"))
                                     for n in NAMES):
        print("The two agents are not set up yet. Run SETUP.bat first (see README.md).")
        return 1

    root = make_sandbox() if args.simulate else HERE
    orthros = Orthros(root, simulate=args.simulate)
    port = int(orthros.settings.get("port") or 8770)
    try:
        serve(orthros, port)
    except OSError:
        print("Port %d is taken -- is Orthros already running? Open http://127.0.0.1:%d/"
              % (port, port))
        return 1
    url = "http://127.0.0.1:%d/" % port
    print("Orthros%s -- %s" % (" (simulation)" if args.simulate else "", url))
    print("Close this window to stop Orthros. A session in progress finishes on its own.")
    if not args.no_browser:
        open_window(url)
    loop = threading.Thread(target=orthros.loop, daemon=True)
    loop.start()
    if args.resume:
        if orthros.state.get("wanted"):
            orthros.event("resuming: Orthros was running when it last stopped", "start")
            orthros.start()
        else:
            print("Not resuming: Orthros was paused or stopped by hand, or gave up. "
                  "Press Start when ready.")
    if orthros.settings.get("gpu_telemetry", True):
        threading.Thread(target=orthros.watch_gpu, daemon=True).start()
    try:
        while True:
            time.sleep(15)
            if not loop.is_alive():
                # The loop catches what it can; this is for what it cannot.
                # A dead loop thread leaves a page that looks alive and a
                # machine that does nothing.
                orthros.event("Orthros's loop stopped unexpectedly; starting it again", "bad")
                orthros.pause("Orthros's own loop died and was restarted. Look at the console "
                              "window for the traceback, then press Start.", error=True)
                loop = threading.Thread(target=orthros.loop, daemon=True)
                loop.start()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
