"""Fit the settings to the machine, and keep the ones that have worked.

The shipped settings suit one machine: a 24 GB card, 32 GB of memory, a 27B
model. On a bigger machine they waste it; on a smaller one they crash. So
Orthros looks at the hardware -- but only when there is reason to:

    - there are no settings yet, or SETUP.bat has been run since the last look;
    - the operator asks (the page's "Check hardware", or `orthros.py --probe`);
    - the card itself has changed (its name or size, from the readings the
      page already takes).

Between looks, each turn's own log says how much of the card was left free
once the model loaded, and how fast it answered. From that, one step at a
time: more context when a lot of the card sits idle, less when it runs short,
longer timeouts for a slower machine. Every change is tried for one turn and
kept as the last good settings only if that turn runs clean; one that fails
to load or runs out of memory puts the last good settings back and is not
tried again. Standard library only.
"""

import ctypes
import json
import os
import re
import subprocess
import time

HARDWARE_FILE = "hardware.json"
REPROBE_FLAG = ".orthros-reprobe"        # SETUP.bat leaves this; the next start looks again
RESERVE_MB = 3072          # VRAM left free after loading: decode needs room to allocate
CONTEXT_STEPS = (16384, 24576, 32768, 49152, 65536, 98304, 131072, 196608, 262144)
OUT_OF_MEMORY = ("bad allocation", "out of memory", "failed to allocate", "cudaMalloc failed")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- looking

def gpu():
    """(name, total MiB) of the first NVIDIA card, or ('', 0)."""
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                               "--format=csv,noheader,nounits"], capture_output=True,
                              text=True, timeout=15)
        name, total = proc.stdout.strip().splitlines()[0].rsplit(",", 1)
        return name.strip(), int(float(total))
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return "", 0


def ram_mb():
    if os.name == "nt":
        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys // 1048576)
        return 0
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 1048576)
    except (ValueError, OSError, AttributeError):
        return 0


def model_facts(lms, model_key):
    """(size MiB, longest context it supports) from `lms ls --json`, or (0, 0)."""
    if not lms or not model_key:
        return 0, 0
    try:
        out = subprocess.run([lms, "ls", "--json"], capture_output=True, text=True,
                             timeout=60, encoding="utf-8", errors="replace").stdout
        entries = json.loads(out[out.find("["):])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0, 0
    tail = model_key.split("/")[-1].lower()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        names = " ".join(str(entry.get(k, "")) for k in ("modelKey", "path", "displayName"))
        if tail in names.lower():
            return (int(entry.get("sizeBytes") or 0) // 1048576,
                    int(entry.get("maxContextLength") or 0))
    return 0, 0


def probe(lms="", model_key=""):
    name, vram = gpu()
    size, longest = model_facts(lms, model_key)
    return {"when": time.time(), "gpu": name, "vram_mb": vram, "ram_mb": ram_mb(),
            "cpus": os.cpu_count() or 0, "model": model_key, "model_mb": size,
            "model_max_context": longest}


LOADED = re.compile(r"context (\d+) x parallel \d+ = \d+ tokens of cache")
HEADROOM = re.compile(r"VRAM after loading: ([\d.]+) GB free of ([\d.]+) GB")
SPEED = re.compile(r"([\d.]+) tok/sec")


