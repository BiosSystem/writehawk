"""Display adapters, their drivers, and which of them drive a display.

Three sources are joined on the device instance id:

- the configuration manager lists the display class devices that are present,
- the registry holds each device's driver key (version, provider),
- the display configuration lists the active paths and the adapter behind each.

An adapter that is present and drives no display is the case rules care about:
a driver component can stay busy for hardware nobody is using.
"""
from __future__ import annotations

import ctypes
import re
import winreg
from collections.abc import Callable, Iterable, Mapping
from ctypes import wintypes as w
from dataclasses import dataclass

DISPLAY_CLASS = "{4d36e968-e325-11ce-bfc1-08002be10318}"
ENUM_KEY = "SYSTEM\\CurrentControlSet\\Enum\\"
CLASS_KEY = "SYSTEM\\CurrentControlSet\\Control\\Class\\"

CM_GETIDLIST_FILTER_PRESENT = 0x100
CM_GETIDLIST_FILTER_CLASS = 0x200
CR_SUCCESS = 0
CR_BUFFER_SMALL = 0x1A

QDC_ONLY_ACTIVE_PATHS = 2
DISPLAYCONFIG_DEVICE_INFO_GET_ADAPTER_NAME = 4
ERROR_INSUFFICIENT_BUFFER = 122

VENDORS = {0x10DE: "nvidia", 0x1002: "amd", 0x1022: "amd", 0x8086: "intel",
           0x1414: "microsoft", 0x5143: "qualcomm"}

_IDS = re.compile(r"VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})", re.IGNORECASE)


@dataclass(frozen=True)
class Gpu:
    instance_id: str
    name: str
    vendor: str
    """`nvidia`, `amd`, `intel`, `microsoft`, `qualcomm` or `other`."""
    vendor_id: int | None
    device_id: int | None
    driver_version: str
    """The Windows driver version, such as `32.0.15.6094`. Empty when unknown."""
    release: str
    """The vendor's own version number when one can be derived, else empty."""
    driver_provider: str
    driver_date: str
    displays: int | None
    """Active display paths on this adapter. None when paths could not be read."""


def parse_ids(instance_id: str) -> tuple[int | None, int | None]:
    r"""`PCI\VEN_10DE&DEV_1F02&...` -> `(0x10DE, 0x1F02)`; `(None, None)` off the PCI bus."""
    found = _IDS.search(instance_id)
    if found is None:
        return None, None
    return int(found.group(1), 16), int(found.group(2), 16)


def clean_description(text: str) -> str:
    """`@oem98.inf,%dev%;Some Adapter` -> `Some Adapter`."""
    return text.rsplit(";", 1)[-1].strip()


def nvidia_release(driver_version: str) -> str:
    """`32.0.15.6094` -> `560.94`: the last five digits are the public version."""
    digits = driver_version.replace(".", "")
    if not digits.isdigit() or len(digits) < 5:
        return ""
    return f"{digits[-5:-2]}.{digits[-2:]}"


def instance_from_adapter_path(path: str) -> str:
    r"""`\\?\PCI#VEN_..#4&1&0&8#{guid}` -> `PCI\VEN_..\4&1&0&8`."""
    body = path.removeprefix("\\\\?\\")
    if body.endswith("}") and "#{" in body:
        body = body[:body.rindex("#{")]
    return body.replace("#", "\\")


def build(ids: Iterable[str], values_of: Callable[[str], Mapping[str, str]],
          active: Iterable[str] | None) -> list[Gpu]:
    """Join the three sources. `active` holds one instance id per active path."""
    counts: dict[str, int] | None = None
    if active is not None:
        counts = {}
        for instance in active:
            counts[instance.upper()] = counts.get(instance.upper(), 0) + 1
    gpus = []
    for instance in ids:
        values = values_of(instance)
        vendor_id, device_id = parse_ids(instance)
        vendor = VENDORS.get(vendor_id, "other") if vendor_id is not None else "other"
        version = values.get("DriverVersion", "")
        if vendor == "nvidia":
            release = nvidia_release(version)
        elif vendor == "amd":
            release = values.get("RadeonSoftwareVersion", "")
        else:
            release = ""
        gpus.append(Gpu(
            instance_id=instance,
            name=clean_description(values.get("DriverDesc") or values.get("DeviceDesc", "")),
            vendor=vendor, vendor_id=vendor_id, device_id=device_id,
            driver_version=version, release=release,
            driver_provider=values.get("ProviderName", ""),
            driver_date=values.get("DriverDate", ""),
            displays=None if counts is None else counts.get(instance.upper(), 0)))
    return gpus


_cfg = ctypes.WinDLL("cfgmgr32")
_cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(w.ULONG), w.LPCWSTR, w.ULONG]
_cfg.CM_Get_Device_ID_List_SizeW.restype = w.DWORD
_cfg.CM_Get_Device_ID_ListW.argtypes = [w.LPCWSTR, ctypes.c_wchar_p, w.ULONG, w.ULONG]
_cfg.CM_Get_Device_ID_ListW.restype = w.DWORD


