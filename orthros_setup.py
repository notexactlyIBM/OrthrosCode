"""Set OrthrosCode up from a fresh copy: one shared set of packages, two agents.

    python orthros_setup.py              create whatever is missing; touch nothing else
    python orthros_setup.py --mission    rewrite both agents' task lists, prompts and
                                       plans from the templates below (their notes
                                       about each other are lost)

What it makes, next to this file:

    shared-venv\\       aider and its dependencies, installed once (~800 MB)
    OrthrosCode A\\      an agent: a copy of agent\\, its own git history, and a
    OrthrosCode B\\      thin venv layered over shared-venv so each can install
                       packages the other never sees

Standard library only. Needs Python 3.10+ and Git on PATH, and LM Studio for
the model -- see README.md.
"""

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "agent")
SHARED = os.path.join(ROOT, "shared-venv")
NAMES = ("A", "B")
PEER = {"A": "B", "B": "A"}
IDENTITY = ["-c", "user.name=OrthrosCode", "-c", "user.email=orthros@localhost"]

FOCUS = {
    # folder: (areas the twin builds into it, the areas it builds into the twin)
    "B": ("Memory, Knowledge and Skills", "Tools, Efficiency and External interactions"),
    "A": ("Tools, Efficiency and External interactions", "Memory, Knowledge and Skills"),
}

PROMPT = """# How to work

Do the NEXT unfinished item in the task list, and only that one.

1. Find the first item still marked `- [ ]`.
2. Make the change yourself -- edit the files. Never describe an edit instead
   of making it, and never ask anyone to run, paste or apply anything.
3. Re-read what you changed: complete, valid, and consistent with the rest of
   the file and with whatever calls it.
4. Only if it is good: tick it (`- [x]`) and add a one-line `*Note*:` under it
   saying what changed.
5. Stop. Do not start the next item.

Too big for one round? Split it into smaller `- [ ]` items underneath, tick
nothing, and stop.

Need something you do not have? Write one of these lines in the task list and
stop; the answer comes with the next round:

    RESEARCH: <question>   a web search and page fetch        -> RESEARCH.md
    FIND: <text>           every line in this project with it  -> FOUND.md
    DOCS: <module>         an installed library's documentation -> FOUND.md

The tests (`test_*.py`, unittest) run after every edit and before every
launch; a change that leaves them failing is rolled back. Never delete or
weaken a test to get a change through -- add one for what you build.
SKILLS.md, when sent, says how common changes are done here. Lessons at the
top of this prompt are mistakes already made: do not repeat them.

**Be brief.** No narration, no restating the plan, no echoing files back. The
edit, then one line. Everything you write competes with the code for a small
context window, and a long answer runs out of room and loses the round.

# What this is

This folder is **OrthrosCode {X}**: a local, autonomous coding agent -- aider
driven by an unattended loop, on a model served by LM Studio. You are
**OrthrosCode {P}**, its twin. You take turns: this turn you improve {X}; next
turn {X} is started and improves you.

That is the experiment -- recursive self-improvement -- and it has teeth:

- If {X} fails its checks or will not start after your turn, everything you
  did this turn is rolled back, and the reason is written onto this list.
- If {X} starts and does good work, your changes are proven and are copied
  into your own code as well.
- After each of {X}'s turns, FIELD_REPORT.md records how it actually did --
  the real result of your changes. Planning rounds read it.

So you are editing yourself. Make the changes you would want made to you.

# Your focus: {MINE}

The twin is building {THEIRS} into you at the same time, and proven work is
copied both ways -- so stay in your own areas and the two sets of changes
will not collide. What they mean:

- **Tools** -- things it cannot do yet: a check, a test, a code search, a
  safer or cheaper way to edit.
- **Memory** -- what one round or session learns that the next should know,
  where it is written, and how it gets read back.
- **Skills** -- reusable procedures and prompt text that make common jobs go
  right the first time.
- **External interactions** -- better use of web research and documentation
  (search and fetch only).
- **Knowledge** -- facts about its own code, the model and the machine, kept
  where rounds will see them.
- **Efficiency** -- fewer tokens per round, fewer lost rounds, faster checks,
  less waiting.

A real problem in FIELD_REPORT.md comes before anything new, whatever its
area. A small improvement that certainly works beats a big one that might.

# Rules that are not negotiable

- All inference stays local, through LM Studio. Never add an API key, a cloud
  model, a paid service, or anything that needs an account.
- {X} must keep starting: every module imports, `supervisor.py` and the
  `ralph_*` loop run, the tests pass. Nothing slow or risky at import time.
- One item is one change to one function. Keep every file under ~9,000
  tokens -- add a new module rather than grow a big one.
- Leave alone: `LC_WORKSPACE` in config.cmd, `.localcoder-managed`, `venv/`,
  `.git/`, `orthros_shared.pth`. The orchestrator (Orthros) lives outside this
  folder and is not yours to change.
- Never remove a safety net -- rollback, the reviewer, the tests, timeouts,
  crash recovery -- to make something else easier.
- No busywork: no renames, reformatting, or comment-only changes.
- Use the standard library and the packages already installed. A new entry
  in requirements.txt is only installed if the operator has allowed it;
  otherwise the import fails and the turn is rolled back.
"""

