"""Find the path of a file from its kernel file object address.

The file trace cannot name a file that was opened before the trace started: no
event carries the name. Its write events do carry the address of the file
object, and the system handle table says which handle in which process points
at that object. Duplicating that handle and asking for its path gives the name.

Only the path is read. The duplicate is opened with no access rights, so it
cannot read or write the file, and it is closed straight away.

Needs elevation: object addresses are hidden from standard users, and opening
a service's process needs the debug privilege.
"""
from __future__ import annotations

import ctypes
import struct
import threading
from ctypes import wintypes as w

SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
PROCESS_DUP_HANDLE = 0x0040
FILE_TYPE_DISK = 1
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x2

# SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX on 64-bit Windows: Object, UniqueProcessId,
# HandleValue, GrantedAccess, CreatorBackTraceIndex, ObjectTypeIndex,
# HandleAttributes, Reserved.
_ENTRY = struct.Struct("<QQQIHHII")
_HEADER = struct.Struct("<QQ")  # NumberOfHandles, Reserved

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = w.HANDLE
_k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k32.GetCurrentProcess.restype = w.HANDLE
_k32.GetCurrentProcess.argtypes = []
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE),
                                 w.DWORD, w.BOOL, w.DWORD]
_k32.GetFileType.restype = w.DWORD
_k32.GetFileType.argtypes = [w.HANDLE]
_k32.GetFinalPathNameByHandleW.restype = w.DWORD
_k32.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]

_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.restype = w.ULONG
_ntdll.NtQuerySystemInformation.argtypes = [w.ULONG, ctypes.c_void_p, w.ULONG,
                                            ctypes.POINTER(w.ULONG)]


def parse_handle_table(table: bytes, wanted: set[tuple[int, int]]) -> dict[tuple[int, int], int]:
    """(pid, object address) -> handle value, for the pairs in `wanted`."""
    count = _HEADER.unpack_from(table)[0]
    found = {}
    end = min(len(table), _HEADER.size + count * _ENTRY.size)
    for offset in range(_HEADER.size, end - _ENTRY.size + 1, _ENTRY.size):
        obj, pid, handle = struct.unpack_from("<QQQ", table, offset)
        if (pid, obj) in wanted:
            found[(pid, obj)] = handle
            if len(found) == len(wanted):
                break
    return found


def strip_prefix(path: str) -> str:
    r"""`\\?\C:\x` -> `C:\x`, `\\?\UNC\server\share\x` -> `\\server\share\x`"""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def read_handle_table() -> bytes:
    size = 1 << 20
    while True:
        buffer = ctypes.create_string_buffer(size)
        needed = w.ULONG()
        status = _ntdll.NtQuerySystemInformation(SYSTEM_EXTENDED_HANDLE_INFORMATION, buffer,
                                                 size, ctypes.byref(needed))
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, needed.value + (1 << 16))
            continue
        if status:
            raise OSError(f"NtQuerySystemInformation failed with status {status:#x}")
        return buffer.raw[:needed.value or size]


def enable_debug_privilege() -> bool:
    """Lets an elevated process open services. False when the token lacks the privilege."""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.LookupPrivilegeValueW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p]
    advapi.AdjustTokenPrivileges.argtypes = [w.HANDLE, w.BOOL, ctypes.c_void_p, w.DWORD,
                                             ctypes.c_void_p, ctypes.c_void_p]
    token = w.HANDLE()
    if not advapi.OpenProcessToken(_k32.GetCurrentProcess(),
                                   TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        luid = ctypes.create_string_buffer(8)
        if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", luid):
            return False
        # TOKEN_PRIVILEGES with one entry: count, LUID, attributes.
        privileges = struct.pack("<I8sI", 1, luid.raw, SE_PRIVILEGE_ENABLED)
        ctypes.set_last_error(0)
        if not advapi.AdjustTokenPrivileges(token, False, privileges, 0, None, None):
            return False
        return ctypes.get_last_error() == 0  # ERROR_NOT_ALL_ASSIGNED otherwise
    finally:
        _k32.CloseHandle(token)


def path_of_handle(pid: int, handle: int, timeout: float = 1.0) -> str | None:
    """Path behind `handle` in process `pid`, or None if it is not a disk file.

    The query runs on a worker thread with a time limit, because asking about a
    busy pipe or device handle can block for as long as its owner is waiting.
    """
    process = _k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not process:
        return None
    duplicate = w.HANDLE()
    try:
        # Desired access 0: enough to ask for the path, not enough to touch the data.
        if not _k32.DuplicateHandle(process, handle, _k32.GetCurrentProcess(),
                                    ctypes.byref(duplicate), 0, False, 0):
            return None
    finally:
        _k32.CloseHandle(process)

    result: list[str] = []

    def query() -> None:
        try:
            if _k32.GetFileType(duplicate) != FILE_TYPE_DISK:
                return
            buffer = ctypes.create_unicode_buffer(1024)
            length = _k32.GetFinalPathNameByHandleW(duplicate, buffer, len(buffer), 0)
            if 0 < length < len(buffer):
                result.append(strip_prefix(buffer.value))
        finally:
            _k32.CloseHandle(duplicate)

    worker = threading.Thread(target=query, name="writehawk-handle", daemon=True)
    worker.start()
    worker.join(timeout)
    return result[0] if result else None


def resolve(wanted: set[tuple[int, int]]) -> dict[tuple[int, int], str]:
    """(pid, file object address) -> path, for every pair that could be resolved."""
    if not wanted:
        return {}
    enable_debug_privilege()
    paths = {}
    for pair, handle in parse_handle_table(read_handle_table(), wanted).items():
        path = path_of_handle(pair[0], handle)
        if path:
            paths[pair] = path
    return paths


def diagnose(pid: int, obj: int) -> dict[str, object]:
    """Why a (pid, file object) pair did or did not resolve. For troubleshooting."""
    report: dict[str, object] = {"debug_privilege": enable_debug_privilege()}
    handle = parse_handle_table(read_handle_table(), {(pid, obj)}).get((pid, obj))
    report["handle"] = handle
    if handle is None:
        return report
    ctypes.set_last_error(0)
    process = _k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    report["open_process_error"] = ctypes.get_last_error()
    if not process:
        return report
    duplicate = w.HANDLE()
    try:
        ctypes.set_last_error(0)
        ok = _k32.DuplicateHandle(process, handle, _k32.GetCurrentProcess(),
                                  ctypes.byref(duplicate), 0, False, 0)
        report["duplicate_error"] = 0 if ok else ctypes.get_last_error()
    finally:
        _k32.CloseHandle(process)
    if duplicate:
        _k32.CloseHandle(duplicate)
        report["path"] = path_of_handle(pid, handle)
    return report
