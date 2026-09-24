"""LocalCoder supervisor.

Brings up the whole local coding stack in the right order and, more importantly,
tears all of it down again when this window closes -- including on a hard click
of the X button, which normally leaves orphaned servers running.

Order of operations:
    1. Put ourselves in a Windows Job Object that kills its children on close.
    2. Start the LM Studio HTTP server.
    3. Load the configured model (skipped if it is already loaded).
    4. Write an aider metadata file so aider knows the real context size.
    5. Launch aider pointed at the local server, and wait.
    6. On exit: unload the model, stop the server, kill any stragglers.

Everything is configured through environment variables set by config.cmd.

Split by job, each part small enough for one round of the model to read:
    supervisor_env.py     settings and console helpers
    supervisor_win.py     the job object and lms.exe
    supervisor_engine.py  LM Studio's engine: load, probe, revive, watch
    supervisor_git.py     the workspace's git history
    supervisor_aider.py   aider's settings, the reviewer, the command line
This file is the entry point: start-up order, shutdown, and main().
"""

import atexit
import ctypes
import glob
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

import status

from supervisor_env import (BASE_URL, CONTEXT, IDENTIFIER, INIT_GIT, MODEL_KEY, PARALLEL,
    PORT, RALPH_FILES, RALPH_ITER_TIMEOUT, RALPH_MINUTES,
    RALPH_NOTES, RALPH_RUN, RALPH_RUN_SECONDS, REVIEW, SHARE_GPU,
    STOP_SERVER_ON_EXIT, TEMP_BRAINSTORM, TEMP_CODE, UI,
    UNLOAD_ON_EXIT, VENV_SCRIPTS, WORKSPACE, fail, say, step)
from supervisor_win import LMS, install_job_object, kernel32, lms
from supervisor_engine import (SHUTTING_DOWN, check_gpu_is_free, describe_entry, entry_name,
    gpu_memory, kill_orphan_engine, load_model_now, loaded_models,
    report_headroom, resident_entries, revive_model,
    start_model_watchdog, wait_for_server)
from supervisor_git import (commit_everything, discard_uncommitted, ensure_git_repo,
    is_managed, snapshot_workspace, workspace_file_count,
    workspace_is_usable_git_repo)
from supervisor_aider import (ask_model, build_aider_command, grow_round_output, review_change,
    set_temperature, shrink_round_output, write_model_metadata,
    write_nobrowser)


# Catch the console X button / logoff, which do not raise KeyboardInterrupt.
PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)


def _console_ctrl_handler(event):
    cleanup()
    return False  # fall through to default handling, which ends the process


_ctrl_handler_ref = PHANDLER_ROUTINE(_console_ctrl_handler)


_cleaned = False


def cleanup():
    global _cleaned
    if _cleaned:
        return
    SHUTTING_DOWN.set()   # stop the watchdog reviving what we are unloading
    _cleaned = True
    say()
    say("Shutting down...")
    if status.read(WORKSPACE).get("phase") != "finished":
        status.phase("stopped", "shut down")
    if UNLOAD_ON_EXIT and LMS:
        lms("unload", "--all")
        say("  model unloaded from VRAM")
    if STOP_SERVER_ON_EXIT and LMS:
        lms("server", "stop")
        say("  LM Studio server stopped")
    kill_orphan_engine()
    say("Done.")


def smoke_test(model_id):
    """Send one tiny completion so we know the whole chain really answers."""
    say("    sending a test message to the model...")
    # Give it real headroom: this family thinks before it answers, and a small
    # token budget gets spent entirely on reasoning, returning empty content.
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
        "max_tokens": 512,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        elapsed = time.time() - started
        message = payload["choices"][0]["message"]
        reply = (message.get("content") or "").strip()
        thinking = (message.get("reasoning_content") or message.get("reasoning") or "").strip()
        usage = payload.get("usage") or {}
        produced = int(usage.get("completion_tokens") or 0)

        if produced and elapsed > 0:
            say("    %d tokens in %.1fs = %.1f tokens/sec" % (produced, elapsed, produced / elapsed))
        else:
            say("    replied in %.1fs" % elapsed)

        if reply:
            say("    answer: %r" % reply[:80])
            return True
        if thinking:
            say("    the model produced only reasoning, no answer.")
            say("    It is alive, but it thinks too long for short questions.")
            return True
        fail("The model returned an empty response.")
        return False
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TimeoutError) as exc:
        fail("The model did not answer: %s" % exc)
        return False


