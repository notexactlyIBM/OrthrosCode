"""The LocalCoder dashboard. Start it with GUI.bat.

A small local web server and one page: pick a project, start a run, and
watch the agents take turns -- planner, worker, checks, reviewer -- with the
live numbers, the plan, and the log. Nothing new to install: the standard
library serves it, and tkinter (which ships with Python) provides the folder
picker.

Runs it starts get their own console window, exactly as LAUNCH.bat would,
so closing that window still shuts everything down cleanly. Runs started
from LAUNCH.bat show up here too: the dashboard reads the same status file
the run writes, whoever started it.

Bound to 127.0.0.1 only. It can start programs on this machine, so it is
not something to expose to a network.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import status  # noqa: E402

PYTHON = os.path.join(HERE, "venv", "Scripts", "python.exe")
PAGE = os.path.join(HERE, "gui.html")
PREFS = os.path.join(HERE, ".localcoder-gui.json")
CREATE_NEW_CONSOLE = 0x00000010

_run = {"proc": None, "folder": None, "started": None}
_lock = threading.Lock()


# --------------------------------------------------------------------------
# settings and projects
# --------------------------------------------------------------------------

def config():
    """Every `set "NAME=value"` in config.cmd, as the run would see them."""
    try:
        body = open(os.path.join(HERE, "config.cmd"), encoding="utf-8").read()
    except OSError:
        return {}
    here = HERE + os.sep
    return {k: os.path.normpath(v.replace("%~dp0", here)) if "%~dp0" in v else v
            for k, v in re.findall(r'^set "([A-Z_][A-Z0-9_]*)=(.*)"\s*$', body, re.MULTILINE)}


def prefs():
    try:
        return json.load(open(PREFS, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(data):
    try:
        json.dump(data, open(PREFS, "w", encoding="utf-8"), indent=2)
    except OSError:
        pass


def remember(folder):
    data = prefs()
    recent = [f for f in data.get("recent", []) if f != folder]
    data["recent"] = [folder] + recent[:7]
    data["last"] = folder
    save_prefs(data)


LANGS = (("python", ".py", "*.py"), ("javascript", ".js", "*.js"),
         ("typescript", ".ts", "*.ts"))


def inspect(folder):
    """What LocalCoder would find if pointed at this folder."""
    info = {"folder": folder, "exists": os.path.isdir(folder)}
    if not info["exists"]:
        return info
    try:
        names = os.listdir(folder)
    except OSError:
        return info
    counts = {lang: sum(1 for n in names if n.endswith(ext)) for lang, ext, _ in LANGS}
    lang = max(counts, key=counts.get) if any(counts.values()) else ""
    info.update(
        counts=counts, language=lang,
        files=next((g for l, _, g in LANGS if l == lang), "*.py"),
        git=os.path.isdir(os.path.join(folder, ".git")),
        tests=any(n.startswith("test_") and n.endswith(".py") for n in names)
        or os.path.isdir(os.path.join(folder, "tests")),
        venv=os.path.isfile(os.path.join(folder, "venv", "Scripts", "python.exe")),
    )
    try:
        import ralph
        notes = ralph.find_notes_file(folder, config().get("LC_RALPH_NOTES", ""))
        info["notes"] = os.path.basename(notes) if notes else ""
        if notes:
            info["open"] = len(ralph.open_tasks(notes))
            info["done"] = ralph.done_count(notes)
    except Exception:
        info["notes"] = ""
    return info


def plan_and_history(folder):
    out = {"milestones": [], "history": []}
    try:
        import ralph
        out["milestones"] = [[t, d] for t, _, d in
                             ralph.milestones(os.path.join(folder, ralph.PLAN_FILE))]
        for row in ralph.progress_rows(os.path.join(folder, "x"), last=20):
            out["history"].append({"when": row[0], "rounds": row[1], "ticked": row[2],
                                   "lines": row[4] if len(row) > 4 else "",
                                   "tokens": row[5] if len(row) > 5 else "",
                                   "state": row[6] if len(row) > 6 else "",
                                   "review": row[7] if len(row) > 7 else ""})
    except Exception:
        pass
    return out


def log_tail(folder, lines=40):
    """The summary log, for runs that predate the status file."""
    try:
        with open(os.path.join(folder, ".localcoder-ralph.log"), encoding="utf-8",
                  errors="replace") as handle:
            body = handle.read()[-12000:]
    except OSError:
        return []
    out = []
    for line in body.splitlines()[-lines:]:
        m = re.match(r"^(\d\d:\d\d:\d\d)  (.*)$", line)
        if m:
            out.append([m.group(1), m.group(2)])
    return out


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------

def running(folder=None):
    """(alive, started_here) for this folder. A LAUNCH.bat run counts if live."""
    proc = _run["proc"]
    if proc is not None and proc.poll() is None and (not folder or folder == _run["folder"]):
        return True, True
    folder = folder or _run["folder"] or prefs().get("last")
    if folder:
        st = status.read(folder)
        fresh = time.time() - st.get("updated", 0) < 90
        if fresh and st.get("phase") not in (None, "finished", "stopped"):
            return True, False
    return False, False


def start(folder, mode, minutes):
    with _lock:
        alive, _ = running()
        if alive or running(folder)[0]:
            return False, "A run is already going."
        info = inspect(folder)
        if not info.get("exists"):
            return False, "That folder does not exist."
        env = os.environ.copy()
        env.update(config())
        env["LC_WORKSPACE"] = folder
        if info.get("files"):
            env["LC_RALPH_FILES"] = info["files"]
        args = [PYTHON, os.path.join(HERE, "supervisor.py")]
        if mode == "once":
            args.append("--once")
        elif mode == "loop":
            args += ["--loop", "--minutes", str(max(1, int(minutes)))]
        # chat: no switch -- the supervisor's default is the chat box
        try:
            os.remove(os.path.join(folder, status.STOP_FILE))
        except OSError:
            pass
        try:
            proc = subprocess.Popen(args, cwd=HERE, env=env,
                                    creationflags=CREATE_NEW_CONSOLE)
        except OSError as exc:
            return False, "Could not start: %s" % exc
        _run.update(proc=proc, folder=folder, started=time.time())
        remember(folder)
        return True, "Started."


def stop(folder, force=False):
    if not force:
        ok = status.request_stop(folder)
        return ok, ("Stopping after the current round." if ok
                    else "Could not ask it to stop.")
    proc = _run["proc"]
    if proc is not None and proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
    # A hard stop skips the run's own cleanup, which is what unloads the
    # model -- so do that here, the way STOP.bat does.
    env = os.environ.copy()
    env.update(config())
    subprocess.run([PYTHON, os.path.join(HERE, "supervisor.py"), "--stop"],
                   cwd=HERE, env=env, capture_output=True, timeout=120)
    return True, "Stopped, and the model unloaded."


def browse():
    """A native folder picker. Run apart so tkinter owns its own thread."""
    code = ("import tkinter as t, tkinter.filedialog as f\n"
            "r = t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "print(f.askdirectory(title='Choose a project for LocalCoder') or '')\n")
    try:
        out = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True,
                             timeout=600).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return os.path.normpath(out) if out else ""


def state(folder):
    folder = folder or _run["folder"] or prefs().get("last") or config().get("LC_WORKSPACE", "")
    alive, here = running(folder)
    st = status.read(folder) if folder else {}
    if not st.get("log"):
        st["log"] = log_tail(folder) if folder else []
    cfg = config()
    return {
        "running": alive, "started_here": here, "folder": folder,
        "status": st, "project": inspect(folder) if folder else {},
        "config": {k: cfg.get(k, "") for k in ("LC_MODEL_KEY", "LC_CONTEXT",
                                               "LC_RALPH_REVIEW", "LC_RALPH_MINUTES")},
        "recent": prefs().get("recent", []),
        "now": time.time(),
        **plan_and_history(folder),
    }


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))

    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path
        q = self._query()
        if route in ("/", "/index.html"):
            try:
                self._send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"gui.html is missing", "text/plain")
        elif route == "/api/state":
            self._send(200, state(q.get("folder", "")))
        elif route == "/api/inspect":
            self._send(200, inspect(q.get("folder", "")))
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        if route == "/api/start":
            ok, msg = start(body.get("folder", ""), body.get("mode", "loop"),
                            body.get("minutes", 30))
            self._send(200, {"ok": ok, "message": msg})
        elif route == "/api/stop":
            ok, msg = stop(body.get("folder", ""), bool(body.get("force")))
            self._send(200, {"ok": ok, "message": msg})
        elif route == "/api/browse":
            self._send(200, {"folder": browse()})
        else:
            self._send(404, {"error": "not found"})


def main():
    port = 8765
    for candidate in range(8765, 8785):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    else:
        print("No free port between 8765 and 8784.")
        return 1
    url = "http://127.0.0.1:%d/" % port
    print("LocalCoder dashboard: %s" % url)
    print("Leave this window open while you use it. Ctrl-C to close.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
