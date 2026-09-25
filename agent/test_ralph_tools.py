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
from ralph_tools import (FOUND_FILE, REQUESTS, code_search, define_search, handle_tool_requests,
                         outline_file, record_lesson, recent_lessons)

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

    def test_define_search_whole_word_only(self):
        write_text(os.path.join(self.dir, "mod.py"),
                   "def addition(a, b):\n    return a + b\n\ndef add(a, b):\n    return a + b\n")
        hits = define_search(self.dir, "add")
        self.assertEqual(len(hits), 1)
        self.assertIn("def add", hits[0])
        self.assertNotIn("addition", hits[0])

    def test_outline_capped_at_80(self):
        body = "\n".join("def func_%d():\n    pass\n" % i for i in range(100))
        write_text(os.path.join(self.dir, "big.py"), body)
        lines = outline_file(self.dir, "big.py")
        self.assertEqual(len(lines), 81)
        self.assertEqual(lines[-1], "... truncated")
        self.assertIn("def func_0", lines[0])

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


class TestTestsRequest(unittest.TestCase):
    def test_tests_request_writes_ran_to_found(self):
        with tempfile.TemporaryDirectory() as workspace:
            test_module = os.path.join(workspace, "test_ralph_tools.py")
            with open(test_module, "w") as f:
                f.write("import unittest\n\n"
                        "class TestX(unittest.TestCase):\n"
                        "    def test_ok(self):\n"
                        "        self.assertTrue(True)\n")
            notes_path = os.path.join(workspace, "tasks.md")
            with open(notes_path, "w") as f:
                f.write("# Tasks\n\nTESTS: test_ralph_tools\n")
            handled = handle_tool_requests(workspace, notes_path, sys.executable)
            self.assertIn("TESTS", handled)
            found_path = os.path.join(workspace, "FOUND.md")
            self.assertTrue(os.path.isfile(found_path))
            with open(found_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Ran", content)

    def test_only_a_test_file_in_this_folder_is_run(self):
        with tempfile.TemporaryDirectory() as workspace:
            notes_path = os.path.join(workspace, "tasks.md")
            with open(notes_path, "w") as f:
                f.write("# Tasks\n\nTESTS: json\nTESTS: test_missing\n")
            handle_tool_requests(workspace, notes_path, sys.executable)
            with open(os.path.join(workspace, "FOUND.md"), encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content.count("no test file"), 2)
            self.assertNotIn("Ran", content)


class TestOutlineFileNotFound(unittest.TestCase):
    def test_outline_missing_file_says_not_found(self):
        with tempfile.TemporaryDirectory() as ws:
            notes = os.path.join(ws, "tasks.md")
            with open(notes, "w", encoding="utf-8") as f:
                f.write("- [ ] Do something\n")
                f.write("  OUTLINE: missing.py\n")
            handle_tool_requests(ws, notes, python="python")
            found = os.path.join(ws, "FOUND.md")
            self.assertTrue(os.path.isfile(found), "FOUND.md was not written")
            with open(found, encoding="utf-8") as f:
                lines = f.read().splitlines()
            heading = next(i for i, l in enumerate(lines) if l == "## OUTLINE: missing.py")
            self.assertIn("file not found: missing.py", lines[heading + 2])


if __name__ == "__main__":
    unittest.main()
