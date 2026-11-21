"""Processes that must never be throttled, stopped or otherwise acted on.

A process is protected when its image is at a listed path and that file
carries a valid signature from a listed signer. The name alone proves nothing:
a copy of a listed image somewhere else is an ordinary program, and so is a
different file that only borrows the name.

A process that cannot be identified is reported as `unknown`. Callers that
change anything must treat `unknown` like `protected`.
"""
from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Callable, Iterable
from ctypes import wintypes as w
from dataclasses import dataclass

PROTECTED = "protected"
OPEN = "open"
UNKNOWN = "unknown"

WINDOWS_SIGNERS = ("Microsoft Windows", "Microsoft Windows Publisher")
SYSTEM_PIDS = (0, 4)


@dataclass(frozen=True)
class Signature:
    status: str
    """`embedded`, `catalog`, `unsigned`, `invalid` or `unreadable`."""
    signer: str
    """Subject name of the signing certificate. Empty unless the signature is valid."""

    @property
    def valid(self) -> bool:
        return self.status in ("embedded", "catalog")


@dataclass(frozen=True)
class Entry:
    path: str
    """Full image path. Environment variables are expanded; `*` stands for one
    whole folder or file name, for images installed under a version folder."""
    signers: tuple[str, ...]


def _system(name: str) -> Entry:
    return Entry("%SystemRoot%\\System32\\" + name, WINDOWS_SIGNERS)


DEFAULT_ENTRIES = (
    _system("smss.exe"), _system("csrss.exe"), _system("wininit.exe"), _system("winlogon.exe"),
    _system("services.exe"), _system("lsass.exe"), _system("svchost.exe"), _system("dwm.exe"),
    _system("fontdrvhost.exe"),
    Entry("%SystemRoot%\\explorer.exe", WINDOWS_SIGNERS),
    Entry("%ProgramData%\\Microsoft\\Windows Defender\\Platform\\*\\MsMpEng.exe", WINDOWS_SIGNERS),
    Entry("%ProgramFiles%\\Windows Defender\\MsMpEng.exe", WINDOWS_SIGNERS),
)


def normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(path)))


def path_pattern(path: str) -> re.Pattern[str]:
    """Exact match on the normalized path; `*` matches within one component."""
    parts = (re.escape(part) for part in normalize(path).split("*"))
    return re.compile(r"[^\\]+".join(parts))


# --- signatures -----------------------------------------------------------------------------

TRUST_E_PROVIDER_UNKNOWN = 0x800B0001
TRUST_E_SUBJECT_FORM_UNKNOWN = 0x800B0003
TRUST_E_NOSIGNATURE = 0x800B0100
NOT_EMBEDDED = (TRUST_E_PROVIDER_UNKNOWN, TRUST_E_SUBJECT_FORM_UNKNOWN, TRUST_E_NOSIGNATURE)

WTD_UI_NONE = 2
WTD_REVOKE_NONE = 0
WTD_CHOICE_FILE = 1
WTD_CHOICE_CATALOG = 2
WTD_STATEACTION_VERIFY = 1
WTD_STATEACTION_CLOSE = 2
# No revocation check and nothing fetched: the check must not touch the network.
WTD_PROV_FLAGS = 0x10 | 0x1000
CERT_NAME_SIMPLE_DISPLAY_TYPE = 4
GENERIC_READ = 0x80000000
INVALID_HANDLE = w.HANDLE(-1).value


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


