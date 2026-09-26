"""Proof by score: a version's changes reach its twin only after a held-out
score that is not worse than the last version that passed."""

import os
import unittest

from test_orthros import Sandbox, orthros

GOOD_TURN = dict(kept=2, ticked=2, rounds=6, seconds=45 * 60,
                 reason="Time is up after 45 minutes.")


class TestCompare(unittest.TestCase):
    def test_sign_test(self):
        self.assertEqual(orthros.sign_test(0, 0), 1.0)
        self.assertAlmostEqual(orthros.sign_test(4, 0), 1 / 16.0)
        self.assertAlmostEqual(orthros.sign_test(3, 1), 5 / 16.0)

    def test_a_clear_regression_is_worse(self):
        parent = {e: [5, 5] for e in "abcdefgh"}
        child = dict(parent, a=[0, 5], b=[1, 5], c=[2, 5], d=[4, 5])
        self.assertEqual(orthros.compare_scores(child, parent), (0, 4, False))

    def test_noise_is_not_worse(self):
        parent = {e: [5, 5] for e in "abcdefgh"}
        self.assertTrue(orthros.compare_scores(dict(parent, a=[4, 5], b=[4, 5]), parent)[2])
        self.assertTrue(orthros.compare_scores(dict(parent, a=[4, 5], b=[4, 5], c=[3, 5]),
                                               dict(parent, d=[1, 5]))[2])

    def test_only_exercises_both_were_scored_on_count(self):
        self.assertEqual(orthros.compare_scores({"a": [0, 5], "z": [0, 5]}, {"a": [0, 5]}),
                         (0, 0, True))

    def test_totals(self):
        self.assertEqual(orthros.score_totals({"a": [5, 5], "b": [2, 4]}), (1, 2, 7, 9))


