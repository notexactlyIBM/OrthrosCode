"""One unattended session: re-prompt until the work is done, the clock runs out,
or it stops moving.

This was a single 930-line function. It is a class now so its state has names
and its phases can live in separate files:
    ralph_setup.py    before the first round
    ralph_refill.py   when the list runs dry
    ralph_outcome.py  what a round amounted to: symptoms, stalls, inventions
    ralph_report.py   the checkpoint and the closing summary
    ralph_send.py     what one round is sent, and the numbers it came back with
"""

import os
import time
import traceback

import ralph_common as common
import ralph_ledger as ledger
import status
from ralph_checks import code_fingerprint, find_project_python, full_check
from ralph_common import LOG_FILE, ROUNDS_IF_SMALL, TRANSCRIPT_FILE, say
from ralph_outcome import OutcomeMixin
from ralph_refill import RefillMixin
from ralph_report import ReportMixin
from ralph_send import SendMixin
from ralph_rounds import round_diff
from ralph_scan import put_main_last
from ralph_tools import handle_tool_requests, record_lesson
from ralph_setup import SetupMixin, last_line
from ralph_testfirst import TestFirstMixin, snapshot
from ralph_ladder import next_rung, outcome
from ralph_memory import git_head
from ralph_tasks import done_count, open_tasks, park_task, remember_review, triage

# Unexpected exceptions in a row before the session gives up. One is a bug in
# a rare branch; the loop logs it and carries on, because an unattended run
# that dies on the first surprise loses the rest of the night. Three in a row
# means it would only keep failing the same way.
MAX_INTERNAL_ERRORS = 3

