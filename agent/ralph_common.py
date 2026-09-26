"""Settings, file names and small helpers every part of the Ralph loop shares.

Nothing here imports another ralph_* module, so anything may import this.
"""

import os
import re
import sys
import time
import unittest

# The console this lands in is whatever Windows hands over, often cp1252, which
# cannot encode a good deal of what aider prints. Echoing is the least
# important thing a round does, so it must never be the thing that ends one:
# replace what will not fit rather than raising. Seen for real on 2026-08-06 --
# a refill round killed by UnicodeEncodeError while printing a line it had
# already captured safely to the transcript.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

TASK_OPEN = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+?)\s*$", re.MULTILINE)
TASK_DONE = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.MULTILINE)
TASK_DONE_LINE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(.+?)\s*$", re.MULTILINE)
TASK_PARKED = re.compile(r"^\s*[-*]\s*\[!\]", re.MULTILINE)
RESEARCH_ASK = re.compile(r"^\s*RESEARCH:\s*(.+?)\s*$", re.MULTILINE)
HEADING_LINE = re.compile(r"^(#{2,4})\s*(.+?)\s*$", re.MULTILINE)

RESEARCH_FILE = "RESEARCH.md"
PROMPT_FILE = "RALPH_PROMPT.md"
CONVENTIONS_FILE = "CONVENTIONS.md"
ROUND_FILE = ".localcoder-round.md"
LOG_FILE = ".localcoder-ralph.log"
# aider's own output, verbatim. The summary log says what happened; this says
# why. Every failure that ever stopped a run overnight -- the engine falling
# over, a diff that would not apply, a reply cut off mid-edit -- announced
# itself here and nowhere else, and it was going to the console only.
TRANSCRIPT_FILE = ".localcoder-aider.log"
TRANSCRIPT_CAP = 8 * 1024 * 1024

# The task list does three jobs -- queue, changelog, brief -- and only the
# queue belongs in every round. Measured on this project at 8,342 tokens, of
# which the four open items were 180: 2%. The rest is history and standing
# instructions that only a refill round has any use for, resent on every
# round, editable, so the model could quietly rewrite its own past.
#
# Splitting by who needs it, rather than by what it is about, is what stops
# the file outgrowing the window. It grows forever; the window does not.
ARCHIVE_FILE = "DONE.md"
BRIEF_FILE = "BRIEF.md"

# One line per session, so the project has a memory of its own shape over
# time. Kept because a round with no memory cannot tell whether an hour of
# work made anything better, and neither could anyone reading one session's log.
PROGRESS_FILE = "PROGRESS.md"

# The outline layer. A round holds one small job and nothing else, which is
# what makes the loop work at all -- and also why, left to itself, it only ever
# produces small disconnected jobs. The plan is where the shape of the work
# lives between rounds: coarse milestones, written once, decomposed one at a
# time into items as the list empties.
#
# `## [ ] Title` means not yet broken into items. `[x]` means it has been --
# which is not the same as finished; the items carry that. `[!]` means no
# round could make items of it, and it is skipped.
PLAN_FILE = "PLAN.md"
MILESTONE = re.compile(r"^##[ \t]*\[( |x|X|!)\][ \t]*(.+?)[ \t]*$", re.MULTILINE)

# Headings at the bottom of a task list that hold standing instructions rather
# than checkboxes -- the operator's own answer to "what next". Matched loosely
# because people write these headings by hand and never twice the same way.
SEED_HEADINGS = (
    "out of task", "when out of", "next up", "ideas", "backlog", "wishlist",
    "features", "bug hunt", "design review", "polish", "improvements",
)



