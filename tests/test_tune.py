"""Tests for fitting the settings to the machine (orthros_tune.py)."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orthros_tune as tune  # noqa: E402


def turn_log(context, free_gb, total_gb=24.0, speed=28.0, extra=""):
    return ("    context %d x parallel 1 = %d tokens of cache to allocate\n"
            "    VRAM after loading: %.1f GB free of %.1f GB\n"
            "  80s, 20,000 tokens in / 2,200 out, %.0f tok/sec\n%s"
            % (context, context, free_gb, total_gb, speed, extra))


LOOK = {"gpu": "Big Card", "vram_mb": 49152, "ram_mb": 131072, "model_max_context": 131072}


class TestPlan(unittest.TestCase):
    def test_idle_card_steps_up_one(self):
        settings, why = tune.plan(LOOK, tune.measured(turn_log(65536, 28.0, 48.0)),
                                  {"LC_CONTEXT": 65536})
        self.assertEqual(settings["LC_CONTEXT"], 98304)
        self.assertIn("one step up", why[0])

    def test_a_card_in_its_band_is_left_alone(self):
        settings, _ = tune.plan(LOOK, tune.measured(turn_log(65536, 5.3)),
                                {"LC_CONTEXT": 65536, "LC_RALPH_API_TIMEOUT": 321,
                                 "LC_RALPH_ITER_TIMEOUT": 548})
        self.assertEqual(settings, {})

    def test_a_short_card_steps_down(self):
        settings, _ = tune.plan(LOOK, tune.measured(turn_log(65536, 1.0)), {"LC_CONTEXT": 65536})
        self.assertEqual(settings["LC_CONTEXT"], 49152)

    def test_never_past_what_the_model_supports(self):
        look = dict(LOOK, model_max_context=65536)
        settings, _ = tune.plan(look, tune.measured(turn_log(65536, 30.0, 48.0)),
                                {"LC_CONTEXT": 65536})
        self.assertNotIn("LC_CONTEXT", settings)

    def test_a_slow_machine_gets_longer_rounds(self):
        settings, _ = tune.plan(LOOK, tune.measured(turn_log(32768, 5.0, speed=8)),
                                {"LC_CONTEXT": 32768, "LC_RALPH_ITER_TIMEOUT": 420})
        self.assertGreater(settings["LC_RALPH_ITER_TIMEOUT"], 1000)


class TestTuner(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tuner = tune.Tuner(self.dir)
        self.tuner.data["look"] = dict(LOOK)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_clean_turn_keeps_the_trial_and_proposes_the_next_step(self):
        self.tuner.data["trial"] = {"LC_CONTEXT": 98304}
        note = self.tuner.after_turn(turn_log(98304, 20.0, 48.0), True, {"LC_CONTEXT": 65536})
        self.assertEqual(self.tuner.data["good"]["LC_CONTEXT"], 98304)
        self.assertEqual(self.tuner.data["trial"].get("LC_CONTEXT"), 131072)
        self.assertIn("kept", note)

    def test_out_of_memory_puts_the_last_good_back_and_never_retries_it(self):
        self.tuner.data["good"] = {"LC_CONTEXT": 65536}
        self.tuner.data["trial"] = {"LC_CONTEXT": 98304}
        self.tuner.after_turn(turn_log(98304, 0.5, 48.0, extra="bad allocation\n"), True, {})
        self.assertEqual(self.tuner.settings(), {"LC_CONTEXT": 65536})
        self.tuner.after_turn(turn_log(65536, 20.0, 48.0), True, {})
        self.assertNotEqual(self.tuner.data["trial"].get("LC_CONTEXT"), 98304)

    def test_a_model_that_will_not_load_steps_down(self):
        self.tuner.data["good"] = {"LC_CONTEXT": 65536}
        self.tuner.after_turn("!! Could not load 'qwen'.\n", False, {})
        self.assertEqual(self.tuner.settings()["LC_CONTEXT"], 49152)

    def test_looks_only_when_there_is_a_reason(self):
        self.tuner.data["look"] = {"gpu": "RTX 4090", "vram_mb": 24564}
        self.assertEqual(self.tuner.due(("RTX 4090", 24564)), "")
        self.assertIn("changed", self.tuner.due(("RTX 6000", 49152)))
        open(os.path.join(self.dir, tune.REPROBE_FLAG), "w").close()
        self.assertEqual(self.tuner.due(("RTX 4090", 24564)), "setup was run")
        self.assertEqual(tune.Tuner(tempfile.mkdtemp()).due(), "first look")

    def test_settings_survive_a_restart(self):
        self.tuner.data["good"] = {"LC_CONTEXT": 98304}
        self.tuner.save()
        self.assertEqual(tune.Tuner(self.dir).settings(), {"LC_CONTEXT": 98304})


if __name__ == "__main__":
    unittest.main()
