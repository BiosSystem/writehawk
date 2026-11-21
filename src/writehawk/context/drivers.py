"""Facts that explain how drivers reach this machine, and why an update may not.

A vendor can publish a fix that never arrives: it may be a manual download,
the vendor's updater may not be installed, Windows Update may be told to leave
drivers alone, or the machine may be one whose maker ships its own drivers.
Everything here is read without elevation.
"""
from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes as w
from dataclasses import dataclass

UNINSTALL_KEYS = ("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
                  "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
# Display names of the programs that check a vendor for new drivers.
UPDATERS = {"nvidia": ("nvidia app", "nvidia geforce experience"),
            "amd": ("amd software",),
            "intel": ("intel driver & support assistant", "intel® driver & support assistant")}
WU_POLICY_KEY = "SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate"
BIOS_KEY = "HARDWARE\\DESCRIPTION\\System\\BIOS"
NO_SYSTEM_BATTERY = 128
BATTERY_UNKNOWN = 255


@dataclass(frozen=True)
class DriverDelivery:
    updaters: dict[str, tuple[str, ...]]
    """Vendor -> names of its installed updater programs. Empty tuple when none."""
    windows_update_excludes_drivers: bool
    """The policy that keeps drivers out of Windows Update is set."""
    system_maker: str
    portable: bool | None
    """The machine has a battery. None when that cannot be told."""


def match_updaters(names: list[str]) -> dict[str, tuple[str, ...]]:
    found = {}
    for vendor, wanted in UPDATERS.items():
        found[vendor] = tuple(sorted({name for name in names
                                      if name.lower().startswith(wanted)}))
    return found


def installed_program_names() -> list[str]:
    names = []
    for path in UNINSTALL_KEYS:
        try:
            parent = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        with parent:
            index = 0
            while True:
                try:
                    child = winreg.EnumKey(parent, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(parent, child) as key:
                        name = winreg.QueryValueEx(key, "DisplayName")[0]
                except OSError:
                    continue
                if isinstance(name, str) and name:
                    names.append(name)
    return names


def _value(path: str, name: str) -> object:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", w.DWORD), ("BatteryFullLifeTime", w.DWORD)]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(_SYSTEM_POWER_STATUS)]


def battery_from_flag(flag: int) -> bool | None:
    if flag == BATTERY_UNKNOWN:
        return None
    return not flag & NO_SYSTEM_BATTERY


def has_battery() -> bool | None:
    status = _SYSTEM_POWER_STATUS()
    if not _kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return battery_from_flag(status.BatteryFlag)


def read() -> DriverDelivery:
    maker = _value(BIOS_KEY, "SystemManufacturer")
    return DriverDelivery(
        updaters=match_updaters(installed_program_names()),
        windows_update_excludes_drivers=_value(
            WU_POLICY_KEY, "ExcludeWUDriversInQualityUpdate") == 1,
        system_maker=maker.strip() if isinstance(maker, str) else "",
        portable=has_battery())
