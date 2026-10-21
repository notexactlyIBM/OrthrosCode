"""Tests for the bear beside the window's chat, and the mood tag it plays. No window:
a stand-in canvas records what would be drawn.

    python -m unittest tests.test_bear
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import orthros  # noqa: E402
import orthros_bear as ob  # noqa: E402


class Canvas:
    """Just enough of a tkinter canvas: items are numbers, nothing is drawn."""

    def __init__(self, w=150, h=320):
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
        n = len(self.items) + 1
        self.items[n] = (kind, args, kw)
        return n

    def create_polygon(self, *a, **kw):
        return self._new("polygon", *a, **kw)

    def create_oval(self, *a, **kw):
        return self._new("oval", *a, **kw)

    def create_text(self, *a, **kw):
        return self._new("text", *a, **kw)

    def coords(self, item, flat):
        pass

    def itemconfigure(self, item, **kw):
        pass

    def tag_raise(self, item):
        pass

    def delete(self, tag):
        pass


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
        self.shown = []
        self.canvas = Canvas()
        self.bear = ob.Bear(self.canvas, shown=self.shown.append)

    def test_it_comes_when_spoken_to_and_leaves_when_told(self):
        self.bear.heard()
        self.assertTrue(self.bear.on)
        self.assertEqual(self.shown, [True])
        run(self.bear, 1)
        self.assertTrue(any(k == "polygon" for k, _, _ in self.canvas.items.values()))
        self.bear.leave()
        self.assertFalse(self.bear.on)
        self.assertEqual(self.shown, [True, False])

    def test_every_mood_plays_through(self):
        self.bear.heard()
        t = run(self.bear, 2)
        for mood in ob.MOODS:
            self.bear.answered(mood)
            self.assertEqual(self.bear.mood.name, mood)
            t = run(self.bear, ob.MOOD[mood][0] + 0.5, t)
            self.assertIsNone(self.bear.mood, mood)

    def test_no_mood_or_an_unknown_one_is_a_nod(self):
        self.bear.answered("")
        self.assertEqual(self.bear.action.name, "nod")
        self.bear.answered("furious")
        self.assertIsNone(self.bear.mood)

    def test_it_goes_its_own_way_while_thinking_and_after(self):
        self.bear.heard()
        self.bear.thinking(True)
        t = run(self.bear, 40)
        self.bear.thinking(False)
        run(self.bear, 60, t)
        self.assertGreater(len(self.bear.cool), 2)       # it did a few things of its own

    def test_a_quiet_chat_sends_it_away(self):
        self.bear.heard()
        self.bear.active_at -= ob.LINGER + 1
        self.bear.tick()
        self.assertFalse(self.bear.on)


class MoodTagTest(unittest.TestCase):
    def test_the_tag_comes_off_and_its_mood_is_kept(self):
        self.assertEqual(orthros.split_mood("All quiet.\n\n[mood: Calm]"), ("All quiet.", "calm"))
        self.assertEqual(orthros.split_mood("B was rolled back. [ mood : sad ]"),
                         ("B was rolled back.", "sad"))
        self.assertEqual(orthros.split_mood("No tag."), ("No tag.", ""))

    def test_the_brief_names_every_mood_the_bear_can_play(self):
        self.assertEqual(set(ob.MOODS), set(ob.MOOD))
        for mood in ob.MOODS:
            self.assertIn(mood, orthros.CHAT_BRIEF)


if __name__ == "__main__":
    unittest.main()
