"""The Ralph loop -- re-prompting so you do not have to.

Named after the technique of the same name: run a coding agent on the *same*
prompt over and over, in a fresh process each time, and let progress live in
files and git rather than in the model's memory. It suits a small context
window exactly, because no single run ever has to hold the whole project.

One round is one `aider --message-file ... --yes-always` process:

    read the task list -> do ONE item -> check it -> tick the box -> exit

Exiting is the point. The next round starts with an empty context and re-reads
the task list from disk, so the file *is* the memory.

Five things watch over the rounds, because nobody else is:

    triage      -- does this item name one job or several? That sets how many
                   rounds it gets before the loop parks it and moves on.
    health      -- after every round the program is actually started, headless.
                   Parsing only proves it is grammatical; starting it proves it
                   works. A round that breaks it is rolled straight back.
    checkpoint  -- every ten minutes, has anything really moved? Boxes ticked,
                   lines changed, still runs, how fast it is going.
    stall       -- three rounds in a row that change nothing ends it.
    the clock   -- a dead engine does not hang up, so requests get a short
                   leash. That one number was costing 80% of every session.

This file used to hold all of it -- 3,000 lines, more than one round of the
model it drives could read. It is split by job now, each part small enough to
be worked on by a round of its own:

    ralph_common.py    settings, file names, read/write helpers
    ralph_tasks.py     the task list, plan and progress ledger
    ralph_prompts.py   everything the model is told
    ralph_checks.py    parse, import, run, look, and catch inventions
    ralph_rounds.py    one aider round, research, the second opinion
    ralph_session.py   the loop itself (with ralph_refill.py, ralph_report.py)

What other modules import from here still works: the names below are
re-exported so `import ralph; ralph.open_tasks(...)` keeps its meaning.
"""

from ralph_checks import full_check, health_check, import_check, smoke_run  # noqa: F401
from ralph_common import PLAN_FILE, read_text, say, write_text  # noqa: F401
from ralph_rounds import run_round  # noqa: F401
from ralph_session import Session
from ralph_tasks import (done_count, find_notes_file, milestones, open_tasks,  # noqa: F401
    progress_rows, progress_summary)


def run_loop(base_cmd, workspace, child_env, minutes, single_shot, **options):
    """Re-prompt until the work is done, the clock runs out, or it stops moving.

    Options are Session's keyword arguments: notes_hint, edit_files,
    iteration_timeout, commit, revive, rollback, entry_hint, run_seconds,
    shrink_output, grow_output, gpu_probe, set_temperature, temps, review.
    """
    return Session(base_cmd, workspace, child_env, minutes, single_shot, **options).run()
