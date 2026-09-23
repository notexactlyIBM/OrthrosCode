"""Windows plumbing: the job object that takes our children down with us, and lms.exe."""

import ctypes
import os
import shutil
import subprocess
from ctypes import wintypes

from supervisor_env import env, say


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


JobObjectExtendedLimitInformation = 9


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_job_handle = None


def install_job_object():
    """Anything we spawn dies with us, however we die."""
    global _job_handle
    try:
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return False
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            return False
        if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
            return False
        _job_handle = handle
        return True
    except OSError:
        return False


def _lms_candidates():
    """Where LM Studio's lms.exe usually is: the CLI it installs for the user,
    the default per-user install, and an "LM Studio" folder at the top of
    any drive or under Program Files. LC_LMS_PATH in config.cmd wins over all."""
    tail = os.path.join("resources", "app", ".webpack", "lms.exe")
    found = [os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe"),
             os.path.expandvars(os.path.join(r"%LOCALAPPDATA%\Programs\LM Studio", tail)),
             os.path.expandvars(os.path.join(r"%LOCALAPPDATA%\LM-Studio", tail)),
             os.path.expandvars(os.path.join(r"%ProgramFiles%\LM Studio", tail))]
    for drive in "CDEFGH":
        found.append(os.path.join("%s:\\" % drive, "LM Studio", tail))
    return found


LMS_CANDIDATES = _lms_candidates()


def find_lms():
    override = env("LC_LMS_PATH")
    if override and os.path.isfile(override):
        return override
    for path in LMS_CANDIDATES:
        if os.path.isfile(path):
            return path
    found = shutil.which("lms")
    if found:
        return found
    return None


LMS = find_lms()


def lms(*args, quiet=True):
    """Run an lms subcommand. Returns (returncode, output)."""
    if not LMS:
        return 1, "lms CLI not found"
    try:
        proc = subprocess.run(
            [LMS] + list(args),
            capture_output=True,
            text=True,
            # lms draws boxes and colour codes; the console's cp1252 default
            # blows up on them and would hide any error message underneath.
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if not quiet and out.strip():
            say(out.strip())
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        return 1, "lms %s timed out" % " ".join(args)
    except OSError as exc:
        return 1, str(exc)
