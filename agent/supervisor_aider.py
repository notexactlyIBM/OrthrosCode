"""Everything aider is told: model settings, linter, tests, the reviewer, the command line."""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from supervisor_env import (BASE_URL, CONTEXT, EDIT_FORMAT, HERE, IDENTIFIER, MAP_TOKENS,
    PROMPT_CACHE, RALPH_API_TIMEOUT, RALPH_ARCHITECT, REVIEW_PASSES,
    RALPH_MAP_TOKENS, REASONING, TEMP_CODE, TIMEOUT, VENV_SCRIPTS,
    WORKSPACE, env_int)


RALPH_MAX_OUTPUT = env_int("LC_RALPH_MAX_OUTPUT", 8000)


TEMPERATURE = TEMP_CODE


def grow_round_output(step=2000):
    """Raise the reply ceiling after a reply was cut off with room to spare.

    The opposite case to shrinking, and it needs the opposite cure. Measured
    2026-08-06: three review rounds "hit a token limit" at 42%, 59% and 59% of
    a 32,768 window -- nowhere near full. What they hit was our own ceiling.
    Lowering it, which is what the code did, made the next two fail sooner.

    This model reasons at length before it answers, and the ceiling covers the
    reasoning as well as the answer. One review round spent 2,900 tokens
    thinking against a 3,000 ceiling and had a hundred left to reply with.

    Capped by what aider will accept for the model, so this cannot climb into
    the window itself.
    """
    global RALPH_MAX_OUTPUT
    limit = max(2048, min(16384, CONTEXT // 4))
    if RALPH_MAX_OUTPUT >= limit:
        return RALPH_MAX_OUTPUT
    RALPH_MAX_OUTPUT = min(limit, RALPH_MAX_OUTPUT + step)
    write_model_settings()
    return RALPH_MAX_OUTPUT


def shrink_round_output(floor=3000):
    """Halve the reply ceiling after a round overflowed the context window.

    Without this, an overflowing round simply repeats: the same item, the same
    files, the same runaway reply, until the clock runs out. The log calls
    overflow "the single thing most likely to stop unattended work on this rig"
    and then does nothing about it. Cutting the ceiling makes the next round
    fit, at the cost of shorter answers -- which is the right trade at 3am.

    The floor matters more than it looks. It was 1500, which is below what a
    real edit needs -- measured at ~2,700 for a successful round -- so once the
    ceiling dropped that far every reply was truncated, every truncation read
    as another overflow, and the run cut itself to death. 3000 is the smallest
    ceiling that can still hold a working answer.

    Returns the new ceiling.
    """
    global RALPH_MAX_OUTPUT
    if RALPH_MAX_OUTPUT <= floor:
        return RALPH_MAX_OUTPUT
    RALPH_MAX_OUTPUT = max(floor, RALPH_MAX_OUTPUT // 2)
    write_model_settings()
    return RALPH_MAX_OUTPUT


def write_model_metadata(model_id):
    """Tell aider the real context size, so it stops guessing 8k and truncating."""
    path = os.path.join(HERE, ".localcoder.model.json")
    meta = {
        "openai/" + model_id: {
            "max_input_tokens": CONTEXT,
            "max_output_tokens": max(2048, min(16384, CONTEXT // 4)),
            "input_cost_per_token": 0,
            "output_cost_per_token": 0,
            "litellm_provider": "openai",
            "mode": "chat",
        }
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    return path


def set_temperature(value):
    """Rewrite the settings file for a different kind of round. Returns it.

    Editing code and thinking up work want opposite things from the same
    model. A diff has exactly one correct form -- every degree of freedom is
    another chance the SEARCH block does not match the file -- while a round
    asked for the next ten things to build wants range, and at a low
    temperature returns the same safe four ideas it returned last time.

    One number, set per round type: cold to write code, warm to invent work.
    """
    global TEMPERATURE
    TEMPERATURE = value
    return write_model_settings()


def write_model_settings():
    """Put a hard ceiling on how much the model may say in one reply.

    aider never sends max_tokens itself, so nothing stops this model talking
    until the context window is full -- measured at 21,278 output tokens
    against a nominal 8,192 limit, which exhausts the window, loses the round
    and can take the engine down with it. A successful round's reply is around
    2,700 tokens, so this is roughly twice what good work needs and a fraction
    of what a runaway one takes.

    The magic name `aider/extra_params` is merged into whatever model is in
    use, which saves knowing the model id here.
    """
    path = os.path.join(HERE, ".localcoder.settings.yml")
    body = (
        "# Written by LocalCoder. Reply length and temperature for this round.\n"
        "- name: aider/extra_params\n"
        "  extra_params:\n"
        "    max_tokens: %d\n"
        "    temperature: %.2f\n" % (RALPH_MAX_OUTPUT, TEMPERATURE)
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def find_linter():
    """A real linter, if the machine has one. Returns an aider --lint-cmd.

    aider lints after every edit already, with its own parser, and that only
    catches code that will not parse. A linter catches the tier above: a name
    used and never defined, an import left behind by a change, a variable
    assigned and never read. Those are exactly the mistakes a small model
    makes when it edits one function without seeing the rest of the file.

    The win is where it happens. aider feeds the output back to the model
    within the same round, so the fix costs nothing extra -- no round, no
    context, no tokens beyond the error text. Free, local, and already
    installed on this machine.

    Only the F rules: real errors. Style rules would fill the reply with
    line-length complaints and teach it to spend its budget on whitespace.
    """
    # Run as `python -m`, never through the .exe launchers pip writes into
    # venv\Scripts: those hard-code the path the venv was created at, and a
    # venv that has been copied or moved -- every OrthrosCode one -- points
    # them at an interpreter that no longer exists.
    python = venv_python()
    for name in ("ruff", "flake8"):
        if not module_available(python, name):
            continue
        if name == "ruff":
            return "python: \"%s\" -m ruff check --select F --quiet" % python
        return "python: \"%s\" -m flake8 --select=F --max-line-length=200" % python
    return ""


def venv_python():
    """LocalCoder's own interpreter: the venv's if it has one, else this one."""
    path = os.path.join(VENV_SCRIPTS, "python.exe")
    return path if os.path.isfile(path) else sys.executable


def module_available(python, module):
    """True if `python -m <module>` would find it. Checked without running it."""
    try:
        proc = subprocess.run([python, "-c", "import importlib.util, sys; "
                               "sys.exit(0 if importlib.util.find_spec(%r) else 1)" % module],
                              capture_output=True, timeout=60)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


REVIEW_PROMPT = """You are reviewing one change made by another developer. You did not write it
and you have no reason to defend it.

The task they were given:

    %s

The change they made (git diff):

%s

Decide whether to keep this change.

REJECT if any of these is true:
- It does not do what the task asked, or does only part of it.
- It is cut off: an unfinished function, an unclosed bracket, code that stops mid-line.
- It uses a name, method or attribute the diff does not define and that is unlikely to exist.
- It reads something before it is assigned.
- It breaks or contradicts nearby code it did not mean to touch.
- It changes things the task did not ask for.
- The task says `Done when:` and the change does not meet that check.

Otherwise ACCEPT. Do not reject for style or taste.

Reply in exactly two lines:
VERDICT: ACCEPT or REJECT
REASON: one sentence
"""


BUG_HUNT = """Another developer made this change for this task:

    %s

%s

Assume it has a bug, and look for it line by line: a wrong condition, an
off-by-one, a case the task asks for that is not handled, a name used before it
exists, a call with the wrong arguments, code cut off or left unfinished,
something removed that other code still needs.

Reply in exactly one line:
BUG: <the line, and what is wrong with it>
or, only if after careful reading there is truly none:
NONE
"""

CONFIRM = """A change was made for this task:

    %s

%s

A second reader claims it has this bug:

    %s

Read the code the claim points at. Is the claim right -- a real fault, not a
matter of style?

Reply in exactly two lines:
VERDICT: ACCEPT (the claim is wrong, keep the change) or REJECT (the claim is right)
REASON: one sentence
"""


def _chat(prompt, max_tokens, timeout, temperature=0.1):
    """(answer and reasoning text, finish reason), or (None, error)."""
    body = json.dumps({
        "model": IDENTIFIER,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer lm-studio"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return None, type(exc).__name__
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    # Thinking models put the answer in content and the working in
    # reasoning_content; look in both, answer first.
    return ((message.get("content") or "") + "\n" + (message.get("reasoning_content") or ""),
            choice.get("finish_reason"))


def _verdict(prompt, timeout):
    """('accept'|'reject'|'', reason) from a two-line VERDICT/REASON reply.

    This model thinks before it answers, out of the same budget: when the
    thinking uses it up there is no verdict, so one retry with twice the room.
    """
    reason = ""
    for budget in (3000, 6000):
        text, finish = _chat(prompt, budget, timeout)
        if text is None:
            return "", "review request failed: %s" % finish
        verdict = re.search(r"VERDICT:\s*(ACCEPT|REJECT)", text, re.I)
        found = re.search(r"REASON:\s*(.+)", text, re.I)
        if verdict:
            return verdict.group(1).lower(), (found.group(1).strip() if found else "")
        reason = ("it ran out of room before answering" if finish == "length"
                  else "its reply had no VERDICT line")
        if finish != "length":
            break
    return "", reason


def review_change(task, diff, timeout=300, notes=()):
    """A second agent's verdict on one round's change. Returns (verdict, reason).

    verdict is "accept", "reject", or "" when no clear answer came back -- in
    which case the change is kept. Losing good work because the reviewer
    timed out is a worse failure than keeping one unreviewed change.

    Deliberately not an aider round: it gets the diff and the task and nothing
    else, cannot edit a file, and starts with an empty head. Cold, because a
    verdict should not vary with sampling. `notes` are what the automatic
    checks noticed but did not reject on; the reviewer weighs them.

    When the plain review keeps a change, a second read looks for the bug on
    the assumption there is one -- a different question gets a different
    answer from the same model. A bug it names is put to a third, neutral read
    before the change is thrown away, so one false alarm cannot cost a round.
    """
    if not diff.strip():
        return "", "nothing to review"
    seen = ""
    if notes:
        seen = ("\nThe automatic checks noticed (not errors by themselves, but look):\n"
                + "\n".join("- %s" % n for n in notes[:6]) + "\n")
    verdict, reason = _verdict(REVIEW_PROMPT % (task, diff) + seen, timeout)
    if verdict != "accept" or REVIEW_PASSES < 2:
        return verdict, reason
    text, _ = _chat(BUG_HUNT % (task, diff), 3000, timeout)
    bug = re.search(r"BUG:\s*(.+)", text or "")
    if not bug or len(bug.group(1).strip()) < 20:
        return verdict, reason
    claim = bug.group(1).strip()[:300]
    second, why = _verdict(CONFIRM % (task, diff, claim), timeout)
    if second == "reject":
        return "reject", "a second look found: %s" % (why or claim)[:200]
    return verdict, reason


THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def ask_model(prompt, max_tokens=2500, temperature=0.2, timeout=300):
    """One plain request to the loaded model, for the loop's own small jobs.

    Finding the files an item needs, a module's gist, a part of a long file:
    each is a question with a short answer, not a round of editing. Returns
    the answer text, or '' -- the callers all have a way on without it. A
    prompt the window cannot hold is not sent at all.
    """
    if len(prompt) // 4 > CONTEXT * 0.8:
        return ""
    body = json.dumps({
        "model": IDENTIFIER,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer lm-studio"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    message = ((data.get("choices") or [{}])[0].get("message") or {})
    return THINKING.sub("", message.get("content") or "").strip()


def find_test_cmd():
    """A command that runs the project's tests, if it has any. Else ''.

    The strongest check there is, and until now unused: aider will run it after
    every edit and hand failures straight back to the model inside the same
    round, so a change that breaks something gets fixed before the round ends
    rather than discovered three rounds later. Same mechanism as the linter,
    but it checks what the code *does*, not only how it is written.

    Only switched on when there is something to run -- a test_*.py or a tests
    folder -- and a pytest the project's own interpreter can import. The
    project's interpreter, not LocalCoder's, because tests need the project's
    libraries.
    """
    try:
        names = os.listdir(WORKSPACE)
    except OSError:
        return ""
    has_tests = any(n.startswith("test_") and n.endswith(".py") for n in names) \
        or os.path.isdir(os.path.join(WORKSPACE, "tests"))
    if not has_tests:
        return ""
    python = os.path.join(WORKSPACE, "venv", "Scripts", "python.exe")
    if not os.path.isfile(python):
        python = sys.executable
    if module_available(python, "pytest"):
        return "\"%s\" -m pytest -q -x --no-header -p no:cacheprovider" % python
    # No pytest, and an unattended round cannot install one -- but unittest
    # ships with Python and runs the same test_*.py files, as long as they
    # are written as unittest.TestCase classes.
    return "\"%s\" -m unittest discover -s . -p \"test_*.py\" -q" % python


NOBROWSER_FILE = ".localcoder-nobrowser.bat"


def write_nobrowser():
    """A browser that isn't one. Returns its path.

    `BROWSER` has to name an executable, not a command line. It was set to
    "cmd /c rem", which Python's webbrowser dutifully tried to run as a file
    called `cmd /c rem`; that raised FileNotFoundError, webbrowser swallowed it
    and moved on to the next entry -- `windows-default` -- and opened the page
    in the operator's real browser. Every time. The suppression had never
    worked, and the token-limit page has been opening itself for as long as
    there have been token limits.

    A batch file that exits 0 is the whole fix: webbrowser takes the first
    entry that succeeds and stops there.
    """
    path = os.path.join(HERE, NOBROWSER_FILE)
    try:
        with open(path, "w", encoding="ascii", newline="\r\n") as handle:
            handle.write("@rem LocalCoder: swallow aider's offers to open help pages.\r\n")
            handle.write("@exit /b 0\r\n")
    except OSError:
        return ""
    return path


def build_aider_command(model_id, metadata_path, use_git, ui, loop_mode=False, prompt_path=None):
    # `python -m aider`, not aider.exe: see find_linter for why the .exe
    # launchers cannot be trusted in a venv that has been moved.
    python = venv_python()
    if not module_available(python, "aider"):
        return None
    cmd = [
        python, "-m", "aider",
        "--model", "openai/" + model_id,
        "--model-metadata-file", metadata_path,
        "--edit-format", EDIT_FORMAT,
        # An unattended round names the files it wants outright, so the repo
        # map is mostly dead weight -- and on a 32k window every token it eats
        # is a token the reply cannot have.
        "--map-tokens", str(RALPH_MAP_TOKENS if loop_mode else MAP_TOKENS),
        # Unattended rounds get a much shorter leash. A dead engine does not
        # close the connection, so this number *is* how long a corpse costs.
        "--timeout", str(RALPH_API_TIMEOUT if loop_mode else TIMEOUT),
        "--no-show-model-warnings",
        "--no-check-update",
    ]
    if loop_mode:
        cmd += ["--model-settings-file", write_model_settings()]
        linter = find_linter()
        if linter:
            cmd += ["--lint-cmd", linter]
        tests = find_test_cmd()
        if tests:
            cmd += ["--test-cmd", tests, "--auto-test"]
        # This model reasons at length before it answers, and the reasoning
        # comes out of the same reply budget as the edit -- one review round
        # spent 2,900 tokens thinking against a 3,000 ceiling. If the build
        # honours the parameter this is the only lever that reaches it;
        # telling it to be brief in the prompt does not, and never has.
        if REASONING:
            cmd += ["--reasoning-effort", REASONING]
        # An unattended round answers yes to everything. aider offers to fetch
        # any URL it spots in the text it is given, and the task list is full
        # of prose -- so one pasted link becomes a silent web fetch injected
        # into a context window that has no room for it.
        cmd.append("--no-detect-urls")
        # Unattended, `--yes-always` would also say yes to any shell command
        # the model suggests -- pip installs, deletes, anything -- in a folder
        # nobody is watching. Edits only.
        cmd.append("--no-suggest-shell-commands")
        # Read the round's prompt from a file instead of waiting for an
        # interactive message: the ralph loop writes the composed prompt
        # there before each aider invocation.
        if prompt_path:
            cmd += ["--message-file", prompt_path]
        if RALPH_ARCHITECT:
            # Propose then apply, as two passes. More reliable on weak
            # models by aider's own account, at the cost of doubling the
            # requests -- which is why it is off unless asked for.
            cmd.append("--architect")
    cmd += [
        "--analytics-disable",
        "--dark-mode",
    ]
    # Off because it does nothing against this endpoint: aider's prompt
    # caching is an Anthropic/DeepSeek API feature, and litellm has nothing
    # to send for an OpenAI-compatible local server.
    #
    # It is NOT the cure for the engine crash, though it looks like a
    # candidate. LM Studio keeps a prompt cache of its own -- a ~2 GB
    # snapshot after every request, out of the same card the model sits on --
    # and when that allocation fails the engine goes down:
    #
    #   E srv alloc: failed to allocate memory for prompt cache state:
    #                bad allocation
    #   W srv alloc:  - cache size limit reduced to 0.000 MiB
    #
    # Tested 2026-08-06 with this flag off: the crash happened anyway, at
    # 13:12:52, same signature. LM Studio's cache is its own and answers to
    # nothing aider sends. What it does do is give up after failing once and
    # skip the snapshot from then on, which is why a session crashes twice
    # early and then runs clean for the rest of its life.
    if PROMPT_CACHE:
        cmd.append("--cache-prompts")
    if use_git:
        # Keep git history intact but never commit behind the operator's back.
        cmd.append("--no-auto-commits")
        if loop_mode:
            # Unattended runs say yes to everything, which would otherwise let
            # aider commit whatever it found already uncommitted in the folder.
            # LocalCoder does its own committing, and only in folders it made.
            cmd.append("--no-dirty-commits")
    else:
        # Without this, a folder that is not a committed repo gives aider an
        # empty file list and the file picker has nothing in it. Only ever
        # reached in terminal mode -- the browser UI cannot run without git.
        cmd.append("--no-git")
    if ui == "browser":
        cmd.append("--gui")
    return cmd
