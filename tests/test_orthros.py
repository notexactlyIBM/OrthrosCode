"""Tests for the orchestrator: parking, early stops, rollback notes, restarts,
the chat box, operator patches and the aider guard. No model, no GPU.

    python -m unittest discover -s tests
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import importlib.util  # noqa: E402

import orthros  # noqa: E402

# By path: `import sitecustomize` finds whichever one Python already loaded.
_spec = importlib.util.spec_from_file_location(
    "orthros_guard_site", os.path.join(ROOT, "orthros_guard", "sitecustomize.py"))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

TASKS = "# Orthros: B improving A\n\n## Tasks\n\n- [ ] In `f`, return 2\n- [ ] In `g`, return 3\n"


def git(folder, *args):
    return orthros.git(folder, *args)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for n in orthros.NAMES:
            folder = os.path.join(self.root, "OrthrosCode %s" % n)
            os.makedirs(folder)
            self.write(folder, "agent.py", "def f():\n    return 1\n")
            self.write(folder, "orthros_tasks.md", TASKS)
            self.write(folder, ".gitignore", ".localcoder*\n")
            git(folder, "init", "-q")
            orthros.commit_all(folder, "start")
        self.o = orthros.Orthros(self.root, simulate=True)
        self.o.event = lambda text, kind="info": self.events.append(text)
        self.events = []
        self.o.prepare_folders()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def write(folder, name, body):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(body)

    def notes(self, n):
        return orthros.read_text(os.path.join(self.o.folders[n], "orthros_tasks.md"))

    def result(self, agent="A", **kw):
        log = os.path.join(self.root, "turn.log")
        self.write(self.root, "turn.log", kw.pop("log_text", ""))
        base = {"agent": agent, "started": 0, "seconds": 400, "exit": 0, "launched": True,
                "rounds": 5, "ticked": 0, "kept": 0, "sent_back": 0, "tokens": 0,
                "reason": "Five rounds in a row lost to the engine. Stopping --", "log": log,
                "own": orthros.head(self.o.folders[agent]),
                "pre": orthros.head(self.o.folders[orthros.PEER[agent]]),
                "post": orthros.head(self.o.folders[orthros.PEER[agent]]),
                "item": "In `f`, return 2", "minutes": 45, "lowest_free_mb": None}
        base.update(kw)
        return base


class TestTaskList(Sandbox):
    def test_add_first_goes_before_the_first_item(self):
        path = os.path.join(self.o.folders["A"], "orthros_tasks.md")
        self.assertTrue(orthros.add_first(path, "From the operator: do X"))
        items = orthros.OPEN_ITEM.findall(self.notes("A"))
        self.assertEqual(items[0], "From the operator: do X")
        self.assertEqual(len(items), 3)

    def test_park_item(self):
        path = os.path.join(self.o.folders["A"], "orthros_tasks.md")
        self.assertTrue(orthros.park_item(path, "In `f`, return 2", "stuck"))
        self.assertNotIn("In `f`, return 2", orthros.OPEN_ITEM.findall(self.notes("A")))
        self.assertIn("*Parked by Orthros*: stuck", self.notes("A"))
        self.assertFalse(orthros.park_item(path, "not there", "x"))


class TestJudging(Sandbox):
    def test_item_a_turn_keeps_dying_on_is_parked_on_the_second_turn(self):
        # A works on B's list; the item it died on is B's.
        self.o.judge(self.result("A"))
        self.assertIn("In `f`, return 2", orthros.OPEN_ITEM.findall(self.notes("B")))
        self.o.judge(self.result("A"))
        self.assertNotIn("In `f`, return 2", orthros.OPEN_ITEM.findall(self.notes("B")))
        self.assertIn("Parked by Orthros", self.notes("B"))

    def test_progress_clears_the_count(self):
        self.o.judge(self.result("A"))
        self.o.judge(self.result("A", kept=2, reason="Time is up after 45 minutes."))
        self.o.judge(self.result("A"))
        self.assertIn("In `f`, return 2", orthros.OPEN_ITEM.findall(self.notes("B")))

    def test_early_stop_becomes_the_twins_first_item_once(self):
        self.o.judge(self.result("A"))
        first = orthros.OPEN_ITEM.findall(self.notes("A"))[0]
        self.assertIn("stopped itself after 6 of 45 minutes", first)
        self.assertIn("FIND: Five rounds in a", first)
        self.o.judge(self.result("A"))
        self.assertEqual(self.notes("A").count("stopped itself"), 1)

    def test_a_practice_that_ends_early_is_not_an_early_stop(self):
        self.o.note_early_stop("A", self.result(
            "A", kind="practice", reason="It could not think of anything else. Stopping."))
        self.assertNotIn("stopped itself", self.notes("A"))

    def test_a_full_turn_is_not_an_early_stop(self):
        self.o.judge(self.result("A", seconds=45 * 60, reason="Time is up after 45 minutes."))
        self.assertNotIn("stopped itself", self.notes("A"))

    def test_oversize_prompts_spare_one_rollback_and_say_so(self):
        folder = self.o.folders["A"]
        self.write(folder, "agent.py", "def f():\n    return 5\n")      # unproven change
        orthros.commit_all(folder, "B's change to A")
        text = ('request (32958 tokens) exceeds the available context size (32768 tokens)')
        self.o.judge(self.result("A", log_text=text))
        self.o.judge(self.result("A", log_text=text))
        self.assertEqual(self.o.agent("A")["rollbacks"], 0)
        self.assertTrue(any("not rolling A back yet" in e for e in self.events))
        self.o.judge(self.result("A", log_text=text))
        self.o.judge(self.result("A", log_text=text))
        self.assertEqual(self.o.agent("A")["rollbacks"], 1)

    def test_a_weak_turn_on_a_proven_version_does_not_count_against_later_changes(self):
        stop = "Nothing moved in 10 minutes. Stopping."
        self.o.judge(self.result("A", reason=stop))              # on its proven baseline
        folder = self.o.folders["A"]
        self.write(folder, "agent.py", "def f():\n    return 5\n")      # B's change to A
        orthros.commit_all(folder, "B's change to A")
        self.o.judge(self.result("A", reason=stop))
        self.assertEqual(self.o.agent("A")["rollbacks"], 0)      # one weak turn on the change
        self.o.judge(self.result("A", reason=stop))
        self.assertEqual(self.o.agent("A")["rollbacks"], 1)      # two: now it goes

    def test_field_report_names_oversize_prompts(self):
        text = ("litellm.APIConnectionError: ... request (32958 tokens) exceeds the available "
                "context size (32768 tokens), try increasing it\n")
        self.o.field_report(self.result("A", log_text=text * 3))
        report = orthros.read_text(os.path.join(self.o.folders["A"], "FIELD_REPORT.md"))
        self.assertIn("The engine did not die", report)
        self.assertIn("32,958", report)

    def test_field_report_says_where_this_turns_rounds_went(self):
        # Written by the agents' own module, read by Orthros's own query: the
        # two must agree on the table.
        spec = importlib.util.spec_from_file_location(
            "ralph_ledger", os.path.join(ROOT, "agent", "ralph_ledger.py"))
        ledger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ledger)
        env = self.o.agent_env("A")
        self.assertEqual(env["ORTHROS_AGENT"], "A")
        blank = dict(symptom="", failed=0, applied=1, broken="", caught="", verdict="")
        with mock.patch.dict(os.environ, {"ORTHROS_LEDGER": env["ORTHROS_LEDGER"]}):
            ledger.record(self.root, agent="A", at=50, kept=1, **blank)     # an older turn
            ledger.record(self.root, agent="A", at=150, kept=1, **blank)
            ledger.record(self.root, agent="A", at=160, kept=0,
                          **dict(blank, verdict="reject"))
            ledger.record(self.root, agent="B", at=170, kept=1, **blank)   # the twin's
        self.o.field_report(self.result("A", started=100))
        report = orthros.read_text(os.path.join(self.o.folders["A"], "FIELD_REPORT.md"))
        self.assertIn("Where the rounds went: kept 1, rejected by reviewer 1.", report)


class TestRollbackNote(Sandbox):
    def test_rollback_writes_the_undone_diff_where_a_round_can_read_it(self):
        folder = self.o.folders["A"]
        self.write(folder, "agent.py", "def f():\n    return 42\n")
        self.o.rollback("A", "it failed to start")
        note = orthros.read_text(os.path.join(folder, "ROLLBACK.md"))
        self.assertIn("return 42", note)
        self.assertIn("ROLLBACK.md", self.notes("A"))
        self.assertNotIn("git diff", self.notes("A"))
        self.assertIn("return 1", orthros.read_text(os.path.join(folder, "agent.py")))


class TestRestart(Sandbox):
    def test_a_turn_that_ended_while_orthros_was_down_is_judged(self):
        peer = self.o.folders["B"]
        running = {"agent": "A", "pid": 999999, "started": 0, "minutes": 5, "token": "tok",
                   "log": os.path.join(self.root, "turn.log"), "own": "", "pre": "", "post": ""}
        self.write(self.root, "turn.log", "")
        orthros.write_json(os.path.join(peer, orthros.STATUS_FILE),
                           {"session": "tok", "phase": "finished", "rounds": 4, "accepted": 2,
                            "ticked": 2, "ended": 200, "ended_reason": "Time is up."})
        self.o.state["running"] = running
        self.o.save()
        again = orthros.Orthros(self.root, simulate=True)
        again.event = lambda text, kind="info": self.events.append(text)
        again.release = lambda name: None
        self.assertIn("unjudged", again.state)
        again.adopt_orphan()
        self.assertEqual(again.agent("A")["sessions"], 1)
        self.assertEqual(again.agent("A")["kept"], 2)
        self.assertEqual(again.state["next"], "B")


class TestResume(Sandbox):
    def test_only_a_run_that_died_is_resumed(self):
        self.o.start()
        self.assertTrue(orthros.Orthros(self.root, simulate=True).state["wanted"])
        self.o.pause("Paused after the session, as asked.")
        self.assertFalse(orthros.Orthros(self.root, simulate=True).state["wanted"])


class TestDoctor(Sandbox):
    def test_it_reports_and_changes_nothing(self):
        before = {n: orthros.head(self.o.folders[n]) for n in orthros.NAMES}
        lines = []
        fails = orthros.doctor(self.root, out=lines.append)
        text = "\n".join(lines)
        self.assertEqual(fails, 0, text)
        self.assertIn("held-out exercises", text)
        self.assertIn("A's Python", text)
        self.assertEqual(before, {n: orthros.head(self.o.folders[n]) for n in orthros.NAMES})

    def test_a_missing_agent_is_a_failure(self):
        shutil.rmtree(os.path.join(self.o.folders["B"], ".git"))
        lines = []
        self.assertEqual(orthros.doctor(self.root, out=lines.append), 1)
        self.assertTrue(any(l.startswith("FAIL  B: no agent") for l in lines))


class TestSurrender(Sandbox):
    def test_giving_up_is_loud_and_start_clears_it(self):
        self.o.pause("the card is gone", error=True)
        alert = os.path.join(self.root, orthros.ALERT_FILE)
        self.assertIn("the card is gone", orthros.read_text(alert))
        self.assertEqual(self.o.view()["alert"][1], "the card is gone")
        self.o.start()
        self.assertFalse(os.path.exists(alert))
        self.assertIsNone(self.o.view()["alert"])

    def test_an_ordinary_pause_is_quiet(self):
        self.o.pause("Paused after the session, as asked.")
        self.assertFalse(os.path.exists(os.path.join(self.root, orthros.ALERT_FILE)))

    def test_machine_failures_are_retried_with_backoff_then_surrendered(self):
        self.o.settings["env_retry_minutes"] = [2, 5]
        failed = self.result("A", launched=False, log_text="The LM Studio server never came up.")
        self.o.launch_failed("A", failed)
        self.assertGreater(self.o.backoff_until, orthros.now() + 100)
        self.assertFalse(self.o.state["paused"] and self.o.phase == "error")
        self.o.launch_failed("A", failed)
        self.assertGreater(self.o.backoff_until, orthros.now() + 250)
        self.o.launch_failed("A", failed)
        self.assertEqual(self.o.phase, "error")
        self.assertTrue(os.path.exists(os.path.join(self.root, orthros.ALERT_FILE)))


class TestTail(Sandbox):
    def test_reads_new_output_by_offset(self):
        log = os.path.join(self.o.logs, "20260101-000000-A.log")
        self.write(self.o.logs, "20260101-000000-A.log", "one\n\x1b[1mtwo\x1b[0m\n")
        first = self.o.tail_log("A", "", -1)
        self.assertEqual(first["text"], "one\ntwo\n")    # escapes gone
        with open(log, "a") as handle:
            handle.write("three\n")
        more = self.o.tail_log("A", first["file"], first["offset"])
        self.assertEqual((more["text"], more["reset"]), ("three\n", False))

    def test_a_long_log_starts_on_a_whole_line(self):
        self.write(self.o.logs, "20260101-000000-B.log", "x" * 30000 + "\nlast line\n")
        self.assertEqual(self.o.tail_log("B", "", -1)["text"], "last line\n")


class TestModes(Sandbox):
    def test_self_mode_practises_every_few_turns(self):
        self.o.settings["practice_every"] = 2
        self.assertEqual(self.o.next_work("A")["kind"], "self")
        self.o.agent("A")["since_practice"] = 2
        w = self.o.next_work("A")
        self.assertEqual(w["kind"], "practice")
        self.assertTrue(os.path.isfile(os.path.join(w["folder"], "orthros_tasks.md")))
        self.assertFalse(os.path.exists(os.path.join(w["folder"], "hidden")))

    def test_task_mode_needs_a_task_and_then_both_agents_work_it(self):
        self.assertEqual(self.o.set_mode("task"), "choose or create a task first")
        made = self.o.new_task("Line counter", "Count lines, words and characters in files.")
        self.assertEqual(made["key"], "line-counter")
        self.assertEqual(self.o.set_mode("task", "line-counter"), "ok")
        for n in orthros.NAMES:
            w = self.o.next_work(n)
            self.assertEqual((w["kind"], os.path.basename(w["folder"])), ("task", "line-counter"))
        self.assertEqual(self.o.new_task("x", "too short")["error"][:3], "Say")

    def test_a_practice_turn_is_scored_recorded_and_reported(self):
        result = self.result("A", kind="practice", label="word_count", score=[5, 7], kept=2,
                             reason="Time is up.", seconds=1200, minutes=20)
        self.o.field_report(result)
        self.o.judge(result)
        self.assertEqual(self.o.agent("A")["practice"][-1][1:], ["word_count", 5, 7])
        self.assertEqual(self.o.agent("A")["since_practice"], 0)
        report = orthros.read_text(os.path.join(self.o.folders["A"], "FIELD_REPORT.md"))
        self.assertIn("**Practice** on word_count: 5 of 7", report)
        self.assertEqual(self.o.agent("B")["pending"], [])     # no carry-over from a practice

    def test_self_turns_count_towards_the_next_practice(self):
        self.o.judge(self.result("A", kept=1, reason="Time is up.", seconds=2700))
        self.assertEqual(self.o.agent("A")["since_practice"], 1)

    def test_start_puts_the_definition_of_better_into_the_mission(self):
        for n in orthros.NAMES:
            self.write(self.o.folders[n], "RALPH_PROMPT.md", "# How to work\n")
        self.o.prepare_folders()
        self.assertIn("# What better means",
                      orthros.read_text(os.path.join(self.o.folders["B"], "RALPH_PROMPT.md")))

    def test_direction_for_the_task(self):
        self.o.new_task("demo", "Build a small demo of something useful.")
        self.o.set_mode("task", "demo")
        self.o.chat("use argparse", kind="direct", target="task")
        notes = orthros.read_text(os.path.join(self.root, "tasks", "demo", "orthros_tasks.md"))
        self.assertIn("From the operator: use argparse", notes)


class TestChat(Sandbox):
    def test_status_question_gets_a_plain_answer(self):
        reply = self.o.chat("how is it going?")
        self.assertIn("paused", reply)
        self.assertIn("A has had 0 turns", reply)
        self.assertLess(len(reply.splitlines()), 8)

    def test_temperature_question(self):
        self.assertIn("LC_TEMP_CODE", self.o.chat("what temperature is used?"))

    def test_direction_goes_first_when_the_list_is_free(self):
        self.o.chat("cache research answers", kind="direct", target="B")
        self.assertEqual(orthros.OPEN_ITEM.findall(self.notes("B"))[0],
                         "From the operator: cache research answers")
        self.assertNotIn("cache research", self.notes("A"))

    def test_direction_waits_while_a_turn_uses_the_list(self):
        self.o.state["running"] = {"agent": "A", "started": 0, "minutes": 5}
        reply = self.o.chat("cache research answers", kind="direct", target="B")
        self.assertIn("Queued", reply)
        self.assertNotIn("cache research", self.notes("B"))
        self.o.state["running"] = None
        self.o.apply_directions(from_loop=True)
        self.assertIn("From the operator: cache research answers", self.notes("B"))


class TestApplyPatch(Sandbox):
    def test_applies_checks_commits_and_proves(self):
        patch = ("diff --git a/agent.py b/agent.py\n--- a/agent.py\n+++ b/agent.py\n"
                 "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 7\n")
        self.write(self.root, "fix.patch", patch)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orthros.apply_patch(self.root, os.path.join(self.root, "fix.patch")),
                             0)
        state = orthros.read_json(os.path.join(self.root, ".orthros-state.json"))
        for n in orthros.NAMES:
            folder = self.o.folders[n]
            self.assertIn("return 7", orthros.read_text(os.path.join(folder, "agent.py")))
            self.assertEqual(state["agents"][n]["goods"][-1], orthros.head(folder))
        self.assertIn("now proven", out.getvalue())

    def test_tests_without_their_code_put_everything_back_and_say_why(self):
        patch = ("diff --git a/agent.py b/agent.py\n--- a/agent.py\n+++ b/agent.py\n"
                 "@@ -1,2 +1,2 @@\n def f():\n-    return 99\n+    return 7\n"
                 "diff --git a/test_agent.py b/test_agent.py\nnew file mode 100644\n"
                 "--- /dev/null\n+++ b/test_agent.py\n@@ -0,0 +1,5 @@\n+import unittest\n"
                 "+import agent\n+class T(unittest.TestCase):\n+    def test_f(self):\n"
                 "+        self.assertEqual(agent.f(), 7)\n")
        self.write(self.root, "half.patch", patch)
        before = orthros.head(self.o.folders["A"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orthros.apply_patch(self.root, os.path.join(self.root, "half.patch")),
                             1)
        self.assertIn("did not fit A's code: agent.py", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.o.folders["A"], "test_agent.py")))
        self.assertEqual(orthros.git(self.o.folders["A"], "diff", "--quiet", before)[0], True)

    def test_a_crlf_file_takes_an_lf_patch(self):
        for n in orthros.NAMES:
            folder = self.o.folders[n]
            with open(os.path.join(folder, "config.cmd"), "wb") as handle:
                handle.write(b"@echo off\r\nset \"X=1\"\r\n")
            orthros.commit_all(folder, "cmd")
        patch = ("diff --git a/config.cmd b/config.cmd\n--- a/config.cmd\n+++ b/config.cmd\n"
                 "@@ -1,2 +1,3 @@\n @echo off\n set \"X=1\"\n+set \"Y=2\"\n")
        self.write(self.root, "cmd.patch", patch)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(orthros.apply_patch(self.root, os.path.join(self.root, "cmd.patch")), 0)
        with open(os.path.join(self.o.folders["A"], "config.cmd"), "rb") as handle:
            self.assertEqual(handle.read(), b"@echo off\r\nset \"X=1\"\r\nset \"Y=2\"\r\n")

    def test_a_file_that_fails_does_not_undo_the_files_before_it(self):
        for n in orthros.NAMES:
            self.write(self.o.folders[n], "NOTES.md", "one\n")
            orthros.commit_all(self.o.folders[n], "notes")
        patch = ("diff --git a/NOTES.md b/NOTES.md\n--- a/NOTES.md\n+++ b/NOTES.md\n"
                 "@@ -1 +1,2 @@\n one\n+two\n"
                 "diff --git a/agent.py b/agent.py\n--- a/agent.py\n+++ b/agent.py\n"
                 "@@ -1,2 +1,2 @@\n def f():\n-    return 99\n+    return 7\n")
        self.write(self.root, "mixed.patch", patch)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orthros.apply_patch(self.root, os.path.join(self.root, "mixed.patch")),
                             1)
        self.assertIn("Left out: agent.py", out.getvalue())
        for n in orthros.NAMES:
            folder = self.o.folders[n]
            self.assertEqual(orthros.read_text(os.path.join(folder, "NOTES.md")), "one\ntwo\n")
            self.assertTrue(orthros.git(folder, "diff", "--quiet", "HEAD")[0])   # and committed

    def test_a_file_that_does_not_apply_is_left_out(self):
        patch = ("diff --git a/agent.py b/agent.py\n--- a/agent.py\n+++ b/agent.py\n"
                 "@@ -1,2 +1,2 @@\n def f():\n-    return 99\n+    return 7\n")
        self.write(self.root, "bad.patch", patch)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(orthros.apply_patch(self.root, os.path.join(self.root, "bad.patch")),
                             1)
        self.assertIn("return 1", orthros.read_text(os.path.join(self.o.folders["A"],
                                                                 "agent.py")))


class FakeCoder:
    """The parts of aider's Coder the guard touches."""

    def __init__(self, window, files, mentioned):
        self.main_model = types.SimpleNamespace(info={"max_input_tokens": window},
                                                token_count=lambda m: sum(len(x) for x in m) // 4)
        self.abs_fnames, self.abs_read_only_fnames = set(files), set()
        self.ignore_mentions = set()
        self.mentioned = mentioned
        self.io = types.SimpleNamespace(tool_output=lambda *a: None, tool_error=lambda *a: None)
        self.added = []

    def abs_root_path(self, rel):
        return rel

    def get_file_mentions(self, content):
        return set(self.mentioned)

    def check_for_file_mentions(self, content):
        self.added = sorted(self.get_file_mentions(content) - self.ignore_mentions)
        return "added" if self.added else None

    def check_tokens(self, messages):
        return True


class TestGuard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.small = self.file("small.py", 400)
        self.big = self.file("big.py", 40000)
        guard.patch(types.SimpleNamespace(Coder=FakeCoder))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def file(self, name, size):
        path = os.path.join(self.dir, name)
        with open(path, "w") as handle:
            handle.write("x" * size)
        return path

    def test_mentions_only_add_what_fits(self):
        coder = FakeCoder(8000, [self.small], [self.small, self.big])
        coder.check_for_file_mentions("see small.py and big.py")
        self.assertEqual(coder.added, [self.small])

    def test_a_reply_with_an_edit_pulls_nothing_in(self):
        coder = FakeCoder(8000, [], [self.small])
        self.assertIsNone(coder.check_for_file_mentions("x\n>>>>>>> REPLACE\n"))

    def test_oversize_prompt_is_not_sent(self):
        coder = FakeCoder(1000, [], [])
        self.assertFalse(coder.check_tokens(["y" * 4000]))
        self.assertTrue(coder.check_tokens(["y" * 400]))


if __name__ == "__main__":
    unittest.main()
