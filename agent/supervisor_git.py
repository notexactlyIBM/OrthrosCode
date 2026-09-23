"""The workspace's git history: the undo button for everything the model does."""

import os
import shutil
import subprocess

from supervisor_env import WORKSPACE, say


def workspace_is_usable_git_repo():
    """True only if git would actually hand aider a list of files.

    A folder with a .git directory but no commits yields an empty file list, and
    aider then shows an empty file picker with nothing to edit.
    """
    git = shutil.which("git")
    if not git:
        return False
    try:
        inside = subprocess.run(
            [git, "-C", WORKSPACE, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if inside.returncode != 0 or "true" not in (inside.stdout or "").lower():
            return False
        tracked = subprocess.run(
            [git, "-C", WORKSPACE, "ls-files"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        return bool((tracked.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


MANAGED_MARKER = ".localcoder-managed"


def run_git(*args):
    """Run a git command in the workspace. Returns (ok, combined output)."""
    git = shutil.which("git")
    if not git:
        return False, "git is not installed"
    try:
        proc = subprocess.run(
            [git, "-C", WORKSPACE] + list(args),
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, combined


def is_managed():
    """True if LocalCoder created this repo and may therefore commit to it."""
    return os.path.isfile(os.path.join(WORKSPACE, MANAGED_MARKER))


def commit_everything(message):
    ok, _ = run_git("add", "-A")
    if not ok:
        return False
    ok, out = run_git(
        "-c", "user.name=LocalCoder", "-c", "user.email=localcoder@localhost",
        "commit", "-m", message,
    )
    # "nothing to commit" is a success as far as we are concerned.
    return ok or "nothing to commit" in out.lower()


def discard_uncommitted():
    """Throw away everything since the last commit. Returns True if it worked.

    The last commit is the last round that left the program runnable, so this
    is exactly "undo the round that just broke it". Only ever called on a
    folder LocalCoder created and has been committing to itself.
    """
    ok, _ = run_git("checkout", "--", ".")
    return ok


def ensure_git_repo():
    """Turn the workspace into a repo so the browser chat box will run.

    Aider's browser interface refuses to start outside a git repo. An empty
    folder is fine to initialise -- the repo alone is what the UI needs.
    """
    git = shutil.which("git")
    if not git:
        say("    git is not installed, so this cannot be set up automatically")
        return False
    ok, out = run_git("init")
    if not ok:
        say("    git init failed: %s" % out[:200])
        return False
    marker = os.path.join(WORKSPACE, MANAGED_MARKER)
    if not os.path.isfile(marker):
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(
                "This folder is looked after by LocalCoder.\n"
                "Its contents are snapshotted to git every time LocalCoder starts,\n"
                "so you can drop files in, take them out, and still undo AI edits.\n"
                "Delete this file to stop that happening.\n"
            )
    commit_everything("LocalCoder: snapshot before any AI edits")
    return True


def snapshot_workspace():
    """Commit whatever the operator has dropped in since last time.

    Only ever runs on folders LocalCoder created, never on a real project.
    """
    ok, out = run_git("status", "--porcelain")
    if not ok or not out.strip():
        return False
    if commit_everything("LocalCoder: snapshot of dropped-in files"):
        say("    committed the files you added since last time")
        return True
    return False


def workspace_file_count(cap=200):
    skip = {".git", ".venv", "venv", "__pycache__", "node_modules", ".aider.tags.cache.v4"}
    total = 0
    for root, dirs, files in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in skip]
        total += len(files)
        if total >= cap:
            break
    return total
