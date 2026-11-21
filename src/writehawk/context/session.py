"""Whether someone is using the machine right now.

Both answers are about the session the calling process runs in. A process in
another session, such as a service, sees its own session and not the user's.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass

# QUERY_USER_NOTIFICATION_STATE
STATES = {1: "not_present", 2: "busy", 3: "d3d_fullscreen", 4: "presentation", 5: "normal",
          6: "quiet_time", 7: "app"}
FULLSCREEN_STATES = ("busy", "d3d_fullscreen")


@dataclass(frozen=True)
class Session:
    idle_seconds: float
    """Time since the last keyboard or mouse input in this session."""
    state: str
    """A name from `STATES`, or `unknown`."""

    @property
    def fullscreen(self) -> bool:
        """A fullscreen application is in front, exclusive or borderless."""
        return self.state in FULLSCREEN_STATES

    @property
    def user_present(self) -> bool:
        """False when the session is locked, switched away or showing a screen saver."""
        return self.state != "not_present"


def idle_from_ticks(now: int, last_input: int) -> float:
    """Both are 32-bit millisecond tick counts, which wrap after about 49.7 days."""
    return ((now - last_input) & 0xFFFFFFFF) / 1000


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetTickCount.restype = w.DWORD
_shell32 = ctypes.WinDLL("shell32")
_shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
_shell32.SHQueryUserNotificationState.restype = ctypes.c_long


def idle_seconds() -> float:
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return idle_from_ticks(_kernel32.GetTickCount(), info.dwTime)


def notification_state() -> str:
    state = ctypes.c_int()
    if _shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return "unknown"
    return STATES.get(state.value, "unknown")


def read() -> Session:
    """Idle time is -1 when the caller has no interactive session to ask about."""
    try:
        idle = idle_seconds()
    except OSError:
        idle = -1.0
    return Session(idle, notification_state())
