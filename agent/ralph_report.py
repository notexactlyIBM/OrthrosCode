"""The ten-minute checkpoint and the end-of-session summary.

Part of Session (ralph_session.py).
"""

import os
import time

import status
from ralph_checks import code_fingerprint, code_lines
from ralph_common import (CHECKPOINT_MINUTES, CHECKPOINT_ROUNDS, LOG_FILE, ROUND_FILE,
    TRANSCRIPT_FILE, say)
from ralph_tasks import (done_count, open_tasks, parked_count, progress_summary,
    record_progress)
from ralph_tools import record_lesson


class ReportMixin:

    def mark_checkpoint(self):
        self.next_checkpoint = time.time() + CHECKPOINT_MINUTES * 60
        self.mark_done = done_count(self.notes_path)
        self.mark_size = code_lines(self.edit_files)
        self.mark_print = code_fingerprint(self.edit_files)
        self.mark_rounds = self.rounds
        self.engine_failures = 0

    def pace_summary(self):
        """Typical round, in numbers, so 'it feels slow' can be checked.

        Only rounds that actually got a reply count towards the rate. A round
        killed on the clock produced no tokens over a long time, and averaging
        it in reports a speed the machine never ran at.
        """
        real = [p for p in self.pace if p[2] > 0]
        if not real:
            return "no round got a reply"
        secs = sorted(p[0] for p in real)
        mid = secs[(len(secs) - 1) // 2]
        got = sum(p[2] for p in real)
        spent = sum(p[0] for p in real)
        lost = len(self.pace) - len(real)
        return ("typical round %.0fs, %s in / %s out, %.0f tok/sec%s"
                % (mid, "{:,}".format(sum(p[1] for p in real)), "{:,}".format(got),
                   got / spent if spent else 0,
                   "  (%d round(s) got nothing back)" % lost if lost else ""))

    def checkpoint(self):
        """Ten-minute look up from the desk. Returns False to stop."""
        ticked = done_count(self.notes_path) - self.mark_done
        grew = code_lines(self.edit_files) - self.mark_size
        did = self.rounds - self.mark_rounds

        say()
        say("+" + "-" * 60 + "+")
        self.note("  CHECKPOINT  |  %d min in" % int((time.time() - self.started) // 60))
        self.note("  %d rounds, %d items ticked, %+d lines of code" % (did, ticked, grew))
        self.note("  it %s" % ("is BROKEN" if self.broken else "still runs"))
        if self.pace:
            self.note("  %s" % self.pace_summary())

        changed = code_fingerprint(self.edit_files) != self.mark_print
        if ticked <= 0 and grew == 0 and not changed and did < CHECKPOINT_ROUNDS:
            # Too few rounds to judge. Look again later, from the same mark.
            self.note("  Nothing moved yet, but only %d round(s) ran. Looking again"
                      % did)
            self.note("  in %d minutes." % CHECKPOINT_MINUTES)
            say("+" + "-" * 60 + "+")
            say()
            self.next_checkpoint = time.time() + CHECKPOINT_MINUTES * 60
            return True
        if ticked <= 0 and grew == 0 and not changed:
            # Why nothing moved decides whether stopping is the right answer.
            # An engine that spent the last ten minutes refusing to answer has
            # told us nothing about the task list, and ending the run blames
            # the work for the machine's failure.
            if self.engine_failures:
                self.note("  Nothing moved, but %d round(s) lost the engine."
                          % self.engine_failures)
                self.note("  That is the machine, not the list. Carrying on.")
                say("+" + "-" * 60 + "+")
                say()
                self.mark_checkpoint()
                return True
            self.stop("  Nothing moved in %d minutes. Stopping." % CHECKPOINT_MINUTES)
            self.note("  The top item is likely too vague, or needs you.")
            say("+" + "-" * 60 + "+")
            say()
            return False
        if ticked <= 0:
            self.note("  Code is changing but nothing is getting ticked off.")
            self.note("  Carrying on -- it may be mid-way through a big item.")
        else:
            self.note("  Progress looks real. Carrying on.")

        say("+" + "-" * 60 + "+")
        say()
        self.mark_checkpoint()
        return True

    def finish(self):
        """The summary, the progress row, the final status. Never raises."""
        try:
            self._finish()
        except Exception as exc:
            say("!! could not write the session summary: %s" % exc)
        finally:
            if self.log_handle:
                try:
                    self.log_handle.close()
                except OSError:
                    pass
                self.log_handle = None

    def _finish(self):
        notes_path = self.notes_path
        try:
            os.remove(os.path.join(self.workspace, ROUND_FILE))
        except OSError:
            pass

        elapsed = int(time.time() - self.started)
        parked = parked_count(notes_path) - self.parked_before
        done_now = done_count(notes_path)
        open_now = len(open_tasks(notes_path))
        say()
        say("=" * 62)
        say("  Ralph finished")
        say("=" * 62)
        # `note`, not `say`: an unattended run is read afterwards, and a summary
        # that only ever reached a console nobody was sitting at is no summary.
        note = self.note
        note("  rounds    : %d in %d min %d sec" % (self.rounds, elapsed // 60, elapsed % 60))
        note("  ticked    : %d items now done" % done_now)
        note("  remaining : %d items still open" % open_now)
        if parked:
            note("  parked    : %d marked `- [!]` - stuck, needs your eye" % parked)
        if self.reverted:
            note("  undone    : %d round(s) rolled back for breaking it" % self.reverted)
        if self.refills:
            note("  refilled  : %d time(s) it ran out of list and found more" % self.refills)
        if self.suspect:
            note("  unproven  : %d item(s) ticked without changing any code" % self.suspect)
        if self.overflows:
            note("  overflowed: %d round(s) lost to over-long replies" % self.overflows)
        if self.fat_rounds:
            note("  crowded   : %d of those had no room to reply in -- the prompt"
                 % self.fat_rounds)
            note("              was most of the window. Split the source further;")
            note("              no setting fixes this one.")
        if self.accepted or self.rejected:
            note("  reviewed  : %d kept, %d sent back by the second agent"
                 % (self.accepted, self.rejected))
        if self.hallucinations:
            note("  invented  : %d attribute(s) read that nothing assigns"
                 % self.hallucinations)
        if self.wobbles:
            note("  wobbles   : %d engine error(s) survived by retrying - the card"
                 % self.wobbles)
            note("              is close to the edge; lower LC_CONTEXT")
        if self.pace:
            note("  speed     : %s" % self.pace_summary())
        if self.stop_reason:
            note("  ended     : %s" % self.stop_reason)
        if self.rounds and not self.accepted and not self.reverted:
            record_lesson(
                self.workspace,
                "ran %d rounds, ended %s, kept no changes"
                % (self.rounds, self.stop_reason or "finished"),
            )
        note("  state     : %s" % ("BROKEN - fix before using it" if self.broken else "runs"))
        note("  logs      : %s (this summary), %s (aider, verbatim)"
             % (LOG_FILE, TRANSCRIPT_FILE))

        # One row, written whatever happened -- a session that achieved nothing
        # is exactly as much a part of the trend as one that went well.
        record_progress(notes_path, [
            self.rounds,
            done_now - self.started_done,
            open_now,
            code_lines(self.edit_files),
            "{:,}".format(self.tokens_in + self.tokens_out),
            "BROKEN" if self.broken else "runs",
            # Whether a second opinion is earning its keep: how much of what the
            # worker produced the reviewer turned back, session by session.
            "%d/%d" % (self.accepted, self.rejected) if (self.accepted or self.rejected) else "-",
        ])
        trend = progress_summary(notes_path)
        if trend:
            note("  %s" % trend)
        say("=" * 62)
        say()

        status.update(ended=time.time(), ended_reason=self.stop_reason or "finished",
                      ticked=done_now - self.started_done,
                      accepted=self.accepted, rejected=self.rejected, rounds=self.rounds,
                      items_open=open_now, items_done=done_now,
                      milestones=self.milestone_state())
        status.phase("finished", self.stop_reason or "")
