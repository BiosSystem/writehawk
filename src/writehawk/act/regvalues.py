"""Registry values under HKLM: read with type, set, and put back exactly.

The 64-bit view is always used so that the same key is read and written
whatever the bitness of the interpreter.
"""
from __future__ import annotations

import winreg
from dataclasses import dataclass

VIEW = winreg.KEY_WOW64_64KEY
ERROR_FILE_NOT_FOUND = 2


@dataclass(frozen=True)
class Value:
    exists: bool
    kind: int = 0
    data: object = None
    """An int, a string, a list of strings, or hex text for binary kinds."""


ABSENT = Value(False)


def split(key: str) -> str:
    root, _, path = key.partition("\\")
    if root.upper() != "HKLM" or not path:
        raise ValueError(f"only keys under HKLM are handled: {key!r}")
    return path


def _plain(kind: int, data: object) -> object:
    return data.hex() if isinstance(data, bytes) else data


def _native(kind: int, data: object) -> object:
    text_kinds = (winreg.REG_SZ, winreg.REG_EXPAND_SZ)
    if isinstance(data, str) and kind not in text_kinds:
        return bytes.fromhex(data)
    return data


def read(key: str, name: str) -> Value:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, split(key), 0,
                            winreg.KEY_QUERY_VALUE | VIEW) as handle:
            data, kind = winreg.QueryValueEx(handle, name)
    except FileNotFoundError:
        return ABSENT
    return Value(True, kind, _plain(kind, data))


def key_exists(key: str) -> bool:
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, split(key), 0,
                       winreg.KEY_QUERY_VALUE | VIEW).Close()
    except FileNotFoundError:
        return False
    return True


def missing_keys(key: str) -> list[str]:
    """The key and those of its ancestors that do not exist, outermost first."""
    missing = []
    while "\\" in key and not key_exists(key):
        missing.append(key)
        key = key.rsplit("\\", 1)[0]
    return missing[::-1]


def write(key: str, name: str, value: Value) -> None:
    """Set the value, creating the key if needed; or delete it when `value` is absent."""
    if not value.exists:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, split(key), 0,
                                winreg.KEY_SET_VALUE | VIEW) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass
        return
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, split(key), 0,
                            winreg.KEY_SET_VALUE | VIEW) as handle:
        winreg.SetValueEx(handle, name, 0, value.kind, _native(value.kind, value.data))


def delete_key_if_empty(key: str) -> bool:
    """Remove a key this tool created. Refuses when anything is left inside it."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, split(key), 0,
                            winreg.KEY_READ | VIEW) as handle:
            subkeys, values, _ = winreg.QueryInfoKey(handle)
    except FileNotFoundError:
        return True
    if subkeys or values:
        return False
    winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, split(key), VIEW, 0)
    return True
