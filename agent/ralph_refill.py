"""When the list runs dry and the clock has not: plan, decompose, brief, verify.

Part of Session (ralph_session.py). Kept apart because it is the one phase
with its own failure modes -- a refill round sends the largest prompt of any
session, so it is where the engine dies and where the reply runs out of room.
"""

from ralph_common import (BRAINSTORM_ROUNDS, BRAINSTORM_UNTIL, MAX_REFILLS, more_refills, say)
from ralph_rounds import refill_list
from ralph_tasks import mark_decomposed, milestones, open_tasks

import status


class RefillMixin:

    def refill_step(self, left):
        """The list is done but the clock is not. Returns False to stop.

        Rather than hand back an hour of unused budget, ask for the next work
        and carry on.
        """
        if self.single_shot or (MAX_REFILLS and self.refills >= MAX_REFILLS) or left < 120:
            self.stop("Every item is ticked. Done.")
            return False
        self.refills += 1
        say("-" * 62)
        self.note("List is empty with %d min left. Looking for more (%s)."
                  % (int(left // 60),
                     "%d of %d" % (self.refills, MAX_REFILLS) if MAX_REFILLS
                     else "round %d" % self.refills))
        say("-" * 62)
        before = len(open_tasks(self.notes_path))
        # Warm for this. Inventing work at the temperature that writes good
        # diffs returns the same four safe ideas every time.
        self.set_temperature(self.temp_brainstorm)
        status.phase("planning", "looking for the next work")
        try:
            result, source, mode, milestone = refill_list(
                self.base_cmd, self.workspace, self.child_env, self.notes_path,
                self.edit_files, self.iteration_timeout, self.refills)
        finally:
            self.set_temperature(self.temp_code)
        self.count_tokens(result)
        self.note("  %s: %s" % (mode, source))
        added = len(open_tasks(self.notes_path)) - before
        if added > 0:
            return self.refill_added(added, milestone, left)

        # A planning round writes milestones, not items, so an empty task list
        # afterwards is success rather than failure.
        if mode == "plan":
            fresh = sum(1 for _, _, d in milestones(self.plan_path) if not d)
            if fresh:
                self.note("Planned %d milestone(s). Breaking the first one down." % fresh)
                self.refill_retries = 0
                return True

        # An empty refill used to mean one thing -- out of ideas -- and was
        # reported that way whatever had actually happened. It is far more
        # often the engine having died on the largest prompt of the session.
        if result.symptom == "enginedied":
            return self.refill_engine_died(result, left)
        if result.symptom == "context":
            return self.refill_out_of_room(result, left)
        if not result.ran:
            self.note_tail(result, "The review round was killed after %ds"
                           % self.iteration_timeout)
            return False
        self.stop("It could not think of anything else. Stopping.")
        self.note_tail(result, "The review round finished but added nothing")
        return False

    def refill_added(self, added, milestone, left):
        self.note("Added %d new item(s)." % added)
        self.refill_retries = 0
        self.empty_refills = 0
        self.engine_streak = 0     # it answered; the run is alive
        # Mark it done *here*, before anything below can jump back to the top
        # of the loop. Its items are on the list, which is the whole definition
        # of broken down. The brainstorm check used to return early past this,
        # so a milestone that triggered one came up again next time: on 08-09
        # one milestone was decomposed three times for 21 items.
        if milestone and mark_decomposed(self.plan_path, milestone):
            left_over = sum(1 for _, _, d in milestones(self.plan_path) if not d)
            self.note("  milestone broken down; %d left in the plan" % left_over)
        # One refill is a top-up, not a plan. If the list is still thin, stay
        # in generation rather than doing the two items it produced and coming
        # straight back -- each return trip costs a full round of context.
        queued = len(open_tasks(self.notes_path))
        if queued < BRAINSTORM_UNTIL and left > 300 and self.brainstormed < BRAINSTORM_ROUNDS:
            self.brainstormed += 1
            self.note("Only %d item(s) on the list. Staying in brainstorm" % queued)
            self.note("for another round (%d of %d)." % (self.brainstormed, BRAINSTORM_ROUNDS))
            return True
        self.brainstormed = 0
        self.current_task = None
        return True

    def refill_engine_died(self, result, left):
        self.engine_failures += 1
        self.engine_streak += 1
        self.note_tail(result, "The engine died during the review round")
        # The same ceiling the working rounds have. Without it this branch
        # cannot give up: three crashes rotate to the next brief and reset the
        # count, and with refills uncapped it rotates for ever -- 48 minutes
        # and about ten attempts without a round of work on 2026-08-11.
        if self.engine_streak >= 5:
            self.stop("Five attempts in a row lost to the engine, with no")
            self.note("work done in between. Stopping: it comes back and")
            self.note("then stops answering, which retrying cannot fix.")
            self.note("Check nothing else is using the card -- another")
            self.note("LM Studio, ollama, a game -- then start again.")
            return False
        if not (self.revive and self.revive()):
            self.stop("Could not get the engine back. Stopping.")
            return False
        if self.refill_retries < 2:
            self.refill_retries += 1
            self.refills -= 1          # a crash is not an idea we spent
            self.note("Engine is back. Asking the same brief again.")
            return True
        # Three crashes on one brief is that brief, not bad luck. A long brief
        # generates a long answer, the most crash-prone thing a session does;
        # another brief is a different length.
        if more_refills(self.refills) and left > 180:
            self.refill_retries = 0
            self.note("Three crashes on this brief. Trying the next one.")
            return True
        self.stop("Out of briefs to try. This is the machine, not the")
        self.note("task list -- lower LC_CONTEXT, or close what else")
        self.note("wants the card.")
        return False

    def refill_out_of_room(self, result, left):
        # Same distinction the working rounds make: a reply cut off at 42% of
        # the window did not outgrow the window. It outgrew the ceiling we set,
        # and shrinking that ceiling is what turned one failed review into
        # three and ended a session with twelve minutes and four briefs left.
        self.empty_refills += 1
        if result.overstuffed:
            # The prompt was most of the window before the model spoke. Neither
            # ceiling lever reaches that, and every other brief carries the
            # same source, so rotating just fails again the same way.
            self.note_tail(result, "The review round's prompt filled the window on its own")
        elif result.crowded:
            self.note_tail(result, "The review round outgrew the window")
            if self.shrink_output:
                self.note("Capping replies at %s tokens." % "{:,}".format(self.shrink_output()))
        else:
            self.note_tail(result, "The review round was cut off at our ceiling "
                                   "with window to spare")
            if self.grow_output:
                self.note("Giving it more room: %s tokens." % "{:,}".format(self.grow_output()))
        # A ceiling on refills that achieve nothing. There was none: on
        # 2026-08-14 every brief failed the same way for 45 minutes -- about
        # forty refills, not one item.
        if self.empty_refills >= 4:
            self.stop("Four refills in a row added nothing. Stopping --")
            self.note("they are all failing the same way, so the next")
            self.note("one will too. See the lines above for why.")
            return False
        # Move to the next brief rather than asking the same one again. An
        # open-ended section keeps running long; repeating it fails the same
        # way while the sections after it never get their turn.
        if more_refills(self.refills) and left > 180:
            self.note("Moving on to the next brief.")
            return True
        return False