class Session(SetupMixin, RefillMixin, OutcomeMixin, ReportMixin, SendMixin, TestFirstMixin):

    def __init__(self, base_cmd, workspace, child_env, minutes, single_shot,
                 notes_hint="", edit_files=(), iteration_timeout=420,
                 commit=None, revive=None, rollback=None, entry_hint="", run_seconds=6,
                 shrink_output=None, grow_output=None, gpu_probe=None,
                 set_temperature=None, temps=None, review=None, list_files=None, ask=None):
        self.base_cmd = list(base_cmd)
        self.workspace = workspace
        self.child_env = child_env
        self.minutes = minutes
        self.single_shot = single_shot
        self.notes_hint = notes_hint
        self.edit_files = [f for f in edit_files if f]
        self.iteration_timeout = iteration_timeout
        self.commit = commit
        self.revive = revive
        self.rollback = rollback
        self.entry_hint = entry_hint
        self.run_seconds = run_seconds
        self.shrink_output = shrink_output
        self.grow_output = grow_output
        self.gpu_probe = gpu_probe
        self._set_temperature = set_temperature
        self.temp_code, self.temp_brainstorm = temps or (common.TEMP_CODE,
                                                         common.TEMP_BRAINSTORM)
        self.review = review
        self.list_files = list_files   # re-reads the file globs, to see new modules
        self.ask = ask                 # a plain request to the model: prompt -> text
        self.located = {}              # item -> the files a locate request chose

        self.log_handle = None
        self.broken = []
        self.stop_reason = ""   # why the loop ended, carried into the summary

        self.rounds = 0
        self.stalled = 0
        self.pace = []          # (seconds, sent, received) per round, for the numbers
        self.reverted = 0
        self.refills = 0        # times the list ran dry and was topped up by review
        self.refill_retries = 0  # refills lost to a crash rather than a shortage of ideas
        self.edit_misses = 0    # consecutive rounds whose diffs would not apply
        self.suspect = 0        # items ticked without the code moving
        self.overflows = 0      # rounds lost to the reply outgrowing the window
        self.wobbles = 0        # engine errors survived by retrying, across the run
        self.dead_ends = 0      # items parked for going nowhere, in a row
        self.engine_failures = 0  # rounds lost to the engine since the last checkpoint
        self.engine_streak = 0    # consecutive rounds lost to the engine
        self.was_cut_off = False  # last round ran out of room part-way through
        self.temperature = None   # the last one set, if it could be
        self.pending_tests = {}   # item -> the test a test round wrote for it (ralph_testfirst)
        self.test_misses = {}     # item -> test rounds sent back
        self.test_budgeted = set()  # items given one more round for their test round
        self.review_note = ""     # what execution settled, for the reviewer
        self.review_tag = ""      # cited / uncited / refuted: how a rejection stood
        self.last_kept = False
        self.item_history = {}    # item -> what each round on it came to (ralph_ladder)
        self.memory = None        # past kept rounds, for examples (ralph_memory)
        self.rung = "plain"       # how this round is being tried
        self.last_failure_kind = ""  # kind of the latest lesson recorded, ranked first
        self.lean = False         # the last prompt was refused as too big: send less
        self.fat_rounds = 0       # rounds lost to the prompt, not the reply
        self.brainstormed = 0     # generation rounds run back to back
        self.empty_refills = 0    # refills in a row that added nothing
        self.milestone_misses = {}  # refills that made nothing of each milestone
        self.accepted = 0         # changes the reviewer kept
        self.rejected = 0         # changes the reviewer sent back
        self.caught = 0           # of those, caught by the automatic checks
        self.hallucinations = 0   # invented attributes caught this run
        self.known_phantoms = set()   # so one invention is only reported once
        self.internal_errors = 0  # unexpected exceptions in a row
        self.tokens_in = 0        # across every round of the session, refills too
        self.tokens_out = 0

        # per-item budget, set once by triage when the item first comes up
        self.current_task = None
        self.rounds_on_task = 0
        self.task_budget = ROUNDS_IF_SMALL

    # ------------------------------------------------------------------ logging

    def note(self, line):
        say(line)
        status.log(line.strip())
        self._log("%s  %s\n" % (time.strftime("%H:%M:%S"), line.strip()))

    def _log(self, text):
        if not self.log_handle:
            return
        try:
            self.log_handle.write(text)
            self.log_handle.flush()
        except (OSError, ValueError):
            pass

    def stop(self, line):
        """Note why the run is ending, and remember it for the summary.

        A summary reading `rounds: 0 ... state: runs` after three engine
        crashes is worse than no summary: it is the shape of a clean run. The
        reason was in the log twenty lines up and nowhere in the report.
        """
        self.stop_reason = line.strip()
        self.note(line)

    def note_tail(self, result, why):
        """Put aider's own last words in the log, not just on the console.

        A round that achieved nothing looks identical in the summary whether
        the model shrugged or the engine died. These are the lines that tell
        them apart, and they were being printed and thrown away.
        """
        if not result.tail:
            self.note("  %s, and said nothing at all." % why)
            return
        self.note("  %s. aider's last words:" % why)
        for line in list(result.tail)[-6:]:
            self.note("    | %s" % line[:100])
        self.note("  full output: %s" % TRANSCRIPT_FILE)

    def set_temperature(self, value):
        """Best effort: a failed temperature change must not cost the round."""
        if not self._set_temperature:
            return
        try:
            self._set_temperature(value)
            self.temperature = value        # for the ledger
        except Exception as exc:
            self.note("  could not set temperature %.2f: %s" % (value, exc))

    def headroom(self):
        """Free VRAM in MiB, or None. Logged per round so a crash has a trend.

        `bad allocation` is the engine asking for memory it cannot have. When
        that happens at 3am the only useful question is what the card looked
        like in the rounds before it, and nothing was recording that.
        """
        if not self.gpu_probe:
            return None
        try:
            reading = self.gpu_probe()
        except Exception:
            return None
        if not reading:
            return None
        used, total = reading
        return max(0, total - used)

    # ------------------------------------------------------------------ the loop

    def run(self):
        code = self.prepare()
        if code is not None:
            return code
        try:
            while True:
                try:
                    keep_going = self.step()
                    self.internal_errors = 0
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    if not self.survive(exc):
                        break
                    continue
                if not keep_going:
                    break
        except KeyboardInterrupt:
            say()
            self.stop("Stopped by hand.")
        finally:
            # Whatever ended it, the summary, the progress row and the status
            # file are written. A run that died on an exception used to leave
            # the dashboard showing "working" and no record of the session.
            self.finish()
        return 0

    def survive(self, exc):
        """An unexpected exception inside a round. Returns False to stop.

        Logged in full -- the traceback is the only way to fix the bug -- and
        then the loop carries on with the item re-sized from scratch.
        """
        self.internal_errors += 1
        self.note("LocalCoder hit an unexpected error: %s: %s"
                  % (type(exc).__name__, str(exc)[:120]))
        self._log(traceback.format_exc())
        self.current_task = None
        if self.internal_errors >= MAX_INTERNAL_ERRORS:
            self.stop("%d unexpected errors in a row. Stopping -- the full "
                      "tracebacks are in %s." % (self.internal_errors, LOG_FILE))
            return False
        self.note("  Traceback is in %s. Carrying on." % LOG_FILE)
        return True

    def step(self):
        """One pass of the loop: a refill, a park, or a round. False to stop."""
        # Between rounds, never during one: a stop request lets the round in
        # flight finish and be checked, so nothing is left half-edited.
        if status.stop_requested(self.workspace):
            self.stop("Stopped from the dashboard.")
            return False
        if self.single_shot and self.rounds >= 1:
            self.stop("Single round finished.")
            return False
        left = self.deadline - time.time()
        if not self.single_shot and left <= 0:
            self.stop("Time is up after %d minutes." % self.minutes)
            return False

        remaining = open_tasks(self.notes_path)
        if not remaining:
            return self.refill_step(left)

        # A new item at the top means a new budget for it.
        if remaining[0] != self.current_task:
            self.current_task = remaining[0]
            self.rounds_on_task = 0
            self.stalled = 0        # three empty rounds means three on this item
            self.lean = False
            if self.single_shot:
                self.task_budget = ROUNDS_IF_SMALL
            else:
                say("    sizing up: %s" % self.current_task[:60])
                self.task_budget, verdict = triage(self.current_task)
                self.note("    -> %s, worth up to %d round(s)" % (verdict, self.task_budget))

        # Spent its budget without getting ticked: set it aside and move on
        # rather than spend the rest of the session on one stubborn item.
        if self.rounds_on_task >= self.task_budget:
            if park_task(self.notes_path, self.current_task,
                         "no result after %d rounds - needs a human eye" % self.rounds_on_task):
                self.note("Parked after %d rounds: %s"
                          % (self.rounds_on_task, self.current_task[:50]))
                record_lesson(self.workspace, "Parked, no result in %d rounds: %s -- split "
                              "items like it smaller" % (self.rounds_on_task, self.current_task[:100]))
                self.current_task = None
                return True
            self.stop("Could not park the stuck item. Stopping.")
            return False

        return self.work_round(remaining, left)

    # ------------------------------------------------------------------ a round

    def work_round(self, remaining, left):
        self.rounds += 1
        self.rounds_on_task += 1
        task = self.current_task
        phase = self.round_phase(task)
        history = self.item_history.setdefault(task, [])
        self.rung = "plain"
        if phase == "code":
            from ralph_rounds import files_for_task
            self.rung = next_rung(history, files_for_task(task, self.edit_files))
            if self.rung != "plain":
                self.note("  trying it differently: %s (the last try %s)"
                          % ({"whole": "whole-file edits", "architect": "architect mode",
                              "split": "asking for it to be split"}[self.rung],
                             {"edit-missed": "did not apply", "broke": "broke the checks",
                              "no-change": "changed nothing", "rejected": "was sent back"}
                             .get(history[-1], history[-1])))
            if self.rung == "split":
                history.append("split")
        if phase == "test" and task not in self.test_budgeted:
            self.test_budgeted.add(task)
            self.task_budget += 1           # the test round is not one of the tries
        say("-" * 62)
        if self.single_shot:
            self.note("Round %d  |  %d items left" % (self.rounds, len(remaining)))
        else:
            self.note("Round %d  |  %d left  |  %d min  |  %d/%d on this item"
                      % (self.rounds, len(remaining), int(left // 60),
                         self.rounds_on_task, self.task_budget))
        say("    %s" % task[:64])
        if phase == "test":
            say("    (test round: the test for it, no code)")
        say("-" * 62)

        # Commit what the loop wrote since the last round -- a refill's items,
        # ticks, parks, lessons, answers -- so that undoing this round undoes
        # only this round. Undo is `git checkout -- .`: it took all of that
        # too, and a rejected round after a refill emptied the list again.
        if self.commit and not self.broken:
            self.commit("LocalCoder ralph: notes before round %d" % self.rounds)
        if phase == "code":
            self.put_test_back(task)
        tests_before = snapshot(self.workspace) if phase == "test" else {}
        code_before = code_fingerprint(self.non_test_files()) if phase == "test" else ""
        before = (len(remaining), done_count(self.notes_path), code_fingerprint(self.edit_files),
                  self.listing())
        self.maybe_switch_to_whole_files()

        status.update(round=self.rounds, item=task, attempt=self.rounds_on_task,
                      budget=self.task_budget, items_open=len(remaining),
                      items_done=done_count(self.notes_path))
        status.phase("working", task)
        result = self.send_round(task, phase=phase, rung=self.rung)
        if phase == "test":
            if not self.react_to_symptom(result):
                self.after_test_round(result, task, tests_before, code_before, before[3])
                return False
            return self.after_test_round(result, task, tests_before, code_before, before[3])
        self.hold_test(task)
        if not self.react_to_symptom(result):
            self.settle_test(task, False)
            return False
        self.last_kept = False
        keep_going = self.after_round(result, before)
        self.settle_test(task, self.last_kept)
        return keep_going

    def non_test_files(self):
        return [f for f in self.edit_files if not os.path.basename(f).startswith("test_")]

    def maybe_switch_to_whole_files(self):
        """A small model that keeps producing SEARCH blocks which do not match
        the file will keep doing it. aider's documented remedy is to stop
        sending diffs and rewrite whole files instead: far more tokens, but
        they land."""
        if self.edit_misses < 2 or "--edit-format" not in self.base_cmd:
            return
        spot = self.base_cmd.index("--edit-format") + 1
        if spot < len(self.base_cmd) and self.base_cmd[spot] != "whole":
            self.base_cmd[spot] = "whole"
            self.note("Diffs keep missing - switching to whole-file edits.")
            self.edit_misses = 0

    def after_round(self, result, before):
        """Check, review, record and commit what the round did. False to stop."""
        before_open, before_done, before_print, before_files = before
        notes_path, ws = self.notes_path, self.workspace
        task_text = self.current_task or ""
        after_open = len(open_tasks(notes_path))
        after_done = done_count(notes_path)
        # Files the round created count as its work. A new project has none to
        # begin with, and they were only picked up after a commit -- which
        # needs a change seen in the files already known. So none ever were.
        self.refresh_files()
        touched = code_fingerprint(self.edit_files) != before_print

        # The model does not always work the item we pointed it at -- it often
        # ticks something else off instead. A round like that is productive,
        # so it should not count against the top item's budget.
        if after_done > before_done or after_open > before_open:
            self.rounds_on_task = max(0, self.rounds_on_task - 1)

        was_broken = bool(self.broken)
        broke = False
        status.phase("checking", "does it still build and run")
        self.broken = full_check(ws, self.edit_files, self.entry, self.run_seconds)

        # A round that leaves it unable to start is worse than a round that did
        # nothing, so undo it outright rather than spending the next round
        # repairing damage. Only where LocalCoder owns the history.
        if self.broken and not was_broken and touched and self.rollback:
            self.note("That round broke it. Rolling the round back.")
            say("      %s" % last_line(self.broken[0][1])[:70])
            if self.rollback():
                self.remove_new_sources(before_files)
                self.reverted += 1
                broke = True
                # The credit for ticking was for work now undone, as for a
                # rejection below. Kept, a round that ticked the item and broke
                # the tests was free, and the item was retried until the clock
                # ran out (found 2026-09-26 by test_ralph_testfirst).
                if after_done > before_done or after_open > before_open:
                    self.rounds_on_task += 1
                after_done = done_count(notes_path)
                after_open = len(open_tasks(notes_path))
                record_lesson(ws, "Broke start-up and was undone: %s -- %s"
                              % (self.current_task[:80], last_line(self.broken[0][1])[:100]))
                self.broken = full_check(ws, self.edit_files, self.entry, self.run_seconds)
                touched = code_fingerprint(self.edit_files) != before_print
                self.note("Rolled back; it %s."
                          % ("runs again" if not self.broken else "is still broken"))
            else:
                self.note("Could not roll it back - next round repairs instead.")

        # A second opinion, from an agent that did not write the change. Every
        # check before this asks whether the code is well formed; none can ask
        # whether it does what the item said.
        rejected_now = False
        verdict, why = "", ""
        self.review_tag = ""
        diff = round_diff(ws, self.edit_files) if touched and not self.broken else ""
        moved = put_main_last(self.edit_files, diff) if diff else []
        if moved:
            self.note("  put `if __name__ == \"__main__\":` back at the end of %s"
                      % ", ".join(os.path.basename(f) for f in moved))
            diff = round_diff(ws, self.edit_files)
        findings = self.scan_round(diff) if diff else []
        caught = [m for kind, m in findings if kind == "reject"]
        if (self.review or caught) and touched and not self.broken:
            if caught:
                verdict, why = "reject", "automatic check: " + "; ".join(caught[:3])
                self.caught += 1
            else:
                status.phase("reviewing", self.current_task)
                verdict, why = self.second_opinion(self.current_task, diff,
                                                   [m for kind, m in findings if kind == "warn"])
            if verdict == "reject":
                self.rejected += 1
                self.note("%s rejected it: %s" % ("An automatic check" if caught else "Reviewer",
                                                  why[:110]))
                if self.rollback and self.rollback():
                    self.remove_new_sources(before_files)
                    rejected_now = True
                    touched = False
                    if after_done > before_done or after_open > before_open:
                        self.rounds_on_task += 1      # the credit was for work now undone
                    after_done = done_count(notes_path)
                    after_open = len(open_tasks(notes_path))
                    remember_review(notes_path, self.current_task, why)
                    record_lesson(ws, "Reviewer rejected: %s -- %s"
                                  % (self.current_task[:80], why[:100]))
                else:
                    self.note("  Could not roll it back -- keeping it, flagged.")
            elif verdict == "accept":
                self.accepted += 1
                self.note("Reviewer accepted it%s." % (": " + why[:90] if why else ""))
            else:
                self.note("Reviewer gave no clear verdict (%s) -- keeping the change."
                          % (why or "no reason given")[:80])

        self.report_inventions()
        counted = self.judge_round(result, touched, was_broken, rejected_now,
                                   after_done - before_done, after_open - before_open)

        # Only ever commit a round that left the code runnable, so `git
        # revert` never lands on a broken snapshot.
        kept = bool(self.commit and touched and not self.broken)
        if kept:
            # The item goes in the message: it is how ralph_memory finds this
            # change again as an example for a similar item.
            self.commit("LocalCoder ralph: round %d\n\nItem: %s" % (self.rounds,
                                                                   " ".join(task_text.split())))
            self.refresh_files()
            if self.memory is not None:
                self.memory.remember(git_head(ws), " ".join(task_text.split()))
        self.ledger_round(result, touched, verdict, self.review_tag + (why or ""), caught,
                          after_done - before_done, kept, diff)
        if self.current_task:
            self.item_history.setdefault(self.current_task, []).append(
                outcome(result, touched, kept, rejected_now, broke or bool(self.broken)))

        self.last_kept = kept
        return self.finish_round(result, counted)

    def finish_round(self, result, counted):
        """What every round ends with: answer requests, report, park or stop. False to stop."""
        notes_path, ws = self.notes_path, self.workspace
        handle_tool_requests(ws, notes_path, find_project_python(ws), ask=self.ask)
        status.update(ticked=done_count(notes_path) - self.started_done,
                      accepted=self.accepted, rejected=self.rejected,
                      items_open=len(open_tasks(notes_path)),
                      items_done=done_count(notes_path),
                      milestones=self.milestone_state())

        if not result.ran and not counted:
            self.stalled += 1       # killed on the clock; once, not twice
        if self.stalled >= 3 and not self.park_stalled():
            return False
        if not self.single_shot and time.time() >= self.next_checkpoint \
                and not self.checkpoint():
            return False
        return True

    def ledger_round(self, result, touched, verdict, why, caught, ticked, kept, diff):
        """One row in the ledger for this round (ralph_ledger.py). Never raises."""
        if verdict not in ("accept", "reject"):
            verdict = "unclear" if verdict else ("skipped" if not diff else "")
        try:
            self._ledger_row(result, touched, verdict, why, caught, ticked, kept, diff)
        except Exception as exc:          # bookkeeping must not cost a round
            self.note("  could not write the ledger: %s" % exc)

    def _ledger_row(self, result, touched, verdict, why, caught, ticked, kept, diff):
        ledger.record(self.workspace, agent=os.environ.get("ORTHROS_AGENT", ""),
                      workspace=os.path.basename(os.path.normpath(self.workspace)),
                      kind=os.environ.get("ORTHROS_KIND", "self"),
                      item=self.current_task or "", attempt=self.rounds_on_task,
                      temperature=self.temperature, tokens_in=result.sent or 0,
                      tokens_out=result.got or 0,
                      seconds=self.pace[-1][0] if self.pace else 0,
                      symptom=result.symptom or "", applied=result.applied or 0,
                      failed=result.failed or 0, touched=int(bool(touched)),
                      broken=last_line(self.broken[0][1])[:200] if self.broken else "",
                      caught="; ".join(caught)[:300], verdict=verdict,
                      reason=(why or "")[:300], ticked=max(0, ticked), kept=int(kept),
                      diff=diff, rung=getattr(self, "rung", "plain"))

    # ------------------------------------------------------------------ files

    SOURCE_EXTS = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")

    def listing(self):
        try:
            return set(os.listdir(self.workspace))
        except OSError:
            return set()

    def remove_new_sources(self, before):
        """Delete source files a rolled-back round created.

        Rolling back is `git checkout -- .`, which restores tracked files and
        never touches new ones. A rejected round that added a module left it
        behind, and the next commit swept it into the history the reviewer had
        just refused. Only source files, only ones that did not exist when the
        round began -- never the loop's own logs and notes.
        """
        for name in sorted(self.listing() - before):
            path = os.path.join(self.workspace, name)
            if name.startswith(".") or not name.lower().endswith(self.SOURCE_EXTS)                     or not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                self.note("  removed %s, which the undone round had created" % name)
            except OSError:
                pass

    def refresh_files(self):
        """Pick up modules the model created, so later rounds can see and check them.

        The file list used to be fixed when the session started. A round that
        split a module in two left the new half out of every later round:
        never sent, never parsed, never imported by the checks.
        """
        if not self.list_files:
            return
        try:
            fresh = [f for f in self.list_files() if f]
        except Exception:
            return
        added = [f for f in fresh if f not in self.edit_files]
        if added:
            self.edit_files += added
            self.note("  now also working on: %s"
                      % ", ".join(os.path.basename(f) for f in added)[:100])

    def count_tokens(self, result):
        self.tokens_in += result.sent or 0
        self.tokens_out += result.got or 0
        status.update(tokens_in=self.tokens_in, tokens_out=self.tokens_out)
