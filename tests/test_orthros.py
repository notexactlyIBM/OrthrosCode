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

    def test_field_report_names_oversize_prompts(self):
        text = ("litellm.APIConnectionError: ... request (32958 tokens) exceeds the available "
                "context size (32768 tokens), try increasing it\n")
        self.o.field_report(self.result("A", log_text=text * 3))
        report = orthros.read_text(os.path.join(self.o.folders["A"], "FIELD_REPORT.md"))
        self.assertIn("The engine did not die", report)
        self.assertIn("32,958", report)


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
