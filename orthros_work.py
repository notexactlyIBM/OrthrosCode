"""What a turn works on: the twin's code, a task, a tool or a practice exercise.

Orthros has three modes. In self-improvement mode each agent works on the
other's code, as it always has -- and every few turns one turn is instead a
practice exercise, scored by tests the agent never sees, so that "better" is
measured on coding in general and not only on editing itself. In task mode
both agents take turns on one project in tasks\\<name>, with the same turn
lengths, handovers and safety nets. In serve mode (orthros_service.py) the
card serves the network, and the agents take turns only on the tools other
machines ask for, in tools\\<name>.

Standard library only, like orthros.py.
"""

import contextlib
import ctypes
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXERCISES = os.path.join(HERE, "exercises")
EVALS = os.path.join(HERE, "evals")     # held out: scoring versions, never practice
KEEP_PRACTICE = 6            # practice folders kept per agent, newest first
# One SQLite file at the root: a row per round from both agents (their
# agent/ralph_ledger.py writes it) and, in serve mode, a row per request.
LEDGER = "ledger.sqlite"
# A folder to work on that is not a git repository is copied whole into the
# task folder. Past this size, say so rather than fill the disk.
COPY_LIMIT_MB = 512
SKIP_COPY = ("__pycache__", "*.pyc", ".localcoder*", ".aider*", "venv", "node_modules")

TASK_PROMPT = """# How to work

Do the NEXT unfinished item in the task list, and only that one.

1. Find the first item still marked `- [ ]`.
2. Make the change yourself -- edit or create the files. Never describe an
   edit instead of making it, and never ask anyone to run or apply anything.
3. Re-read what you changed: complete, valid, and consistent with the rest.
4. Only if it is good: tick it (`- [x]`) and add a one-line `*Note*:` under it.
5. Stop. Do not start the next item.

Too big for one round? Split it into smaller `- [ ]` items underneath, tick
nothing, and stop. If an item ends with `Done when:`, that check is what
finished means. Before building something, make sure it is not already
there: write `FIND: <name>` in the task list and stop; the answer comes next
round. `DIGEST: <file> -- <question>` reads a file too big to be sent.

Write tests as you go: `test_*.py` files with `unittest.TestCase` classes.
They run after every edit, and a change that breaks them is undone. Keep
every file small -- a new module rather than a big one. Use Python and its
standard library unless the task says otherwise.

**Be brief.** No narration. The edit, then one line.

# The task

%s
"""

TASK_LIST = """# Task: %s

The task itself is in RALPH_PROMPT.md, sent with every round.

## Tasks

- [ ] Read the task in RALPH_PROMPT.md and write it into this list as small `- [ ]` items, below this one -- one change to one file each, naming the file in backticks, each ending with `Done when:` and a check anyone can make. Start with the layout: which files, and what each is for. Then tick this item.

## When out of tasks

Compare the code with the task in RALPH_PROMPT.md. Add items for what is
missing, what is broken, and what has no test. Then make it better to use.
"""

# A tool is a task with a fixed shape, so that a program on another machine
# can run it knowing nothing about it but its name and what it is for.
TOOL_CONTRACT = """

# The tool contract

This is a tool other programs run, so its shape is fixed. `tool.py` is the
entry point. It is started as `python tool.py` in this folder, with no
arguments, and is sent its whole input on stdin. It prints its answer to
stdout, and nothing else goes there, then exits 0. If it cannot answer, it
prints one line saying why to stderr and exits 1. It never waits for anything
more and it answers within two minutes.

Its tests run it exactly that way, as a subprocess, and include what an
adversary would send: nothing, garbage, far too much. It must refuse those
cleanly -- never hang, never crash.
"""

IGNORE = ".localcoder*\n.aider*\nvenv/\n__pycache__/\n*.pyc\n*.tmp\n"
MARKER = ("Looked after by Orthros: the agents commit and roll back here.\n")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "task"


