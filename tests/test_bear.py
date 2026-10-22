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

    def winfo_toplevel(self):         # (a window just big enough to show it all)
        return self

    def winfo_rooty(self):
        return 0

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


def run(bear, seconds, t0=None, seen=None):
    """Step the bear `seconds` at 15 frames a second, on its own clock (noting where it
    was each frame in `seen`, if given)."""
    t = bear.clock() if t0 is None else t0
    for _ in range(int(seconds * ob.FPS)):
        t += 1 / ob.FPS
        bear.clock = lambda t=t: t
        bear.step(t)
        if seen is not None and (not seen or seen[-1] != bear.where):
            seen.append(bear.where)
    return t


class RigTest(unittest.TestCase):
    def test_every_face_has_a_part_and_every_vertex_its_bones(self):
        rig = ob.Rig()
        walls = sum(1 for f in rig.faces if f.get("wall"))
        self.assertGreater(walls, 50)
        self.assertEqual(len(rig.faces), 2 * len(ob.FACES) + walls)      # front, back, sides
        for v in rig.verts:
            self.assertAlmostEqual(sum(k for _, k in v["w"]), 1.0, places=6)

    def test_at_rest_it_stands_inside_its_canvas_facing_you(self):
        rig = ob.Rig()
        shapes = rig.shapes((75, 316, 0.25))
        self.assertGreater(len(shapes), len(ob.FACES) * 0.9)
        xs = [c for _, _, flat, _ in shapes for c in flat[0::2]]
        ys = [c for _, _, flat, _ in shapes for c in flat[1::2]]
        self.assertGreater(min(xs), 0)
        self.assertLess(max(xs), 150)
        self.assertGreater(min(ys), 0)
        self.assertLess(max(ys), 320)

    def test_side_on_its_body_is_a_solid_not_a_sheet(self):
        # 2026-10-21: the outline lay on the middle plane, and side-on the chest was 0 deep
        rig = ob.Rig()

        def across(yaw, top):
            rig.set_pose({"root": {"yaw": yaw}})
            xs = [p[0] for p, v in zip(rig.out, rig.verts) if top < p[1] < top + 60 and v["part"] == "body"]
            return max(xs) - min(xs)
        for top in range(260, 620, 60):           # from the shoulders down to the hips
            self.assertGreater(across(90, top), across(0, top) * 0.5, top)

    def test_a_snout_turning_away_shows_the_part_still_facing_you(self):
        rig = ob.Rig()
        rig.set_pose({"head": {"yaw": 50}})
        pieces = [(key, flat) for key, _, flat, _ in rig.shapes((100, 300, 0.36)) if isinstance(key, tuple)]
        self.assertTrue([key for key, _ in pieces if not rig.faces[key[0]].get("back")])
        for key, flat in pieces:
            self.assertGreaterEqual(len(flat), 6, key)
        rig.set_pose({})                          # facing you, every polygon is whole again
        self.assertFalse([k for k, _, _, _ in rig.shapes((100, 300, 0.36)) if isinstance(k, tuple)])

    def test_a_paw_takes_only_itself_when_it_lifts(self):
        # 2026-10-21: the right paw took two bits of the thigh showing between its claws
        between = [f for f in ob.FACES if set(f) in ({301, 302, 303}, {303, 305, 306, 307})]
        self.assertEqual(len(between), 2)
        for f in between:
            self.assertNotIn(ob.part_of(f), ("armL", "armR"))

    def test_a_paw_reaches_what_it_is_sent_to(self):
        rig = ob.Rig()
        goal = rig.anchor("chinL")
        rig.set_pose({"armL": goal})
        self.assertLess(ob.math.dist(rig.joint("pawL"), goal), 2)


