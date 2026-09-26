"""What a turn works on: the twin's code, a task, or a practice exercise.

Orthros has two modes. In self-improvement mode each agent works on the
other's code, as it always has -- and every few turns one turn is instead a
practice exercise, scored by tests the agent never sees, so that "better" is
measured on coding in general and not only on editing itself. In task mode
both agents take turns on one project in tasks\\<name>, with the same turn
lengths, handovers and safety nets.

Standard library only, like orthros.py.
"""

import os
import re
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXERCISES = os.path.join(HERE, "exercises")
EVALS = os.path.join(HERE, "evals")     # held out: scoring versions, never practice
KEEP_PRACTICE = 6            # practice folders kept per agent, newest first

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

IGNORE = ".localcoder*\n.aider*\nvenv/\n__pycache__/\n*.pyc\n*.tmp\n"
MARKER = ("Looked after by Orthros: the agents commit and roll back here.\n")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "task"


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


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def seed(folder, prompt, task_list):
    """Make `folder` a workspace the agents can use: prompt, list, git, marker."""
    os.makedirs(folder, exist_ok=True)
    write(os.path.join(folder, "RALPH_PROMPT.md"), prompt)
    write(os.path.join(folder, "orthros_tasks.md"), task_list)
    if not os.path.isfile(os.path.join(folder, ".gitignore")):
        write(os.path.join(folder, ".gitignore"), IGNORE)
    write(os.path.join(folder, ".localcoder-managed"), MARKER)
    if not os.path.isdir(os.path.join(folder, ".git")):
        git(folder, "init", "-q")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "Orthros: the starting point")


# ---------------------------------------------------------------- tasks

def tasks_root(root):
    return os.path.join(root, "tasks")


def create_task(root, name, brief):
    """A new project in tasks\\<slug>. Returns (slug, error)."""
    brief = (brief or "").strip()
    if len(brief) < 10:
        return "", "Say what to build -- a sentence at least."
    key = slug(name or brief[:40])
    folder = os.path.join(tasks_root(root), key)
    if os.path.exists(folder):
        return "", "There is already a task called %s. Pick another name." % key
    seed(folder, TASK_PROMPT % brief, TASK_LIST % (name or key))
    write(os.path.join(folder, "TASK.md"), "# %s\n\n%s\n" % (name or key, brief))
    return key, ""


def task_folder(root, key):
    folder = os.path.join(tasks_root(root), slug(key))
    return folder if os.path.isdir(folder) else ""


def list_tasks(root):
    """[{key, name, open, done, parked}] for every task folder, newest first."""
    out = []
    base = tasks_root(root)
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for key in names:
        folder = os.path.join(base, key)
        if not os.path.isdir(folder):
            continue
        title = (read(os.path.join(folder, "TASK.md")).splitlines() or ["# " + key])[0]
        notes = read(os.path.join(folder, "orthros_tasks.md"))
        out.append({"key": key, "name": title.lstrip("# ").strip() or key,
                    "folder": folder,
                    "open": len(re.findall(r"^\s*[-*]\s*\[ \]", notes, re.M)),
                    "done": len(re.findall(r"^\s*[-*]\s*\[[xX]\]", notes, re.M))
                    + len(re.findall(r"^\s*[-*]\s*\[[xX]\]",
                                     read(os.path.join(folder, "DONE.md")), re.M)),
                    "parked": len(re.findall(r"^\s*[-*]\s*\[!\]", notes, re.M)),
                    "made": os.path.getmtime(folder)})
    return sorted(out, key=lambda t: -t["made"])


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

    A held-out exercise goes to evals-runs\ rather than practice\, and its
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


def contained_run(cmd, timeout, **kwargs):
    """subprocess.run with captured text output, inside the limits above."""
    job = _job()
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **kwargs)
    try:
        if job:
            job[0].AssignProcessToJobObject(job[1], int(proc._handle))
        try:
            out, err = proc.communicate(timeout=timeout)
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
    env = dict(os.environ, PYTHONPATH=folder, PYTHONDONTWRITEBYTECODE="1")
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