def find_lms(configured=""):
    """LM Studio's lms.exe: the configured path (LC_LMS_PATH), the usual places, then PATH.

    One list for every caller -- a turn, --doctor, SETUP.bat -- so what one
    finds the others find. Until 2026-11-07 --doctor looked in two places and
    could say "not found" for an lms that every turn found.
    """
    tail = os.path.join("resources", "app", ".webpack", "lms.exe")
    candidates = [configured, os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe"),
                  os.path.expandvars(os.path.join(r"%LOCALAPPDATA%\Programs\LM Studio", tail)),
                  os.path.expandvars(os.path.join(r"%ProgramFiles%\LM Studio", tail))]
    candidates += [os.path.join("%s:\\" % d, "LM Studio", tail) for d in "CDEFGH"]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return shutil.which("lms")


def git(folder, *args):
    try:
        proc = subprocess.run(["git", "-C", folder, "-c", "user.name=Orthros",
                               "-c", "user.email=orthros@localhost"] + list(args),
                              capture_output=True, text=True, timeout=120,
                              encoding="utf-8", errors="replace")
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def write(path, body):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """True once written; False when the disk would not take it -- for the caller to say."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory_status():
    """Windows's memory figures (a MEMORYSTATUSEX), or None off Windows or when it will
    not answer. One reading for the referee's checks and the tuner's look."""
    if os.name != "nt":
        return None
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status


_MEMO = {}


def memo(key, paths, compute):
    """compute() again only once one of `paths` has changed (its mtime or size), else the
    value from last time. The page and the window each poll every two seconds, and every
    poll read every task's and tool's files to list them (2026-11-07)."""
    stamp = tuple(_stamp(p) for p in paths)
    hit = _MEMO.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = compute()
    _MEMO[key] = (stamp, value)
    return value


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


TASKS_HEADING = re.compile(r"^##[ \t]+Tasks[ \t]*\n", re.MULTILINE)


def add_first(path, text):
    """Put one open item at the top of the `## Tasks` section -- the next round takes it.

    The end of the list when there is no such heading. Nothing when there is
    no task list at all: an agent that keeps none is not one to steer.
    """
    body = read(path)
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
    write(path, body)
    return True


def seed(folder, prompt, task_list):
    """Make `folder` a workspace the agents can use: prompt, list, git, marker."""
    os.makedirs(folder, exist_ok=True)
    write(os.path.join(folder, "RALPH_PROMPT.md"), prompt)
    write(os.path.join(folder, "orthros_tasks.md"), task_list)
    if not os.path.isfile(os.path.join(folder, ".gitignore")):
        write(os.path.join(folder, ".gitignore"), IGNORE)
    write(os.path.join(folder, ".localcoder-managed"), MARKER)
    if not os.path.exists(os.path.join(folder, ".git")):       # a file in a worktree
        git(folder, "init", "-q")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "Orthros: the starting point")


# ---------------------------------------------------------------- tasks

def tasks_root(root, tool=False):
    """tasks\\, or tools\\ for the tools serve mode builds."""
    return os.path.join(root, "tools" if tool else "tasks")


def create_task(root, name, brief, tool=False, source=""):
    """A new project in tasks\\<slug>, or a tool in tools\\<slug>. With `source`, the
    project is an existing git repository, worked on through a worktree of it
    (attach). Returns (slug, error)."""
    brief = (brief or "").strip()
    if len(brief) < 10:
        return "", "Say what to build -- a sentence at least."
    key = slug(name or brief[:40])
    folder = os.path.join(tasks_root(root, tool), key)
    if os.path.exists(folder):
        return "", "There is already a %s called %s. Pick another name." % (
            "tool" if tool else "task", key)
    note = ""
    if (source or "").strip():
        note, problem = attach(source, folder, key)
        if problem:
            return "", problem
    seed(folder, TASK_PROMPT % (brief + (TOOL_CONTRACT if tool else "")), TASK_LIST % (name or key))
    write(os.path.join(folder, "TASK.md"), "# %s\n\n%s\n%s" % (name or key, brief, note))
    return key, ""


def git_out(folder, *args, data=None):
    """(ok, output) of a git command; `data` goes to its stdin."""
    try:
        proc = subprocess.run(["git", "-C", folder, "-c", "user.name=Orthros",
                               "-c", "user.email=orthros@localhost"] + list(args),
                              input=data, capture_output=True, timeout=600)
        out = (proc.stdout or b"") + (proc.stderr or b"")
        return proc.returncode == 0, out.decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


SOURCE_LINE = re.compile(r"^Works on a copy of (.+?)(?:, on the branch (\S+)|, copied here)\.", re.M)


def folder_mb(path):
    """Megabytes of files under `path`, skipping what a copy skips."""
    total = 0
    for root_, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_COPY]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root_, name))
            except OSError:
                pass
    return total / 1048576.0


def copy_in(source, folder):
    """A folder that is not a git repository -- files to process, say -- is copied
    whole into the task folder, which becomes a repository of its own: the agents
    work there, the results are there, and nothing in the source changes. Returns
    (note, error)."""
    size = folder_mb(source)
    if size > COPY_LIMIT_MB:
        return "", ("%s holds %d MB; a folder that is not a git repository is copied whole, "
                    "and that stops at %d MB. Run  git init  there and it is worked on as a "
                    "worktree instead, whatever its size." % (source, size, COPY_LIMIT_MB))
    try:
        shutil.copytree(source, folder, ignore=shutil.ignore_patterns(*SKIP_COPY))
    except (OSError, shutil.Error) as exc:
        wipe(folder)
        return "", "Could not copy %s: %s" % (source, str(exc)[-200:])
    return ("\nWorks on a copy of %s, copied here. Nothing in %s changes: the results are in "
            "this folder.\n" % (source, source)), ""


def attach(source, folder, key):
    """Work on an existing folder without touching it. A git repository: a worktree
    of it in `folder`, on a branch of its own, starting from the repository as it
    stands -- uncommitted changes included; its owner takes the work by merging
    the branch. Any other folder: a copy (copy_in). A rollback here can never
    reach their files either way. Returns (note, error)."""
    source = os.path.abspath(os.path.expandvars(source.strip().strip('"')))
    if not os.path.isdir(source):
        return "", "There is no folder %s." % source
    ok, top = git_out(source, "rev-parse", "--show-toplevel")
    if not ok:
        return copy_in(source, folder)
    top, branch = os.path.normpath(top), "orthros/" + key
    ok, out = git_out(top, "worktree", "add", "-b", branch, folder, "HEAD")
    if not ok:
        return "", "Could not make a working copy of %s: %s" % (top, out[-300:])
    # The agents start from the folder as it is, not as it was last committed.
    note = ""
    try:
        diff = subprocess.run(["git", "-C", top, "diff", "--binary", "HEAD"],
                              capture_output=True, timeout=600).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        diff, note = b"", " Its uncommitted changes could not be read (%s)." % exc
    if diff.strip():
        ok, out = git_out(folder, "apply", "--binary", "--whitespace=nowarn", data=diff)
        if not ok:
            note = " Its uncommitted changes could not be carried over (%s)." % out[-160:]
    _, listing = git_out(top, "ls-files", "--others", "--exclude-standard", "-z")
    for rel in filter(None, listing.split("\0")):
        target = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            shutil.copy2(os.path.join(top, rel), target)
        except OSError:
            pass
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "Orthros: %s as it stood, uncommitted changes included" % top)
    # The agents' own files stay out of the branch: ignored for the repository,
    # without a change to its .gitignore.
    ok, common = git_out(top, "rev-parse", "--git-common-dir")
    if ok:
        exclude = os.path.join(top, common, "info", "exclude")
        have = read(exclude)
        missing = [p for p in IGNORE.split() if p not in have.split()]
        if missing:
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            write(exclude, have.rstrip("\n") + ("\n" if have.strip() else "") +
                  "# Orthros's agents\n" + "\n".join(missing) + "\n")
    return ("\nWorks on a copy of %s, on the branch %s. Nothing in %s itself changes: "
            "merge the branch to take the work.%s\n" % (top, branch, top, note)), ""


def folders(path=""):
    """For the page's folder picker: `path` and the folders in it. Drives, when
    there is no path."""
    path = os.path.abspath(path) if path else ""
    if not path or not os.path.isdir(path):
        drives = ["%s:\\" % d for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir("%s:\\" % d)]
        return {"path": "", "parent": "", "dirs": drives or ["/"], "git": False}
    try:
        names = sorted((n for n in os.listdir(path) if not n.startswith(("$", "."))
                        and os.path.isdir(os.path.join(path, n))), key=str.lower)[:300]
    except OSError:
        names = []
    parent = os.path.dirname(path.rstrip("\\/"))
    return {"path": path, "parent": "" if parent == path.rstrip("\\/") else parent,
            "dirs": [os.path.join(path, n) for n in names],
            "git": os.path.exists(os.path.join(path, ".git"))}


def task_folder(root, key, tool=False):
    folder = os.path.join(tasks_root(root, tool), slug(key))
    return folder if os.path.isdir(folder) else ""


def list_tasks(root, tool=False):
    """[{key, name, open, done, parked}] for every task (or tool) folder, newest first."""
    out = []
    base = tasks_root(root, tool)
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for key in names:
        folder = os.path.join(base, key)
        if not os.path.isdir(folder):
            continue
        files = [os.path.join(folder, f) for f in ("TASK.md", "orthros_tasks.md", "DONE.md")]
        out.append(dict(memo(("task", folder), [folder] + files,
                             lambda: task_entry(key, folder, files))))
    return sorted(out, key=lambda t: -t["made"])


def task_entry(key, folder, files):
    brief, notes, done = (read(f) for f in files)
    title = (brief.splitlines() or ["# " + key])[0]
    source = SOURCE_LINE.search(brief)
    return {"key": key, "name": title.lstrip("# ").strip() or key,
            "folder": folder, "source": source.group(1) if source else "",
            "branch": (source.group(2) or "") if source else "",
            "open": len(re.findall(r"^\s*[-*]\s*\[ \]", notes, re.M)),
            "done": len(re.findall(r"^\s*[-*]\s*\[[xX]\]", notes, re.M))
            + len(re.findall(r"^\s*[-*]\s*\[[xX]\]", done, re.M)),
            "parked": len(re.findall(r"^\s*[-*]\s*\[!\]", notes, re.M)),
            "made": os.path.getmtime(folder)}


# ---------------------------------------------------------------- practice

def exercises(base=EXERCISES):
    try:
        return sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d, "hidden")))
    except OSError:
        return []


def eval_exercises():
    return exercises(EVALS)


def next_exercise(history):
    """The exercise tried longest ago (or never)."""
    names = exercises()
    if not names:
        return ""
    last = {h[1]: h[0] for h in history}
    return min(names, key=lambda n: (last.get(n, 0), n))


def start_practice(root, agent, exercise, held_out=False):
    """A fresh copy of an exercise, without its hidden tests. Returns the folder.

    A held-out exercise goes to evals-runs\\ rather than practice\\, and its
    folder is named by number, not by exercise: the name is not to turn up in
    anything the agents keep.
    """
    source = os.path.join(EVALS if held_out else EXERCISES, exercise)
    base = os.path.join(root, "evals-runs" if held_out else "practice")
    label = "eval%02d" % eval_exercises().index(exercise) if held_out else exercise
    folder = os.path.join(base, "%s-%s-%s" % (agent, label, time.strftime("%Y%m%d-%H%M%S")))
    shutil.copytree(source, folder, ignore=shutil.ignore_patterns("hidden", "__pycache__"))
    brief = read(os.path.join(folder, "task.md"))
    first, _, items = brief.partition("\n\n")
    seed(folder, TASK_PROMPT % first.strip(),
         "# Practice: %s\n\n## Tasks\n\n%s\n" % (label, items.strip()))
    prune_practice(base, agent, keep=KEEP_PRACTICE * (3 if held_out else 1))
    return folder


def prune_practice(base, agent, keep=KEEP_PRACTICE):
    try:
        mine = sorted((d for d in os.listdir(base) if d.startswith(agent + "-")),
                      key=lambda d: d.rsplit("-", 2)[-2:])
    except OSError:
        return
    for old in mine[:-keep]:
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)


# ---------------------------------------------------------------- running their code

# The solutions scored here are the model's code. Like the agents' own checks
# (agent/ralph_contain.py), each run gets a Windows job: 4 GB between its
# processes, 32 of them, all killed when it ends -- or a process group of its
# own elsewhere. Written again here rather than imported: the agents rewrite
# agent\, and the referee must not depend on anything they can break.
SCORE_MEMORY_MB = 4096

HARNESS = ("ORTHROS_", "LC_")


def check_env(quick=False):
    """The environment the model's code runs in: this machine's, with none of
    the harness's settings. The one definition for every run of it -- the
    pre-launch check, --doctor, a task's tests, a tool.

    Built the same way for every check, so what --doctor passes the pre-launch
    check passes too. On 2026-09-26 the pre-launch check ran in a turn's own
    environment, which names Orthros's ledger: the ledger's tests wrote into
    it, failed, and stopped Orthros on A's baseline -- while --doctor, without
    that environment, had said all clear. Dropped by prefix, not by name, so
    the next setting a turn needs cannot leak in either.
    """
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(HARNESS)}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if quick:
        env["LC_QUICK_TESTS"] = "1"      # the suite the check after each round runs
    return env


# Each run of the model's code gets a temp folder of its own, emptied when it
# ends. Its tests make git repos in temp and remove them with
# rmtree(ignore_errors=True), which on Windows cannot delete git's read-only
# files and says nothing: by 2026-10-18 the user's temp held 17,884 of them,
# and logging in took 12 minutes while Windows walked through them. The same
# prefix as agent/ralph_contain.py, so either one sweeps what the other left.
CHECK_TEMP_PREFIX = "lc-check-"
STALE_TEMP_SECONDS = 3600


def wipe(path):
    """Remove `path` and everything in it, read-only files too. Never raises."""
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def own_temp(env):
    """`env` with TEMP, TMP and TMPDIR naming a new folder, wiped afterwards.
    Also clears check temps older than an hour: a run killed with Orthros."""
    base = tempfile.gettempdir()
    try:
        for name in os.listdir(base):
            path = os.path.join(base, name)
            if name.startswith(CHECK_TEMP_PREFIX) \
                    and time.time() - os.path.getmtime(path) > STALE_TEMP_SECONDS:
                wipe(path)
    except OSError:
        pass
    temp = tempfile.mkdtemp(prefix=CHECK_TEMP_PREFIX)
    try:
        yield dict(env, TEMP=temp, TMP=temp, TMPDIR=temp)
    finally:
        wipe(temp)


def _job():
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic),
                        ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x200 | 0x8 | 0x2000   # memory, count, kill
        info.BasicLimitInformation.ActiveProcessLimit = 32
        info.JobMemoryLimit = SCORE_MEMORY_MB * 1024 * 1024
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        return (kernel32, job)
    except Exception:
        return None


def contained_run(cmd, timeout, input=None, **kwargs):
    """subprocess.run with captured text output, inside the limits above and
    with a temp of its own. `input`, if given, is sent on stdin."""
    with own_temp(kwargs.pop("env", None) or os.environ) as env:
        return _contained_run(cmd, timeout, input, env=env, **kwargs)


def _contained_run(cmd, timeout, input, **kwargs):
    job = _job()
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdin=None if input is None else subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **kwargs)
    try:
        if job:
            job[0].AssignProcessToJobObject(job[1], int(proc._handle))
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            if job:
                job[0].TerminateJobObject(job[1], 1)
            elif os.name != "nt":
                try:
                    os.killpg(proc.pid, 9)
                except OSError:
                    pass
            proc.kill()
            try:
                proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, ValueError, OSError):
                pass
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    finally:
        if job:
            job[0].CloseHandle(job[1])


RAN = re.compile(r"^Ran (\d+) tests?", re.M)
FAILED = re.compile(r"^FAILED \((.*?)\)", re.M)


def run_tests(folder, python, tests_dir=None, timeout=300):
    """(passed, total) for the unittest tests in `tests_dir` (default: the folder's own),
    run against the code in `folder`. (0, 0) when there are none; None if they could not run."""
    return run_tests_output(folder, python, tests_dir, timeout)[0]


def run_tests_output(folder, python, tests_dir=None, timeout=300):
    """run_tests, and the runner's output with it: ((passed, total), text)."""
    tests_dir = tests_dir or folder
    try:
        expected = sum(read(os.path.join(tests_dir, f)).count("def test_")
                       for f in os.listdir(tests_dir) if f.startswith("test_") and f.endswith(".py"))
    except OSError:
        return None, ""
    if not expected:
        return (0, 0), ""
    env = dict(check_env(), PYTHONPATH=folder, PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = contained_run([python, "-m", "unittest", "discover", "-s", tests_dir, "-t",
                              tests_dir, "-p", "test_*.py"], timeout, cwd=folder, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return (0, expected), ""
    out = (proc.stderr or "") + (proc.stdout or "")
    ran = RAN.search(out)
    if not ran:
        return (0, expected), out
    ran = int(ran.group(1))
    bad = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)",
                                          (FAILED.search(out) or re.match("", "")).group(0)))
    if ran < expected:                     # a module that would not even import
        return (max(0, ran - bad), expected), out
    return (max(0, ran - bad), ran), out