HEADER = """# Orthros: OrthrosCode {P} improving OrthrosCode {X}

## How to use this list

The mission and the rules are in RALPH_PROMPT.md, sent with every round.
Your focus: **{MINE}**. The coarse plan is PLAN.md; when this list runs dry
the next milestone there is broken into items.

One `- [ ]` item is one round: **one change, to one function**. Name the
function in backticks so only its file is sent -- ``In `record_lesson`
(ralph_tools.py), ...``, or `Class.method` for a method. Naming the file
works too. An item that names neither sends no source at all.

Where things are:

- `ralph_session.py` the loop, with `ralph_setup.py`, `ralph_refill.py`,
  `ralph_outcome.py` (what a round amounted to), `ralph_report.py`
- `ralph_rounds.py` one aider round, research, the diff the reviewer sees
- `ralph_tools.py` RESEARCH:/FIND:/DOCS: requests, and LESSONS.md
- `ralph_prompts.py` everything the model is told
- `ralph_tasks.py` the task list, plan and progress ledger
- `ralph_checks.py`, `ralph_inventions.py` the checks after each round
- `supervisor*.py` LM Studio, aider's command line, the reviewer, git
- `research.py` web search and fetch; `split.py` mechanical refactoring
- `test_*.py` the tests; SKILLS.md how common changes are done

If an item cannot be finished in one go, split it into smaller `- [ ]` items
underneath and tick nothing. `- [!]` means stuck and waiting for a human.

## Tasks

{TASKS}

## When out of tasks

First read FIELD_REPORT.md and LESSONS.md: if they show a real problem --
lost rounds, rejected changes, errors, a slowdown -- fix that before anything
new. Then, in your focus areas ({MINE}):

{WHEN_OUT}

Check the ticked items above really work before building on them.
"""

TASKS = {
    "B": """- [ ] In `recent_lessons` (ralph_tools.py), add an optional `task` argument; when given, return the lessons sharing the most words with it, newest first among equals, still at most `count`.
- [ ] In `compose_round_prompt` (ralph_prompts.py), add an optional `task` argument and pass it on to `recent_lessons`.
- [ ] In `Session.send_round` (ralph_session.py), pass the current task to `compose_round_prompt`.
- [ ] In test_ralph_tools.py, add a unittest test that `recent_lessons` with a `task` puts the matching lesson first.
- [ ] In `OutcomeMixin.judge_round` (ralph_outcome.py), call `record_lesson` when an item is ticked without any code changing, naming the item.
- [ ] In `ReportMixin._finish` (ralph_report.py), when the session kept no changes, call `record_lesson` with one line saying how many rounds it ran and what ended it.
- [ ] Create KNOWLEDGE.md with what rounds keep rediscovering: the 32k context and what a round sends, the ~9,000-token file limit, which module owns what, and the machine's known failure modes from config.cmd's comments. Under 60 lines.
- [ ] In `refill_list` (ralph_rounds.py), add KNOWLEDGE.md from the workspace to the read-only files when it exists.
- [ ] In SKILLS.md, add a skill: adding a new ralph_ module, and covering it with a test_ file.""",
    "A": """- [ ] In `handle_tool_requests` (ralph_tools.py), add a `CALLERS: <function>` request that lists every line calling the function (`name(`), leaving out its own `def` line, into FOUND.md.
- [ ] In test_ralph_tools.py, add a unittest test for the `CALLERS:` request.
- [ ] In `test_check` (ralph_checks.py), include the first failing test's assertion message in the report, not only its name.
- [ ] In `files_for_refill` (ralph_rounds.py), size files with `os.path.getsize` instead of reading every file's text twice.
- [ ] In `Session.send_round` (ralph_session.py), add the approximate tokens sent (bytes / 4 of the files) to the "sending N of M files" line.
- [ ] In `import_check` (ralph_checks.py), remember the result for the last `code_fingerprint` of the files and return it without running Python again when nothing changed.
- [ ] In research.py, add a `--site` option that restricts a search to one domain by adding `site:<domain>` to the query.
- [ ] In research.py, cache each query's result in `.localcoder-research-cache/` for 24 hours, so repeating a lookup costs nothing.
- [ ] Add test_supervisor_aider.py with unittest tests that `build_aider_command` starts aider with `-m aider` and includes `--no-suggest-shell-commands`.""",
}