def measured(log_text):
    """What a turn's log shows: {context, free_mb, total_mb, tok_per_sec}, or {}."""
    loaded, room = LOADED.findall(log_text), HEADROOM.findall(log_text)
    if not loaded or not room:
        return {}
    speeds = sorted(float(s) for s in SPEED.findall(log_text) if 0 < float(s) < 10000)
    return {"context": int(loaded[-1]), "free_mb": int(float(room[-1][0]) * 1024),
            "total_mb": int(float(room[-1][1]) * 1024),
            "tok_per_sec": speeds[len(speeds) // 2] if speeds else 0}


# ---------------------------------------------------------------- deciding

def plan(look, seen, current):
    """Settings for this machine: ({LC_...: value}, [reasons]).

    `look` is probe(); `seen` is measured() from a real turn (may be {});
    `current` the settings in use now. One step at a time, and only on what a
    turn showed: estimating the cache's cost from the model's size was tried,
    and a few hundred MB of error in the size moved the answer by 100,000
    tokens. The card's own reading after loading does not lie.
    """
    out, why = {}, []
    ctx_now = int(current.get("LC_CONTEXT") or 32768)
    longest = look.get("model_max_context") or 0
    if seen:
        free = seen["free_mb"]
        bigger = [c for c in CONTEXT_STEPS if c > ctx_now and (not longest or c <= longest)]
        smaller = [c for c in CONTEXT_STEPS if c < ctx_now]
        if free > 3 * RESERVE_MB and bigger:
            out["LC_CONTEXT"] = bigger[0]
            why.append("%.1f GB of the card was left free at %d tokens of context, so one "
                       "step up" % (free / 1024.0, ctx_now))
        elif free < RESERVE_MB // 2 and smaller:
            out["LC_CONTEXT"] = smaller[-1]
            why.append("only %.1f GB was left free at %d, so one step down"
                       % (free / 1024.0, ctx_now))
    elif look.get("vram_mb") and not current.get("LC_CONTEXT"):
        # Nothing measured yet and nothing set: a starting point by card size.
        vram = look["vram_mb"]
        out["LC_CONTEXT"] = 16384 if vram < 16000 else 32768 if vram < 40000 else 65536
        why.append("a %d GB card: starting at %d" % (vram // 1024, out["LC_CONTEXT"]))
    speed = seen.get("tok_per_sec") or 0
    if speed:
        ceiling = int(current.get("LC_RALPH_MAX_OUTPUT") or 6000)
        answer = ceiling / speed                    # seconds for the longest reply
        want = {"LC_RALPH_API_TIMEOUT": int(min(900, max(240, answer * 1.5))),
                "LC_RALPH_ITER_TIMEOUT": int(min(1800, max(420, answer * 2 + 120)))}
        for key, value in want.items():
            have = int(current.get(key) or 0)
            if not have or abs(value - have) > have * 0.25:
                out[key] = value
        if "LC_RALPH_ITER_TIMEOUT" in out:
            why.append("replies come at %.0f tok/sec, so a round gets %ds"
                       % (speed, out["LC_RALPH_ITER_TIMEOUT"]))
    return {k: v for k, v in out.items() if str(current.get(k)) != str(v)}, why


# ---------------------------------------------------------------- keeping

class Tuner:
    """hardware.json: the last look, the settings on trial, the last good ones."""

    def __init__(self, root):
        self.path = os.path.join(root, HARDWARE_FILE)
        self.flag = os.path.join(root, REPROBE_FLAG)
        self.data = read_json(self.path, {}) or {}
        self.data.setdefault("good", {})
        self.data.setdefault("trial", {})
        self.data.setdefault("look", {})

    def save(self):
        try:
            write_json(self.path, self.data)
        except OSError:
            pass

    def due(self, card=None):
        """Is there a reason to look? `card` is (name, total MiB) from telemetry."""
        if not self.data["look"] or os.path.exists(self.flag):
            return "first look" if not self.data["look"] else "setup was run"
        if card and card[0] and card[1]:
            look = self.data["look"]
            if card[0] != look.get("gpu") or abs(card[1] - (look.get("vram_mb") or 0)) > 512:
                return "the card changed (%s, %d MB)" % card
        return ""

    def look(self, lms, model_key, current, seen=None):
        """Look at the machine and put fitting settings on trial. Returns reasons."""
        self.data["look"] = probe(lms, model_key)
        try:
            os.remove(self.flag)
        except OSError:
            pass
        return self.propose(current, seen or {})

    def propose(self, current, seen):
        base = dict(current, **self.data["good"])
        settings, why = plan(self.data["look"], seen, base)
        self.data["trial"] = settings
        self.data["why"] = why
        self.save()
        return why

    def settings(self):
        """What to run with: the trial if there is one, else the last good."""
        return dict(self.data["good"], **self.data["trial"])

    def after_turn(self, log_text, launched, current):
        """Keep or drop the trial on the evidence of a turn, and propose the next
        step from what the turn measured. Returns a note, or ''. Reads the
        turn's log only -- no looking at the hardware."""
        notes = []
        trial = self.data["trial"]
        bad = any(sign in log_text.lower() for sign in OUT_OF_MEMORY)
        if not launched and "could not load" in log_text.lower():
            bad = True                       # the model did not fit at all
        if trial:
            if launched and not bad:
                self.data["good"].update(trial)
                notes.append("kept %s" % describe(trial))
            else:
                notes.append("%s did not hold (%s); back to the last good settings"
                             % (describe(trial), "out of memory" if bad else "it did not start"))
                self.data.setdefault("failed", {}).update(trial)
            self.data["trial"] = {}
        in_use = dict(current, **self.data["good"])
        if bad and not trial:
            lower = [c for c in CONTEXT_STEPS if c < int(in_use.get("LC_CONTEXT") or 32768)]
            if lower:
                self.data["trial"] = {"LC_CONTEXT": lower[-1]}
                notes.append("ran out of memory; trying %d" % lower[-1])
        elif launched and not bad:
            settings, why = plan(self.data["look"], measured(log_text), in_use)
            failed = self.data.get("failed", {})
            settings = {k: v for k, v in settings.items() if failed.get(k) != v}
            if settings:
                self.data["trial"] = settings
                self.data["why"] = why
                notes.append("next turn tries %s: %s" % (describe(settings), "; ".join(why)))
        self.save()
        return "; ".join(notes)


def describe(settings):
    return ", ".join("%s=%s" % (k, v) for k, v in sorted(settings.items()))