def score_practice(folder, exercise, python, held_out=False):
    """(passed, total) of the hidden tests against the practice folder's code."""
    return score_practice_detail(folder, exercise, python, held_out)[0]


def score_practice_detail(folder, exercise, python, held_out=False, most=4):
    """((passed, total), ["test_name (ErrorType)"]) -- which hidden tests failed
    and how, for a practice exercise; never for a held-out one.

    Names and the kind of error only, not the values: the practice exercises
    repeat, and the expected values in a note the twin reads are answers it
    could tune the agent to, which would make the score measure memory.
    """
    score, out = run_tests_output(folder, python, os.path.join(
        EVALS if held_out else EXERCISES, exercise, "hidden"))
    if held_out or not out:
        return score, []
    lines = out.splitlines()
    failed = []
    for i, line in enumerate(lines):
        head = re.match(r"^(?:FAIL|ERROR): (\w+)", line)
        if not head:
            continue
        kind = "failed"
        for later in lines[i + 1:]:
            if re.match(r"^(?:FAIL|ERROR): ", later):
                break
            found = re.match(r"^((?:[A-Za-z_][\w.]*)?(?:Error|Exception))\b", later)
            if found:
                kind = found.group(1)
        failed.append("%s (%s)" % (head.group(1), kind))
    return score, failed[:most]