class BearTest(unittest.TestCase):
    def setUp(self):
        self.den, self.stream = Canvas(300, 320), Canvas(900, 300)
        self.bear = ob.Bear(self.den, stream=self.stream)
        self.t = self.bear.clock()

    def come(self):
        self.bear.summon()
        self.t = run(self.bear, 8, self.t)
        self.assertEqual(self.bear.where, "here")

    def polygons(self, canvas=None):
        return [kw for kind, _, kw in (canvas or self.den).items.values() if kind == "polygon"]

    def test_it_hides_until_you_come_then_walks_out_from_behind_the_chat(self):
        self.assertEqual(self.bear.where, "away")
        self.t = run(self.bear, 2, self.t)
        self.assertFalse(self.polygons())
        self.bear.summon()
        self.assertEqual(self.bear.where, "coming")
        self.assertGreater(self.bear.walk_x, 0)          # off to the right, behind the box
        self.t = run(self.bear, 8, self.t)
        self.assertEqual((self.bear.where, self.bear.walk_x), ("here", 0.0))
        self.assertTrue(self.polygons())

    def test_it_waves_only_the_first_time_out(self):
        self.come()
        self.assertEqual(self.bear.cool.keys() & {"greet"}, {"greet"})
        self.bear.active_at -= ob.DEN_QUIET + 1
        self.t = run(self.bear, 10, self.t)
        self.bear.cool.clear()
        self.come()
        self.assertNotIn("greet", self.bear.cool)

    def test_a_quiet_chat_sends_it_back_behind_the_box(self):
        self.come()
        self.bear.active_at -= ob.DEN_QUIET + 1
        seen = []
        self.t = run(self.bear, 10, self.t, seen)
        self.assertEqual(seen, ["here", "going", "away"])
        self.assertFalse(self.polygons())

    def test_every_mood_plays_through(self):
        self.come()
        for mood in ob.MOODS:
            self.bear.answered(mood)
            self.assertEqual(self.bear.mood.name, mood)
            self.t = run(self.bear, ob.MOOD[mood][0] + 0.5, self.t)
            self.assertIsNone(self.bear.mood, mood)

    def test_no_mood_or_an_unknown_one_is_a_nod(self):
        self.come()
        self.bear.answered("")
        self.assertEqual(self.bear.action.name, "nod")
        self.bear.answered("furious")
        self.assertIsNone(self.bear.mood)

    def test_a_cued_move_comes_first_then_the_mood(self):
        self.come()
        self.bear.answered("happy", ["sniff"])
        self.assertEqual(self.bear.action.name, "sniff")
        self.assertIsNone(self.bear.mood)
        run(self.bear, ob.ACTIONS["sniff"][0] + 0.2, self.t)
        self.assertEqual(self.bear.mood.name, "happy")

    def test_asked_for_a_salmon_it_climbs_up_eats_it_and_comes_back(self):
        self.come()
        self.bear.answered("happy", ["fish"])
        seen = []
        self.t = run(self.bear, 20, self.t, seen)
        self.assertEqual(seen, ["here", "up", "fishing", "down", "here"])
        self.assertIsNone(self.bear.salmon)
        self.assertFalse(self.polygons(self.stream))      # nothing left behind up there
        self.assertTrue(self.polygons())

    def test_while_you_chat_no_salmon_comes_unasked(self):
        self.come()
        self.bear.next_salmon = 0
        seen = []
        run(self.bear, 30, self.t, seen)
        self.assertNotIn("fishing", seen)

    def test_left_alone_it_goes_fishing_now_and_then_and_hides_again(self):
        self.bear.next_salmon = self.t - 1
        self.bear.tick()
        self.assertEqual(self.bear.where, "fishing")
        self.assertIs(self.bear.c, self.stream)
        seen = []
        self.t = run(self.bear, 10, self.t, seen)
        self.assertEqual(seen[-1], "away")
        self.assertFalse(self.polygons(self.stream))
        self.assertGreater(self.bear.next_salmon, self.t + ob.SALMON_EVERY[0] - 1)
        # 2026-10-21: it kept its height under the picture, and walked out half out of sight
        self.come()
        self.assertEqual(self.bear.spot(300, 320)[1], 320 - 3)

    def test_a_salmon_is_held_across_both_paws_and_eaten_in_bites(self):
        fish = ob.Salmon(self.stream, 0, True)
        counts = []
        for fish.bites in range(ob.BITES + 1):
            counts.append(len(fish.left()))
        self.assertEqual(counts[0], len(ob.SALMON))
        self.assertEqual(counts[-1], 0)
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(len(set(counts)), len(counts))        # every bite takes some
        self.bear.fish()
        self.t = run(self.bear, sum(d for _, d in ob.FISH[:4]) + 0.5, self.t)
        self.assertEqual(ob.fish_phase(self.t - self.bear.since)[0], "chew")
        fish = self.bear.salmon
        self.assertEqual(fish.angle, 0)                        # level
        paws = sorted(self.bear.rig.project(self.bear.rig.joint("paw" + s), self.bear.o)[0] for s in "LR")
        self.assertGreater(paws[1] - paws[0], fish.size * 0.25)   # apart, along it

    def test_a_busy_card_lights_its_lines(self):
        self.come()
        lines = lambda: {kw["outline"] for kw in self.polygons()}
        quiet = lines()
        self.bear.energy = 1.0
        run(self.bear, 8, self.t)
        self.assertGreater(self.bear.glow, 0.9)
        self.assertNotEqual(lines(), quiet)

    def test_it_goes_its_own_way_while_thinking_and_after(self):
        self.come()
        self.bear.thinking(True)
        t = run(self.bear, 60, self.t)
        self.assertTrue(set(self.bear.cool) & {"ponder", "sway", "sniff"})
        self.bear.thinking(False)
        self.bear.summon()
        run(self.bear, 90, t)
        self.assertTrue(set(self.bear.cool) & {"scratch_face", "stretch", "sway", "sniff"})

    def test_a_hidden_tab_stops_it(self):
        self.come()
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
            "*waves* Hello there, I *really* mean it.\n[do: catch a salmon]\n[mood: happy]")
        self.assertEqual(text, "Hello there, I *really* mean it.")
        self.assertEqual((mood, acts), ("happy", ["fish", "greet"]))

    def test_a_stage_direction_can_carry_the_mood(self):
        self.assertEqual(orthros.bear_cues("*chuckles* Fair point."), ("Fair point.", "laugh", []))

    def test_the_briefs_name_every_mood_and_move_the_bear_can_play(self):
        self.assertEqual(set(ob.MOODS), set(ob.MOOD))
        for mood in ob.MOODS:
            self.assertIn(mood, orthros.MOOD_RULE)
        for _, kind, name in orthros.GESTURES:
            self.assertIn(name, ob.CUES if kind == "act" else ob.MOOD)


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