WHEN_OUT = {
    "B": """- **Memory**: what did recent sessions learn that is now lost? Where should it
  be written, and which round should read it back -- and how is it kept short?
- **Knowledge**: what does the agent not know about its own code, the model or
  this machine that rounds keep rediscovering? Write it where rounds see it.
- **Skills**: which jobs keep going wrong or taking several rounds? Write the
  procedure down and give it to the rounds that need it, and only those.""",
    "A": """- **Tools**: what does a round fail at for want of a tool? A code search, a
  cheaper check, a safer edit, a test for something fragile.
- **Efficiency**: where do tokens, rounds or minutes go to waste? The newest
  `.localcoder-ralph.log`, PROGRESS.md and FIELD_REPORT.md are the evidence.
- **External interactions**: where would documentation or a web search have
  saved a failed round? Make research easier to ask for and easier to use.""",
}

PLAN_HEAD = """# Plan

Milestones, coarsest first. LocalCoder breaks one at a time into the task list
as the list empties, and writes a fresh set of milestones when they run out.

`## [ ]` means not yet broken into items. `## [x]` means it has been -- which
is not the same as finished. The task list carries what is done.

Yours to edit. Reorder them, rewrite them, add your own; the next milestone
taken is simply the first one still marked `[ ]`.

"""

PLAN = {
    "B": """## [ ] Lessons that fit the item
Rank lessons by how much they share with the current item, record lessons from
more kinds of failure (edits that do not apply, replies cut off, inspection-only
ticks), and keep LESSONS.md short by folding old lines into a summary.

## [ ] Memory across sessions
At the end of a session write a short structured summary -- done, failed, next
-- that the first planning round of the next session reads. Test it.

## [ ] Self-knowledge
KNOWLEDGE.md with facts about the agent's own code, the model and the machine,
fed to planning rounds, and kept current from FIELD_REPORT.md.

## [ ] A skills library
One procedure per file under skills/, attached only to rounds whose item needs
it. New skills written down from jobs that went well after going badly.

## [ ] Learning from the reviewer
Track which kinds of items the reviewer rejects most, and feed that back into
how new items are written -- the rules and examples refill rounds are given.

## [ ] Memory hygiene
Keep DONE.md, LESSONS.md and RESEARCH.md from growing without bound: summarise
or archive old entries so what rounds read stays small and current.
""",
    "A": """## [ ] Code navigation tools
Requests a round can make to find its way around: who calls a function, where
something is defined, a one-screen outline of a module. Each with a test.

## [ ] Stronger verification
Clearer test failure reports, tests for the supervisor's command line and the
refill path, and a check that catches what the current ones miss.

## [ ] Fewer lost rounds
Find the commonest cause of lost rounds in FIELD_REPORT.md and the logs, and
fix it. Then the next one.

## [ ] Fewer tokens per round
Measure what each round sends and where the tokens go; stop sending what is
not needed; never send the same thing twice.

## [ ] Faster checks
Skip checks when nothing changed, and make the slow ones cheaper, without
weakening what they catch.

## [ ] Better research
Site-restricted searches, documentation first for known libraries, a cache,
and RESEARCH.md written so a small model can use it at a glance.
""",
}



def say(msg=""):
    print(msg, flush=True)


