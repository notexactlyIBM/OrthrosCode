"""Everything a session does before its first round.

Part of Session (ralph_session.py): find the task list, trim and split it,
check the program runs, and say what the session is starting from.
"""

import os
import time

import status
from ralph_checks import ensure_ignored, find_entry_point, full_check, keep_files_small
from ralph_common import (ARCHIVE_FILE, BRIEF_FILE, CHECKPOINT_MINUTES, LOG_FILE, PLAN_FILE,
    PROMPT_FILE, RESEARCH_FILE, _env_int, read_text, say)
from ralph_memory import EXAMPLES, Memory
from ralph_prompts import ensure_prompt, seed_sections
from ralph_tools import FOUND_FILE, fold_old_lessons
from ralph_tasks import (add_items, archive_done, done_count, ensure_conventions, extract_brief,
    find_notes_file, milestones, open_tasks, parked_count, progress_regressions,
    progress_summary, trim_notes)


LESSONS_KEPT = _env_int("LC_RALPH_KEEP_LESSONS", 40)


def last_line(text, first=False):
    """One line of an error message to show, whatever shape it came in."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return (text or "").strip() or "(no detail)"
    return lines[0] if first else lines[-1]


class SetupMixin:

    def prepare(self):
        """Everything before the first round. Returns an exit code to stop with, or None."""
        ws = self.workspace
        self.notes_path = notes_path = find_notes_file(ws, self.notes_hint)
        if not notes_path:
            say("!! No task list found in %s" % ws)
            say("   Ralph needs a markdown file with `- [ ]` checkboxes in it.")
            say("   Name it something with 'notes', 'tasks' or 'todo' in it, or")
            say("   set LC_RALPH_NOTES in config.cmd.")
            return 1

        self.prompt_path = ensure_prompt(ws)
        try:
            os.remove(os.path.join(ws, FOUND_FILE))     # answers from an earlier session
        except OSError:
            pass
        ensure_ignored(ws)
        self.conventions = ensure_conventions(ws, notes_path)
        saved = trim_notes(notes_path)
        if saved:
            say("    trimmed %d bytes of old notes out of the task list" % saved)
        # LESSONS.md goes whole into every refill round (ralph_rounds.py), and
        # fold_old_lessons, written for this on 2026-09-24, was never called.
        if fold_old_lessons(ws, keep=LESSONS_KEPT):
            say("    folded lessons older than the newest %d into LESSONS.summary.md"
                % LESSONS_KEPT)

        # Split the task list by who needs what, before anything is sent. The
        # queue goes in every round; the changelog and the brief go only to the
        # round that reviews and refills, which is the only one that reads them.
        was = len(read_text(notes_path))
        lifted = extract_brief(ws, notes_path)
        if lifted:
            say("    moved %d bytes of standing instructions to %s" % (lifted, BRIEF_FILE))
        filed = archive_done(notes_path, _env_int("LC_RALPH_KEEP_DONE", 8))
        if filed:
            say("    filed %d finished item(s) into %s" % (filed, ARCHIVE_FILE))
        now = len(read_text(notes_path))
        if now < was:
            say("    task list is %d bytes, down from %d (~%d fewer tokens per round)"
                % (now, was, (was - now) // 4))
        self.research_path = os.path.join(ws, RESEARCH_FILE)
        if EXAMPLES:
            self.memory = Memory(ws)
            if self.memory.items:
                say("    memory     : %d kept round(s) to draw examples from"
                    % len(self.memory.items))
        self.plan_path = os.path.join(os.path.dirname(notes_path), PLAN_FILE)

        # Opened now and flushed line by line, not gathered up and written at
        # the end. A session that is killed, wedged, or takes the machine down
        # with it is exactly the session whose log you want.
        try:
            self.log_handle = open(os.path.join(ws, LOG_FILE), "a",
                                   encoding="utf-8", errors="replace")
            self._log("\n\n== %s ==\n" % time.strftime("%Y-%m-%d %H:%M"))
        except OSError:
            self.log_handle = None

        say("    task list : %s" % os.path.basename(notes_path))
        say("    prompt    : %s" % PROMPT_FILE)
        remaining = open_tasks(notes_path)
        say("    %d items left, %d done" % (len(remaining), done_count(notes_path)))
        # An empty list is only a reason to stop when there is no time to go
        # and find work. Otherwise the loop reviews what has been done and
        # writes the next items itself.
        if not remaining and (self.single_shot or self.minutes < 3):
            say()
            say("    Nothing is unticked, so there is nothing to do.")
            say("    Add some `- [ ]` items to %s first." % os.path.basename(notes_path))
            return 0
        seeds = seed_sections(notes_path)
        if seeds:
            say("    briefs     : %s" % ", ".join(t for t, _ in seeds)[:60])
        todo = [t for t, _, d in milestones(self.plan_path) if not d]
        if todo:
            say("    plan       : %d milestone(s) left, next is %s" % (len(todo), todo[0][:34]))
        elif os.path.isfile(self.plan_path):
            say("    plan       : all milestones broken down - it will write more")
        else:
            say("    plan       : none yet - it will write %s when the list empties" % PLAN_FILE)
        if not remaining:
            say("    List is empty -- the first round goes looking for more.")

        self.entry = find_entry_point(ws, self.edit_files, self.entry_hint)
        if self.entry:
            say("    launches   : %s (started headless after each round)"
                % os.path.basename(self.entry))
        # Before any round is sent, make sure a round can fit. Each move is
        # checked by actually starting the program, and put back if it fails.
        moved = keep_files_small(ws, self.edit_files, self.entry, self.run_seconds)
        for line in moved:
            say("    %s" % line)
        # Committed straight away. Rollback is `git checkout -- .`, which would
        # restore the old single file while leaving the new modules behind.
        if moved and self.commit:
            self.commit("LocalCoder: split oversized files")
        self.broken = full_check(ws, self.edit_files, self.entry, self.run_seconds)
        self.started_done = done_count(notes_path)
        trend = progress_summary(notes_path)
        if trend:
            say("    %s" % trend)
        # Numbers below their own best are the one signal that says an hour of
        # ticked boxes made the thing worse. Put them in front of the work.
        slipped = progress_regressions(notes_path)
        for regression in slipped:
            say("    REGRESSION: %s" % regression)
        if slipped:
            add_items(notes_path, "Found by comparing with earlier sessions",
                      ["Something has regressed: %s. Find what changed and fix it, "
                       "or say in a note why the new value is the right one." % s
                       for s in slipped])
        if self.broken:
            say("    NOTE: it is broken right now. The first round fixes that.")
            say("          %s" % last_line(self.broken[0][1], first=True)[:60])
        say()

        self.deadline = time.time() + self.minutes * 60
        if not status._path:
            status.attach(ws)
        status.update(mode="one item" if self.single_shot else "work the list",
                      deadline=self.deadline, minutes=self.minutes, workspace=ws,
                      notes=os.path.basename(notes_path),
                      items_open=len(open_tasks(notes_path)),
                      items_done=done_count(notes_path),
                      milestones=self.milestone_state(),
                      ticked=0, accepted=0, rejected=0, rounds=0)
        status.phase("ready")
        self.started = time.time()
        # `- [!]` marks survive between sessions, so report the ones this run
        # made rather than every one the file has ever collected.
        self.parked_before = parked_count(notes_path)
        self.next_checkpoint = time.time() + CHECKPOINT_MINUTES * 60
        self.mark_checkpoint()
        return None

    def milestone_state(self):
        return [[t, d] for t, _, d in milestones(self.plan_path)]
