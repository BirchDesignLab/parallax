"""Running a command with a timeout, and killing everything it started when time runs out.

Only the project's `check` and `lint` strings go through a shell; everything else is an argument list.

On Windows the process starts suspended, is put in a Job Object of its own and only then resumed,
so every process it ever starts is in that job (unless it explicitly breaks away). Ending the job
kills the whole tree at once, including grandchildren whose parent has already exited, which
`taskkill /T` (it walks parent pids at kill time) would miss. If the job cannot be set up,
`taskkill /F /T` is the fallback. Elsewhere the process leads a new session and `os.killpg` ends it.

Whatever is still running from the tree when the command itself exits is killed too: a leftover
process would otherwise hold the output pipe open (so the read never ends) and keep files in the
working folder locked.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

_WINDOWS = sys.platform == "win32"
_DRAIN_SECONDS = 5  # how long to wait for the pipe to close after the tree is dead


@dataclass(frozen=True)
class RunResult:
    code: int | None       # None when it timed out
    output: str            # stdout and stderr together, decoded as UTF-8 with replacement
    timed_out: bool


if _WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_SUSPEND_RESUME = 0x0800
    _CREATE_SUSPENDED = 0x00000004

    _kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    # NtResumeProcess is undocumented but long stable (psutil resumes processes with it). Popen
    # closes the main thread's handle, so this is the way to resume a process started suspended.
    _ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    def _new_job() -> int | None:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _ExtendedLimits()
        # If the conductor itself dies, closing its handle to the job kills the tree too.
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation,
                                                 ctypes.byref(limits), ctypes.sizeof(limits)):
            _kernel32.CloseHandle(job)
            return None
        return job

    def _adopt_and_resume(pid: int) -> int | None:
        """Put the suspended process in a new job, then resume it. The job handle, or None if that failed."""
        handle = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            raise OSError(f"could not open process {pid} (error {ctypes.get_last_error()})")
        try:
            job = _new_job()
            if job is not None and not _kernel32.AssignProcessToJobObject(job, handle):
                _kernel32.CloseHandle(job)
                job = None
            status = _ntdll.NtResumeProcess(handle)
            if status != 0:
                raise OSError(f"could not resume process {pid} (status {status & 0xFFFFFFFF:#x})")
            return job
        finally:
            _kernel32.CloseHandle(handle)


def _start(cmd: str | Sequence[str], cwd: Path, env: Mapping[str, str] | None,
           has_input: bool) -> tuple[subprocess.Popen, int | None]:
    shell = isinstance(cmd, str)
    args = cmd if shell else list(cmd)
    common = dict(cwd=str(cwd), shell=shell, env=None if env is None else dict(env),
                  stdin=subprocess.PIPE if has_input else subprocess.DEVNULL,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not _WINDOWS:
        return subprocess.Popen(args, start_new_session=True, **common), None
    proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED, **common)
    try:
        return proc, _adopt_and_resume(proc.pid)
    except BaseException:
        proc.kill()
        proc.wait()
        raise


def _kill_tree(proc: subprocess.Popen, job: int | None) -> None:
    """Kill the process and everything it started. Safe to call when some or all of it already exited."""
    if _WINDOWS:
        if job is not None:
            _kernel32.TerminateJobObject(job, 1)
        elif proc.poll() is None:
            # Popen holds a handle to the process, so its pid cannot have been reused.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _feed(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except (BrokenPipeError, OSError):
        pass  # the process stopped reading; its output and exit code say what happened
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _drain(stream, chunks: list[bytes]) -> None:
    try:
        while True:
            chunk = stream.read1(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except (OSError, ValueError):
        pass


def run_command(cmd: str | Sequence[str], cwd: Path, timeout: int, input: str | None = None,
                env: Mapping[str, str] | None = None) -> RunResult:
    """Run `cmd` in `cwd`; a str runs through the shell. On timeout the whole process tree is killed.

    `env`, when given, is the complete environment of the process.
    """
    proc, job = _start(cmd, Path(cwd), env, input is not None)
    chunks: list[bytes] = []
    threads = [threading.Thread(target=_drain, args=(proc.stdout, chunks), daemon=True)]
    if input is not None:
        threads.append(threading.Thread(target=_feed, args=(proc.stdin, input.encode("utf-8")), daemon=True))
    try:
        for thread in threads:
            thread.start()
        try:
            code = proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
        # Timed out: kill the tree. Exited: kill whatever it left running.
        _kill_tree(proc, job)
        proc.wait()
        for thread in threads:
            thread.join(_DRAIN_SECONDS)
        if not threads[0].is_alive():
            proc.stdout.close()
    finally:
        if proc.returncode is None:
            _kill_tree(proc, job)
            proc.wait()
        if job is not None:
            _kernel32.CloseHandle(job)
    output = b"".join(chunks).decode("utf-8", errors="replace").replace("\r\n", "\n")
    return RunResult(code=code, output=output, timed_out=timed_out)
