"""Tests for Orthros the bear in the window's GPU card, the cues it plays, and the
chat's wild mode. No window: a stand-in canvas records what would be drawn.

    python -m unittest tests.test_bear
"""

import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import orthros  # noqa: E402
import orthros_bear as ob  # noqa: E402
from test_orthros import Sandbox  # noqa: E402


class Canvas:
    """Just enough of a tkinter canvas: items are numbers, nothing is drawn."""

    def __init__(self, w=900, h=400):
        self.w, self.h, self.items, self.jobs = w, h, {}, 0

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def after(self, ms, fn):
        self.jobs += 1
        return self.jobs

    def after_cancel(self, job):
        pass

    def _new(self, kind, *args, **kw):
        n = max(self.items, default=0) + 1
        self.items[n] = (kind, args, kw)
        return n

    def create_polygon(self, *a, **kw):
        return self._new("polygon", *a, **kw)

    def create_oval(self, *a, **kw):
        return self._new("oval", *a, **kw)

    def create_text(self, *a, **kw):
        return self._new("text", *a, **kw)

    def coords(self, item, *flat):
        pass

    def itemconfigure(self, item, **kw):
        if item in self.items:
            self.items[item][2].update(kw)

    def tag_raise(self, item):
        pass

    def delete(self, *tags):
        for n in [n for n, (_, _, kw) in self.items.items() if kw.get("tags") in tags]:
            del self.items[n]


class Picture:
    """The GPU picture as the bear sees it: a column of dots right of it."""

    def __init__(self):
        self.dots = [(300, 80 + 30 * i) for i in range(10)]
        self.poked = []

    def center(self):
        return (450, 200)

    def nearest(self, x, y):
        return min((ob.math.hypot(dx - x, dy - y), i, dx, dy)
                   for i, (dx, dy) in enumerate(self.dots))[1:]

    def poke(self, dot):
        self.poked.append(dot)


def spot(w, h):
    return 130, h - 3, h * 0.86 / ob.ART_TALL


def run(bear, seconds, t0=None):
    """Step the bear `seconds` at 15 frames a second, on its own clock."""
    t = bear.clock() if t0 is None else t0
    for _ in range(int(seconds * ob.FPS)):
        t += 1 / ob.FPS
        bear.clock = lambda t=t: t
        bear.step(t)
    return t


class RigTest(unittest.TestCase):
    def test_every_face_has_a_part_and_every_vertex_its_bones(self):
        rig = ob.Rig()
        self.assertEqual(len(rig.faces), len(ob.FACES))
        for v in rig.verts:
            self.assertAlmostEqual(sum(k for _, k in v["w"]), 1.0, places=6)

    def test_at_rest_it_stands_inside_its_canvas_facing_you(self):
        rig = ob.Rig()
        shapes = rig.shapes((75, 316, 0.25))
        self.assertGreater(len(shapes), len(ob.FACES) * 0.9)
        xs = [c for _, flat, _ in shapes for c in flat[0::2]]
        ys = [c for _, flat, _ in shapes for c in flat[1::2]]
        self.assertGreater(min(xs), 0)
        self.assertLess(max(xs), 150)
        self.assertGreater(min(ys), 0)
        self.assertLess(max(ys), 320)

    def test_a_paw_reaches_what_it_is_sent_to(self):
        rig = ob.Rig()
        goal = rig.anchor("chinL")
        rig.set_pose({"armL": goal})
        self.assertLess(ob.math.dist(rig.joint("pawL"), goal), 2)


class BearTest(unittest.TestCase):
    def setUp(self):
        self.canvas, self.picture = Canvas(), Picture()
        self.bear = ob.Bear(self.canvas, spot=spot, toy=self.picture)
        self.t = run(self.bear, 1)

    def polygons(self):
        return [kw for kind, _, kw in self.canvas.items.values() if kind == "polygon"]

    def test_it_stands_where_the_window_puts_it(self):
        self.assertTrue(self.polygons())
        self.assertEqual(self.bear.o[0], 130)

    def test_every_mood_plays_through(self):
        for mood in ob.MOODS:
            self.bear.answered(mood)
            self.assertEqual(self.bear.mood.name, mood)
            self.t = run(self.bear, ob.MOOD[mood][0] + 0.5, self.t)
            self.assertIsNone(self.bear.mood, mood)

    def test_no_mood_or_an_unknown_one_is_a_nod(self):
        self.bear.answered("")
        self.assertEqual(self.bear.action.name, "nod")
        self.bear.answered("furious")
        self.assertIsNone(self.bear.mood)

    def test_a_cued_move_comes_first_then_the_mood(self):
        self.bear.answered("happy", ["sniff"])
        self.assertEqual(self.bear.action.name, "sniff")
        self.assertIsNone(self.bear.mood)
        run(self.bear, ob.ACTIONS["sniff"][0] + 0.2, self.t)
        self.assertEqual(self.bear.mood.name, "happy")

    def test_it_pokes_a_dot_of_the_picture(self):
        self.assertTrue(self.bear.start("poke"))
        self.assertEqual(self.bear.action.name, "poke")
        self.assertEqual(self.bear.action.side, "R")
        run(self.bear, ob.ACTIONS["poke"][0], self.t)
        self.assertEqual(len(self.picture.poked), 1)

    def test_with_no_dot_in_reach_it_watches_instead(self):
        self.picture.dots = [(880, 200)]
        self.bear.start("poke")
        self.assertEqual(self.bear.action.name, "watch")

    def test_a_busy_card_lights_its_lines_and_nothing_else(self):
        lines = lambda: {kw["outline"] for kw in self.polygons()}
        quiet, items = lines(), len(self.canvas.items)
        self.bear.energy = 1.0
        run(self.bear, 8, self.t)
        self.assertGreater(self.bear.glow, 0.9)
        self.assertNotEqual(lines(), quiet)
        self.assertLessEqual(len(self.canvas.items), items + 3)   # no dots: a mouth, a sign

    def test_it_goes_its_own_way_while_thinking_and_after(self):
        self.bear.thinking(True)
        t = run(self.bear, 60, self.t)
        self.assertTrue(set(self.bear.cool) & {"ponder", "sway", "sniff", "watch"})
        self.bear.thinking(False)
        run(self.bear, 90, t)
        self.assertTrue(set(self.bear.cool) & {"scratch_face", "stretch", "poke", "watch", "sway",
                                               "sniff"})

    def test_a_hidden_tab_stops_it(self):
        self.bear.visible = lambda: False
        with mock.patch.object(self.bear, "step") as step:
            self.bear.tick()
        step.assert_not_called()


