"""Tests for the tools rounds ask for, lessons, and the invented-attribute checks."""

import contextlib
import inspect
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

import ralph_tools
from ralph_common import read_text, write_text
from ralph_inventions import phantom_attributes, used_before_set
from ralph_prompts import compose_round_prompt
from ralph_tools import (FOUND_FILE, REQUESTS, code_search, handle_tool_requests, record_lesson,
                         recent_lessons)

SAMPLE = '''import threading


class Base:
    speed = 3

    def __init__(self):
        self.x = 1


class Kid(Base):
    def __init__(self):
        super().__init__()
        self.y = self.x + self.speed
        self.cb = lambda: self.later
        self.later = 2

    def go(self):
        return self.missing + self.y


class Worker(threading.Thread):
    def run(self):
        return self.name


class Bad:
    def __init__(self, w):
        self.r = self.w * 2
        self.w = w
'''


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.notes = os.path.join(self.dir, "tasks.md")
        write_text(self.notes, "# Tasks\n\n- [ ] do it\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestInventions(Temp):
    def test_finds_only_real_inventions(self):
        path = os.path.join(self.dir, "sample.py")
        write_text(path, SAMPLE)
        self.assertEqual([n for _, n in phantom_attributes([path])], ["missing"])
        self.assertEqual([(k, n) for _, k, n in used_before_set([path])], [("Bad", "w")])


class TestInheritedFromOutside(Temp):
    def test_subclass_of_a_test_class_is_not_invented(self):
        """A class inheriting through a project class from unittest.TestCase
        gets its asserts from outside: reporting them wasted real rounds."""
        sample = os.path.join(self.dir, "test_sample.py")
        write_text(sample, "import unittest\n\n\n"
                           "class Base(unittest.TestCase):\n"
                           "    def setUp(self):\n"
                           "        self.thing = 1\n\n\n"
                           "class Kid(Base):\n"
                           "    def test_it(self):\n"
                           "        self.assertEqual(self.thing, 1)\n")
        self.assertEqual(phantom_attributes([sample]), [])


class TestRequestsAreAdvertised(Temp):
    def test_every_request_handled_is_one_the_rounds_are_told_of(self):
        handled = set(re.findall(r'handled\.append\("(\w+)"\)', inspect.getsource(ralph_tools)))
        self.assertIn("CALLERS", handled)
        self.assertEqual(handled - {word.rstrip(":") for word, _ in REQUESTS}, set())

    def test_the_round_prompt_adds_only_what_the_mission_leaves_out(self):
        prompt = os.path.join(self.dir, "RALPH_PROMPT.md")
        write_text(prompt, "# How to work\n\n    FIND: <text>   every line with it -> FOUND.md\n")
        body = read_text(compose_round_prompt(self.dir, prompt, []))
        for word, _ in REQUESTS:
            self.assertIn(word, body)
        self.assertEqual(body.count("FIND:"), 1)


class TestTools(Temp):
    def test_code_search(self):
        write_text(os.path.join(self.dir, "mod.py"), "def target():\n    return 1\n")
        self.assertEqual(code_search(self.dir, "TARGET"), ["mod.py:1: def target():"])

    def test_find_and_docs_requests(self):
        write_text(os.path.join(self.dir, "mod.py"), "def target():\n    pass\n")
        write_text(self.notes, read_text(self.notes) + "FIND: target\nDOCS: json\n")
        with contextlib.redirect_stdout(io.StringIO()):
            handled = handle_tool_requests(self.dir, self.notes, sys.executable)
        self.assertEqual(sorted(handled), ["DOCS", "FIND"])
        found = read_text(os.path.join(self.dir, FOUND_FILE))
        self.assertIn("mod.py:1: def target():", found)
        self.assertIn("json", found.lower())
        self.assertNotIn("FIND: target\n", read_text(self.notes))

    def test_callers_request(self):
        write_text(os.path.join(self.dir, "mod.py"), "def target():\n    return 1\n\ndef caller():\n    return target()\n")
        write_text(self.notes, read_text(self.notes) + "CALLERS: target\n")
        with contextlib.redirect_stdout(io.StringIO()):
            handled = handle_tool_requests(self.dir, self.notes, sys.executable)
        self.assertIn("CALLERS", handled)
        found = read_text(os.path.join(self.dir, FOUND_FILE))
        self.assertIn("return target()", found)
        self.assertNotIn("def target", found)
        self.assertNotIn("CALLERS: target\n", read_text(self.notes))

    def test_def_request(self):
        write_text(os.path.join(self.dir, "mod.py"), "def target():\n    return 1\n\ndef caller():\n    return target()\n")
        write_text(self.notes, read_text(self.notes) + "DEF: target\n")
        with contextlib.redirect_stdout(io.StringIO()):
            handled = handle_tool_requests(self.dir, self.notes, sys.executable)
        self.assertIn("DEF", handled)
        found = read_text(os.path.join(self.dir, FOUND_FILE))
        self.assertIn("def target", found)
        self.assertNotIn("return target()", found)
        self.assertNotIn("DEF: target\n", read_text(self.notes))

    def test_outline_request(self):
        write_text(os.path.join(self.dir, "mod.py"), "import os\n\nclass Foo:\n    def bar(self):\n        return 1\n")
        write_text(self.notes, read_text(self.notes) + "OUTLINE: mod.py\n")
        with contextlib.redirect_stdout(io.StringIO()):
            handled = handle_tool_requests(self.dir, self.notes, sys.executable)
        self.assertIn("OUTLINE", handled)
        found = read_text(os.path.join(self.dir, FOUND_FILE))
        self.assertIn("mod.py:3: class Foo:", found)
        self.assertIn("mod.py:4: def bar(self):", found)
        self.assertNotIn("OUTLINE: mod.py\n", read_text(self.notes))

    def test_lessons(self):
        self.assertTrue(record_lesson(self.dir, "do not do that"))
        self.assertFalse(record_lesson(self.dir, "do not do that"))
        self.assertTrue(record_lesson(self.dir, "nor this"))
        self.assertEqual(len(recent_lessons(self.dir)), 2)
        prompt = os.path.join(self.dir, "RALPH_PROMPT.md")
        write_text(prompt, "# How to work\n")
        round_file = compose_round_prompt(self.dir, prompt, [])
        self.assertIn("nor this", read_text(round_file))

    def test_recent_lessons_task_ranking(self):
        record_lesson(self.dir, "use the database connection pool")
        record_lesson(self.dir, "always close file handles")
        record_lesson(self.dir, "the database query was too slow")
        result = recent_lessons(self.dir, task="database query")
        self.assertIn("database query", result[0])


if __name__ == "__main__":
    unittest.main()
