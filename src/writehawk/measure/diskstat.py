"""Cumulative read/write counters for a volume or physical disk.

These count what the storage stack was asked to transfer, after the cache
manager has merged repeated writes to the same cached pages. That makes them
the closest thing to "what reached the device" short of SMART data.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass

IOCTL_DISK_PERFORMANCE = 0x70020
INVALID_HANDLE = w.HANDLE(-1).value


class _DISK_PERFORMANCE(ctypes.Structure):
    _fields_ = [("BytesRead", ctypes.c_longlong), ("BytesWritten", ctypes.c_longlong),
                ("ReadTime", ctypes.c_longlong), ("WriteTime", ctypes.c_longlong),
                ("IdleTime", ctypes.c_longlong), ("ReadCount", w.DWORD),
                ("WriteCount", w.DWORD), ("QueueDepth", w.DWORD), ("SplitCount", w.DWORD),
                ("QueryTime", ctypes.c_longlong), ("StorageDeviceNumber", w.DWORD),
                ("StorageManagerName", w.WCHAR * 8)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD,
                             w.HANDLE]
_k32.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p,
                                 w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [w.HANDLE]


@dataclass(frozen=True)
class DiskCounters:
    bytes_read: int
    bytes_written: int
    read_count: int
    write_count: int


def read_counters(device: str) -> DiskCounters:
    r"""`device` is a volume (`\\.\C:`) or a disk (`\\.\PhysicalDrive0`)."""
    # Access 0 is enough for this IOCTL, so no elevation is needed.
    handle = _k32.CreateFileW(device, 0, 3, None, 3, 0, None)
    if handle == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        perf = _DISK_PERFORMANCE()
        returned = w.DWORD()
        if not _k32.DeviceIoControl(handle, IOCTL_DISK_PERFORMANCE, None, 0, ctypes.byref(perf),
                                    ctypes.sizeof(perf), ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return DiskCounters(perf.BytesRead, perf.BytesWritten, perf.ReadCount, perf.WriteCount)
    finally:
        _k32.CloseHandle(handle)


def volume_device(path: str) -> str:
    r"""`C:\Users\x\file` -> `\\.\C:`"""
    drive = path[:2]
    if len(drive) != 2 or drive[1] != ":":
        raise ValueError(f"no drive letter in {path!r}")
    return "\\\\.\\" + drive.upper()