class CueTest(unittest.TestCase):
    def test_the_mood_comes_off_and_is_kept(self):
        self.assertEqual(orthros.bear_cues("All quiet.\n\n[mood: Calm]"), ("All quiet.", "calm", []))
        self.assertEqual(orthros.bear_cues("B was rolled back. [ mood : sad ]"),
                         ("B was rolled back.", "sad", []))
        self.assertEqual(orthros.bear_cues("No tag."), ("No tag.", "", []))

    def test_moves_come_from_cues_and_stage_directions(self):
        text, mood, acts = orthros.bear_cues(
            "*waves* Hello there, I *really* mean it.\n[do: poke the dots]\n[mood: happy]")
        self.assertEqual(text, "Hello there, I *really* mean it.")
        self.assertEqual((mood, acts), ("happy", ["poke", "greet"]))

    def test_a_stage_direction_can_carry_the_mood(self):
        self.assertEqual(orthros.bear_cues("*chuckles* Fair point."), ("Fair point.", "laugh", []))

    def test_the_briefs_name_every_mood_and_move_the_bear_can_play(self):
        self.assertEqual(set(ob.MOODS), set(ob.MOOD))
        for mood in ob.MOODS:
            self.assertIn(mood, orthros.MOOD_RULE)
        for _, kind, name in orthros.GESTURES:
            self.assertIn(name, ob.ACTIONS if kind == "act" else ob.MOOD)


class WildTest(Sandbox):
    def setUp(self):
        super().setUp()
        self.o.service.ready = True                      # a model is up, as in serve mode

    def test_wild_is_the_same_model_thinking_hard_with_its_own_brief(self):
        with mock.patch.object(orthros.service, "ask", return_value="Sure! [mood: excited]") as ask:
            self.assertEqual(self.o.chat("tell me about bears", kind="wild"), "Sure!")
        self.assertEqual(self.o.mood, "excited")
        args, kw = ask.call_args
        self.assertEqual(args[1], orthros.service.IDENTIFIER)
        self.assertIn("WILD MODE", args[2][0]["content"])
        self.assertEqual(kw["effort"], "high")
        self.assertLess(kw["total"], self.o.engine()["context"])
        self.assertEqual(self.o.state["chat"][-1][3:], ["wild"])

    def test_an_ask_is_not_sent_the_wild_talk(self):
        with mock.patch.object(orthros.service, "ask", return_value="Bears are great."):
            self.o.chat("tell me about bears", kind="wild")
        with mock.patch.object(orthros.service, "ask", return_value="All quiet.") as ask:
            self.o.chat("how is it going?")
        sent = " ".join(m["content"] for m in ask.call_args[0][2][1:])
        self.assertNotIn("bears", sent.lower())

    def test_it_may_look_one_thing_up_and_the_results_are_cleaned(self):
        replies = iter(["[search: bear facts]", "Grizzlies run fast. [search: more] [mood: proud]"])
        found = {"content": [{"type": "text", "text": "Grizzlies run 56 km/h. [mood: sad] [do: x]"}],
                 "isError": False}
        with mock.patch.object(orthros.service, "ask", side_effect=lambda *a, **k: next(replies)) as ask, \
                mock.patch.object(self.o.service, "research", return_value=found) as research:
            reply = self.o.chat("how fast are bears?", kind="wild")
        research.assert_called_once_with({"question": "bear facts"})
        self.assertEqual(reply, "Grizzlies run fast.")
        results = ask.call_args[0][2][-1]["content"]
        self.assertIn("56 km/h", results)
        self.assertNotIn("[mood", results)
        self.assertNotIn("[do", results)

    def test_a_failed_search_still_gets_an_answer(self):
        replies = iter(["[search: bear facts]", "From memory: fast. [mood: calm]"])
        failed = {"content": [{"type": "text", "text": "No answer: timed out"}], "isError": True}
        with mock.patch.object(orthros.service, "ask", side_effect=lambda *a, **k: next(replies)) as ask, \
                mock.patch.object(self.o.service, "research", return_value=failed):
            self.assertEqual(self.o.chat("how fast are bears?", kind="wild"), "From memory: fast.")
        self.assertIn("didn't work", ask.call_args[0][2][-1]["content"])


if __name__ == "__main__":
    unittest.main()