class TestProofByScore(Sandbox):
    def setUp(self):
        super().setUp()
        self.o.settings.update(prove_by_score=True, eval_every=1, eval_count=4)
        self.o.release = lambda name: None
        self.exercises = orthros.work.eval_exercises()[:4]

    def b_changes_a(self, body):
        """B's turn on A: A's code changes, and that range waits in A's pending."""
        a = self.o.folders["A"]
        pre = orthros.head(a)
        self.write(a, "agent.py", body)
        post = orthros.commit_all(a, "B's change to A")
        self.o.judge(self.result("B", pre=pre, post=post, **GOOD_TURN))
        return post

    def score(self, ev, *scores):
        for exercise, score in zip(list(ev["todo"]), scores):
            self.o.judge_eval({"agent": ev["agent"], "launched": True, "exercise": exercise,
                               "score": score})

    def b_code(self):
        return orthros.read_text(os.path.join(self.o.folders["B"], "agent.py"))

    def baseline(self):
        """A good turn, then A's first score -- which it passes by definition."""
        self.o.judge(self.result("A", **GOOD_TURN))
        ev = self.o.maybe_start_eval("A")
        self.assertEqual(ev["todo"], self.exercises)
        self.score(ev, [3, 5], [4, 4], [5, 5], [5, 5])
        self.assertEqual(self.o.agent("A")["scored_good"], ev["sha"])
        return ev["sha"]

    def test_the_first_score_is_the_baseline(self):
        self.baseline()
        self.assertNotIn("evaluating", self.o.state)
        report = orthros.read_text(os.path.join(self.o.folders["A"], "FIELD_REPORT.md"))
        self.assertIn("3 of 4 held-out exercises fully passed, 17 of 19 hidden tests", report)
        for name in self.exercises:                       # totals only, never names
            self.assertNotIn(name, report)
        self.assertEqual(self.o.view()["agents"]["A"]["held_out"], [3, 4, 17, 19])

    def test_a_change_waits_for_its_score_then_carries_over(self):
        self.baseline()
        self.b_changes_a("def f():\n    return 2\n")
        self.o.judge(self.result("A", **GOOD_TURN))       # works: proven, not yet carried
        self.assertNotIn("return 2", self.b_code())
        self.assertEqual(len(self.o.agent("A")["proven_pending"]), 1)
        ev = self.o.maybe_start_eval("A")
        self.assertTrue(ev["parent"])
        self.score(ev, [4, 5], [4, 4], [5, 5], [5, 5])    # one better, none worse
        self.assertIn("return 2", self.b_code())
        self.assertEqual(self.o.agent("A")["scored_good"], ev["sha"])
        self.assertTrue(any("proven by score" in e for e in self.events))

    def test_a_worse_score_rolls_back_and_nothing_carries_over(self):
        self.baseline()
        self.b_changes_a("def f():\n    return 3\n")
        self.o.judge(self.result("A", **GOOD_TURN))
        ev = self.o.maybe_start_eval("A")
        self.score(ev, [0, 5], [1, 4], [2, 5], [3, 5])    # four worse, none better
        self.assertEqual(self.o.agent("A")["scored"][ev["sha"]]["verdict"], "rolled back")
        self.assertNotIn("return 3", orthros.read_text(os.path.join(self.o.folders["A"],
                                                                    "agent.py")))
        self.assertNotIn("return 3", self.b_code())
        self.assertEqual(self.o.agent("A")["proven_pending"], [])
        self.assertIn("held-out score fell", orthros.read_text(
            os.path.join(self.o.folders["A"], orthros.ROLLBACK_NOTE)))
        self.assertEqual(self.o.good("A"), self.o.agent("A")["scored_good"])

    def test_a_slow_slide_is_stopped_by_the_best_score(self):
        # No worse than the last version, which had already slipped; all eight
        # worse than the best. The last alone would let it through.
        exercises = orthros.work.eval_exercises()[:8]
        me = self.o.agent("A")
        me["scored"] = {"best": {"scores": {e: [5, 5] for e in exercises}, "verdict": "kept",
                                 "at": 1},
                        "last": {"scores": {e: [4, 5] for e in exercises}, "verdict": "kept",
                                 "at": 2}}
        me["scored_good"] = "last"
        ev = {"agent": "A", "sha": orthros.head(self.o.folders["A"]), "parent": "last",
              "todo": [], "scores": {e: [4, 5] for e in exercises}, "resume": "B"}
        self.assertTrue(orthros.compare_scores(ev["scores"], me["scored"]["last"]["scores"])[2])
        self.o.state["evaluating"] = ev
        self.o.rollback_to_scored = lambda name, why: self.events.append("slid: " + why)
        self.o.decide_eval(ev)
        self.assertEqual(me["scored"][ev["sha"]]["verdict"], "rolled back")
        self.assertTrue(any(e.startswith("slid") for e in self.events))

    def test_a_small_step_down_from_a_lucky_best_is_allowed(self):
        exercises = orthros.work.eval_exercises()[:4]
        me = self.o.agent("A")
        me["scored"] = {"best": {"scores": {e: [5, 5] for e in exercises}, "verdict": "kept",
                                 "at": 1},
                        "last": {"scores": {e: [4, 5] for e in exercises}, "verdict": "kept",
                                 "at": 2}}
        me["scored_good"] = "last"
        ev = {"agent": "A", "sha": orthros.head(self.o.folders["A"]), "parent": "last",
              "todo": [], "scores": {e: [4, 5] for e in exercises}, "resume": "B"}
        self.o.state["evaluating"] = ev
        self.o.decide_eval(ev)
        self.assertEqual(me["scored"][ev["sha"]]["verdict"], "kept")

    def test_nothing_to_score_when_the_code_has_not_changed(self):
        self.baseline()
        self.o.agent("A")["since_eval"] = 5
        self.assertIsNone(self.o.maybe_start_eval("A"))
        self.assertEqual(self.o.agent("A")["since_eval"], 0)

    def test_task_mode_is_never_scored(self):
        self.o.state["mode"] = "task"
        self.o.agent("A")["since_eval"] = 5
        self.assertIsNone(self.o.maybe_start_eval("A"))

    def test_a_version_that_cannot_start_ends_its_scoring(self):
        self.baseline()
        self.b_changes_a("def f():\n    return 4\n")
        self.o.judge(self.result("A", **GOOD_TURN))
        ev = self.o.maybe_start_eval("A")
        self.o.judge_eval(self.result("A", launched=False, exercise=ev["todo"][0]))
        self.assertNotIn("evaluating", self.o.state)

    def test_an_agent_that_names_a_held_out_exercise_is_flagged(self):
        distinctive = [e for e in orthros.work.eval_exercises() if "_" in e]
        self.write(self.o.folders["A"], "cheat.py", "ANSWERS = {'%s': 1}\n" % distinctive[0])
        self.assertTrue(self.o.warn_if_gamed("A"))
        self.assertFalse(self.o.warn_if_gamed("B"))


if __name__ == "__main__":
    unittest.main()
