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

Every request is a row in ledger.sqlite (the `requests` table, beside the
agents' rounds): when, from where, what it asked, how long it waited for the
model, how long the answer took, and its tokens. The page's counts are the
last day's, and its list the newest rows, both read from there -- so a restart
forgets nothing. Until 2026-11-07 the list lived in memory, Orthros restarted
most days, and nothing said whether a quiet card meant few requests or slow
answers.

Standard library only, like orthros.py.
"""

import collections
import hmac
import http.client
import http.server
import json
import os
import re
import select
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.parse

import orthros_work as work

IDENTIFIER = "orthros-serve"         # the served model's name inside LM Studio
RECORD = ".orthros-tool.json"        # a tool's build record, kept in its own folder
LEDGER = work.LEDGER                 # the requests table lives beside the agents' rounds
REQUESTS = ("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, at REAL, count INTEGER, "
            "who TEXT, user TEXT, ask TEXT, full TEXT, tag TEXT, result TEXT, waited REAL, "
            "seconds REAL, tokens_in INTEGER, tokens_out INTEGER)")
# The last day's counts, and the seconds the model spent answering in the last hour.
TOTALS = """SELECT SUM(result = 'answered'), SUM(result LIKE 'caller gave up%'),
       SUM(result LIKE 'failed%'),
       SUM(CASE WHEN result LIKE 'turned away%' THEN count ELSE 0 END),
       SUM(CASE WHEN result LIKE 'turned back%' THEN count ELSE 0 END),
       SUM(tokens_in + tokens_out), SUM(CASE WHEN at > ? THEN seconds ELSE 0 END)
FROM requests WHERE at > ?"""
ROW = ("id", "at", "count", "who", "user", "ask", "full", "tag", "result", "waited", "seconds",
       "tokens_in", "tokens_out")
RECENT = 25                          # requests kept for the page
KEEP_DAYS = 30                       # requests kept in the ledger
REPEAT = 60                          # a refusal repeated by one machine within this is one row
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
# The agents' own tools that make sense from outside, run with their code.
RESEARCH = {
    "name": "research",
    "description": "Search the web and read the top page: titles, links and snippets, and "
                   "that page's text, trimmed. Runs on the machine with the GPU and costs no "
                   "tokens.",
    "inputSchema": {"type": "object", "required": ["question"], "properties": {
        "question": {"type": "string"},
        "site": {"type": "string", "description": "only this domain, e.g. python.org"}}},
}
READ_PAGE = {
    "name": "read_page",
    "description": "Fetch one web page and return its text, trimmed.",
    "inputSchema": {"type": "object", "required": ["url"], "properties": {
        "url": {"type": "string"}}},
}
PYTHON_DOCS = {
    "name": "python_docs",
    "description": "The documentation of an installed Python module, class or function, "
                   "as pydoc prints it.",
    "inputSchema": {"type": "object", "required": ["name"], "properties": {
        "name": {"type": "string", "description": "e.g. json.dumps or httpx.Client"}}},
}
BUILT_IN = (BUILD_TOOL, TOOL_STATUS, RESEARCH, READ_PAGE, PYTHON_DOCS)
TAG_ASK = ("In at most eight words, say what this request asks for -- a task label such as "
           "\"summarise news about the Taiwan Strait\" or \"rate a market's odds\". Reply with "
           "the label only.\n\nThe request:\n%s")


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
    """{name LM Studio holds a model in memory under: that model's key}."""
    code, out = lms_run(lms, "ps", "--json", timeout=60)
    start = out.find("[")
    try:
        entries = json.loads(out[start:]) if code == 0 and start >= 0 else []
    except ValueError:
        return {}
    return {str(e.get("identifier") or ""): str(e.get("modelKey") or e.get("path") or "")
            for e in entries if isinstance(e, dict)}


def same_model(held, wanted):
    """Is the model held the one wanted? Keys come with and without their publisher."""
    held, wanted = (held or "").lower(), (wanted or "").lower()
    return bool(held and wanted) and (held == wanted or held.endswith("/" + wanted)
                                      or wanted.endswith("/" + held))


class DualStack(http.server.ThreadingHTTPServer):
    """IPv6 and IPv4 on one socket. A machine that finds this one by name can be
    handed its IPv6 address first, and gets nowhere on IPv4 alone (2026-09-27)."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def every_address(port, handler):
    """A server on all of this machine's addresses; IPv4's alone where it has no IPv6."""
    try:
        return DualStack(("::", port), handler)
    except OSError:
        return http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)


def said(path, body):
    """The last thing a request's user said, whitespace folded."""
    if path.endswith("/embeddings"):
        return "embeddings"
    text = body.get("prompt") if isinstance(body.get("prompt"), str) else ""
    for m in reversed(body.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(
                p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else ""
            break
    return " ".join(str(text).split())


def excerpt(text):
    """A request in one line: its start and its end, where an instruction usually sits."""
    return (text[:320] + " … " + text[-160:]) if len(text) > 500 else (text or "(no text)")


def ask(upstream, model, messages, max_tokens=700, timeout=180, effort="low", temperature=0.3,
        total=None):
    """One chat completion from a model LM Studio has up: its answer, or ''. The model
    thinks first, out of the same budget, so it is asked to think little and given room.
    `total`: the whole budget, thinking included, for a caller that sized it from the
    window in use (the chat's wild mode, which thinks hard)."""
    try:
        conn = http.client.HTTPConnection(*upstream, timeout=timeout)
        conn.request("POST", "/v1/chat/completions", json.dumps({
            "model": model, "messages": messages, "max_tokens": total or max_tokens + 1024,
            "temperature": temperature, "reasoning_effort": effort}),
            {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
        resp = conn.getresponse()
        data = json.loads(resp.read() or b"{}")
        if resp.status != 200:
            return ""
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        # an unfinished one (out of tokens) too
        return re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.S | re.I).strip()
    except (OSError, ValueError, http.client.HTTPException):
        return ""


def usage_in(data):
    """(prompt tokens, completion tokens) from an answer's `usage`, or None."""
    try:
        usage = json.loads(data).get("usage") or {}
        if usage.get("prompt_tokens") is None and usage.get("completion_tokens") is None:
            total = int(usage.get("total_tokens") or 0)
            return (total, 0) if total else None
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    except (ValueError, AttributeError, TypeError):
        return None


def guess_tokens(body):
    """About how many tokens a request's messages are, for a stream that reports no
    usage: four characters to a token, near enough for the page's totals."""
    try:
        return len(json.dumps(body.get("messages") or body.get("prompt") or "")) // 4
    except (TypeError, ValueError):
        return 0


def record(folder):
    try:
        with open(os.path.join(folder, RECORD), encoding="utf-8") as handle:
            return json.load(handle) or {}
    except (OSError, ValueError):
        return {}


def keep_record(folder, rec):
    work.write(os.path.join(folder, RECORD), json.dumps(rec, indent=1))


def send(req, code, body, headers=None):
    """Answer one request. False if its caller had already gone."""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    try:
        req.send_response(code)
        req.send_header("Content-Type", "application/json")
        req.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            req.send_header(key, value)
        req.end_headers()
        req.wfile.write(data)
        req.wfile.flush()
        return True
    except OSError:
        return False


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
        # Loading and unloading, one at a time: the loop serves and starts turns,
        # the chat box loads the model to answer while Orthros is paused.
        self.engine_lock = threading.RLock()
        self.server = None               # the listener, while open
        self.listen_error = ""
        self.ready = False               # the model is loaded and answered
        self.why, self.retry = "not started", 60   # why inference is refused, if it is
        self.upstream = ("127.0.0.1", 1234)
        self.model = ""
        self.waiting = 0                 # inference requests in flight
        self.turn = threading.Semaphore(1)   # the model's turns: one at a time, like the card
        self.gave_up_at = 0.0
        self.turned_back_at = {}         # machine -> when its last one was logged
        # Every request is a row in the ledger; the newest are kept here for the
        # page, and read back on start so a restart forgets nothing.
        self.ledger = os.path.join(orthros.root, LEDGER)
        self.recent = collections.deque(maxlen=RECENT)
        self._totals = (0.0, {})
        self.remember()
        self.tagger = None               # labels them, once there is one to label
        self.checked = 0.0
        self.recheck = False             # a request failed upstream: is the model still there?
        self.fake = None                 # the stand-in for LM Studio in a simulation
        self._urls = (0.0, [])

    # ------------------------------------------------------------ the engine

    def engine_up(self):
        """Load the model to serve, the way the agents load it. '' once it answers,
        else why not."""
        with self.engine_lock:
            return self._engine_up()

    def _engine_up(self):
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
        # The name it is served under says nothing about which model is behind
        # it: after the serving model is changed, the old one still answers.
        if not (self.answers(20) and same_model(resident(e["lms"]).get(IDENTIFIER), e["model"])):
            if self.upstream_get("/v1/models") is None:
                lms_run(e["lms"], "server", "start", "-p", str(e["port"]))    # 127.0.0.1 only
            deadline = now() + 60
            while self.upstream_get("/v1/models") is None:
                if now() > deadline:
                    return "the LM Studio server never came up"
                time.sleep(1.5)
            if not same_model(resident(e["lms"]).get(IDENTIFIER), e["model"]):
                lms_run(e["lms"], "unload", "--all")
                args = ["load", e["model"], "--gpu", e["gpu"], "-c", str(e["context"]),
                        "--parallel", str(e["parallel"]), "--identifier", IDENTIFIER, "-y"]
                if not e["speculative"]:
                    args.append("--no-speculative-draft-mtp")
                code, out = lms_run(e["lms"], *args, timeout=900)
                if code and e["speculative"] and "mtp" in out.lower():
                    # A build without the draft head: load it without, as the agents do.
                    code, out = lms_run(e["lms"], *(args + ["--no-speculative-draft-mtp"]),
                                        timeout=900)
                if code:
                    return "Could not load '%s': %s" % (e["model"], " ".join(out.split())[-300:])
            if not self.answers(180):
                return "the model is loaded but does not answer"
        self.ready, self.checked, self.recheck = True, now(), False
        return ""

    def engine_down(self, force=False):
        """Unload the served model and stop LM Studio's server: the card is free. Only
        when this loaded it, unless `force`: before a turn, whatever is there goes."""
        with self.engine_lock:           # waits for a load the chat box has under way
            was, self.ready = self.ready, False
            if self.o.simulate or not (was or force):
                return
            lms = self.o.engine()["lms"]
            if lms:
                lms_run(lms, "unload", "--all", timeout=120)
                lms_run(lms, "server", "stop", timeout=120)
            if was:
                time.sleep(8)            # let the driver hand the memory back

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
            # Every address, which is what makes it the network's. The tests
            # set serve_host to 127.0.0.1: no firewall prompt for a test run.
            host = self.o.settings.get("serve_host")
            try:
                server = http.server.ThreadingHTTPServer((host, port), self.handler()) \
                    if host else every_address(port, self.handler())
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
        """For the page: the last day's counts and the newest requests, from the ledger."""
        built = self.tools()
        shown = {"open": bool(self.server), "ready": self.ready and not self.why,
                 "why": self.why if self.server else "", "error": self.listen_error,
                 "urls": self.urls(), "key": self.o.settings.get("serve_key", ""),
                 "model": self.model, "in_hand": self.waiting,
                 "recent": [self.shown(r) for r in list(self.recent)[::-1][:12]],
                 "catalog": self.catalog(built),
                 "tools": [{k: t[k] for k in ("key", "state", "tests", "turns", "open", "done",
                                              "parked")} for t in built]}
        shown.update(self.totals())
        return shown

    @staticmethod
    def shown(r):
        """One request as the page lists it: its tokens in all, and the answer's speed."""
        out = {k: v for k, v in r.items() if k not in ("text", "id")}
        out["tokens"] = (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0)
        out["speed"] = round((r.get("tokens_out") or 0) / r["seconds"]) \
            if r.get("seconds") and r.get("tokens_out") else 0
        return out

    # ------------------------------------------------------------ the record

    def sql(self, statement, args=(), rows=False):
        """One statement on the requests table: its rows, or the new row's id. None
        when the ledger cannot be used -- never an exception: the record must not
        be what stops serving."""
        try:
            db = sqlite3.connect(self.ledger, timeout=10)
            try:
                with db:
                    db.execute(REQUESTS)
                    cur = db.execute(statement, args)
                    return cur.fetchall() if rows else cur.lastrowid
            finally:
                db.close()           # `with db` commits but does not close; Windows keeps the lock
        except (sqlite3.Error, OSError):
            return None

    def remember(self):
        """The newest requests back from the ledger, and the old ones out of it."""
        self.sql("DELETE FROM requests WHERE at < ?", (now() - KEEP_DAYS * 86400,))
        found = self.sql("SELECT %s FROM requests ORDER BY id DESC LIMIT ?" % ", ".join(ROW),
                         (RECENT,), rows=True) or []
        for row in reversed(found):
            r = dict(zip(ROW, row))
            r["from"] = r.pop("who")
            r["text"] = "" if r["tag"] else (r["full"] or "")[:1500]   # still to be labelled
            self.recent.append(r)

    def totals(self):
        """The last day's counts: answered, gave up, failed, turned away, wrong key,
        tokens -- and the share of the last hour the model spent answering. Read
        again after a request, else at most every 30 s."""
        at, value = self._totals
        if value and now() - at < 30:
            return value
        found = (self.sql(TOTALS, (now() - 3600, now() - 86400), rows=True) or [()])[0]
        found = [v or 0 for v in found] + [0] * 7
        value = {"served": found[0], "gave_up": found[1], "failed": found[2],
                 "refused": found[3], "denied": found[4], "tokens": found[5],
                 "busy": round(min(1.0, found[6] / 3600.0), 2)}
        self._totals = (now(), value)
        return value

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
        header = req.headers.get("Authorization")
        if not self.authorized(header):
            self.turned_back(req.client_address[0], header, "%s %s" % (method, path))
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
                    self.note(req.client_address[0], "", "GET /v1/models",
                              "turned away: " + (self.why or "not serving"))
                    return self.unavailable(req)
                return send(req, 200, {"object": "list", "data": [
                    {"id": self.model, "object": "model", "owned_by": "orthros"}]})
            if path.startswith("/v1/") and method == "POST":
                return self.infer(req, path, raw)
            send(req, 404, error("no such endpoint: %s %s" % (method, path), "not_found"))
        except Exception as exc:         # a bug here must not take the listener down
            send(req, 500, error("Orthros: %s" % exc, "server_error"))

    def turned_back(self, who, header, what):
        """Record a request without the right key -- where it came from, what it
        tried, what was wrong with it -- and say so in the log once a minute per
        machine."""
        scheme, _, token = (header or "").partition(" ")
        token, key = token.strip(), self.o.settings.get("serve_key") or ""
        why = ("it sent no key" if not header else
               "it did not send 'Bearer <key>'" if scheme.lower() != "bearer" else
               "its key has <> or quotes around it" if token[:1] in "<'\"" else
               "its key is a different one (%d characters, the right one has %d)"
               % (len(token), len(key)))
        with self.lock:
            quiet = now() - self.turned_back_at.get(who, 0) < 60
            if not quiet:
                self.turned_back_at[who] = now()
        if not quiet:
            self.o.event("turned back a request from %s: %s" % (who, why), "bad")
        self.note(who, "", what, "turned back: " + why)

    def note(self, who, user, what, result, tokens=(0, 0), seconds=0.0, waited=0.0):
        """One request, as it went, into the ledger and the page's list. `what` is the
        line shown, or (that line, the request's text: shown whole when the line is
        opened, and the tagger labels its start). `seconds` is the answer's own time;
        `waited`, the wait for the model before it. A refusal repeated from one
        machine within a minute is one row, counted up: a misconfigured client
        retrying is one line, not a page of them."""
        line, text = what if isinstance(what, tuple) else (what, "")
        with self.lock:
            last = self.recent[-1] if self.recent else None
            if result.startswith("turned") and last and last["result"] == result \
                    and last["from"] == who and now() - last["at"] < REPEAT:
                last["count"], last["at"] = (last.get("count") or 1) + 1, now()
                self.sql("UPDATE requests SET count = ?, at = ? WHERE id = ?",
                         (last["count"], last["at"], last.get("id")))
                self._totals = (0.0, {})
                return
            row = {"at": now(), "count": 1, "from": who, "user": str(user or "")[:60],
                   "ask": line, "full": text, "tag": "" if text else line, "result": result,
                   "waited": round(waited, 1), "seconds": round(seconds, 1),
                   "tokens_in": int(tokens[0] or 0), "tokens_out": int(tokens[1] or 0),
                   "text": text[:1500]}
            row["id"] = self.sql(
                "INSERT INTO requests (%s) VALUES (%s)" % (", ".join(ROW[1:]),
                                                           ", ".join("?" * len(ROW[1:]))),
                (row["at"], 1, who, row["user"], line, text, row["tag"], result,
                 row["waited"], row["seconds"], row["tokens_in"], row["tokens_out"]))
            self.recent.append(row)
            self._totals = (0.0, {})
        if text and not self.tagger:
            self.tagger = threading.Thread(target=self.tag_loop, daemon=True)
            self.tagger.start()

    def tag_loop(self):
        """Label each request in a few words -- what it asked Orthros to do -- by asking the
        served model, only while no request is waiting for it."""
        while True:
            time.sleep(3)
            if not self.server or not self.ready or self.why or self.waiting:
                continue
            with self.lock:
                todo = next((r for r in reversed(self.recent) if not r["tag"]), None)
            if not todo:
                continue
            label = ask(self.upstream, IDENTIFIER, [
                {"role": "user", "content": TAG_ASK % todo["text"]}], max_tokens=24, timeout=90)
            label = (label.strip().splitlines() or [""])[0].strip(" \"'.*")[:80]
            with self.lock:
                todo["tag"], todo["text"] = label or "-", ""
            self.sql("UPDATE requests SET tag = ? WHERE id = ?", (todo["tag"], todo.get("id")))

    def unavailable(self, req, why=None, retry=None):
        send(req, 503, error(why or self.why or "not serving yet"),
             {"Retry-After": str(retry or self.retry)})

    # ------------------------------------------------------------ inference

    def infer(self, req, path, raw):
        """See one OpenAI-style request through to LM Studio. It ends in one of three
        ways: answered; failed, once nothing is left to try; or its caller stopped
        waiting. Never because Orthros gave up first: requests wait their turn in
        order, and a model that broke is reloaded and asked again, once."""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return send(req, 400, error("the body must be a JSON object", "invalid_request_error"))
        # Who asked what, for the page: OpenAI's `user` field names the caller, if sent.
        who, user, text, begun = req.client_address[0], body.get("user"), said(path, body), now()
        what = (excerpt(text), text[:8000])
        if self.why and not self.why.startswith("loading") or not self.server:
            self.note(who, user, what, "turned away: " + (self.why or "not serving"))
            return self.unavailable(req)
        body["model"] = IDENTIFIER
        gone, done, upstream = threading.Event(), threading.Event(), {}
        threading.Thread(target=self.watch_caller, args=(req, gone, done, upstream),
                         daemon=True).start()
        with self.lock:
            self.waiting += 1
        outcome, why, used, went = "failed", "", (0, 0), 0.0
        try:
            for attempt in (1, 2):
                turn = self.take_turn(gone)
                if turn != "go":
                    outcome, why = turn, self.why
                    break
                went = now()                  # its turn: the wait is over
                try:
                    outcome, why, used = self.forward(req, path, body, gone, upstream)
                finally:
                    self.turn.release()
                if outcome != "broken" or attempt == 2:
                    break
                # The model broke before answering: have Orthros look at it -- the
                # loop reloads a model that is gone -- then ask once more.
                checked, self.recheck = self.checked, True
                deadline = now() + 15
                while self.checked == checked and now() < deadline and not gone.is_set():
                    time.sleep(0.5)
        finally:
            done.set()
            with self.lock:
                self.waiting -= 1
        seconds = now() - begun                     # the caller's whole wait
        waited, answering = (went - begun, now() - went) if went else (seconds, 0.0)
        if outcome == "answered":
            return self.note(who, user, what, "answered", used, answering, waited)
        if outcome == "gone":
            with self.lock:
                loud, self.gave_up_at = now() - self.gave_up_at > 60, now()
            if loud:
                self.o.event("a caller from %s stopped waiting after %d s%s -- it needs a longer "
                             "timeout, or Orthros is too slow for it" % (
                                 who, seconds, ", %d s of it in the queue" % waited
                                 if waited >= 1 else ""), "bad")
            return self.note(who, user, what, "caller gave up after %d s" % seconds, (0, 0),
                             answering, waited)
        if outcome == "refused":
            self.note(who, user, what, "turned away: " + (why or "not serving"))
            return self.unavailable(req)
        # "rejected": LM Studio refused it, and the caller heard why
        self.o.event("a request from %s failed for good: %s" % (who, why), "bad")
        self.note(who, user, what, "failed: " + why, (0, 0), answering, waited)
        if outcome == "broken":           # nothing reached the caller yet: say why
            send(req, 502, error("the model failed twice: %s" % why, "server_error"))

    def watch_caller(self, req, gone, done, upstream):
        """Notice the caller hanging up -- its socket readable with nothing to read -- and
        cut the model off mid-answer, so it stops working for nobody."""
        sock = req.connection
        while not done.is_set():
            try:
                readable, _, _ = select.select([sock], [], [], 1.0)
                if readable and not sock.recv(1, socket.MSG_PEEK):
                    break
            except (OSError, ValueError):
                break
        else:
            return
        if done.is_set():
            return
        gone.set()
        conn = upstream.get("conn")
        try:
            if conn is not None and conn.sock is not None:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def take_turn(self, gone):
        """Wait for the model and for the requests ahead: 'go', 'gone' if the caller
        left first, or 'refused' if the card is taken for longer than a caller waits."""
        while True:
            if gone.is_set():
                return "gone"
            if self.why and not self.why.startswith("loading") or not self.server:
                return "refused"
            if self.ready and not self.why and self.turn.acquire(timeout=1):
                if gone.is_set():
                    self.turn.release()
                    return "gone"
                return "go"
            if not self.ready or self.why:
                time.sleep(1)

    def forward(self, req, path, body, gone, upstream):
        """One try at LM Studio: (outcome, why, (prompt tokens, answer tokens)). 'broken'
        means it failed before anything reached the caller, so it may be tried again.
        A whole answer says its usage; a stream usually does not, so its chunks are
        counted -- one is about one token -- and its prompt is estimated."""
        conn = http.client.HTTPConnection(*self.upstream, timeout=3600)
        upstream["conn"] = conn
        started = False
        try:
            conn.request("POST", path, json.dumps(body).encode("utf-8"),
                         {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
            resp = conn.getresponse()
            kind, status = resp.getheader("Content-Type") or "application/json", resp.status
            if status >= 500 or (status in (400, 404) and "text/event-stream" not in kind):
                data = resp.read()
                reason = " ".join(data.decode("utf-8", "replace").split())[:200]
                gone_model = re.search(r"model.*(not (loaded|found)|unload)|no models",
                                       reason, re.I)
                if status >= 500 or gone_model:
                    self.recheck = True
                    return "broken", "HTTP %d: %s" % (status, reason), (0, 0)
                # About this request alone -- too long for the window, say: the caller hears it.
                sent = send(req, status, data)
                return ("rejected" if sent else "gone"), "HTTP %d: %s" % (status, reason), (0, 0)
            if "text/event-stream" in kind:
                try:
                    req.send_response(status)
                    req.send_header("Content-Type", kind)
                    req.send_header("Cache-Control", "no-cache")
                    req.end_headers()
                    started = True
                except OSError:
                    return "gone", "", (0, 0)
                got, usage = 0, None
                for line in resp:
                    try:
                        req.wfile.write(line)
                        if not line.strip():
                            req.wfile.flush()
                    except OSError:
                        return "gone", "", (0, got)
                    if line.startswith(b"data:"):
                        if b'"content"' in line:
                            got += 1
                        if b'"usage"' in line:
                            usage = usage_in(line[5:]) or usage
                return "answered", "", usage or (guess_tokens(body), got)
            data = resp.read()
            if gone.is_set() or not send(req, status, data):
                return "gone", "", (0, 0)
            return "answered", "", usage_in(data) or (0, 0)
        except (OSError, http.client.HTTPException, ValueError, AttributeError) as exc:
            if gone.is_set():
                return "gone", "", (0, 0)
            self.recheck = True
            if started:                   # the model stopped mid-answer: nothing to retry
                return "failed", "the model stopped mid-answer (%s)" % exc, (0, 0)
            return "broken", "the model did not answer (%s)" % exc, (0, 0)
        finally:
            conn.close()

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
        if msg["method"] == "tools/call":
            args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            said = " ".join(str(args.get("input") or args.get("description") or "").split())
            self.note(req.client_address[0], "MCP", "tool %s%s" % (
                params.get("name"), (": " + said[:150]) if said else ""),
                "failed" if fault or (result or {}).get("isError") else "answered")
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
            tools = list(BUILT_IN) + [
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
            if name in ("research", "read_page"):
                return self.research(args, name == "read_page"), None
            if name == "python_docs":
                return self.python_docs(args.get("name")), None
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

    def building(self, folder):
        """Is a turn working in this tool's folder right now?"""
        running = (self.o.state.get("running") or {}).get("workspace") or ""
        return bool(running) and os.path.normcase(running) == os.path.normcase(folder)

    def tools(self):
        """Every tool asked for, with its list, its tests and its state."""
        limit = self.turn_limit()
        out = []
        for t in work.list_tasks(self.o.root, tool=True):
            folder = t["folder"]
            rec, brief = work.memo(
                ("tool", folder), (os.path.join(folder, RECORD), os.path.join(folder, "TASK.md")),
                lambda: (record(folder), " ".join(work.read(os.path.join(folder, "TASK.md"))
                                                  .split("\n", 1)[-1].split())))
            tests = list(rec.get("tests") or [0, 0])
            passing = bool(tests[1]) and tests[0] == tests[1] and \
                os.path.isfile(os.path.join(folder, "tool.py"))
            busy = self.building(folder)
            wanted = bool(rec) and not rec.get("done") and rec.get("turns", 0) < limit
            t.update(tests=tests, turns=rec.get("turns", 0), asked=rec.get("asked", 0),
                     wanted=wanted, brief=brief, callable=passing and not busy,
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
            if self.building(folder):
                # Its list and record are the running turn's: a rollback there
                # would quietly undo this request.
                return ("%s is being built right now. Ask again once tool_status no longer "
                        "says building." % key), True
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

    def research(self, args, page=False):
        """The agents' own web research (their research.py): a search and the top page,
        or one page -- run in a folder of its own, so it touches no agent's files."""
        question, url = str(args.get("question") or "").strip(), str(args.get("url") or "").strip()
        if page and not url.startswith(("http://", "https://")):
            return text_result("Give read_page an http(s) URL.", True)
        if not page and not question:
            return text_result("Give research a question.", True)
        script = os.path.join(self.o.folders["A"], "research.py")
        if not os.path.isfile(script):
            return text_result("The agents have no research.py to run.", True)
        where = os.path.join(self.o.root, "serve-work")
        os.makedirs(where, exist_ok=True)
        out = os.path.join(where, "research-%d.md" % threading.get_ident())
        cmd = [self.o.python_for("A"), script, "--out", out]
        cmd += ["--url", url] if page else ["--query", question] + (
            ["--site", str(args["site"])] if args.get("site") else [])
        try:
            proc = work.contained_run(cmd, 120, cwd=where, env=work.check_env(),
                                      creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return text_result("research did not finish: %s" % exc, True)
        found = work.read(out)
        try:
            os.remove(out)
        except OSError:
            pass
        if not found.strip():
            reason = ((proc.stderr or "").strip().splitlines() or ["nothing found"])[-1]
            return text_result("No answer: %s" % reason, True)
        return text_result(found[:TOOL_OUTPUT])

    def python_docs(self, name):
        name = str(name or "").strip()
        if not re.fullmatch(r"[A-Za-z_][\w.]*", name):
            return text_result("Give python_docs a module or name, e.g. json.dumps.", True)
        try:
            proc = work.contained_run([self.o.python_for("A"), "-m", "pydoc", name], 60,
                                      env=work.check_env(),
                                      creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return text_result("pydoc did not finish: %s" % exc, True)
        text = "\n".join((proc.stdout or "").splitlines()[:400])
        return text_result(text or (proc.stderr or "no documentation found"), not text)

    def catalog(self, built=None):
        """Every tool there is, for the page: what the network can call -- built in, and
        built on request (`built`, from tools()) -- and what the agents use inside their
        own turns (read from their code, which they grow)."""
        code = os.path.join(self.o.folders["A"], "ralph_tools.py")
        agents = work.memo(("agent_tools", code), (code,), lambda: [
            {"name": word.rstrip(":"), "what": " ".join(line.split(None, 1)[1:])}
            for word, line in re.findall(r'\(\s*"([A-Z]+:)",\s*"(.+?)"\)', work.read(code))])
        return {"network": [{"name": t["name"], "what": t["description"].split(". ")[0]}
                            for t in BUILT_IN],
                "built": [{"name": t["key"], "what": t["brief"][:160], "state": t["state"]}
                          for t in (self.tools() if built is None else built)],
                "agents": agents}

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
