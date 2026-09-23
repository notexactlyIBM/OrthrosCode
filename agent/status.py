"""What LocalCoder is doing right now, in a file anything can read.

The console tells a person sitting in front of it. The dashboard, a script,
or a second look at a run that is still going need the same thing without
scraping text, so every phase change, counter and log line also lands here:
one small JSON document in the workspace, rewritten atomically so a reader
never sees half of it.

Cheap enough to call on every event. Never raises -- a status file that
cannot be written must not be the thing that stops a run.
"""

import json
import os
import threading
import time

STATUS_FILE = ".localcoder-status.json"
STOP_FILE = ".localcoder-stop"
RECENT = 80

_lock = threading.Lock()
_state = {}
_path = None


def attach(workspace):
    """Say where the status file lives. Clears the last session's."""
    global _path
    with _lock:
        _path = os.path.join(workspace, STATUS_FILE)
        _state.clear()
        _state.update({"started": time.time(), "log": [], "pid": os.getpid()})
    _write()


def update(**fields):
    with _lock:
        _state.update(fields)
        _state["updated"] = time.time()
    _write()


def phase(name, detail=""):
    """The one-word answer to "what is it doing": working, reviewing..."""
    update(phase=name, detail=detail, phase_since=time.time())


def log(line):
    with _lock:
        entries = _state.setdefault("log", [])
        entries.append([time.strftime("%H:%M:%S"), line])
        del entries[:-RECENT]
        _state["updated"] = time.time()
    _write()


def bump(name, by=1):
    with _lock:
        _state[name] = _state.get(name, 0) + by
        _state["updated"] = time.time()
    _write()


def stop_requested(workspace):
    """True once, if someone asked for the run to stop. Clears the request."""
    path = os.path.join(workspace, STOP_FILE)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
        return True
    return False


def request_stop(workspace):
    try:
        with open(os.path.join(workspace, STOP_FILE), "w") as handle:
            handle.write(str(time.time()))
        return True
    except OSError:
        return False


def read(workspace):
    try:
        with open(os.path.join(workspace, STATUS_FILE), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _write():
    if not _path:
        return
    with _lock:
        body = json.dumps(_state)
    tmp = _path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(tmp, _path)
    except OSError:
        pass
