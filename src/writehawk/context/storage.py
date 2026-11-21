"""Volumes with a drive letter, and what kind of device is behind each.

Everything here is asked through a handle opened with no access rights, so it
works for a standard user. The serial number is deliberately not read.
"""
from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes as w
from dataclasses import dataclass

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x560000

PROPERTY_DEVICE = 0
PROPERTY_SEEK_PENALTY = 7
PROPERTY_TRIM = 8

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
INVALID_HANDLE = w.HANDLE(-1).value

BUS_TYPES = {1: "scsi", 2: "atapi", 3: "ata", 4: "1394", 5: "ssa", 6: "fibre", 7: "usb",
             8: "raid", 9: "iscsi", 10: "sas", 11: "sata", 12: "sd", 13: "mmc", 14: "virtual",
             15: "file-backed", 16: "spaces", 17: "nvme", 18: "scm", 19: "ufs"}

_EXTENT_HEADER = struct.Struct("<I4x")
_EXTENT = struct.Struct("<I4xqq")
_DESCRIPTOR = struct.Struct("<IIBBBBIIIII")
_FLAG = struct.Struct("<II?")


@dataclass(frozen=True)
class Volume:
    root: str
    """Such as `C:\\`."""
    filesystem: str
    disks: tuple[int, ...]
    """Physical disk numbers behind the volume. More than one for a spanned volume."""
    media: str
    """`ssd` (no seek penalty), `hdd`, or `unknown` when the device does not say."""
    bus: str
    trim: bool | None
    removable: bool
    model: str


def parse_extents(raw: bytes) -> tuple[int, ...]:
    """Disk numbers from a VOLUME_DISK_EXTENTS buffer, in order, without repeats."""
    if len(raw) < _EXTENT_HEADER.size:
        return ()
    (count,) = _EXTENT_HEADER.unpack_from(raw)
    disks: list[int] = []
    for index in range(count):
        offset = _EXTENT_HEADER.size + index * _EXTENT.size
        if offset + _EXTENT.size > len(raw):
            break
        disk = _EXTENT.unpack_from(raw, offset)[0]
        if disk not in disks:
            disks.append(disk)
    return tuple(disks)


def _text(raw: bytes, offset: int) -> str:
    if offset == 0 or offset >= len(raw):
        return ""
    end = raw.find(b"\0", offset)
    return raw[offset:end if end >= 0 else len(raw)].decode("ascii", "replace").strip()


def parse_descriptor(raw: bytes) -> tuple[str, bool, str]:
    """`(bus, removable, model)` from a STORAGE_DEVICE_DESCRIPTOR buffer."""
    if len(raw) < _DESCRIPTOR.size:
        return "unknown", False, ""
    (_version, _size, _type, _modifier, removable, _queueing, vendor_at, product_at,
     _revision_at, _serial_at, bus) = _DESCRIPTOR.unpack_from(raw)
    model = " ".join(part for part in (_text(raw, vendor_at), _text(raw, product_at)) if part)
    return BUS_TYPES.get(bus, "unknown"), bool(removable), model


def parse_flag(raw: bytes) -> bool | None:
    """The single BOOLEAN of a seek penalty or trim descriptor."""
    if len(raw) < _FLAG.size:
        return None
    return _FLAG.unpack_from(raw)[2]


def media_type(seek_penalty: bool | None) -> str:
    if seek_penalty is None:
        return "unknown"
    return "hdd" if seek_penalty else "ssd"


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD,
                             w.HANDLE]
_k32.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p,
                                 w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.GetLogicalDriveStringsW.argtypes = [w.DWORD, ctypes.c_wchar_p]
_k32.GetDriveTypeW.argtypes = [w.LPCWSTR]
_k32.GetVolumeInformationW.argtypes = [w.LPCWSTR, ctypes.c_wchar_p, w.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p,
                                       w.DWORD]


def _ioctl(handle: int, code: int, request: bytes | None) -> bytes | None:
    out = ctypes.create_string_buffer(1024)
    returned = w.DWORD()
    if not _k32.DeviceIoControl(handle, code, request, len(request) if request else 0, out,
                                len(out), ctypes.byref(returned), None):
        return None
    return out.raw[:returned.value]


def _query(handle: int, property_id: int) -> bytes:
    # STORAGE_PROPERTY_QUERY: property id, PropertyStandardQuery (0), one padded byte.
    return _ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY, struct.pack("<II4x", property_id, 0)) or b""


def roots() -> list[tuple[str, int]]:
    """`(root, drive type)` for every drive letter."""
    size = _k32.GetLogicalDriveStringsW(0, None)
    buffer = ctypes.create_unicode_buffer(size + 1)
    size = _k32.GetLogicalDriveStringsW(size + 1, buffer)
    return [(root, _k32.GetDriveTypeW(root)) for root in buffer[:size].split("\0") if root]


def read_volume(root: str) -> Volume:
    filesystem = ctypes.create_unicode_buffer(64)
    if not _k32.GetVolumeInformationW(root, None, 0, None, None, None, filesystem, 64):
        filesystem.value = ""  # no media, or a volume that is not mounted
    disks: tuple[int, ...] = ()
    bus, removable, model, seek, trim = "unknown", False, "", None, None
    handle = _k32.CreateFileW("\\\\.\\" + root[:2], 0, 3, None, 3, 0, None)
    if handle != INVALID_HANDLE:
        try:
            disks = parse_extents(_ioctl(handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, None) or b"")
            bus, removable, model = parse_descriptor(_query(handle, PROPERTY_DEVICE))
            seek = parse_flag(_query(handle, PROPERTY_SEEK_PENALTY))
            trim = parse_flag(_query(handle, PROPERTY_TRIM))
        finally:
            _k32.CloseHandle(handle)
    return Volume(root=root, filesystem=filesystem.value, disks=disks, media=media_type(seek),
                  bus=bus, trim=trim, removable=removable, model=model)


def volumes() -> list[Volume]:
    """Fixed and removable volumes. Network, optical and RAM drives are left out."""
    return [read_volume(root) for root, kind in roots() if kind in (DRIVE_FIXED, DRIVE_REMOVABLE)]