def device_ids() -> list[str]:
    """Instance ids of the display class devices that are present."""
    flags = CM_GETIDLIST_FILTER_CLASS | CM_GETIDLIST_FILTER_PRESENT
    for _ in range(3):  # the list can grow between the two calls
        size = w.ULONG()
        code = _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), DISPLAY_CLASS, flags)
        if code != CR_SUCCESS:
            raise OSError(f"CM_Get_Device_ID_List_Size failed with {code:#x}")
        buffer = ctypes.create_unicode_buffer(size.value)
        code = _cfg.CM_Get_Device_ID_ListW(DISPLAY_CLASS, buffer, size, flags)
        if code == CR_SUCCESS:
            return [item for item in buffer[:size.value].split("\0") if item]
        if code != CR_BUFFER_SMALL:
            raise OSError(f"CM_Get_Device_ID_List failed with {code:#x}")
    raise OSError("device list kept changing")


def _values(key_path: str, names: Iterable[str]) -> dict[str, str]:
    found = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for name in names:
                try:
                    value = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    continue
                if isinstance(value, str):
                    found[name] = value
    except OSError:
        pass
    return found


def driver_values(instance_id: str) -> dict[str, str]:
    """Description and driver facts of one device, from its two registry keys."""
    values = _values(ENUM_KEY + instance_id, ("DeviceDesc", "Driver"))
    driver = values.pop("Driver", "")
    if driver:
        values.update(_values(CLASS_KEY + driver, (
            "DriverDesc", "DriverVersion", "DriverDate", "ProviderName",
            "RadeonSoftwareVersion")))
    return values


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]


class _PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", w.UINT), ("modeInfoIdx", w.UINT),
                ("statusFlags", w.UINT)]


class _RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", w.UINT), ("Denominator", w.UINT)]


class _PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", _LUID), ("id", w.UINT), ("modeInfoIdx", w.UINT),
                ("outputTechnology", w.UINT), ("rotation", w.UINT), ("scaling", w.UINT),
                ("refreshRate", _RATIONAL), ("scanLineOrdering", w.UINT),
                ("targetAvailable", w.BOOL), ("statusFlags", w.UINT)]


class _PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", _PATH_SOURCE), ("targetInfo", _PATH_TARGET), ("flags", w.UINT)]


class _MODE_INFO(ctypes.Structure):
    # Only its size matters here: the modes are not read.
    _fields_ = [("infoType", w.UINT), ("id", w.UINT), ("adapterId", _LUID),
                ("mode", ctypes.c_byte * 48)]


class _DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", w.UINT), ("size", w.UINT), ("adapterId", _LUID), ("id", w.UINT)]


class _ADAPTER_NAME(ctypes.Structure):
    _fields_ = [("header", _DEVICE_INFO_HEADER), ("adapterDevicePath", w.WCHAR * 128)]


_user32 = ctypes.WinDLL("user32")
_user32.GetDisplayConfigBufferSizes.argtypes = [w.UINT, ctypes.POINTER(w.UINT),
                                                ctypes.POINTER(w.UINT)]
_user32.GetDisplayConfigBufferSizes.restype = w.LONG
_user32.QueryDisplayConfig.argtypes = [w.UINT, ctypes.POINTER(w.UINT), ctypes.c_void_p,
                                       ctypes.POINTER(w.UINT), ctypes.c_void_p, ctypes.c_void_p]
_user32.QueryDisplayConfig.restype = w.LONG
_user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
_user32.DisplayConfigGetDeviceInfo.restype = w.LONG


def active_adapters() -> list[str] | None:
    """One device instance id per active display path.

    None when the display configuration cannot be read, which is the case for
    a process without a desktop, such as a service.
    """
    for _ in range(3):  # the path count can change between the two calls
        path_count, mode_count = w.UINT(), w.UINT()
        if _user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count),
                                               ctypes.byref(mode_count)):
            return None
        paths = (_PATH_INFO * path_count.value)()
        modes = (_MODE_INFO * mode_count.value)()
        code = _user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), paths,
                                          ctypes.byref(mode_count), modes, None)
        if code == ERROR_INSUFFICIENT_BUFFER:
            continue
        if code:
            return None
        found = []
        for path in paths[:path_count.value]:
            name = _ADAPTER_NAME()
            name.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADAPTER_NAME
            name.header.size = ctypes.sizeof(name)
            name.header.adapterId = path.sourceInfo.adapterId
            if _user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0:
                found.append(instance_from_adapter_path(name.adapterDevicePath))
        return found
    return None


def gpus() -> list[Gpu]:
    return build(device_ids(), driver_values, active_adapters())
