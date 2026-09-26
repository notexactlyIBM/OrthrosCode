"""Run the code the model wrote -- tests, imports, a start -- inside limits.

The loop never runs a command the model suggests, but every check runs the
code it writes, with the operator's account and all the machine's memory. On
this machine memory is what runs out, and when it does Windows kills whatever
asks next: the engine, an agent, Orthros. A test that allocates without end
should fail, not take the machine with it (ORTHROSCODE-IMPROVEMENTS.md, 15).

On Windows each check gets a Job Object of its own: a cap on the memory all
its processes may commit together, a cap on how many there may be, and
everything in it killed when the check is over -- a test that leaves a server
running leaves nothing. Elsewhere, and if any of that cannot be set up, the
check runs exactly as before.
"""

import ctypes
import os
import subprocess

CHECK_MEMORY_MB = int(os.environ.get("LC_CHECK_MEMORY_MB", "") or 4096)
CHECK_PROCESSES = 32

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


def _limited_job(memory_mb, processes):
    """A Windows job with the limits, or None. Never raises."""
    if os.name != "nt" or memory_mb <= 0:
        return None
    try:
        from supervisor_win import JOBOBJECT_EXTENDED_LIMIT_INFORMATION, kernel32
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


def start(cmd, memory_mb=None, **kwargs):
    """subprocess.Popen, inside a limited job where there is one. Returns (proc, job)."""
    proc = subprocess.Popen(cmd, **kwargs)
    job = _limited_job(CHECK_MEMORY_MB if memory_mb is None else memory_mb, CHECK_PROCESSES)
    if job is not None and not _assign(job, proc):
        _close(job)
        job = None
    return proc, job


def finish(job):
    if job is not None:
        _close(job)


def run(cmd, timeout=None, memory_mb=None, **kwargs):
    """subprocess.run(cmd, capture_output=True, ...) inside the limits.

    Same result, same TimeoutExpired, and on a timeout everything the check
    started is killed, not only the first process.
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.pop("capture_output", None)
    proc, job = start(cmd, memory_mb=memory_mb, **kwargs)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    finally:
        finish(job)