# ---------------------------------------------------------------- what "better" means

BETTER = """
# What better means

Better means writing working code on projects it has never seen -- fewer
rounds per item, fewer changes sent back, more tests passing -- not only
getting better at editing itself. FIELD_REPORT.md has the evidence: lines
starting **Held-out score** say how a version did on exercises it never
practises on, compared with the version before it -- a version that does
worse is rolled back, and its changes never reach the twin. Lines starting
**Practice** are exercises scored by tests the agent never saw, and lines
starting **Task** are real projects. A change is worth making when it moves
those numbers. Improving the machinery that improves itself counts only when
it shows up there too.
"""


def ensure_better(folder):
    """Put the current definition of better into a folder's standing prompt."""
    path = os.path.join(folder, "RALPH_PROMPT.md")
    body = read(path)
    if not body:
        return False
    if "# What better means" not in body:
        write(path, body.rstrip() + "\n" + BETTER)
        return True
    # An older definition is replaced, up to the next heading or the end.
    start = body.index("# What better means")
    rest = body[start + 1:]
    nxt = rest.find("\n# ")
    end = len(body) if nxt < 0 else start + 1 + nxt + 1
    fixed = body[:start].rstrip() + "\n" + BETTER + ("\n" + body[end:] if nxt >= 0 else "")
    if fixed != body:
        write(path, fixed)
        return True
    return False