def list_models():
    """Print the model keys on disk, for pasting into config.cmd."""
    if not LMS:
        fail("Could not find LM Studio's lms.exe.\n"
             "   Set LC_LMS_PATH in config.cmd to its full path.")
        return 2
    say("Models on disk:")
    say()
    code, out = lms("ls", "--llm")
    say(out.strip() or "(none found -- download one in LM Studio first)")
    say()
    say("Copy a model key into LC_MODEL_KEY in config.cmd.")
    return 0 if code == 0 else 1


def ralph_edit_files():
    """The files unattended rounds may edit: LC_RALPH_FILES, globs expanded.

    Globs allowed, so `*.py` keeps working as one file becomes several.
    Splitting a project into modules is the one move that buys back context as
    it grows -- ralph sends only the files an item names -- and it should not
    also require editing config.cmd before the next run.
    """
    found = []
    for name in RALPH_FILES:
        path = name if os.path.isabs(name) else os.path.join(WORKSPACE, name)
        matches = sorted(glob.glob(path)) if any(c in name for c in "*?[") else [path]
        found += [m for m in matches if m not in found]
    return found


def main():
    if "--list" in sys.argv:
        return list_models()

    if "--stop" in sys.argv:
        if not LMS:
            # Still worth continuing: a stranded engine holding the whole card
            # is the one thing STOP.bat is really for, and killing it needs no
            # help from the lms CLI.
            fail("Could not find LM Studio's lms.exe - freeing memory anyway.")
            kill_orphan_engine()
            return 2
        cleanup()
        return 0

    check_only = "--check" in sys.argv

    # Unattended mode: re-feed one prompt until the task list is done or the
    # clock runs out, instead of opening a chat box and waiting for typing.
    single_shot = "--once" in sys.argv
    loop_mode = single_shot or "--loop" in sys.argv
    minutes = RALPH_MINUTES
    if "--minutes" in sys.argv:
        try:
            minutes = max(1, int(sys.argv[sys.argv.index("--minutes") + 1]))
        except (IndexError, ValueError):
            pass

    install_job_object()
    kernel32.SetConsoleCtrlHandler(_ctrl_handler_ref, True)
    atexit.register(cleanup)

    if os.path.isdir(WORKSPACE):
        status.attach(WORKSPACE)
        status.update(model=MODEL_KEY or "(already loaded)", context=CONTEXT,
                      mode=("one item" if single_shot else
                            "work the list" if loop_mode else "chat"),
                      minutes=minutes if loop_mode else None,
                      review=REVIEW, workspace=WORKSPACE, pid=os.getpid(),
                      started=time.time(),
                      # Set by Orthros, so it can tell this session's status
                      # file from one left by an earlier session.
                      session=os.environ.get("ORTHROS_SESSION", ""))
        status.phase("starting", "bringing up LM Studio")

    say("=" * 62)
    say("  LocalCoder")
    say("=" * 62)
    say("  workspace : %s" % WORKSPACE)
    say("  model     : %s" % (MODEL_KEY or "(whatever is already loaded)"))
    say("  context   : %d tokens" % CONTEXT)
    if single_shot:
        say("  mode      : one run, then stop")
    elif loop_mode:
        say("  mode      : unattended, up to %d minutes" % minutes)
    else:
        say("  chat box  : %s" % UI)
    say("=" * 62)
    say()

    if not os.path.isdir(WORKSPACE):
        fail("Workspace folder does not exist:\n   %s\n"
             "   Edit LC_WORKSPACE in config.cmd." % WORKSPACE)
        return 2

    if not LMS:
        fail("Could not find LM Studio's lms.exe.\n"
             "   Set LC_LMS_PATH in config.cmd to its full path.")
        return 2

    step(1, "Starting LM Studio server on port %d..." % PORT)
    lms("server", "start", "-p", str(PORT))
    if not wait_for_server(60):
        fail("The LM Studio server never came up.\n"
             "   Open LM Studio, go to the Developer tab, and start the server by hand.")
        return 3
    say("    server is up at %s" % BASE_URL)

    step(2, "Checking what is actually loaded in memory...")
    entries = resident_entries()
    key_tail = MODEL_KEY.split("/")[-1].lower() if MODEL_KEY else ""

    if MODEL_KEY:
        match = next((e for e in entries if key_tail in entry_name(e).lower()), None)

        # A model loaded by hand in the LM Studio window may be using settings
        # that do not match config.cmd -- most importantly a parallel count above
        # 1, which quietly multiplies the memory the context costs.
        if match is not None:
            mismatch = []
            ctx_now = int(match.get("contextLength") or 0)
            par_now = int(match.get("parallel") or 0)
            if ctx_now and ctx_now != CONTEXT:
                mismatch.append("context is %d, config says %d" % (ctx_now, CONTEXT))
            if par_now and par_now != PARALLEL:
                mismatch.append("parallel is %d, config says %d" % (par_now, PARALLEL))
            if mismatch:
                for line in mismatch:
                    say("    wrong settings: %s" % line)
                say("    reloading it properly")
                lms("unload", "--all")
                match = None
            else:
                say("    already loaded with the right settings")
                describe_entry(match)

        if match is None:
            if resident_entries():
                say("    unloading what is there to free VRAM")
                lms("unload", "--all")
            # The answer was being thrown away: it warned about a contested
            # card and then loaded onto it regardless. Nobody is reading the
            # warning during an unattended run, which is precisely the run
            # that cannot survive losing the card halfway through -- so that
            # one stops here instead of spending an hour finding out.
            if not check_gpu_is_free() and loop_mode and not SHARE_GPU:
                fail("Not starting an unattended run while the card is shared.\n"
                     "   Close the other model servers and try again, or set\n"
                     "   LC_SHARE_GPU=1 if you have measured that it fits.")
                return 4
            say("    loading %s" % MODEL_KEY)
            say("    context %d x parallel %d = %d tokens of cache to allocate"
                % (CONTEXT, PARALLEL, CONTEXT * PARALLEL))
            say("    (takes a minute or two and prints nothing - be patient)")
            ok, out = load_model_now()
            if not ok:
                fail("Could not load '%s'.\n\n%s\n"
                     "   Run LIST_MODELS.bat to check the model key.\n"
                     "   If it ran out of memory, halve LC_CONTEXT in config.cmd.\n"
                     "   Remember the real cost is LC_CONTEXT x LC_PARALLEL."
                     % (MODEL_KEY, out.strip()))
                return 4
            entries = resident_entries()
            # It comes back under our own identifier, so match on the model key
            # rather than the display name.
            fresh = next(
                (e for e in entries
                 if key_tail in (str(e.get("modelKey") or "") + entry_name(e)).lower()),
                entries[0] if entries else None,
            )
            if fresh is not None:
                describe_entry(fresh)
            free = report_headroom()
            if free is not None:
                status.update(vram_free=free)

    if not entries:
        entries = resident_entries()
    if not entries:
        fail("No model is loaded.\n"
             "   Set LC_MODEL_KEY in config.cmd, or load one in the LM Studio window.")
        return 5

    served = loaded_models() or []
    if IDENTIFIER in served:
        model_id = IDENTIFIER
    else:
        names = [entry_name(e) for e in entries if entry_name(e)]
        model_id = next(
            (name for name in names if key_tail and key_tail in name.lower()),
            names[0] if names else "",
        )
    if not model_id:
        fail("Could not work out what to call the loaded model.")
        return 5
    say("    using: %s" % model_id)

    step(3, "Wiring up the coder...")
    metadata_path = write_model_metadata(model_id)
    use_git = workspace_is_usable_git_repo()
    file_count = workspace_file_count()
    # Unattended runs never open the browser: each iteration is its own
    # short-lived aider process reading a prompt from a file.
    ui = "terminal" if loop_mode else UI

    # Aider's browser interface refuses to start outside a git repo, so a folder
    # that is not one leaves two choices: make it a repo, or use the terminal.
    # A folder LocalCoder looks after gets whatever was dropped into it since
    # last time committed, so new files show up in the file picker.
    if is_managed():
        snapshot_workspace()
        use_git = workspace_is_usable_git_repo()

    # Unattended runs want git even in the terminal: a commit per iteration is
    # what makes a single bad run undoable without losing the good ones.
    if not use_git and loop_mode and INIT_GIT:
        say("    setting this folder up as a git repo so each run can be undone")
        if ensure_git_repo():
            use_git = True

    if not use_git and ui == "browser":
        if INIT_GIT:
            say("    setting this folder up as a git repo so the browser can run")
            if ensure_git_repo():
                use_git = True
        if not use_git:
            ui = "terminal"
            say("    this folder is not a committed git repo, and aider's browser")
            say("    chat box will not run outside one - using the terminal instead.")
            say("    For the browser: point LC_WORKSPACE at a git project, or set")
            say("    LC_INIT_GIT=1 in config.cmd to let LocalCoder set this one up.")

    if use_git:
        say("    workspace is a git repo - history and undo available")
    else:
        say("    workspace is not a committed git repo - running without git")
    if file_count == 0:
        say()
        say("    WARNING: there are no files in %s" % WORKSPACE)
        say("             The chat box will open with nothing to edit.")
        say("             Point LC_WORKSPACE in config.cmd at a real project folder.")
        say()
    else:
        say("    %s%d files visible in the workspace" % ("" if file_count < 200 else "at least ", file_count))
    prompt_path = os.path.join(WORKSPACE, ".localcoder-prompt.md") if loop_mode else None
    cmd = build_aider_command(model_id, metadata_path, use_git, ui, loop_mode, prompt_path=prompt_path)
    if cmd is None:
        fail("aider is not installed in the venv.  Run SETUP.bat first.")
        return 6

    if check_only:
        ok = smoke_test(model_id)
        say()
        say("    aider command that would run:")
        say("      " + " ".join(cmd))
        say()
        say("=" * 62)
        say("  SELF-TEST %s" % ("PASSED" if ok else "FAILED"))
        say("=" * 62)
        cleanup()
        return 0 if ok else 8

    child_env = os.environ.copy()
    child_env["OPENAI_API_BASE"] = BASE_URL
    child_env["OPENAI_API_KEY"] = "lm-studio"
    child_env["OPENAI_BASE_URL"] = BASE_URL
    child_env["AIDER_ANALYTICS"] = "false"
    # All inference is local, and nothing else should phone out either: no
    # update check, and litellm reads its bundled model list instead of
    # fetching one from the internet at start-up.
    child_env["AIDER_CHECK_UPDATE"] = "false"
    child_env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    child_env["PATH"] = VENV_SCRIPTS + os.pathsep + child_env.get("PATH", "")
    # aider's output is read through a pipe, and on this box that meant it
    # decoded as cp1252 and gave up on formatting entirely -- "Terminal does
    # not support pretty output (UnicodeDecodeError)" on every single round.
    # Harmless to the work, but it mangles the transcript we now keep.
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"

    if loop_mode:
        # aider offers to open a help page whenever it hits an error carrying a
        # URL, and --yes-always accepts on your behalf -- so an unattended run
        # that hits the token limit a dozen times opens a dozen browser tabs at
        # somebody who is not in the room. Only in loop mode: the chat box is a
        # browser window and needs the real thing.
        child_env["BROWSER"] = write_nobrowser()

    if loop_mode:
        step(4, "Handing the task list to the model, over and over.")
        say("    Ctrl-C stops it. Nothing is lost -- every run saves as it goes.")
        say()
    else:
        step(4, "Starting the chat box.")
        if ui == "browser":
            say("    A browser tab will open in a few seconds.")
            say("    Leave THIS window open -- closing it shuts everything down.")
        else:
            say("    Type your request below. /add <file> to give it a file to edit,")
            say("    /help for the rest. Ctrl-C or /exit when you are done.")
        say()

    watchdog_stop = threading.Event()
    start_model_watchdog(watchdog_stop)

    try:
        if loop_mode:
            import ralph
            # Only ever commit in a folder LocalCoder made. Real projects keep
            # the same promise they always had: nothing is committed for you.
            committer = commit_everything if (use_git and is_managed()) else None
            edit_files = ralph_edit_files()
            return ralph.run_loop(
                cmd, WORKSPACE, child_env,
                minutes=minutes,
                single_shot=single_shot,
                notes_hint=RALPH_NOTES,
                edit_files=edit_files,
                iteration_timeout=RALPH_ITER_TIMEOUT,
                commit=committer,
                # Bringing the engine back needs patience and more than one go.
                revive=revive_model if MODEL_KEY else None,
                # Undoing a round means going back to the last commit, so this
                # is only offered where LocalCoder owns the history.
                rollback=discard_uncommitted if (use_git and is_managed()) else None,
                entry_hint=RALPH_RUN,
                run_seconds=RALPH_RUN_SECONDS,
                # An overflowing round repeats forever unless something gives.
                shrink_output=shrink_round_output,
                # ...and a round cut off by the ceiling needs the reverse.
                grow_output=grow_round_output,
                # Recorded per round so "bad allocation" at 3am has a trend
                # behind it rather than being the first anyone knew of it.
                gpu_probe=gpu_memory,
                # Cold to write code, warm to think up what to write.
                set_temperature=set_temperature,
                temps=(TEMP_CODE, TEMP_BRAINSTORM),
                # The worker should not be the one who decides its work is done.
                review=review_change if REVIEW else None,
                # The loop's own small questions: which files an item needs,
                # a gist of each module, a long file read in parts.
                ask=ask_model,
                # Re-read after each kept round, so a module the model creates
                # is sent and checked like the rest.
                list_files=ralph_edit_files,
            )
        proc = subprocess.Popen(cmd, cwd=WORKSPACE, env=child_env)
        proc.wait()
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        fail("Could not start aider: %s" % exc)
        return 7
    finally:
        watchdog_stop.set()
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