def _env_int(name, default, floor=1):
    try:
        return max(floor, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _env_flag(name, default=False):
    value = os.environ.get(name, "").strip()
    return default if not value else value == "1"


# Attempts an item gets before it is parked. Each retry runs warmer than the
# one before (ralph_send.attempt_temperature): repeated sampling only helps
# when the samples differ, and the tests and the reviewer pick the one that
# holds. Brown et al., "Large Language Monkeys" (2024). See config.cmd.
ROUNDS_IF_SMALL = _env_int("LC_RALPH_ATTEMPTS", 3)
ROUNDS_IF_BIG = max(ROUNDS_IF_SMALL, 5)


# How many times a session may go back and look for more work once the list is
# empty. Zero means as often as the clock allows, which is the point: a run
# asked for ninety minutes should spend ninety minutes. Four used to be the
# cap, and a 90-minute run spent 32 of them before handing the rest back with
# a plan half-built and three untried briefs.
#
# What makes an unlimited cap safe is that the work now comes from a plan
# rather than from asking the model to think of something: it decomposes a
# milestone, checks what it claimed, decomposes the next, and writes a new
# plan when the old one runs out.
MAX_REFILLS = _env_int("LC_RALPH_REFILLS", 0, floor=0)


def more_refills(refills):
    """Is another refill allowed? Zero means unlimited, so this is not `<`.

    Written out because `refills < MAX_REFILLS` reads as obviously right and
    is silently false for every refill once the cap means "no cap": on
    2026-08-10 a 90-minute run stopped after 49 with an empty list, four
    milestones still in the plan and 43 minutes on the clock.
    """
    return not MAX_REFILLS or refills < MAX_REFILLS


# How often the loop stops to ask itself whether any of this is working.
CHECKPOINT_MINUTES = _env_int("LC_RALPH_CHECKPOINT", 10)

# ...and the fewest rounds that look may judge. Ten minutes is two or three
# rounds on this rig, fewer when a refill or a slow review falls inside it --
# too few to call a run stuck. See config.cmd.
CHECKPOINT_ROUNDS = _env_int("LC_RALPH_CHECKPOINT_ROUNDS", 4)

# Short-form instructions in LocalCoder's own prompts. See config.cmd.
TERSE = _env_flag("LC_RALPH_TERSE")

# A single refill tops the list up by five or ten and goes straight back to
# work, which means stopping to think again twenty minutes later. When the
# list is genuinely empty it is worth staying in generation until there is a
# real queue -- brainstorming properly, once, rather than in dribs.
BRAINSTORM_UNTIL = _env_int("LC_RALPH_BRAINSTORM_UNTIL", 12)
BRAINSTORM_ROUNDS = _env_int("LC_RALPH_BRAINSTORM_ROUNDS", 3, floor=0)

# Look things up before decomposing a milestone. Free: the search needs no
# key and no account. On by default because the alternative -- waiting to
# be asked -- produced zero lookups in the whole history of the project.
RESEARCH_AUTO = os.environ.get("LC_RALPH_RESEARCH", "1").strip() != "0"

# Temperature per round type, overridden by the supervisor when it wires in.
TEMP_CODE = 0.2
TEMP_BRAINSTORM = 0.85

# The loop's own small jobs for the model, each a plain request (see config.cmd):
# find the files an item needs when it names none, keep a short summary of
# every module for planning, and read files too big for one window in parts.
LOCATE = os.environ.get("LC_RALPH_LOCATE", "1").strip() != "0"
GISTS_PER_REFILL = _env_int("LC_RALPH_GISTS_PER_REFILL", 6, floor=0)
DIGEST_PARTS = _env_int("LC_RALPH_DIGEST_PARTS", 12)

# Checks after every round that cost no tokens: lint and call signatures across
# the whole project, placeholders, conflict markers, lost tests (ralph_scan.py).
SCAN = _env_flag("LC_RALPH_SCAN", True)

# Split a source file once it passes this many tokens. See config.cmd.
FILE_TOKEN_CAP = _env_int("LC_RALPH_MAX_FILE_TOKENS", 9000)


def say(msg=""):
    print(msg, flush=True)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def write_text(path, body):
    """Replace a file's contents without ever leaving it half-written.

    The task list is the loop's whole memory. Written in place, a crash, a
    full disk or a killed process mid-write leaves it truncated -- and the
    next session starts from whatever fragment survived. Writing a sibling
    and swapping it in means the file is either the old version or the new
    one, never neither.

    Windows refuses the swap while another process has the file open (an
    editor, a virus scanner, aider itself), so it retries briefly and then
    falls back to writing in place: a write that might tear beats one that
    silently never happens.
    """
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(body)
        for _ in range(5):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                time.sleep(0.2)
    except OSError:
        pass
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return True
    except OSError:
        return False


# Tests that run a whole session start dozens of processes each -- git, a fake
# aider, the linters -- and on Windows a process costs ten to twenty times what
# it does on Linux: the suite took 217 s there, against 17 s here, and the
# check after every round has 240 s (2026-09-26). They test the loop, not the
# round's change, so they run before each turn (Orthros's pre-launch check and
# --doctor) and are skipped by the checks after each round and inside it,
# which set LC_QUICK_TESTS=1.
QUICK_TESTS = "LC_QUICK_TESTS"


def session_test(cls):
    """Mark a TestCase that runs whole sessions: skipped when tests must be quick."""
    return unittest.skipIf(os.environ.get(QUICK_TESTS) == "1",
                           "runs whole sessions: checked before each turn, not each round")(cls)
