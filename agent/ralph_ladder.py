"""An escalation ladder: each try at a failing item is made differently.

An item gets a few tries, each warmer (ralph_send.attempt_temperature).
Warmer is one way to get a different answer; for an item that has already
failed there are better ones, chosen by what went wrong
(ORTHROSCODE-IMPROVEMENTS.md, item 5):

    last try              next try
    ------------------    -----------------------------------------------
    edit did not apply    whole-file edits, if the files are small
    broke a check         architect mode: reason in prose, then edit
    changed nothing       architect mode
    two failures in a row ask for the item to be split, once

Architect mode separates what to do from how to write the edit, which is
where small models go wrong, and aider's benchmarks show it helping most
models. Whole-file output is the format that fails least on weak models, at
a token cost only small files can afford.
"""

import os

from ralph_common import _env_flag, read_text

LADDER = _env_flag("LC_RALPH_LADDER", True)
WHOLE_LINES = 300            # whole-file edits only for files up to this long
FAILED = ("rejected", "broke", "edit-missed", "no-change")

SPLIT_ROUND = """# THIS ROUND: SPLIT THE ITEM

The item at the top of the list has failed {count} times in a row ({why}).
Do not try it again as it stands. Write 2 to 4 smaller `- [ ]` items directly
under it: each one change to one function, naming its file in backticks, and
ending with `Done when:` and a check anyone can make. Change no code, and tick
nothing -- the next rounds do the new items.
"""

WHY = {"rejected": "sent back", "broke": "broke the checks", "edit-missed":
       "its edits did not apply", "no-change": "changed nothing"}


def outcome(result, touched, kept, rejected_now, broke):
    """What one round on an item came to, for choosing the next try."""
    if kept:
        return "kept"
    if broke:
        return "broke"
    if rejected_now:
        return "rejected"
    if result.failed and not result.applied:
        return "edit-missed"
    return "no-change" if not touched else "broke"


def failing_streak(history):
    streak = []
    for entry in reversed(history):
        if entry not in FAILED:
            break
        streak.append(entry)
    return streak


def next_rung(history, files):
    """'plain', 'whole', 'architect' or 'split' for the next round on an item."""
    if not LADDER or not history:
        return "plain"
    streak = failing_streak(history)
    if not streak:
        return "plain"
    if len(streak) >= 2 and "split" not in history:
        return "split"
    last = streak[0]
    if last == "edit-missed" and files and all(
            len(read_text(f).splitlines()) <= WHOLE_LINES for f in files if os.path.isfile(f)):
        return "whole"
    if last in ("broke", "no-change"):
        return "architect"
    return "plain"


def split_note(history):
    streak = failing_streak(history)
    return SPLIT_ROUND.format(count=len(streak),
                              why=", ".join(WHY.get(s, s) for s in reversed(streak)))


def rung_command(base_cmd, rung):
    """The round's aider command for this rung: whole-file edits, or architect mode."""
    cmd = list(base_cmd)
    if rung == "whole" and "--edit-format" in cmd:
        spot = cmd.index("--edit-format") + 1
        if spot < len(cmd):
            cmd[spot] = "whole"
    elif rung == "architect" and "--architect" not in cmd:
        cmd.append("--architect")
    return cmd
