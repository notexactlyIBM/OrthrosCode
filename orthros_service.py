"""Serve mode: the card serves the local network.

Orthros's third mode. Instead of improving the agents, the model on this
machine's card answers other machines, in the two protocols most software
already speaks:

    /v1/...  The OpenAI-compatible API that LM Studio itself speaks -- chat
             completions and the rest -- passed through to it. Any OpenAI
             client works: base URL http://<this machine>:<serve_port>/v1.
    /mcp     MCP (streamable HTTP) for tools. build_tool asks A and B to
             build a command-line tool in tools\\<name>, test-first, every
             change reviewed; each tool whose tests pass is then a tool any
             MCP client can call. It runs here, inside the same limits as
             the model's other code.

Every request needs the key (Authorization: Bearer <serve_key>), which the
page shows: the tools run code on this machine. The port is open only while
serve mode is on and started.

One card. While A or B builds a tool the model is theirs, and inference
answers 503 with Retry-After, which tells a client to use its next provider
for a while rather than wait. So does a full queue. A client should also
connect with a short timeout, and treat any failure the same way: this
machine may be off.

LM Studio itself stays on 127.0.0.1. Orthros loads the model under its own
name and sends every request to that, whatever model the client names -- so
nothing a client asks for can make LM Studio load a second model onto a card
that already holds one.

Standard library only, like orthros.py.
"""

import hmac
import http.client
import http.server
import json
import os
import socket
import subprocess
import threading
import time
import urllib.parse

import orthros_work as work

IDENTIFIER = "orthros-serve"         # the served model's name inside LM Studio
RECORD = ".orthros-tool.json"        # a tool's build record, kept in its own folder
MCP_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MAX_BODY = 32 * 1024 * 1024          # bytes of one request
TOOL_OUTPUT = 100000                 # characters of a tool's answer sent back
CREATE_NO_WINDOW = 0x08000000

INSTRUCTIONS = ("Tools built on request by Orthros's two coding agents, and run on the machine "
                "with the GPU. build_tool asks for a new one: the agents build it in turns, "
                "tests first, each change reviewed by the other -- an hour or more, during which "
                "that machine's model answers nothing else. Every tool whose tests pass is "
                "listed here and takes one text input, which it is sent on stdin.")
BUILD_TOOL = {
    "name": "build_tool",
    "description": "Ask for a new command-line tool, or for changes to one. Say what goes in, "
                   "what comes out, and how to check it works. Returns at once; the tool is "
                   "listed, and callable, when its tests pass. Asking again with the same name "
                   "puts the new description at the top of its list.",
    "inputSchema": {"type": "object", "required": ["name", "description"], "properties": {
        "name": {"type": "string", "description": "short, e.g. csv-cleaner"},
        "description": {"type": "string", "description": "what it does: input, output, checks"}}},
}
TOOL_STATUS = {
    "name": "tool_status",
    "description": "How each tool asked for is doing: building, ready or given up, and why.",
    "inputSchema": {"type": "object", "properties": {
        "name": {"type": "string", "description": "one tool; all when left out"}}},
}
TOOL_INPUT = {"type": "object", "required": ["input"], "properties": {
    "input": {"type": "string", "description": "sent to the tool on stdin"}}}


def now():
    return time.time()


