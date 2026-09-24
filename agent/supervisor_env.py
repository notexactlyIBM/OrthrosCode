"""Settings from config.cmd, and the console helpers everything prints with."""

import os
import sys

import status


HERE = os.path.dirname(os.path.abspath(__file__))


# Same reasoning as ralph.py: never let an unprintable character end a run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def say(msg=""):
    print(msg, flush=True)


def step(n, msg):
    say("[%s] %s" % (n, msg))
    status.phase("starting", msg)
    status.log("[%s] %s" % (n, msg))


def fail(msg):
    say()
    say("!! " + msg)
    say()


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_int(name, default):
    try:
        return int(env(name) or default)
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(env(name) or default)
    except ValueError:
        return default


def env_flag(name, default=True):
    raw = env(name)
    if not raw:
        return default
    return raw not in ("0", "no", "false", "off")


WORKSPACE = os.path.normpath(env("LC_WORKSPACE") or os.path.join(HERE, "workspace"))


MODEL_KEY = env("LC_MODEL_KEY")


CONTEXT = env_int("LC_CONTEXT", 32768)


GPU = env("LC_GPU") or "max"


PARALLEL = max(1, env_int("LC_PARALLEL", 1))


SPECULATIVE = env_flag("LC_SPECULATIVE", True)


PROMPT_CACHE = env_flag("LC_PROMPT_CACHE", False)


PORT = env_int("LC_PORT", 1234)


UI = (env("LC_UI") or "browser").lower()


EDIT_FORMAT = env("LC_EDIT_FORMAT") or "diff"


MAP_TOKENS = env_int("LC_MAP_TOKENS", 2048)


INIT_GIT = env_flag("LC_INIT_GIT", False)


UNLOAD_ON_EXIT = env_flag("LC_UNLOAD_ON_EXIT", True)


STOP_SERVER_ON_EXIT = env_flag("LC_STOP_SERVER_ON_EXIT", True)


TIMEOUT = env_int("LC_TIMEOUT", 900)


# --- unattended mode (RALPH.bat) ---
RALPH_NOTES = env("LC_RALPH_NOTES")


RALPH_FILES = [f.strip() for f in env("LC_RALPH_FILES").split(";") if f.strip()]


RALPH_MINUTES = env_int("LC_RALPH_MINUTES", 30)


RALPH_ITER_TIMEOUT = env_int("LC_RALPH_ITER_TIMEOUT", 420)


RALPH_MAP_TOKENS = env_int("LC_RALPH_MAP_TOKENS", 0)


RALPH_API_TIMEOUT = env_int("LC_RALPH_API_TIMEOUT", 240)


RALPH_RUN = env("LC_RALPH_RUN")


RALPH_RUN_SECONDS = env_int("LC_RALPH_RUN_SECONDS", 6)


# Cold for code, warm for thinking up work. Set per round, not per session.
TEMP_CODE = env_float("LC_TEMP_CODE", 0.2)


TEMP_BRAINSTORM = env_float("LC_TEMP_BRAINSTORM", 0.85)


RALPH_ARCHITECT = env_flag("LC_RALPH_ARCHITECT", False)


# "low" / "medium" / "high", or blank to leave it unset.
REASONING = env("LC_RALPH_REASONING")


# An override for someone who has measured that their setup fits.
SHARE_GPU = env_flag("LC_SHARE_GPU", False)


# A second agent reviews every change before it is kept. Slower, better.
REVIEW = env_flag("LC_RALPH_REVIEW", True)


# After the reviewer keeps a change, a second, adversarial read that hunts for
# the bug. 1 = the plain review only.
REVIEW_PASSES = max(1, env_int("LC_RALPH_REVIEWS", 2))


IDENTIFIER = "localcoder"


BASE_URL = "http://127.0.0.1:%d/v1" % PORT


VENV_SCRIPTS = os.path.join(HERE, "venv", "Scripts")
