"""Run the code the model wrote -- tests, imports, a start -- inside limits.

The loop never runs a command the model suggests, but every check runs the
code it writes, with the operator's account and all the machine's memory. On
this machine memory is what runs out, and when it does Windows kills whatever
asks next: the engine, an agent, Orthros. A test that allocates without end
should fail, not take the machine with it (ORTHROSCODE-IMPROVEMENTS.md, 15).

On Windows each check gets a Job Object of its own: a cap on the memory all
its processes may commit together, a cap on how many there may be, and
everything in it killed when the check is over -- a test that leaves a server
running leaves nothing. The job is made before the process starts, so the
gap before it is in the job is as short as it can be without starting it
suspended (a venv's python.exe is a launcher that starts the real one).
Elsewhere each check gets a process group of its own, killed whole on a
timeout. If a job cannot be made, the check runs as before.

Each check also gets a temp folder of its own, emptied when it is over. The
tests make git repos in temp and remove them with rmtree(ignore_errors=True),
which on Windows cannot delete git's read-only files and says nothing. By
2026-10-18 the user's temp held 17,884 of them, and logging in took 12
minutes while Windows walked through them. Cleaning up after the check, not
in each test, keeps temp empty whatever the tests do, and a test killed on a
timeout leaves nothing either.
"""

import ctypes
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time

from ralph_common import QUICK_TESTS, _env_int

CHECK_MEMORY_MB = _env_int("LC_CHECK_MEMORY_MB", 4096, floor=0)
CHECK_PROCESSES = 32
DRAIN_SECONDS = 10          # after a kill, how long to wait for the pipes to close

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200


def _limited_job(memory_mb, processes):
    """A Windows job with the limits, or None. Never raises."""
    if os.name != "nt" or memory_mb <= 0:
        return None
    try:
        from supervisor_win import (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                                    JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
                                    JobObjectExtendedLimitInformation, kernel32)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_JOB_MEMORY
                                                 | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                                                 | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        info.BasicLimitInformation.ActiveProcessLimit = processes
        info.JobMemoryLimit = memory_mb * 1024 * 1024
        if not kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                                ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _assign(job, proc):
    try:
        from supervisor_win import kernel32
        handle = getattr(proc, "_handle", None)
        return bool(handle) and bool(kernel32.AssignProcessToJobObject(job, int(handle)))
    except Exception:
        return False


def _close(job):
    try:
        from supervisor_win import kernel32
        kernel32.CloseHandle(job)          # KILL_ON_JOB_CLOSE: whatever is left goes
    except Exception:
        pass


def _terminate(job):
    try:
        from supervisor_win import kernel32
        kernel32.TerminateJobObject(job, 1)
    except Exception:
        pass


# The harness's own settings: Orthros's and LocalCoder's.
HARNESS = ("ORTHROS_", "LC_")


def without_harness(env, keep=(QUICK_TESTS,)):
    """`env` without the harness's settings, but for those named in `keep`.

    The code a round checks has no business with them, nor has aider. Given
    ORTHROS_LEDGER, the ledger's own tests wrote their fixtures into Orthros's
    records and failed every check (2026-09-26); LC_WORKSPACE names the twin's
    real folder. Dropped by prefix, not by name, so the next one stays out too.
    """
    return {k: v for k, v in env.items() if k in keep or not k.upper().startswith(HARNESS)}


TEMP_PREFIX = "lc-check-"
STALE_TEMP_SECONDS = 3600    # older than any check: its check was killed with us


def wipe(path):
    """Remove `path` and everything in it, read-only files too. Never raises."""
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def _sweep_stale_temps():
    """Remove the check temps a killed agent never got to. Only ours, by prefix."""
    base = tempfile.gettempdir()
    try:
        names = [n for n in os.listdir(base) if n.startswith(TEMP_PREFIX)]
    except OSError:
        return
    for name in names:
        path = os.path.join(base, name)
        try:
            if time.time() - os.path.getmtime(path) > STALE_TEMP_SECONDS:
                wipe(path)
        except OSError:
            pass


def start(cmd, memory_mb=None, **kwargs):
    """subprocess.Popen, inside a limited job where there is one. Returns (proc, job).

    Pass both to finish() when the check is over: that empties its temp."""
    env = without_harness(os.environ if kwargs.get("env") is None else kwargs["env"])
    _sweep_stale_temps()
    temp = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    env.update(TEMP=temp, TMP=temp, TMPDIR=temp)
    kwargs["env"] = env
    job = _limited_job(CHECK_MEMORY_MB if memory_mb is None else memory_mb, CHECK_PROCESSES)
    if os.name != "nt":
        kwargs.setdefault("start_new_session", True)    # its own group, to kill whole
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except Exception:
        if job is not None:
            _close(job)
        wipe(temp)
        raise
    proc.check_temp = temp
    if job is not None and not _assign(job, proc):
        _close(job)
        job = None
    return proc, job


def stop(proc, job):
    """Kill the check and everything it started, then let the pipes drain."""
    if job is not None:
        _terminate(job)
    elif os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=DRAIN_SECONDS)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass             # something outside our reach still holds a pipe: go on


def finish(job, proc=None):
    """The check is over: close its job, killing what is left, and empty its temp."""
    if job is not None:
        _close(job)
    temp = getattr(proc, "check_temp", None)
    if isinstance(temp, str):         # a test's stand-in proc has none
        wipe(temp)


def run(cmd, timeout=None, memory_mb=None, **kwargs):
    """subprocess.run(cmd, capture_output=True, ...) inside the limits.

    Same result, same TimeoutExpired; on a timeout everything the check
    started is killed first, so a leftover child holding the output pipe
    cannot keep the loop waiting.
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.pop("capture_output", None)
    proc, job = start(cmd, memory_mb=memory_mb, **kwargs)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop(proc, job)
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    finally:
        finish(job, proc)