# WINTRUST_ACTION_GENERIC_VERIFY_V2
_ACTION = _GUID(0x00AAC56B, 0xCD44, 0x11D0,
                (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", w.DWORD), ("pcwszFilePath", w.LPCWSTR), ("hFile", w.HANDLE),
                ("pgKnownSubject", ctypes.c_void_p)]


class _WINTRUST_CATALOG_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", w.DWORD), ("dwCatalogVersion", w.DWORD),
                ("pcwszCatalogFilePath", w.LPCWSTR), ("pcwszMemberTag", w.LPCWSTR),
                ("pcwszMemberFilePath", w.LPCWSTR), ("hMemberFile", w.HANDLE),
                ("pbCalculatedFileHash", ctypes.c_void_p), ("cbCalculatedFileHash", w.DWORD),
                ("pcCatalogContext", ctypes.c_void_p), ("hCatAdmin", w.HANDLE)]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [("cbStruct", w.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", w.DWORD),
                ("fdwRevocationChecks", w.DWORD), ("dwUnionChoice", w.DWORD),
                ("pInfo", ctypes.c_void_p), ("dwStateAction", w.DWORD),
                ("hWVTStateData", w.HANDLE), ("pwszURLReference", w.LPCWSTR),
                ("dwProvFlags", w.DWORD), ("dwUIContext", w.DWORD),
                ("pSignatureSettings", ctypes.c_void_p)]


class _CATALOG_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", w.DWORD), ("wszCatalogFile", w.WCHAR * 260)]


_wt = ctypes.WinDLL("wintrust", use_last_error=True)
_wt.WinVerifyTrust.argtypes = [w.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(_WINTRUST_DATA)]
_wt.WinVerifyTrust.restype = w.LONG
_wt.WTHelperProvDataFromStateData.argtypes = [w.HANDLE]
_wt.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
_wt.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD]
_wt.WTHelperGetProvSignerFromChain.restype = ctypes.c_void_p
_wt.WTHelperGetProvCertFromChain.argtypes = [ctypes.c_void_p, w.DWORD]
_wt.WTHelperGetProvCertFromChain.restype = ctypes.c_void_p
_wt.CryptCATAdminAcquireContext2.argtypes = [ctypes.POINTER(w.HANDLE), ctypes.c_void_p,
                                             w.LPCWSTR, ctypes.c_void_p, w.DWORD]
_wt.CryptCATAdminCalcHashFromFileHandle2.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.DWORD),
                                                     ctypes.c_void_p, w.DWORD]
_wt.CryptCATAdminEnumCatalogFromHash.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.DWORD,
                                                 ctypes.c_void_p]
_wt.CryptCATAdminEnumCatalogFromHash.restype = w.HANDLE
_wt.CryptCATCatalogInfoFromContext.argtypes = [w.HANDLE, ctypes.POINTER(_CATALOG_INFO), w.DWORD]
_wt.CryptCATAdminReleaseCatalogContext.argtypes = [w.HANDLE, w.HANDLE, w.DWORD]
_wt.CryptCATAdminReleaseContext.argtypes = [w.HANDLE, w.DWORD]
_c32 = ctypes.WinDLL("crypt32", use_last_error=True)
_c32.CertGetNameStringW.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p,
                                    ctypes.c_wchar_p, w.DWORD]
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = w.HANDLE
_k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD,
                             w.HANDLE]
_k32.CloseHandle.argtypes = [w.HANDLE]
_k32.OpenProcess.restype = w.HANDLE
_k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_wchar_p,
                                            ctypes.POINTER(w.DWORD)]


def _verify(choice: int, info: ctypes.Structure) -> tuple[int, str]:
    """Run the trust check and return `(code, signer name)`. Code 0 means trusted."""
    data = _WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(data)
    data.dwUIChoice = WTD_UI_NONE
    data.fdwRevocationChecks = WTD_REVOKE_NONE
    data.dwUnionChoice = choice
    data.pInfo = ctypes.cast(ctypes.pointer(info), ctypes.c_void_p)
    data.dwStateAction = WTD_STATEACTION_VERIFY
    data.dwProvFlags = WTD_PROV_FLAGS
    code = _wt.WinVerifyTrust(None, ctypes.byref(_ACTION), ctypes.byref(data)) & 0xFFFFFFFF
    name = ""
    try:
        if code == 0:
            provider = _wt.WTHelperProvDataFromStateData(data.hWVTStateData)
            signer = _wt.WTHelperGetProvSignerFromChain(provider, 0, False, 0) if provider else 0
            cert = _wt.WTHelperGetProvCertFromChain(signer, 0) if signer else 0
            if cert:
                # CRYPT_PROVIDER_CERT: cbStruct, then the certificate context pointer.
                context = ctypes.c_void_p.from_address(cert + ctypes.sizeof(ctypes.c_void_p)).value
                buffer = ctypes.create_unicode_buffer(256)
                _c32.CertGetNameStringW(context, CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None, buffer,
                                        len(buffer))
                name = buffer.value
    finally:
        data.dwStateAction = WTD_STATEACTION_CLOSE
        _wt.WinVerifyTrust(None, ctypes.byref(_ACTION), ctypes.byref(data))
    return code, name


