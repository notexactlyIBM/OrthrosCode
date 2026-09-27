"""Tests for serve mode: the key, inference passed through, MCP tools, and
what the loop builds and serves. No model, no GPU: a stand-in answers for
LM Studio, as in --simulate.

    python -m unittest discover -s tests
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import orthros  # noqa: E402
import orthros_service as service  # noqa: E402
import orthros_work as work  # noqa: E402

SHOUT = "import sys\nprint(sys.stdin.read().upper(), end='')\n"


def write(folder, name, body):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
        handle.write(body)


class Served(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for n in orthros.NAMES:
            folder = os.path.join(self.root, "OrthrosCode %s" % n)
            os.makedirs(folder)
            write(folder, "agent.py", "x = 1\n")
            write(folder, "orthros_tasks.md", "# Tasks\n\n## Tasks\n\n- [ ] something\n")
            orthros.git(folder, "init", "-q")
            orthros.commit_all(folder, "start")
        # Loopback and any free port: a test run must not ask the firewall anything.
        write(self.root, "orthros.json", json.dumps(dict(
            orthros.DEFAULTS, serve_port=0, serve_host="127.0.0.1", tool_seconds=5)))
        self.o = orthros.Orthros(self.root, simulate=True)
        self.events = []
        self.o.event = lambda text, kind="info": self.events.append(text)
        self.svc = self.o.service
        self.key = self.o.settings["serve_key"]

    def tearDown(self):
        self.svc.listen(False)
        if self.svc.fake:
            self.svc.fake.shutdown()
            self.svc.fake.server_close()
        shutil.rmtree(self.root, ignore_errors=True)

    def serve(self):
        """What keep_serving does: the model up, inference allowed, the port open."""
        self.assertEqual(self.svc.engine_up(), "")
        self.svc.serving()
        self.svc.listen(True)

    def request(self, method, path, body=None, key=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.svc.port(), timeout=30)
        headers = {"Content-Type": "application/json"}
        if key != "":
            headers["Authorization"] = "Bearer %s" % (key or self.key)
        conn.request(method, path, None if body is None else json.dumps(body), headers)
        resp = conn.getresponse()
        try:
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def rpc(self, method, params=None):
        status, _, raw = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 7,
                                                       "method": method, "params": params or {}})
        self.assertEqual(status, 200)
        return json.loads(raw)

    def call(self, tool, **arguments):
        return self.rpc("tools/call", {"name": tool, "arguments": arguments})["result"]

    def ready_tool(self, key="shout", code=SHOUT):
        """A tool whose tests passed at its last build turn."""
        key, problem = work.create_task(self.root, key, "Print the input in capitals.", tool=True)
        self.assertFalse(problem)
        folder = work.task_folder(self.root, key, tool=True)
        write(folder, "tool.py", code)
        service.keep_record(folder, {"asked": 1, "turns": 1, "tests": [2, 2], "done": True})
        return folder


class TestKey(Served):
    def test_it_is_made_once_and_kept(self):
        self.assertGreaterEqual(len(self.key), 24)
        self.assertEqual(orthros.Orthros(self.root, simulate=True).settings["serve_key"], self.key)

    def test_every_request_needs_it_and_the_page_counts_those_without(self):
        self.serve()
        for key in ("", "wrong"):
            status, _, _ = self.request("GET", "/health", key=key)
            self.assertEqual(status, 401)
        self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.svc.view()["denied"], 2)


class TestInference(Served):
    def test_it_goes_to_the_served_model_whatever_model_is_named(self):
        self.serve()
        status, _, raw = self.request("POST", "/v1/chat/completions", {
            "model": "gpt-4", "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(status, 200)
        answer = json.loads(raw)["choices"][0]["message"]["content"]
        self.assertEqual(answer, "(simulated %s) hello" % service.IDENTIFIER)
        self.assertEqual(self.svc.served, 1)
        self.assertGreater(self.svc.tokens, 0)

    def test_a_stream_is_passed_on_as_it_comes(self):
        self.serve()
        status, headers, raw = self.request("POST", "/v1/chat/completions", {
            "stream": True, "messages": [{"role": "user", "content": "one two"}]})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["content-type"])
        self.assertIn(b'"two "', raw)
        self.assertTrue(raw.rstrip().endswith(b"data: [DONE]"))

    def test_models_lists_only_the_served_one(self):
        self.serve()
        status, _, raw = self.request("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual([m["id"] for m in json.loads(raw)["data"]], ["simulated"])

    def test_while_a_tool_is_built_it_is_refused_and_says_when_to_come_back(self):
        self.serve()
        self.svc.refuse("A is building the tool shout", 900)
        status, headers, raw = self.request("POST", "/v1/chat/completions", {"messages": []})
        self.assertEqual(status, 503)
        self.assertEqual(headers["retry-after"], "900")
        self.assertIn("building the tool shout", json.loads(raw)["error"]["message"])
        self.assertEqual(self.request("GET", "/health")[0], 503)
        self.assertEqual(self.rpc("ping")["result"], {})       # tools go on answering

    def test_a_request_waits_its_turn_and_a_caller_that_leaves_is_counted(self):
        self.serve()
        self.svc.turn.acquire()                  # the model is busy with someone else
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.svc.port(), timeout=2)
            conn.request("POST", "/v1/chat/completions", json.dumps({"messages": [
                {"role": "user", "content": "hi"}]}), {"Authorization": "Bearer " + self.key})
            with self.assertRaises(OSError):     # it waits: the caller times out first
                conn.getresponse()
            conn.close()
            deadline = time.time() + 10
            while not self.svc.gave_up and time.time() < deadline:
                time.sleep(0.2)
        finally:
            self.svc.turn.release()
        self.assertEqual((self.svc.gave_up, self.svc.refused), (1, 0))
        self.assertTrue(self.svc.recent[-1]["result"].startswith("caller gave up after"))

    def test_the_port_is_open_only_while_listening(self):
        self.serve()
        port = self.svc.port()
        self.assertNotEqual(port, 8777)          # 0 is any free port, never the real one
        self.svc.listen(False)
        with self.assertRaises(OSError):
            http.client.HTTPConnection("127.0.0.1", port, timeout=5).connect()


class TestMcp(Served):
    def test_initialize_list_and_notifications(self):
        self.serve()
        hello = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(hello["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", hello["result"]["capabilities"])
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, [t["name"] for t in service.BUILT_IN])
        status, _, _ = self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, 202)
        self.assertEqual(self.request("GET", "/mcp")[0], 405)

    def test_build_tool_makes_a_tool_with_the_contract_and_queues_it(self):
        self.serve()
        said = self.call("build_tool", name="Shout", description="Print the input in capitals.")
        self.assertFalse(said["isError"], said)
        folder = work.task_folder(self.root, "shout", tool=True)
        self.assertIn("# The tool contract", work.read(os.path.join(folder, "RALPH_PROMPT.md")))
        self.assertEqual(self.svc.next_build()["key"], "shout")
        self.assertIn("shout: queued", self.call("tool_status")["content"][0]["text"])
        listed = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual(len(listed), len(service.BUILT_IN))          # not callable yet

    def test_asking_again_puts_the_change_first_and_queues_it_again(self):
        folder = self.ready_tool()
        self.svc.build_tool("shout", "Also keep the newlines exactly as they came.")
        items = orthros.OPEN_ITEM.findall(work.read(os.path.join(folder, "orthros_tasks.md")))
        self.assertTrue(items[0].startswith("From the requester: Also keep the newlines"))
        self.assertEqual(self.svc.next_build()["key"], "shout")

    def test_asking_while_it_is_being_built_changes_nothing(self):
        folder = self.ready_tool()
        before = work.read(os.path.join(folder, "orthros_tasks.md"))
        self.o.state["running"] = {"agent": "A", "workspace": folder}
        said, failed = self.svc.build_tool("shout", "Also keep the newlines exactly.")
        self.assertTrue(failed)
        self.assertIn("being built right now", said)
        self.assertEqual(work.read(os.path.join(folder, "orthros_tasks.md")), before)
        self.assertTrue(service.record(folder)["done"])

    def test_a_ready_tool_is_listed_and_runs_without_the_harness(self):
        self.ready_tool(code="import os, sys\nprint(sys.stdin.read().upper(), "
                             "sorted(k for k in os.environ if k.startswith('ORTHROS_')))\n")
        self.serve()
        listed = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(listed["shout"]["inputSchema"]["required"], ["input"])
        with mock.patch.dict(os.environ, {"ORTHROS_SECRET": "x"}):
            said = self.call("shout", input="hi")
        self.assertEqual((said["isError"], said["content"][0]["text"].strip()), (False, "HI []"))

    def test_a_tool_that_fails_or_hangs_says_so(self):
        self.ready_tool("broken", "import sys\nsys.exit('no input to work on')\n")
        self.ready_tool("stuck", "import time\ntime.sleep(60)\n")
        self.serve()
        said = self.call("broken", input="")
        self.assertTrue(said["isError"])
        self.assertIn("no input to work on", said["content"][0]["text"])
        said = self.call("stuck", input="")
        self.assertTrue(said["isError"])
        self.assertIn("did not answer within 5 seconds", said["content"][0]["text"])

    def test_unknown_tools_and_methods_are_errors(self):
        self.serve()
        self.assertEqual(self.rpc("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertEqual(self.rpc("resources/list")["error"]["code"], -32601)


class TestBuilding(Served):
    def test_a_tool_is_ready_when_its_tests_pass_with_nothing_open(self):
        self.svc.build_tool("shout", "Print the input in capitals.")
        folder = work.task_folder(self.root, "shout", tool=True)
        write(folder, "tool.py", SHOUT)
        write(folder, "orthros_tasks.md", "# Task\n\n## Tasks\n\n- [x] all of it\n")
        self.svc.after_build("shout", {"launched": True, "score": (3, 3)})
        self.assertTrue(service.record(folder)["done"])
        self.assertIsNone(self.svc.next_build())
        self.assertTrue(any("shout is ready: 3 of 3" in e for e in self.events))

    def test_a_tool_is_given_up_when_its_turns_run_out(self):
        self.o.settings["tool_turns"] = 2
        self.svc.build_tool("shout", "Print the input in capitals.")
        for _ in range(2):
            self.assertEqual(self.svc.next_build()["key"], "shout")
            self.svc.after_build("shout", {"launched": True, "score": (0, 2)})
        self.assertIsNone(self.svc.next_build())
        self.assertIn("shout: given up", self.svc.tool_status())

    def test_a_turn_that_never_started_is_not_counted(self):
        self.svc.build_tool("shout", "Print the input in capitals.")
        self.svc.after_build("shout", {"launched": False, "score": (0, 0)})
        self.assertEqual(self.svc.next_build()["turns"], 0)


class TestServeMode(Served):
    def test_serving_loads_the_model_and_says_where(self):
        self.assertEqual(self.o.set_mode("serve"), "ok")
        with mock.patch.object(self.o.wake, "wait"):
            self.o.keep_serving()
        self.assertEqual(self.o.phase, "serving")
        self.assertTrue(self.svc.view()["ready"])
        self.assertTrue(any(e.startswith("serving simulated to the network") for e in self.events))

    def test_what_belongs_to_improving_itself_is_off(self):
        self.o.set_mode("serve")
        self.o.agent("A")["since_eval"] = 99
        self.assertIsNone(self.o.maybe_start_eval("A"))
        self.assertFalse(self.o.score_gated("A"))

    def test_idle_build_turns_never_pause_the_service(self):
        self.o.set_mode("serve")
        self.o.state["idle_streak"] = 50
        folder = self.o.folders["B"]
        with mock.patch.object(self.o, "pause") as pause:
            self.o.judge({"agent": "A", "started": 0, "seconds": 60, "exit": 0,
                          "launched": True, "rounds": 1, "ticked": 0, "kept": 0,
                          "sent_back": 1, "tokens": 0, "reason": "Time is up.", "log": "",
                          "own": orthros.head(self.o.folders["A"]), "pre": orthros.head(folder),
                          "post": orthros.head(folder), "item": "", "minutes": 30,
                          "lowest_free_mb": None, "kind": "task", "label": "shout",
                          "folder": folder, "score": None})
        pause.assert_not_called()
        self.assertEqual(self.o.state["idle_streak"], 0)


class TestChatBox(Served):
    def test_paused_it_loads_the_model_to_answer(self):
        self.assertEqual(self.o.answer("how is it going?"),
                         "(simulated %s) how is it going?" % service.IDENTIFIER)
        self.assertTrue(self.svc.ready)
        self.assertTrue(any("loading the model to answer" in e for e in self.events))


class TestHarness(unittest.TestCase):
    def test_a_tasks_tests_get_nothing_of_the_harness(self):
        folder = tempfile.mkdtemp()
        try:
            write(folder, "test_env.py", "import os, unittest\nclass T(unittest.TestCase):\n"
                                         "    def test_clean(self):\n"
                                         "        self.assertNotIn('ORTHROS_LEDGER', os.environ)\n")
            with mock.patch.dict(os.environ, {"ORTHROS_LEDGER": "x"}):
                self.assertEqual(work.run_tests(folder, sys.executable), (1, 1))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
