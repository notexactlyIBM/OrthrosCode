"""Can this card serve two agents at once? Measure it before building it.

Running several LocalCoder workers side by side only pays if the GPU can
answer two requests at the same time -- every worker queues on the one model.
LM Studio can do that (`--parallel 2`), but it costs a second copy of the
context cache, and on this machine `--parallel 4` once crashed the load at
97%. So: load with one slot, then with two, fire realistic requests, and
report the two numbers that decide it -- VRAM left over, and total tokens per
second across both streams.

    venv\\Scripts\\python.exe bench_parallel.py

Takes about five minutes. Close other GPU users first; it refuses to start if
another model server is running.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def config_value(name, default=""):
    """Read a setting from config.cmd, so this matches what LocalCoder runs."""
    try:
        body = open(os.path.join(HERE, "config.cmd"), encoding="utf-8").read()
    except OSError:
        return default
    match = re.search(r'^set "%s=(.*)"\s*$' % re.escape(name), body, re.MULTILINE)
    return match.group(1) if match else default


for key in ("LC_MODEL_KEY", "LC_CONTEXT", "LC_WORKSPACE", "LC_PORT", "LC_GPU"):
    os.environ.setdefault(key, config_value(key))

import supervisor as S  # noqa: E402  (needs the environment above)

MODEL = S.MODEL_KEY
CONTEXT = S.CONTEXT
REPLY = 1200          # long enough to measure a steady rate, short enough to finish


def prompt():
    """The shape of a real round: a chunk of the project's source and a job."""
    parts = []
    for name in sorted(os.listdir(S.WORKSPACE)):
        if name.endswith(".py") and not name.startswith("test_"):
            parts.append("### %s\n%s" % (name, open(os.path.join(S.WORKSPACE, name),
                                                   encoding="utf-8", errors="replace").read()))
    source = "\n\n".join(parts)[:40000]          # ~10k tokens, like a working round
    return source + "\n\nReview this code. List the five most serious bugs, one line each."


def ask(text, out, index):
    body = json.dumps({
        "model": S.IDENTIFIER,
        "messages": [{"role": "user", "content": text}],
        "max_tokens": REPLY, "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(S.BASE_URL + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer lm-studio"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        got = (data.get("usage") or {}).get("completion_tokens", 0)
        out[index] = (True, got, time.time() - start, "")
    except Exception as exc:
        out[index] = (False, 0, time.time() - start, str(exc)[:120])


def run_together(text, streams):
    """Fire `streams` requests at once. Returns (results, wall seconds)."""
    out = [None] * streams
    threads = [threading.Thread(target=ask, args=(text, out, i)) for i in range(streams)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out, time.time() - start


def load(parallel):
    S.lms("unload", "--all")
    time.sleep(5)
    args = ["load", MODEL, "--gpu", S.GPU, "-c", str(CONTEXT),
            "--parallel", str(parallel), "--identifier", S.IDENTIFIER, "-y"]
    code, out = S.lms(*args)
    return code == 0, out


def free_mib():
    reading = S.gpu_memory()
    return (reading[1] - reading[0]) if reading else None


def case(parallel, text):
    print("\n--- %d slot(s) ---" % parallel, flush=True)
    ok, out = load(parallel)
    if not ok:
        print("  did not load: %s" % out.strip()[:160])
        return None
    time.sleep(3)
    free = free_mib()
    print("  VRAM free after load: %s MiB" % free, flush=True)
    run_together(text, 1)                      # warm-up, not counted
    results, wall = run_together(text, parallel)
    tokens = sum(r[1] for r in results if r and r[0])
    failed = [r[3] for r in results if r and not r[0]]
    for i, r in enumerate(results):
        print("  stream %d: %s, %d tokens in %.0fs%s"
              % (i + 1, "ok" if r[0] else "FAILED", r[1], r[2],
                 "  (%s)" % r[3] if r[3] else ""), flush=True)
    rate = tokens / wall if wall else 0
    print("  total: %.1f tok/sec across %d stream(s)" % (rate, parallel), flush=True)
    return {"parallel": parallel, "free": free, "rate": rate, "failed": failed}


def main():
    if not S.LMS:
        print("lms not found.")
        return 1
    rivals = S.find_rivals()
    if rivals:
        for r in rivals:
            print("!! %s" % r)
        print("Close them and run again.")
        return 1
    print("Model %s, context %d, reply %d tokens." % (MODEL, CONTEXT, REPLY))
    S.lms("server", "start", "-p", str(S.PORT))
    if not S.wait_for_server(60):
        print("LM Studio server did not come up.")
        return 1
    text = prompt()
    one = case(1, text)
    two = case(2, text)
    S.lms("unload", "--all")

    print("\n=== verdict ===")
    if not one:
        print("Could not load even one slot. Nothing to compare.")
        return 1
    if not two:
        print("Two slots will not load at context %d. Parallel workers are out at"
              " this setting; a second GPU or a smaller context is the way in." % CONTEXT)
        return 0
    gain = two["rate"] / one["rate"] if one["rate"] else 0
    print("One slot : %.1f tok/sec, %s MiB free" % (one["rate"], one["free"]))
    print("Two slots: %.1f tok/sec, %s MiB free  (%.2fx)" % (two["rate"], two["free"], gain))
    if two["failed"]:
        print("Two slots FAILED requests: %s" % two["failed"][0])
        print("Not safe to run two workers at this setting.")
    elif two["free"] is not None and two["free"] < 2048:
        print("Works, but under 2 GB left -- the margin where the engine dies mid-session.")
    elif gain >= 1.4:
        print("Worth building: two workers would get %.0f%% more done." % ((gain - 1) * 100))
    else:
        print("Not worth it: the second stream mostly slows the first down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
