"""What a round amounted to, and what to do about it.

Part of Session (ralph_session.py): the engine dying, the reply running out
of room, inventions to report, and the stall counter that parks an item.
"""

import os

import status
from ralph_inventions import phantom_attributes, used_before_set
from ralph_common import say
from ralph_setup import last_line
from ralph_tasks import add_items, open_tasks, park_task
from ralph_tools import record_lesson


class OutcomeMixin:

    def react_to_symptom(self, result):
        """Respond to how the round failed, if it did. Returns False to stop."""
        if result.symptom == "enginedied":
            # A dead server cannot be worked around by trying again harder.
            self.engine_failures += 1
            self.engine_streak += 1
            self.note("LM Studio's engine stopped answering mid-round.")
            self.note_tail(result, "That is what it said on the way down")
            # Not charging these to the item is right, but it removes the thing
            # that used to end a hopeless run. An engine that keeps coming back
            # and keeps failing needs a floor of its own.
            if self.engine_streak >= 5:
                self.stop("Five rounds in a row lost to the engine. Stopping --")
                self.note("it comes back and then stops answering again, which")
                self.note("no amount of retrying fixes. Run STOP.bat and start")
                self.note("again; if it keeps happening, lower LC_CONTEXT.")
                return False
            status.phase("engine down", "reloading the model")
            if self.revive and self.revive():
                self.note("Reloaded it. Carrying on.")
                return True
            self.stop("Could not reload it. Stopping.")
            self.note("Close this window, run STOP.bat, then start again.")
            return False
        if result.symptom != "context":
            return True
        self.overflows += 1
        if result.refused:
            # Not the engine, whatever aider's wording says, and not worth a
            # reload: the same prompt would be refused again. Send less.
            self.lean = True
            self.note("LM Studio refused the prompt: it is bigger than the window.")
            self.note("The engine is fine. The next round on this item sends less.")
            self.note_tail(result, "What it said")
            return True
        if result.overstuffed:
            # Neither lever reaches this one. The prompt is most of the window
            # before the model has said a word, so there is nothing to grow
            # into, and shortening the answer only truncates it sooner. Left
            # alone, the branches below take turns: grow, crowd, shrink, cut
            # off, grow -- six swings and six rounds on 2026-08-10.
            self.was_cut_off = True
            self.fat_rounds += 1
            self.note("The prompt alone is taking most of the window.")
            self.note("Leaving the reply ceiling where it is -- with this much")
            self.note("going in, moving it either way just loses the round")
            self.note("differently. The source needs splitting further.")
            self.note_tail(result, "Where it stopped")
        elif not result.crowded:
            # aider says "hit a token limit" for both of these, and they want
            # opposite treatment. The window was not full, so what the reply
            # hit was our own max_tokens ceiling. Cutting that again is how one
            # genuine overflow took the two rounds after it down with it.
            self.was_cut_off = True
            self.note("The reply was cut off at the ceiling we set, with room")
            self.note("to spare in the window. Raising it -- lowering it is what")
            self.note("turns one lost round into three.")
            if self.grow_output:
                self.note("Replies may now run to %s tokens." % "{:,}".format(self.grow_output()))
            self.note_tail(result, "Where it stopped")
        else:
            self.note("The reply outgrew the context window.")
            self.note_tail(result, "Where it ran out")
            # Repeating the round unchanged just overflows again. Cut how much
            # it is allowed to say, so the next one fits.
            if self.shrink_output:
                self.note("Capping replies at %s tokens from here on."
                          % "{:,}".format(self.shrink_output()))
            else:
                self.note("That round is lost -- keep LC_RALPH_FILES short and")
                self.note("items small, or lower LC_RALPH_MAX_OUTPUT.")
        return True

    def report_inventions(self):
        """Attributes invented this round that nothing ever created. Said now,
        while the round that did it is still the last one, and put in front of
        the next round as work -- it parses, so nothing else catches it."""
        found = [(path, name) for path, name in phantom_attributes(self.edit_files)]
        found += [(path, "%s.%s (read before it is assigned in __init__)" % (klass, name))
                  for path, klass, name in used_before_set(self.edit_files)]
        fresh = [(p, n) for p, n in found if n not in self.known_phantoms]
        if not fresh:
            return
        self.known_phantoms.update(n for _, n in fresh)
        self.hallucinations += len(fresh)
        self.note("Invented %d attribute(s) nothing assigns: %s"
                  % (len(fresh), ", ".join(n for _, n in fresh[:4])))
        self.note("  Added to the list -- it parses, so nothing else catches it.")
        add_items(self.notes_path, "Found by checking for inventions",
                  ["In `%s`, `self.%s` is read but never assigned. Either create "
                   "it where the object is built, or remove the code that reads it."
                   % (os.path.basename(path), name) for path, name in fresh[:4]])

    def judge_round(self, result, touched, was_broken, rejected_now, ticked, split):
        """Say what the round amounted to, and count stalls. True if it counted one."""
        if self.broken:
            self.note("It does not run - next round repairs it.")
            say("      %s" % last_line(self.broken[0][1])[:70])
            self.stalled = 0
        elif was_broken:
            self.note("It runs again.")
            self.stalled = 0
        elif rejected_now:
            # Counts as a stall on purpose: an item the reviewer keeps turning
            # down should end up parked for a person, not retried all session.
            self.stalled += 1
            self.note("Rolled back. The reason is on the item for the next try.")
            return True
        elif ticked > 0:
            self.note("Ticked off %d item(s)." % ticked)
            if not touched:
                # It read the code, decided the job was already done, and
                # ticked the box. Sometimes true. Worth counting, because a run
                # full of these looks productive and changes nothing.
                self.suspect += 1
                self.note("  ...but no code changed. Ticked on inspection alone.")
                self._record_failure(result, ticked=ticked, touched=touched)
            self.stalled = 0
            self.dead_ends = 0
        elif split > 0:
            self.note("Split it into %d smaller item(s)." % split)
            self.stalled = 0
            self.dead_ends = 0
        elif touched:
            self.note("Changed code but ticked nothing off.")
            self.stalled = 0
            self.dead_ends = 0
        elif result.symptom == "enginedied":
            # The engine failing is not the item's fault. Give the round back:
            # no stall, no spent budget.
            self.rounds_on_task = max(0, self.rounds_on_task - 1)
            self.note("Nothing changed, but the engine was down - not this")
            self.note("item's doing. Trying it again.")
        else:
            self.stalled += 1
            self.note("Nothing changed (%d in a row)." % self.stalled)
            # The round that changes nothing is the one worth explaining.
            if not result.symptom:
                self.note_tail(result, "No symptom to name")
            return True
        return False

    def _record_failure(self, result, ticked=0, touched=False):
        """Record a lesson for a failed or inspection-only round. False to stop."""
        if result.symptom == "context" and not result.crowded:
            record_lesson(self.workspace,
                          "Reply was cut off at the ceiling with room to spare.",
                          kind="reply-cut-off")
        if ticked > 0 and not touched:
            record_lesson(self.workspace,
                          "Ticked without code change: %s" % self.current_task[:120],
                          kind="inspection-only")

    def park_stalled(self):
        """Three rounds with nothing to show: park the item. False to stop.

        This used to end the run, and cost 59 minutes of a 90-minute session
        when three rounds died on one item. One item refusing to move is a fact
        about that item; only a run where nothing anywhere moves is stuck.
        """
        if self.current_task and self.current_task not in open_tasks(self.notes_path):
            # Ticked, reworded or split by the round itself: nothing is left to
            # park, and nothing is stuck. This used to end the session.
            self.note("The item is no longer on the list as it was; moving on.")
            self.current_task = None
            self.stalled = 0
            return True
        if self.current_task and park_task(
                self.notes_path, self.current_task,
                "three rounds with nothing to show - needs a human eye"):
            record_lesson(self.workspace, "Parked after three empty rounds: %s"
                          % self.current_task[:120])
            self.note("Three rounds with nothing to show on this item.")
            self.note("Parked it and moving on to the next.")
            self.current_task = None
            self.stalled = 0
            # Reset whenever a round gets somewhere (see judge_round), so this
            # is three in a row as it says -- it used to count every park in
            # the session, and a long run stopped at its third, hours apart.
            self.dead_ends += 1
            if self.dead_ends >= 3:
                self.note("Three items in a row went nowhere. Resetting and carrying on --")
                self.note("the next item gets a fresh budget.")
                self.dead_ends = 0
            return True
        self.stop("Three rounds with nothing to show, and the item could not")
        self.note("be parked. Stopping so it does not spin for the budget.")
        return False
