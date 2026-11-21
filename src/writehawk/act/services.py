"""Service start type and state, through the service control manager."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as w

SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_CONFIG = 0x0001
SERVICE_CHANGE_CONFIG = 0x0002
SERVICE_QUERY_STATUS = 0x0004
SERVICE_START = 0x0010
SERVICE_STOP = 0x0020
SERVICE_NO_CHANGE = 0xFFFFFFFF
SERVICE_CONTROL_STOP = 1
SC_STATUS_PROCESS_INFO = 0
STOPPED, RUNNING = 1, 4
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_SERVICE_ALREADY_RUNNING = 1056


class _STATUS_PROCESS(ctypes.Structure):
    _fields_ = [("dwServiceType", w.DWORD), ("dwCurrentState", w.DWORD),
                ("dwControlsAccepted", w.DWORD), ("dwWin32ExitCode", w.DWORD),
                ("dwServiceSpecificExitCode", w.DWORD), ("dwCheckPoint", w.DWORD),
                ("dwWaitHint", w.DWORD), ("dwProcessId", w.DWORD), ("dwServiceFlags", w.DWORD)]


class _STATUS(ctypes.Structure):
    _fields_ = _STATUS_PROCESS._fields_[:7]


_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_adv.OpenSCManagerW.restype = w.HANDLE
_adv.OpenSCManagerW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
_adv.OpenServiceW.restype = w.HANDLE
_adv.OpenServiceW.argtypes = [w.HANDLE, w.LPCWSTR, w.DWORD]
_adv.CloseServiceHandle.argtypes = [w.HANDLE]
_adv.QueryServiceConfigW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
_adv.ChangeServiceConfigW.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR, w.LPCWSTR,
                                      ctypes.c_void_p, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR]
_adv.QueryServiceStatusEx.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD,
                                      ctypes.POINTER(w.DWORD)]
_adv.ControlService.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(_STATUS)]
_adv.StartServiceW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p]


class _Service:
    def __init__(self, name: str, access: int) -> None:
        self._manager = _adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not self._manager:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = _adv.OpenServiceW(self._manager, name, access)
        if not self.handle:
            error = ctypes.WinError(ctypes.get_last_error())
            _adv.CloseServiceHandle(self._manager)
            raise error

    def __enter__(self) -> int:
        return self.handle

    def __exit__(self, *_exc: object) -> None:
        _adv.CloseServiceHandle(self.handle)
        _adv.CloseServiceHandle(self._manager)


def start_type(name: str) -> int:
    """2 automatic, 3 manual, 4 disabled."""
    with _Service(name, SERVICE_QUERY_CONFIG) as handle:
        needed = w.DWORD()
        _adv.QueryServiceConfigW(handle, None, 0, ctypes.byref(needed))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(needed.value)
        if not _adv.QueryServiceConfigW(handle, buffer, needed, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        # QUERY_SERVICE_CONFIGW starts with dwServiceType, dwStartType.
        return ctypes.cast(buffer, ctypes.POINTER(w.DWORD))[1]


def set_start_type(name: str, value: int) -> None:
    with _Service(name, SERVICE_CHANGE_CONFIG) as handle:
        if not _adv.ChangeServiceConfigW(handle, SERVICE_NO_CHANGE, value, SERVICE_NO_CHANGE,
                                         None, None, None, None, None, None, None):
            raise ctypes.WinError(ctypes.get_last_error())


def state(name: str) -> tuple[int, int]:
    """`(state, pid)`: state 1 is stopped, 4 is running; pid is 0 when stopped."""
    with _Service(name, SERVICE_QUERY_STATUS) as handle:
        return _state(handle)


def _state(handle: int) -> tuple[int, int]:
    status = _STATUS_PROCESS()
    needed = w.DWORD()
    if not _adv.QueryServiceStatusEx(handle, SC_STATUS_PROCESS_INFO, ctypes.byref(status),
                                     ctypes.sizeof(status), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return status.dwCurrentState, status.dwProcessId


def _wait(handle: int, wanted: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _state(handle)[0] == wanted:
            return True
        time.sleep(0.2)
    return False


def stop(name: str, timeout: float = 20.0) -> bool:
    """True when the service is stopped at the end."""
    with _Service(name, SERVICE_STOP | SERVICE_QUERY_STATUS) as handle:
        if (not _adv.ControlService(handle, SERVICE_CONTROL_STOP, ctypes.byref(_STATUS()))
                and ctypes.get_last_error() != ERROR_SERVICE_NOT_ACTIVE):
            raise ctypes.WinError(ctypes.get_last_error())
        return _wait(handle, STOPPED, timeout)


def start(name: str, timeout: float = 20.0) -> bool:
    """True when the service is running at the end."""
    with _Service(name, SERVICE_START | SERVICE_QUERY_STATUS) as handle:
        if (not _adv.StartServiceW(handle, 0, None)
                and ctypes.get_last_error() != ERROR_SERVICE_ALREADY_RUNNING):
            raise ctypes.WinError(ctypes.get_last_error())
        return _wait(handle, RUNNING, timeout)
