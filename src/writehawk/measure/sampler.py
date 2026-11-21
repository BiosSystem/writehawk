"""Per-process I/O counters, sampled into rolling windows.

GetProcessIoCounters counts every ReadFile/WriteFile the process makes: files,
pipes, sockets and devices alike. A high write rate here says "look closer",
not "this hit the disk". diskstat and filetrace answer that part.
"""
from __future__ import annotations

import ctypes
import time
from collections import deque
from collections.abc import Callable
from ctypes import wintypes as w
from dataclasses import dataclass

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE = w.HANDLE(-1).value


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD),
                ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD),
                ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = w.HANDLE
_k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.GetProcessIoCounters.argtypes = [w.HANDLE, ctypes.POINTER(_IO_COUNTERS)]
_k32.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
_k32.CreateToolhelp32Snapshot.restype = w.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
_k32.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]


@dataclass(frozen=True)
class IoCounters:
    read_ops: int
    write_ops: int
    other_ops: int
    read_bytes: int
    write_bytes: int
    other_bytes: int


@dataclass(frozen=True)
class ProcSample:
    pid: int
    name: str
    created: int  # process creation FILETIME; with the pid it survives PID reuse
    counters: IoCounters


@dataclass(frozen=True)
class ProcRate:
    pid: int
    name: str
    seconds: float
    write_bytes: int
    write_ops: int
    read_bytes: int

    @property
    def write_bps(self) -> float:
        return self.write_bytes / self.seconds

    @property
    def write_iops(self) -> float:
        return self.write_ops / self.seconds

    @property
    def avg_write_size(self) -> float:
        return self.write_bytes / self.write_ops if self.write_ops else 0.0


def read_process(pid: int) -> tuple[int, IoCounters] | None:
    """Creation time and I/O counters, or None when the process cannot be opened."""
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        raw = _IO_COUNTERS()
        created, exited, kernel, user = (w.FILETIME() for _ in range(4))
        if not _k32.GetProcessIoCounters(handle, ctypes.byref(raw)):
            return None
        if not _k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)):
            return None
        stamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return stamp, IoCounters(raw.ReadOperationCount, raw.WriteOperationCount,
                                 raw.OtherOperationCount, raw.ReadTransferCount,
                                 raw.WriteTransferCount, raw.OtherTransferCount)
    finally:
        _k32.CloseHandle(handle)


def list_processes() -> list[tuple[int, str]]:
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = []
        more = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            found.append((entry.th32ProcessID, entry.szExeFile))
            more = _k32.Process32NextW(snap, ctypes.byref(entry))
        return found
    finally:
        _k32.CloseHandle(snap)


def snapshot() -> tuple[list[ProcSample], int]:
    """Every readable process, and how many could not be opened."""
    samples, unreadable = [], 0
    for pid, name in list_processes():
        if pid == 0:
            continue
        got = read_process(pid)
        if got is None:
            unreadable += 1
            continue
        samples.append(ProcSample(pid, name, got[0], got[1]))
    return samples, unreadable


class Sampler:
    def __init__(self, source: Callable[[], tuple[list[ProcSample], int]] = snapshot,
                 clock: Callable[[], float] = time.monotonic, keep: float = 120.0) -> None:
        self._source = source
        self._clock = clock
        self._keep = keep
        self._history: dict[tuple[int, int], deque[tuple[float, ProcSample]]] = {}
        self._now = 0.0
        self.unreadable = 0

    def sample(self) -> None:
        samples, self.unreadable = self._source()
        self._now = self._clock()
        live = set()
        for s in samples:
            key = (s.pid, s.created)
            live.add(key)
            history = self._history.setdefault(key, deque())
            history.append((self._now, s))
            while history[0][0] < self._now - self._keep:
                history.popleft()
        for key in [k for k in self._history if k not in live]:
            del self._history[key]

    def rates(self, window: float) -> list[ProcRate]:
        """Deltas over the last `window` seconds, busiest writer first."""
        rows = []
        for history in self._history.values():
            t_new, new = history[-1]
            t_old, old = next((t, s) for t, s in history if t >= self._now - window)
            if t_new <= t_old:
                continue
            a, b = old.counters, new.counters
            rows.append(ProcRate(new.pid, new.name, t_new - t_old,
                                 b.write_bytes - a.write_bytes, b.write_ops - a.write_ops,
                                 b.read_bytes - a.read_bytes))
        rows.sort(key=lambda r: r.write_bytes, reverse=True)
        return rows
