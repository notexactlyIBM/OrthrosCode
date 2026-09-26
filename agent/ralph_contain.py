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
"""

import ctypes
import os
import signal
import subprocess

from ralph_common import _env_int

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


def start(cmd, memory_mb=None, **kwargs):
    """subprocess.Popen, inside a limited job where there is one. Returns (proc, job)."""
    job = _limited_job(CHECK_MEMORY_MB if memory_mb is None else memory_mb, CHECK_PROCESSES)
    if os.name != "nt":
        kwargs.setdefault("start_new_session", True)    # its own group, to kill whole
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except Exception:
        if job is not None:
            _close(job)
        raise
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


def finish(job):
    if job is not None:
        _close(job)


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
        finish(job)
