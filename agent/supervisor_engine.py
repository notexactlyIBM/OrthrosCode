"""LM Studio's engine: is it loaded, is it answering, is the card free, bring it back."""

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request

from supervisor_env import (BASE_URL, CONTEXT, GPU, IDENTIFIER, MODEL_KEY, PARALLEL, PORT,
    SPECULATIVE, say)
from supervisor_win import lms


def loaded_models():
    """Model ids the server currently reports, or None if it is not answering."""
    try:
        with urllib.request.urlopen(BASE_URL + "/models", timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return [m.get("id", "") for m in payload.get("data", []) if m.get("id")]
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def resident_entries():
    """Full records for the models actually held in memory.

    Deliberately not /v1/models -- with just-in-time loading switched on, that
    endpoint lists everything on disk, so it will happily claim a model is ready
    when nothing has been loaded and our context/GPU settings were never applied.
    """
    code, out = lms("ps", "--json")
    if code != 0:
        return []
    start = out.find("[")
    if start < 0:
        return []
    try:
        entries = json.loads(out[start:])
    except ValueError:
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def entry_name(entry):
    for field in ("identifier", "modelKey", "path", "displayName"):
        value = entry.get(field)
        if value:
            return str(value)
    return ""


def gpu_memory():
    """(used_MiB, total_MiB) for the first GPU, or None if we cannot tell."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        used, total = proc.stdout.strip().splitlines()[0].split(",")
        return int(used), int(total)
    except (ValueError, IndexError):
        return None


def count_processes(image):
    """How many copies of an executable are running. -1 if we cannot tell."""
    try:
        listing = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image, "/NH"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return sum(1 for line in (listing.stdout or "").splitlines()
               if image.lower() in line.lower())


def count_instances(image):
    """How many copies of an *app* are running. -1 if we cannot tell.

    Not the same as counting processes, and the difference matters enough to
    have blocked a legitimate run. LM Studio is an Electron app, and one
    Electron app is a whole family of processes sharing a name: a main
    process, a GPU process, a crash handler and a utility process per feature.
    Measured on this machine, Claude desktop was 15 processes and two windows.
    So a single LM Studio looked like five, and the shared-card check refused
    to start.

    The helpers all carry a `--type=` argument and the real ones do not, which
    is the only honest way to tell them apart from outside.
    """
    try:
        listing = subprocess.run(
            ["wmic", "process", "where", "name='%s'" % image, "get", "commandline"],
            capture_output=True, text=True, timeout=45,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    if listing.returncode != 0:
        return -1
    lines = [l.strip() for l in (listing.stdout or "").splitlines() if l.strip()]
    real = [l for l in lines[1:] if "--type=" not in l]     # drop the header
    return len(real)


def find_rivals():
    """Other things that will want this card. Returns a list of descriptions.

    Free VRAM at startup does not settle this on its own. A second LM Studio
    sitting idle shows as nothing until it loads something, and then both
    engines are on the same card and both die. On 2026-08-11 three LM Studios,
    an ollama server and bun were up together: the run made ten attempts in 48
    minutes, never completed a single round, and was killed rather than
    finishing.

    Counting the processes catches what measuring the memory cannot -- a rival
    that has not claimed anything yet, but will.
    """
    rivals = []
    # Electron apps: count windows, not processes. A negative answer means we
    # could not read the command lines, and a check that cannot see is not a
    # reason to stop someone working -- say nothing rather than guess.
    studios = count_instances("LM Studio.exe")
    if studios > 1:
        rivals.append("%d copies of LM Studio are open -- only one can have "
                      "the card" % studios)
    if count_instances("ollama app.exe") > 0 or count_processes("ollama.exe") > 0:
        rivals.append("ollama is running and loads models onto the same card")
    # Not Electron. Every one of these is a real engine holding real memory,
    # so here the raw count is the right count.
    engines = count_processes("llama-server.exe")
    if engines > 1:
        rivals.append("%d llama-server engines are running at once" % engines)
    return rivals


def check_gpu_is_free():
    """Warn if something else is already using the card.

    A 35B model wants around 20GB of a 24GB card, so it only fits on an idle
    GPU. Share the card with a game and the load either fails outright or --
    worse -- succeeds and then dies mid-session, taking the round with it and
    leaving LM Studio unable to restart its engine. Cheaper to say so now.
    """
    rivals = find_rivals()
    for rival in rivals:
        say("    !! %s" % rival)
    if rivals:
        say("       Close them before starting. Two engines on one card is")
        say("       not slow, it is a session that never finishes a round.")
        say()

    memory = gpu_memory()
    if not memory:
        return not rivals
    used, total = memory
    free = total - used
    if used < 1500 and not rivals:
        say("    GPU is idle: %.1f GB free of %.1f GB" % (free / 1024.0, total / 1024.0))
        return True
    if used < 1500:
        return False
    say()
    say("    !! Something else is using the graphics card:")
    say("       %.1f GB already taken, %.1f GB left of %.1f GB"
        % (used / 1024.0, free / 1024.0, total / 1024.0))
    say("       A game, a browser doing video, another model -- close it.")
    say("       Sharing the card is what makes the engine die mid-session.")
    say()
    return False


_MTP_SUPPORTED = None   # None = not yet known, True/False = settled for this run


TAKEN = "already exists"


def _load(args):
    """`lms load`, retried once after clearing a stale identifier.

    LM Studio can hold the registration for `localcoder` while reporting no
    resident models -- seen for real on 2026-08-06, with 20.5 GB of the card
    still occupied by a model that `lms ps` would not admit to. Every caller
    used to check residency first and skip the unload when the list came back
    empty, so the load then died on "A model with identifier localcoder
    already exists" and the session ended before it started.

    Asking whether it is loaded is the unreliable part. Trying, and clearing
    up if the name is taken, is not.
    """
    code, out = lms(*args)
    if code == 0 or TAKEN not in out.lower():
        return code == 0, out
    say("   the name '%s' was still taken - clearing it and retrying" % IDENTIFIER)
    lms("unload", "--all")
    time.sleep(3)
    code, out = lms(*args)
    return code == 0, out


def load_model_now(clear_first=False):
    """Load the configured model with our settings. Returns (ok, output).

    `clear_first` matters when recovering from a crash. The engine can die
    while LM Studio still holds the registration, and the reload then fails
    with "A model with identifier localcoder already exists" -- so the
    watchdog could never actually rescue a session. Clearing first fixes that.
    """
    if clear_first:
        lms("unload", "--all")
    base = [
        "load", MODEL_KEY,
        "--gpu", GPU,
        "-c", str(CONTEXT),
        "--parallel", str(PARALLEL),
        "--identifier", IDENTIFIER,
        "-y",
    ]

    # Multi-token prediction drafts several tokens per step and checks them in
    # one pass, which is free speed -- but only builds shipping an MTP head can
    # do it, and asking for it on a build without one fails the load outright.
    # So ask, and fall back rather than making the operator know which is which.
    #
    # It is not free in memory, though: the draft head and its own compute
    # buffers come out of the same card. LC_SPECULATIVE=0 gives that back,
    # which is the first thing to try when requests start failing with
    # `bad allocation` and you do not want to give up context to fix it.
    # Turning it off takes the explicit negative flag. Simply leaving
    # `--speculative-draft-mtp` off does NOT disable it -- LM Studio's default
    # for a model whose GGUF carries an MTP head is on, so an omitted flag
    # loads with drafting anyway. Measured 2026-08-06: a "no MTP" load still
    # logged `draft acceptance = 0.937`, which made the setting look useless
    # when it had simply never been applied.
    global _MTP_SUPPORTED
    if not SPECULATIVE:
        if _MTP_SUPPORTED is None:
            say("   speculative decoding is off (LC_SPECULATIVE=0).")
        _MTP_SUPPORTED = False
        return _load(base + ["--no-speculative-draft-mtp"])

    if _MTP_SUPPORTED is not False:
        ok, out = _load(base + ["--speculative-draft-mtp"])
        if ok:
            if _MTP_SUPPORTED is None:
                say("   speculative decoding is on (this build has an MTP head).")
            _MTP_SUPPORTED = True
            return True, out
        if "mtp" not in out.lower():
            return False, out          # a real failure, not a missing head
        if _MTP_SUPPORTED is None:
            say("   this build has no MTP head - loading without speculative decoding.")
        _MTP_SUPPORTED = False
        lms("unload", "--all")

    return _load(base)


def model_is_resident():
    """True if the model is really in memory, not merely listed on disk."""
    if not MODEL_KEY:
        return bool(resident_entries())
    key_tail = MODEL_KEY.split("/")[-1].lower()
    for entry in resident_entries():
        haystack = (str(entry.get("modelKey") or "") + entry_name(entry)).lower()
        if key_tail in haystack or entry_name(entry) == IDENTIFIER:
            return True
    return False


_revive_lock = threading.Lock()


# Set by cleanup, so the watchdog stops reviving the model we are unloading.
# An Event rather than a flag: it is set in one module and read in another.
SHUTTING_DOWN = threading.Event()


def engine_answers(seconds=25):
    """True if the engine actually replies. Not the same as being loaded.

    A wedged engine stays resident, keeps the port open, and answers nothing.
    `lms ps` lists it, `model_is_resident()` says yes, and every request comes
    back "InternalServerError: the API provider's servers are down or
    overloaded". Asking whether it is loaded cannot tell the difference; the
    only honest test is to ask it something.

    Seen 2026-08-08: revive() returned True instantly on a wedged engine
    because the model was listed, so nothing was ever restarted and the run
    spent its remaining half-hour talking to a corpse.
    """
    body = json.dumps({
        "model": IDENTIFIER,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer lm-studio"})
    try:
        with urllib.request.urlopen(req, timeout=seconds) as resp:
            return resp.status == 200
    except Exception:
        return False


def revive_model(attempts=3):
    """Bring the engine back after a crash. Returns True once it answers.

    Serialised, because two things watch for the engine dying -- the watchdog
    thread and the round loop -- and they will both notice the same corpse.
    Two `lms load` calls racing is how you get "a model with identifier
    localcoder already exists", which is the error that used to make recovery
    impossible.

    Patience is the whole trick. Measured: a reload attempted 42 seconds after
    the engine died succeeded, and one attempted 10 seconds after it died
    failed with "Engine protocol startup was aborted" and ended the session.
    LM Studio is still tearing down the old runtime in those first seconds, and
    starting a new one on top of it aborts. So wait, clear, load, and check it
    is actually there -- `lms load` returning 0 is not proof on its own.
    """
    if SHUTTING_DOWN.is_set():
        return False
    with _revive_lock:
        # Whoever was waiting may find the other one already fixed it. Being
        # listed is not evidence of that -- a wedged engine is listed too --
        # so make it prove it by answering.
        if model_is_resident() and engine_answers():
            return True
        for attempt in range(attempts):
            # Reviving a model we are about to unload just delays the exit,
            # which is what the tail of a finished run was doing.
            if SHUTTING_DOWN.is_set():
                return False
            wait = 10 + attempt * 20        # 10s, 30s, 50s
            say("   waiting %ds for LM Studio to finish falling over..." % wait)
            time.sleep(wait)
            if SHUTTING_DOWN.is_set():
                return False
            # A plain engine crash is cured by reloading the model. A wedged
            # server is not: it still accepts connections on the port but never
            # answers, and no number of `lms load` calls will shift it. That is
            # what ended the run of 2026-08-05 01:10. From the second attempt
            # on, restart the server itself before trying the model again.
            if attempt >= 1:
                say("   restarting the LM Studio server too...")
                lms("server", "stop")
                time.sleep(3)
                lms("server", "start", "-p", str(PORT))
                if not wait_for_server(45):
                    say("   the server did not come back up.")
                    continue
            lms("unload", "--all")
            ok, out = load_model_now()
            # Same test as above, for the same reason: a reload that comes back
            # wedged looks exactly like a reload that worked.
            if ok and model_is_resident() and engine_answers():
                say("   model is back, and answering.")
                return True
            say("   attempt %d of %d did not take%s"
                % (attempt + 1, attempts, ": " + out.strip()[:90] if out.strip() else ""))
    return False


def start_model_watchdog(stop_event):
    """Reload the model if LM Studio's engine dies underneath us.

    The engine can crash mid-session (exit code 3221226505) when a long
    conversation outgrows the VRAM LM Studio set aside for it. Aider then gets
    "No models loaded" for every message until something reloads it. Without
    this, that is the end of the session.
    """
    if not MODEL_KEY:
        return None

    def loop():
        failures = 0
        while not stop_event.wait(20):
            if model_is_resident():
                failures = 0
                continue
            say("")
            say("!! The model vanished - LM Studio's engine crashed.")
            say("   Bringing it back. The message that failed needs sending again.")
            if revive_model():
                failures = 0
            else:
                failures += 1
                if failures >= 3:
                    say("   Giving up after 3 rounds of trying. Close this window,")
                    say("   run STOP.bat, then LAUNCH.bat. If it keeps happening,")
                    say("   lower LC_CONTEXT in config.cmd.")
                    return
            say("")

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def report_headroom():
    """What is left on the card *after* loading. Returns free MiB or None.

    The check before loading says the card is idle, which tells you nothing
    about whether the model fits with room to work. What kills a session is
    the margin left over: llama.cpp allocates compute buffers and captures a
    CUDA graph on the fly, and if either fails the request dies with
    `bad allocation`. Seen on 2026-08-06 at 65536 context -- 36 failed
    requests, some as small as 1,304 tokens, which is memory pressure and
    nothing to do with the size of the prompt.
    """
    reading = gpu_memory()
    if not reading:
        return None
    used, total = reading
    free = total - used
    say("    VRAM after loading: %.1f GB free of %.1f GB" % (free / 1024.0, total / 1024.0))
    if free < 2048:
        say()
        say("    !! Only %.1f GB of headroom. This is the margin the engine" % (free / 1024.0))
        say("       allocates out of while it answers, and at this size it")
        say("       starts failing requests with 'bad allocation'.")
        say("       Lower LC_CONTEXT (currently %d), or set LC_SPECULATIVE=0" % CONTEXT)
        say("       to drop the draft head and get some of it back.")
        say()
    return free


def describe_entry(entry):
    """Report how the model actually came up, and flag VRAM being wasted."""
    ctx = entry.get("contextLength")
    par = entry.get("parallel")
    if ctx and par:
        say("    context %s x parallel %s = %s tokens of cache" % (ctx, par, int(ctx) * int(par)))
    if entry.get("vision"):
        say("    NOTE: the vision projector is loaded. It costs VRAM and is useless")
        say("          for coding. In LM Studio: My Models -> this model -> gear ->")
        say("          turn Vision off. That buys you context.")


def wait_for_server(seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if loaded_models() is not None:
            return True
        time.sleep(1.5)
    return False


def kill_orphan_engine():
    """Kill a llama-server that outlived the thing that was supposed to stop it.

    When the engine crashes, LM Studio's API server can go down with it, and
    `lms unload` then has nothing to talk to -- it returns an error and the
    orphan keeps every byte it had. Found one holding 21.5 GB of a 24 GB card
    long after its session ended, which is exactly the "it eats all my memory"
    complaint. Nothing else can free it, so do it by hand.
    """
    try:
        listing = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if "llama-server" not in (listing.stdout or ""):
        return
    say("  a crashed engine was still holding video memory - ending it")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