def lms_run(lms, *args, timeout=300):
    """(exit code, output) of LM Studio's lms."""
    try:
        proc = subprocess.run([lms] + list(args), capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def resident(lms):
    """The names LM Studio holds a model in memory under."""
    code, out = lms_run(lms, "ps", "--json", timeout=60)
    start = out.find("[")
    try:
        entries = json.loads(out[start:]) if code == 0 and start >= 0 else []
    except ValueError:
        return []
    return [str(e.get("identifier") or "") for e in entries if isinstance(e, dict)]


def record(folder):
    try:
        with open(os.path.join(folder, RECORD), encoding="utf-8") as handle:
            return json.load(handle) or {}
    except (OSError, ValueError):
        return {}


def keep_record(folder, rec):
    work.write(os.path.join(folder, RECORD), json.dumps(rec, indent=1))


def send(req, code, body, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    try:
        req.send_response(code)
        req.send_header("Content-Type", "application/json")
        req.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            req.send_header(key, value)
        req.end_headers()
        req.wfile.write(data)
    except OSError:
        pass                             # the client went away


def error(message, kind="unavailable"):
    return {"error": {"message": message, "type": kind}}


def text_result(text, failed=False):
    return {"content": [{"type": "text", "text": text}], "isError": failed}


class Service:
    """The network side of serve mode. Orthros's loop decides when the model is
    loaded and when a tool is built; this answers the requests."""

    def __init__(self, orthros):
        self.o = orthros
        self.lock = threading.Lock()
        self.server = None               # the listener, while open
        self.listen_error = ""
        self.ready = False               # the model is loaded and answered
        self.why, self.retry = "not started", 60   # why inference is refused, if it is
        self.upstream = ("127.0.0.1", 1234)
        self.model = ""
        self.waiting = 0                 # inference requests in flight
        self.served = self.refused = self.tokens = 0
        self.checked = 0.0
        self.recheck = False             # a request failed upstream: is the model still there?
        self.fake = None                 # the stand-in for LM Studio in a simulation
        self._urls = (0.0, [])

    # ------------------------------------------------------------ the engine

    def engine_up(self):
        """Load the model to serve, the way the agents load it. '' once it answers,
        else why not."""
        if self.o.simulate:
            if not self.fake:
                self.fake = fake_engine()
            self.upstream, self.model = ("127.0.0.1", self.fake.server_address[1]), "simulated"
            self.ready, self.checked = True, now()
            return ""
        e = self.o.engine()
        if not e["lms"]:
            return "Could not find LM Studio's lms.exe (LC_LMS_PATH in the agents' config.cmd)"
        if not e["model"]:
            return "no model to serve: LC_MODEL_KEY is not set in the agents' config.cmd"
        self.upstream, self.model = ("127.0.0.1", e["port"]), e["model"]
        if not self.answers(20):
            lms_run(e["lms"], "server", "start", "-p", str(e["port"]))    # 127.0.0.1 only
            deadline = now() + 60
            while self.upstream_get("/v1/models") is None:
                if now() > deadline:
                    return "the LM Studio server never came up"
                time.sleep(1.5)
            if IDENTIFIER not in resident(e["lms"]):
                lms_run(e["lms"], "unload", "--all")
                args = ["load", e["model"], "--gpu", e["gpu"], "-c", str(e["context"]),
                        "--parallel", str(e["parallel"]), "--identifier", IDENTIFIER, "-y"]
                if not e["speculative"]:
                    args.append("--no-speculative-draft-mtp")
                code, out = lms_run(e["lms"], *args, timeout=900)
                if code:
                    return "Could not load '%s': %s" % (e["model"], " ".join(out.split())[-300:])
            if not self.answers(180):
                return "the model is loaded but does not answer"
        self.ready, self.checked, self.recheck = True, now(), False
        return ""

    def engine_down(self):
        """Unload the served model and stop LM Studio's server: the card is free."""
        was, self.ready = self.ready, False
        if self.o.simulate:
            return
        lms = self.o.engine()["lms"]
        if lms:
            lms_run(lms, "unload", "--all", timeout=120)
            lms_run(lms, "server", "stop", timeout=120)
        if was:
            time.sleep(8)                # let the driver hand the memory back

    def watch(self):
        """Is the served model still there? Asked of LM Studio once a minute, and at
        once after a request failed on its way to it. False sends Orthros to reload it."""
        if not self.ready or self.o.simulate:
            return self.ready
        if self.recheck or now() - self.checked > 60:
            self.checked, self.recheck = now(), False
            lms = self.o.engine()["lms"]
            if lms and IDENTIFIER not in resident(lms):
                self.ready = False
        return self.ready

    def upstream_get(self, path):
        try:
            conn = http.client.HTTPConnection(*self.upstream, timeout=4)
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.read() if resp.status == 200 else None
        except (OSError, http.client.HTTPException):
            return None

    def answers(self, seconds):
        """Does the served model reply? Being loaded is not the same thing."""
        try:
            conn = http.client.HTTPConnection(*self.upstream, timeout=seconds)
            conn.request("POST", "/v1/chat/completions", json.dumps({
                "model": IDENTIFIER, "max_tokens": 1, "temperature": 0,
                "messages": [{"role": "user", "content": "hi"}]}),
                {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
            resp = conn.getresponse()
            resp.read()
            return resp.status == 200
        except (OSError, http.client.HTTPException):
            return False

    # ------------------------------------------------------------ the network

    def refuse(self, why, retry=60):
        """Inference answers 503 with this reason until serving() -- a tool is being
        built, the model is loading. Everything else goes on answering."""
        self.why, self.retry = why, retry

    def serving(self):
        self.why = ""

    def listen(self, on):
        """Open or close the port to the network. Cheap to call every time round."""
        if on and not self.server:
            port = self.port()
            # Every interface, which is what makes it the network's. The tests
            # set serve_host to 127.0.0.1: no firewall prompt for a test run.
            host = self.o.settings.get("serve_host") or "0.0.0.0"
            try:
                server = http.server.ThreadingHTTPServer((host, port), self.handler())
            except OSError as exc:
                if not self.listen_error:
                    self.o.event("could not open port %d to the network: %s" % (port, exc), "bad")
                self.listen_error = str(exc)
                return
            server.daemon_threads = True
            self.server, self.listen_error = server, ""
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.o.event("open to the network at %s" % self.address(), "start")
        elif not on and self.server:
            server, self.server = self.server, None
            server.shutdown()
            server.server_close()
            self.o.event("closed to the network")

    def port(self):
        """The port in use, or the one to use; a setting of 0 means any free one."""
        if self.server:
            return self.server.server_address[1]
        port = self.o.settings.get("serve_port")
        return 8777 if port in (None, "") else int(port)

    def urls(self):
        """Where other machines find this one: its name, then its addresses."""
        at, found = self._urls
        if now() - at > 60:
            host = socket.gethostname()
            try:
                ips = sorted({i[4][0] for i in socket.getaddrinfo(host, None, socket.AF_INET)}
                             - {"127.0.0.1"})
            except OSError:
                ips = []
            found = [host] + ips
            self._urls = (now(), found)
        return ["http://%s:%d" % (h, self.port()) for h in found]

    def address(self):
        return (self.urls() or ["http://127.0.0.1:%d" % self.port()])[0]

    def view(self):
        """For the page."""
        return {"open": bool(self.server), "ready": self.ready and not self.why,
                "why": self.why if self.server else "", "error": self.listen_error,
                "urls": self.urls(), "key": self.o.settings.get("serve_key", ""),
                "model": self.model, "served": self.served, "refused": self.refused,
                "tokens": self.tokens,
                "tools": [{k: t[k] for k in ("key", "state", "tests", "turns", "open", "done",
                                             "parked")} for t in self.tools()]}

    def handler(self):
        service = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                service.handle(self, "GET")

            def do_POST(self):
                service.handle(self, "POST")

            def do_DELETE(self):
                service.handle(self, "DELETE")
        return Handler

    def authorized(self, header):
        scheme, _, token = (header or "").partition(" ")
        key = self.o.settings.get("serve_key") or ""
        return bool(key) and scheme.lower() == "bearer" and \
            hmac.compare_digest(token.strip().encode("utf-8"), key.encode("utf-8"))

    def handle(self, req, method):
        path = urllib.parse.urlparse(req.path).path.rstrip("/") or "/"
        if not self.authorized(req.headers.get("Authorization")):
            return send(req, 401, error("send the key Orthros's page shows: Authorization: "
                                        "Bearer <key>", "unauthorized"))
        try:
            length = int(req.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return send(req, 413, error("request too large", "invalid_request_error"))
        raw = req.rfile.read(length) if length > 0 else b""
        try:
            if path == "/health":
                up = self.ready and not self.why
                return send(req, 200 if up else 503, {
                    "serving": up, "why": self.why, "model": self.model,
                    "in_flight": self.waiting,
                    "tools": [t["key"] for t in self.tools() if t["callable"]]},
                    None if up else {"Retry-After": str(self.retry)})
            if path == "/mcp":
                return self.mcp(req, method, raw)
            if path == "/v1/models" and method == "GET":
                if not self.ready or self.why:
                    return self.unavailable(req)
                return send(req, 200, {"object": "list", "data": [
                    {"id": self.model, "object": "model", "owned_by": "orthros"}]})
            if path.startswith("/v1/") and method == "POST":
                return self.infer(req, path, raw)
            send(req, 404, error("no such endpoint: %s %s" % (method, path), "not_found"))
        except Exception as exc:         # a bug here must not take the listener down
            send(req, 500, error("Orthros: %s" % exc, "server_error"))

    def unavailable(self, req, why=None, retry=None):
        with self.lock:
            self.refused += 1
        send(req, 503, error(why or self.why or "not serving yet"),
             {"Retry-After": str(retry or self.retry)})

    # ------------------------------------------------------------ inference

    def infer(self, req, path, raw):
        """Pass one OpenAI-style request to LM Studio, streamed or whole."""
        if not self.ready or self.why:
            return self.unavailable(req)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return send(req, 400, error("the body must be a JSON object", "invalid_request_error"))
        limit = max(1, int(self.o.settings.get("serve_queue") or 2))
        with self.lock:
            if self.waiting >= limit:
                self.refused += 1
                return send(req, 503, error("busy: %d request(s) ahead of this one" % self.waiting),
                            {"Retry-After": "5"})
            self.waiting += 1
        body["model"] = IDENTIFIER
        started = False
        conn = http.client.HTTPConnection(*self.upstream, timeout=1800)
        try:
            conn.request("POST", path, json.dumps(body).encode("utf-8"),
                         {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
            resp = conn.getresponse()
            kind = resp.getheader("Content-Type") or "application/json"
            if resp.status >= 400:
                self.recheck = True
            if "text/event-stream" in kind:
                req.send_response(resp.status)
                req.send_header("Content-Type", kind)
                req.send_header("Cache-Control", "no-cache")
                req.end_headers()
                started = True
                for line in resp:
                    req.wfile.write(line)
                    if not line.strip():
                        req.wfile.flush()
                used = 0
            else:
                data = resp.read()
                started = True
                send(req, resp.status, data)
                try:
                    used = int((json.loads(data).get("usage") or {}).get("total_tokens") or 0)
                except (ValueError, AttributeError, TypeError):
                    used = 0
            if resp.status < 400:
                with self.lock:
                    self.served += 1
                    self.tokens += used
        except (OSError, http.client.HTTPException) as exc:
            if not started:              # after that, it is the client that went away
                self.recheck = True
                self.unavailable(req, "the model did not answer: %s" % exc, 30)
        finally:
            conn.close()
            with self.lock:
                self.waiting -= 1

    # ------------------------------------------------------------ MCP

    def mcp(self, req, method, raw):
        """MCP over streamable HTTP, answering every request with plain JSON."""
        if method != "POST":
            return send(req, 405, error("POST JSON-RPC here; this server opens no event stream",
                                        "invalid_request_error"), {"Allow": "POST"})
        try:
            msg = json.loads(raw or b"null")
        except ValueError:
            return send(req, 400, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32700, "message": "parse error"}})
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return send(req, 400, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32600, "message": "invalid request"}})
        if "method" not in msg or "id" not in msg:
            return send(req, 202, b"")   # a notification, or a reply to nothing we asked
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        result, fault = self.rpc(msg["method"], params)
        reply = {"jsonrpc": "2.0", "id": msg["id"]}
        reply.update({"error": fault} if fault else {"result": result})
        send(req, 200, reply)

    def rpc(self, method, params):
        """(result, None) or (None, error) for one JSON-RPC request."""
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in MCP_VERSIONS else MCP_VERSIONS[-2],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "orthros", "version": "1"},
                    "instructions": INSTRUCTIONS}, None
        if method == "ping":
            return {}, None
        if method == "tools/list":
            tools = [BUILD_TOOL, TOOL_STATUS] + [
                {"name": t["key"], "inputSchema": TOOL_INPUT,
                 "description": "%s (tests: %d of %d pass)" % (t["brief"][:1000], t["tests"][0],
                                                               t["tests"][1])}
                for t in self.tools() if t["callable"]]
            return {"tools": tools}, None
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            if name == "build_tool":
                said, failed = self.build_tool(args.get("name"), args.get("description"))
                return text_result(said, failed), None
            if name == "tool_status":
                return text_result(self.tool_status(args.get("name"))), None
            tool = next((t for t in self.tools() if t["key"] == name), None)
            if tool and tool["callable"]:
                return self.run_tool(tool, args.get("input")), None
            if tool:
                return text_result("%s is %s; tool_status says more." % (name, tool["state"]),
                                   True), None
            return None, {"code": -32602, "message": "unknown tool: %s" % name}
        return None, {"code": -32601, "message": "method not found: %s" % method}

    # ------------------------------------------------------------ tools

    def turn_limit(self):
        return max(1, int(self.o.settings.get("tool_turns") or 4))

    def tools(self):
        """Every tool asked for, with its list, its tests and its state."""
        limit = self.turn_limit()
        running = (self.o.state.get("running") or {}).get("workspace") or ""
        out = []
        for t in work.list_tasks(self.o.root, tool=True):
            rec = record(t["folder"])
            tests = list(rec.get("tests") or [0, 0])
            passing = bool(tests[1]) and tests[0] == tests[1] and \
                os.path.isfile(os.path.join(t["folder"], "tool.py"))
            busy = bool(running) and os.path.normcase(running) == os.path.normcase(t["folder"])
            wanted = bool(rec) and not rec.get("done") and rec.get("turns", 0) < limit
            brief = work.read(os.path.join(t["folder"], "TASK.md")).split("\n", 1)[-1].strip()
            t.update(tests=tests, turns=rec.get("turns", 0), asked=rec.get("asked", 0),
                     wanted=wanted, brief=" ".join(brief.split()), callable=passing and not busy,
                     state="building" if busy else "queued" if wanted else
                     "ready" if passing else "given up")
            out.append(t)
        return out

    def next_build(self):
        """The tool to build next: asked for longest ago, not yet done, not over its turns."""
        waiting = [t for t in self.tools() if t["wanted"]]
        return min(waiting, key=lambda t: t["asked"]) if waiting else None

    def build_tool(self, name, description):
        """Ask for a tool, or for changes to one. Returns (message, failed)."""
        description = " ".join(str(description or "").split())[:4000]
        key = work.slug(str(name or "") or description[:40])
        folder = work.task_folder(self.o.root, key, tool=True)
        if folder:
            if len(description) < 10:
                return "Say what to change about %s -- a sentence at least." % key, True
            work.add_first(os.path.join(folder, "orthros_tasks.md"),
                           "From the requester: %s" % description)
        else:
            key, problem = work.create_task(self.o.root, str(name or ""), description, tool=True)
            if problem:
                return problem, True
            folder = work.task_folder(self.o.root, key, tool=True)
        rec = record(folder)
        rec.update(asked=now(), turns=0, done=False)
        keep_record(folder, rec)
        self.o.event("tool %s asked for: %s" % (key, description[:100]), "start")
        self.o.wake.set()
        return ("Queued the tool %s. A and B build it in turns of about %s minutes, up to %d "
                "turns; while they work, this machine's model answers nothing else. It is "
                "listed, and callable, once its tests pass -- tool_status says how it is going."
                % (key, self.o.settings.get("session_minutes"), self.turn_limit())), False

    def tool_status(self, name=None):
        tools = [t for t in self.tools() if not name or t["key"] == work.slug(name)]
        if not tools:
            return ("No tool called %s." % name) if name else \
                "No tools yet: build_tool asks for one."
        return "\n".join(
            "%s: %s. %d done, %d open, %d parked; tests %d of %d pass; %d of %d turns used."
            % (t["key"], t["state"], t["done"], t["open"], t["parked"], t["tests"][0],
               t["tests"][1], t["turns"], self.turn_limit()) for t in tools)

    def after_build(self, key, result):
        """Count a finished build turn. A tool is done when its tests pass with nothing
        left open, or when its turns run out."""
        folder = work.task_folder(self.o.root, key, tool=True)
        if not folder:
            return
        rec = record(folder)
        if result.get("launched"):
            rec["turns"] = rec.get("turns", 0) + 1
        if result.get("score"):
            rec["tests"] = list(result["score"])
        keep_record(folder, rec)
        tool = next((t for t in self.tools() if t["key"] == key), None)
        if not tool or not ((tool["callable"] and not tool["open"])
                            or rec.get("turns", 0) >= self.turn_limit()):
            return
        rec["done"] = True
        keep_record(folder, rec)
        passed, total = tool["tests"]
        if tool["callable"]:
            self.o.event("the tool %s is ready: %d of %d tests pass%s" % (
                key, passed, total, "; %d item(s) were left open" % tool["open"]
                if tool["open"] else ""), "good")
        else:
            self.o.event("the tool %s was given up after %d turns: %d of %d tests pass, %d "
                         "item(s) open" % (key, rec["turns"], passed, total, tool["open"]), "bad")

    def run_tool(self, tool, text):
        """Run a tool once on `text`, inside the limits the model's code always runs in."""
        seconds = max(5, int(self.o.settings.get("tool_seconds") or 120))
        try:
            proc = work.contained_run([self.o.python_for("A"), "tool.py"], seconds,
                                      input=str(text or ""), cwd=tool["folder"],
                                      env=work.check_env(),
                                      creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            return text_result("%s did not answer within %d seconds" % (tool["key"], seconds), True)
        except OSError as exc:
            return text_result("%s could not start: %s" % (tool["key"], exc), True)
        if proc.returncode:
            said = (proc.stderr or "").strip().splitlines() or ["no reason given"]
            return text_result("%s failed (exit %s): %s"
                               % (tool["key"], proc.returncode, said[-1]), True)
        return text_result((proc.stdout or "")[:TOOL_OUTPUT])


def fake_engine(port=0):
    """A stand-in for LM Studio, for --simulate and the tests: every chat
    completion is answered with the last message it was sent, whole or
    streamed. Returns the running server."""

    class Fake(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            send(self, 200, {"object": "list", "data": [{"id": IDENTIFIER, "object": "model"}]})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            said = ((body.get("messages") or [{}])[-1].get("content") or "")
            answer = "(simulated %s) %s" % (body.get("model"), said)
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for word in answer.split(" "):
                    chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                return
            send(self, 200, {"object": "chat.completion", "model": body.get("model"), "choices": [
                {"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": answer}}],
                "usage": {"prompt_tokens": len(said) // 4, "completion_tokens": len(answer) // 4,
                          "total_tokens": (len(said) + len(answer)) // 4}})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Fake)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