def _catalog_signature(path: str) -> Signature:
    admin = w.HANDLE()
    if not _wt.CryptCATAdminAcquireContext2(ctypes.byref(admin), None, "SHA256", None, 0):
        return Signature("unreadable", "")
    handle = _k32.CreateFileW(path, GENERIC_READ, 1, None, 3, 0, None)
    try:
        if handle == INVALID_HANDLE:
            return Signature("unreadable", "")
        size = w.DWORD(64)
        digest = (ctypes.c_ubyte * 64)()
        if not _wt.CryptCATAdminCalcHashFromFileHandle2(admin, handle, ctypes.byref(size), digest,
                                                        0):
            return Signature("unreadable", "")
        catalog = _wt.CryptCATAdminEnumCatalogFromHash(admin, digest, size, 0, None)
        if not catalog:
            return Signature("unsigned", "")
        try:
            found = _CATALOG_INFO(ctypes.sizeof(_CATALOG_INFO))
            if not _wt.CryptCATCatalogInfoFromContext(catalog, ctypes.byref(found), 0):
                return Signature("unreadable", "")
            tag = bytes(digest[:size.value]).hex().upper()
            info = _WINTRUST_CATALOG_INFO(
                ctypes.sizeof(_WINTRUST_CATALOG_INFO), 0, found.wszCatalogFile, tag, path, handle,
                ctypes.cast(digest, ctypes.c_void_p), size.value, None, admin)
            code, name = _verify(WTD_CHOICE_CATALOG, info)
            return Signature("catalog", name) if code == 0 and name else Signature("invalid", "")
        finally:
            _wt.CryptCATAdminReleaseCatalogContext(admin, catalog, 0)
    finally:
        if handle != INVALID_HANDLE:
            _k32.CloseHandle(handle)
        _wt.CryptCATAdminReleaseContext(admin, 0)


def signature_of(path: str) -> Signature:
    """Check the file's embedded signature, then the system catalogs."""
    info = _WINTRUST_FILE_INFO(ctypes.sizeof(_WINTRUST_FILE_INFO), path, None, None)
    code, name = _verify(WTD_CHOICE_FILE, info)
    if code == 0:
        return Signature("embedded", name) if name else Signature("invalid", "")
    if code not in NOT_EMBEDDED:
        return Signature("invalid", "")
    return _catalog_signature(path)


# --- processes ------------------------------------------------------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def image_path(pid: int) -> str | None:
    """Full path of the process image, or None when the process cannot be opened."""
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = w.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value or None
    finally:
        _k32.CloseHandle(handle)


def _stamp(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


class ProtectedList:
    def __init__(self, entries: Iterable[Entry] = DEFAULT_ENTRIES,
                 signature: Callable[[str], Signature] = signature_of,
                 locate: Callable[[int], str | None] = image_path) -> None:
        self._entries = [(path_pattern(entry.path), entry.signers) for entry in entries]
        self._signature = signature
        self._locate = locate
        self._cache: dict[str, tuple[tuple[int, int], Signature]] = {}

    def _signers_for(self, path: str) -> tuple[str, ...] | None:
        normal = normalize(path)
        for pattern, signers in self._entries:
            if pattern.fullmatch(normal):
                return signers
        return None

    def _checked(self, path: str) -> Signature:
        # Keyed on size and modification time so a replaced file is checked again.
        stamp = _stamp(path)
        if stamp is None:
            return Signature("unreadable", "")
        cached = self._cache.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        result = self._signature(path)
        self._cache[path] = (stamp, result)
        return result

    def is_protected_image(self, path: str) -> bool:
        signers = self._signers_for(path)
        if signers is None:
            return False
        found = self._checked(path)
        return found.valid and found.signer in signers

    def classify(self, pid: int) -> str:
        """`protected`, `open`, or `unknown` when the process cannot be identified."""
        if pid in SYSTEM_PIDS:
            return PROTECTED
        path = self._locate(pid)
        if path is None:
            return UNKNOWN
        return PROTECTED if self.is_protected_image(path) else OPEN