def run(cmd, **kw):
    say("  $ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    return subprocess.run(cmd, **kw).returncode == 0


def write_mission(x):
    """RALPH_PROMPT.md, orthros_tasks.md and PLAN.md for agent x's folder --
    read by its twin, which is the one working there."""
    p = PEER[x]
    mine, theirs = FOCUS[x]
    folder = os.path.join(ROOT, "OrthrosCode %s" % x)

    def fill(text):
        return (text.replace("{X}", x).replace("{P}", p)
                .replace("{MINE}", mine).replace("{THEIRS}", theirs))

    with open(os.path.join(folder, "RALPH_PROMPT.md"), "w", encoding="utf-8") as h:
        h.write(fill(PROMPT))
    with open(os.path.join(folder, "orthros_tasks.md"), "w", encoding="utf-8") as h:
        h.write(fill(HEADER).replace("{TASKS}", TASKS[x]).replace("{WHEN_OUT}", WHEN_OUT[x]))
    with open(os.path.join(folder, "PLAN.md"), "w", encoding="utf-8") as h:
        h.write(PLAN_HEAD + PLAN[x])


def point_at_peer(x):
    path = os.path.join(ROOT, "OrthrosCode %s" % x, "config.cmd")
    body = open(path, encoding="utf-8").read()
    body = re.sub(r'^set "LC_WORKSPACE=.*"$',
                  lambda m: 'set "LC_WORKSPACE=%%~dp0..\\OrthrosCode %s"' % PEER[x], body, flags=re.M)
    with open(path, "w", encoding="utf-8", newline="") as h:
        h.write(body)


def make_shared():
    if os.path.isfile(os.path.join(SHARED, "Scripts", "python.exe")):
        say("shared-venv is there.")
        return True
    say("Creating shared-venv and installing aider into it (a few minutes, ~800 MB)...")
    return (run([sys.executable, "-m", "venv", SHARED])
            and run([os.path.join(SHARED, "Scripts", "python.exe"), "-m", "pip", "install",
                     "--disable-pip-version-check", "-r",
                     os.path.join(TEMPLATE, "requirements.txt")]))


def make_agent(x):
    folder = os.path.join(ROOT, "OrthrosCode %s" % x)
    if not os.path.isdir(folder):
        say("Creating OrthrosCode %s from agent\\ ..." % x)
        shutil.copytree(TEMPLATE, folder, ignore=shutil.ignore_patterns(
            "venv", "__pycache__", ".localcoder*", ".aider*"))
        point_at_peer(x)
        write_mission(x)
        run(["git", "-C", folder, "init", "-q"])
        run(["git", "-C", folder] + IDENTITY + ["add", "-A"])
        run(["git", "-C", folder] + IDENTITY + ["commit", "-q", "-m",
                                                "OrthrosCode %s: first version" % x])
    marker = os.path.join(folder, ".localcoder-managed")
    if not os.path.isfile(marker):
        with open(marker, "w", encoding="utf-8") as h:
            h.write("Looked after by Orthros: the other agent commits and rolls back here.\n")
    python = os.path.join(folder, "venv", "Scripts", "python.exe")
    if not os.path.isfile(python):
        say("Creating OrthrosCode %s's own venv, layered over shared-venv..." % x)
        if not run([sys.executable, "-m", "venv", os.path.join(folder, "venv")]):
            return False
    pth = os.path.join(folder, "orthros_shared.pth")
    site = os.path.join(folder, "venv", "Lib", "site-packages")
    if os.path.isfile(pth) and os.path.isdir(site):
        shutil.copy2(pth, site)
    ok = subprocess.run([python, "-c", "import aider, flake8, httpx"],
                        capture_output=True).returncode == 0
    say("OrthrosCode %s: %s" % (x, "ready" if ok else "its venv cannot import aider -- "
                                                  "is shared-venv complete?"))
    return ok


def find_lms():
    tail = os.path.join("resources", "app", ".webpack", "lms.exe")
    for path in [os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe"),
                 os.path.expandvars(os.path.join(r"%LOCALAPPDATA%\Programs\LM Studio", tail)),
                 os.path.expandvars(os.path.join(r"%ProgramFiles%\LM Studio", tail))] + \
            [os.path.join("%s:\\" % d, "LM Studio", tail) for d in "CDEFGH"]:
        if os.path.isfile(path):
            return path
    return shutil.which("lms")


def main():
    say("OrthrosCode setup\n")
    if sys.version_info < (3, 10):
        say("Python 3.10 or newer is needed; this is %s." % sys.version.split()[0])
        return 1
    if not shutil.which("git"):
        say("Git is needed: https://git-scm.com/download/win -- then run this again.")
        return 1
    if not os.path.isdir(TEMPLATE):
        say("agent\\ is missing -- this folder is not a complete copy of OrthrosCode.")
        return 1
    if "--mission" in sys.argv:
        for x in NAMES:
            if os.path.isdir(os.path.join(ROOT, "OrthrosCode %s" % x)):
                write_mission(x)
                say("rewrote OrthrosCode %s's task list, prompt and plan" % x)
        return 0
    if not make_shared():
        say("\nInstalling into shared-venv failed; scroll up for pip's reason.")
        return 1
    ok = all([make_agent(x) for x in NAMES])
    lms = find_lms()
    say()
    say("LM Studio's lms tool: %s" % (lms or "NOT FOUND -- install LM Studio (see README), "
                                            "or set LC_LMS_PATH in each agent's config.cmd"))
    if ok:
        say("\nDone. Next: load-test with SELFTEST.bat in either agent folder, then run "
            "ORTHROS.bat and press Start.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
