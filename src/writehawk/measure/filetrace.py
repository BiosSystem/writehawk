"""Real-time Microsoft-Windows-Kernel-File trace feeding a RewriteTracker.

Every write event carries the issuing pid, the file and the byte offset, which
is what the rewrite ratio needs. Starting a trace session needs elevation (or
membership of Performance Log Users).

One WriteFile call can show up as several write events, so they are sorted:

- Paging writes (IRP_PAGING_IO set) are the cache being flushed: by the System
  process for the lazy writer, or by the caller's own pid during a flush. They
  count as flushed bytes for the file, not as writes the process asked for.
- A write that the fast I/O path refuses is logged once with flags 0 and again
  as an IRP with the same thread, file, offset and size. The second is dropped.

The FileKey in an event is a kernel address that is reused once the file is
closed everywhere, often by the very next file the same program creates. Each
key therefore maps to a fresh tracker id after its name-delete event, so a
rotated log does not inherit the totals of the file it replaced.

No event names a file that was opened before the session started. Such files
are counted, and `resolve_names` looks their paths up through the writing
process's handles.

Payload layouts come from the provider manifest (versions 0 and 1 of each event):
    (Get-WinEvent -ListProvider Microsoft-Windows-Kernel-File).Events
"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import tempfile
import threading
import time
import uuid
from ctypes import wintypes as w
from typing import Self

from . import handles
from .rewrite import RewriteTracker

PROVIDER = "{EDD08927-9CC4-4E65-B970-C2560FB5C289}"
KEYWORD_FILENAME = 0x10
KEYWORD_CREATE = 0x80
KEYWORD_WRITE = 0x200
KEYWORDS = KEYWORD_FILENAME | KEYWORD_CREATE | KEYWORD_WRITE

EVENT_NAME_CREATE = 10
EVENT_NAME_DELETE = 11
EVENT_CREATE = 12
EVENT_WRITE = 16
EVENT_CREATE_NEW_FILE = 30

ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
EVENT_TRACE_REAL_TIME_MODE = 0x100
WNODE_FLAG_TRACED_GUID = 0x20000
PROCESS_TRACE_MODE_REAL_TIME = 0x100
PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000
EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1
EVENT_TRACE_CONTROL_STOP = 1
EVENT_TRACE_CONTROL_FLUSH = 3
IRP_PAGING_IO = 0x2
MAX_THREADS = 100_000
TRACE_LEVEL_INFORMATION = 4
EVENT_HEADER_FLAG_32_BIT_HEADER = 0x20
INVALID_TRACE_HANDLE = 0xFFFFFFFFFFFFFFFF
MAX_OBJECT_NAMES = 200_000


# ---- payload parsing (pure, 64-bit pointers) --------------------------------

def parse_write(version: int, data: bytes) -> tuple[int, int, int, int, int, int]:
    """-> (byte_offset, file_object, file_key, io_size, io_flags, thread)"""
    if version == 0:
        offset, _irp, thread, obj, key, size, flags = struct.unpack_from("<QQQQQII", data)
    else:
        offset, _irp, obj, key, thread, size, flags, _extra = struct.unpack_from("<QQQQIIII", data)
    return offset, obj, key, size, flags, thread


def parse_create(version: int, data: bytes) -> tuple[int, str]:
    """-> (file_object, file_name)"""
    if version == 0:
        obj = struct.unpack_from("<Q", data, 16)[0]
        return obj, _wide(data, 36)
    obj = struct.unpack_from("<Q", data, 8)[0]
    return obj, _wide(data, 32)


def parse_name(data: bytes) -> tuple[int, str]:
    """-> (file_key, file_name)"""
    return struct.unpack_from("<Q", data)[0], _wide(data, 8)


def _wide(data: bytes, start: int) -> str:
    raw = data[start:]
    raw = raw[:len(raw) - len(raw) % 2]
    return raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0]


def dos_path(nt_path: str, devices: dict[str, str]) -> str:
    r"""`\Device\HarddiskVolume3\x` -> `C:\x` when the device is in `devices`."""
    for device, drive in devices.items():
        if nt_path.startswith(device + "\\"):
            return drive + nt_path[len(device):]
    return nt_path


def device_map() -> dict[str, str]:
    r"""`\Device\HarddiskVolumeN` -> `C:` for every drive letter in use."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    found = {}
    buf = ctypes.create_unicode_buffer(1024)
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if k32.QueryDosDeviceW(letter + ":", buf, len(buf)):
            found[buf.value] = letter + ":"
    return found


def is_elevated() -> bool:
    return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())


# ---- ETW structures ---------------------------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", w.BYTE * 8)]

    @classmethod
    def parse(cls, text: str) -> GUID:
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class WNODE_HEADER(ctypes.Structure):
    _fields_ = [("BufferSize", w.ULONG), ("ProviderId", w.ULONG),
                ("HistoricalContext", ctypes.c_uint64), ("TimeStamp", ctypes.c_int64),
                ("Guid", GUID), ("ClientContext", w.ULONG), ("Flags", w.ULONG)]


class EVENT_TRACE_PROPERTIES(ctypes.Structure):
    _fields_ = [("Wnode", WNODE_HEADER), ("BufferSize", w.ULONG), ("MinimumBuffers", w.ULONG),
                ("MaximumBuffers", w.ULONG), ("MaximumFileSize", w.ULONG),
                ("LogFileMode", w.ULONG), ("FlushTimer", w.ULONG), ("EnableFlags", w.ULONG),
                ("AgeLimit", w.LONG), ("NumberOfBuffers", w.ULONG), ("FreeBuffers", w.ULONG),
                ("EventsLost", w.ULONG), ("BuffersWritten", w.ULONG),
                ("LogBuffersLost", w.ULONG), ("RealTimeBuffersLost", w.ULONG),
                ("LoggerThreadId", w.HANDLE), ("LogFileNameOffset", w.ULONG),
                ("LoggerNameOffset", w.ULONG)]


class _SessionProperties(ctypes.Structure):
    _fields_ = [("p", EVENT_TRACE_PROPERTIES), ("name", w.WCHAR * 256)]


class EVENT_TRACE_HEADER(ctypes.Structure):
    _fields_ = [("Size", w.USHORT), ("FieldTypeFlags", w.USHORT), ("Version", w.ULONG),
                ("ThreadId", w.ULONG), ("ProcessId", w.ULONG), ("TimeStamp", ctypes.c_int64),
                ("Guid", GUID), ("ProcessorTime", ctypes.c_uint64)]


class EVENT_TRACE(ctypes.Structure):
    _fields_ = [("Header", EVENT_TRACE_HEADER), ("InstanceId", w.ULONG),
                ("ParentInstanceId", w.ULONG), ("ParentGuid", GUID),
                ("MofData", ctypes.c_void_p), ("MofLength", w.ULONG),
                ("ClientContext", w.ULONG)]


class TRACE_LOGFILE_HEADER(ctypes.Structure):
    _fields_ = [("BufferSize", w.ULONG), ("Version", w.ULONG), ("ProviderVersion", w.ULONG),
                ("NumberOfProcessors", w.ULONG), ("EndTime", ctypes.c_int64),
                ("TimerResolution", w.ULONG), ("MaximumFileSize", w.ULONG),
                ("LogFileMode", w.ULONG), ("BuffersWritten", w.ULONG),
                ("LogInstanceGuid", GUID), ("LoggerName", ctypes.c_void_p),
                ("LogFileName", ctypes.c_void_p), ("TimeZone", ctypes.c_byte * 172),
                ("BootTime", ctypes.c_int64), ("PerfFreq", ctypes.c_int64),
                ("StartTime", ctypes.c_int64), ("ReservedFlags", w.ULONG),
                ("BuffersLost", w.ULONG)]


class EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [("Id", w.USHORT), ("Version", ctypes.c_ubyte), ("Channel", ctypes.c_ubyte),
                ("Level", ctypes.c_ubyte), ("Opcode", ctypes.c_ubyte), ("Task", w.USHORT),
                ("Keyword", ctypes.c_uint64)]


class EVENT_HEADER(ctypes.Structure):
    _fields_ = [("Size", w.USHORT), ("HeaderType", w.USHORT), ("Flags", w.USHORT),
                ("EventProperty", w.USHORT), ("ThreadId", w.ULONG), ("ProcessId", w.ULONG),
                ("TimeStamp", ctypes.c_int64), ("ProviderId", GUID),
                ("EventDescriptor", EVENT_DESCRIPTOR), ("ProcessorTime", ctypes.c_uint64),
                ("ActivityId", GUID)]


class EVENT_RECORD(ctypes.Structure):
    _fields_ = [("EventHeader", EVENT_HEADER), ("BufferContext", w.ULONG),
                ("ExtendedDataCount", w.USHORT), ("UserDataLength", w.USHORT),
                ("ExtendedData", ctypes.c_void_p), ("UserData", ctypes.c_void_p),
                ("UserContext", ctypes.c_void_p)]


_EVENT_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(EVENT_RECORD))


class EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [("LogFileName", w.LPWSTR), ("LoggerName", w.LPWSTR),
                ("CurrentTime", ctypes.c_int64), ("BuffersRead", w.ULONG),
                ("ProcessTraceMode", w.ULONG), ("CurrentEvent", EVENT_TRACE),
                ("LogfileHeader", TRACE_LOGFILE_HEADER), ("BufferCallback", ctypes.c_void_p),
                ("BufferSize", w.ULONG), ("Filled", w.ULONG), ("EventsLost", w.ULONG),
                ("EventRecordCallback", _EVENT_CALLBACK), ("IsKernelTrace", w.ULONG),
                ("Context", ctypes.c_void_p)]


def _advapi():
    lib = ctypes.WinDLL("advapi32", use_last_error=True)
    lib.StartTraceW.restype = w.ULONG
    lib.StartTraceW.argtypes = [ctypes.POINTER(ctypes.c_uint64), w.LPCWSTR, ctypes.c_void_p]
    lib.ControlTraceW.restype = w.ULONG
    lib.ControlTraceW.argtypes = [ctypes.c_uint64, w.LPCWSTR, ctypes.c_void_p, w.ULONG]
    lib.EnableTraceEx2.restype = w.ULONG
    lib.EnableTraceEx2.argtypes = [ctypes.c_uint64, ctypes.POINTER(GUID), w.ULONG,
                                   ctypes.c_ubyte, ctypes.c_uint64, ctypes.c_uint64, w.ULONG,
                                   ctypes.c_void_p]
    lib.OpenTraceW.restype = ctypes.c_uint64
    lib.OpenTraceW.argtypes = [ctypes.POINTER(EVENT_TRACE_LOGFILEW)]
    lib.ProcessTrace.restype = w.ULONG
    lib.ProcessTrace.argtypes = [ctypes.POINTER(ctypes.c_uint64), w.ULONG, ctypes.c_void_p,
                                 ctypes.c_void_p]
    lib.CloseTrace.restype = w.ULONG
    lib.CloseTrace.argtypes = [ctypes.c_uint64]
    return lib


def _session_properties() -> _SessionProperties:
    props = _SessionProperties()
    props.p.Wnode.BufferSize = ctypes.sizeof(props)
    props.p.Wnode.Flags = WNODE_FLAG_TRACED_GUID
    props.p.Wnode.ClientContext = 1
    props.p.LogFileMode = EVENT_TRACE_REAL_TIME_MODE
    # Buffers are per processor and are otherwise handed over only when full, so
    # a quiet writer's events could sit unseen until the session stops.
    props.p.FlushTimer = 1
    props.p.LoggerNameOffset = ctypes.sizeof(EVENT_TRACE_PROPERTIES)
    return props


class FileTrace:
    """Use as a context manager. Read `tracker` under `lock` while it runs."""

    def __init__(self, tracker: RewriteTracker, session: str = "writehawk-file") -> None:
        self.tracker = tracker
        self.session = session
        self.lock = threading.Lock()
        self.events = 0
        self.errors = 0
        self.retries = 0
        self.ready = False  # set by start() once a write of its own came through
        self._last_stamp = 0
        self._flush_mark = 0       # events stamped before this are what flush waits for
        self._late_arrival = 0.0   # when one of those last reached the callback
        self._fast_write: dict[int, tuple[int, int, int]] = {}
        self._ids: dict[int, int] = {}
        self._next_id = 1
        self._key_names: dict[int, str] = {}
        self._object_names: dict[int, str] = {}
        self._unnamed: dict[int, tuple[int, int]] = {}  # file id -> (pid, file object)
        # file id -> (where the name came from, file object, file key). Kept so a wrong
        # name can be traced to its source: `name-event`, `create-event` or `handles`.
        self.name_sources: dict[int, tuple[str, int, int]] = {}
        self._devices: dict[str, str] = {}
        self._callback = _EVENT_CALLBACK(self._on_record)
        self._session_handle = ctypes.c_uint64(0)
        self._trace_handle = ctypes.c_uint64(INVALID_TRACE_HANDLE)
        self._thread: threading.Thread | None = None
        self._lib = None

    def on_event(self, pid: int, event_id: int, version: int, data: bytes) -> None:
        with self.lock:
            self.events += 1
            if event_id == EVENT_WRITE:
                self._on_write(pid, *parse_write(version, data))
            elif event_id in (EVENT_CREATE, EVENT_CREATE_NEW_FILE):
                obj, name = parse_create(version, data)
                if len(self._object_names) >= MAX_OBJECT_NAMES:
                    self._object_names.clear()
                self._object_names[obj] = dos_path(name, self._devices)
            elif event_id == EVENT_NAME_CREATE:
                key, name = parse_name(data)
                self._key_names[key] = dos_path(name, self._devices)
            elif event_id == EVENT_NAME_DELETE:
                key, _name = parse_name(data)
                # Closed everywhere: no handle is left to look the name up through.
                self._unnamed.pop(self._ids.pop(key, None), None)
                self._key_names.pop(key, None)

    def resolve_names(self, min_bytes: int = 0, resolver=handles.resolve) -> int:
        """Name unnamed files with at least `min_bytes` written. Returns how many it named.

        Call it from outside the event callback; it walks the system handle table.
        """
        self.flush()
        with self.lock:
            written: dict[int, int] = {}
            for entry in self.tracker.files.values():
                if entry.file_id in self._unnamed:
                    written[entry.file_id] = written.get(entry.file_id, 0) + entry.bytes_written
            wanted = {self._unnamed[file_id]: file_id
                      for file_id, total in written.items() if total >= min_bytes}
        paths = resolver(set(wanted))
        with self.lock:
            for pair, path in paths.items():
                file_id = wanted[pair]
                self.tracker.set_name(file_id, path)
                self.name_sources[file_id] = ("handles", pair[1], 0)
                self._unnamed.pop(file_id, None)
        return len(paths)

    def _on_write(self, pid: int, offset: int, obj: int, key: int, size: int, flags: int,
                  thread: int) -> None:
        file_id = self._ids.get(key)
        if file_id is None:
            file_id = self._ids[key] = self._next_id
            self._next_id += 1
        if file_id not in self.tracker.names:
            by_key = self._key_names.get(key)
            # A paging write goes through a file object the cache made for itself.
            # No create event announced it, so whatever name is stored under its
            # address belongs to an earlier object that lived there.
            paging = bool(flags & IRP_PAGING_IO)
            name = by_key or (None if paging else self._object_names.get(obj))
            if name:
                self.tracker.set_name(file_id, name)
                self.name_sources[file_id] = ("name-event" if by_key else "create-event", obj,
                                              key)
                self._unnamed.pop(file_id, None)
            elif not paging:
                # No process holds a handle to the cache's file object either, so
                # only the writer's own is worth remembering.
                self._unnamed[file_id] = (pid, obj)
        if flags & IRP_PAGING_IO:
            self.tracker.add_flush(file_id, size)
        elif flags == 0:
            if len(self._fast_write) >= MAX_THREADS:
                self._fast_write.clear()
            self._fast_write[thread] = (key, offset, size)
            self.tracker.add_write(pid, file_id, offset, size)
        elif self._fast_write.pop(thread, None) == (key, offset, size):
            self.retries += 1
        else:
            self.tracker.add_write(pid, file_id, offset, size)

    def _on_record(self, record_ptr) -> None:
        try:
            record = record_ptr.contents
            header = record.EventHeader
            self._last_stamp = header.TimeStamp  # performance counter ticks
            if header.TimeStamp < self._flush_mark:
                self._late_arrival = time.monotonic()
            if header.Flags & EVENT_HEADER_FLAG_32_BIT_HEADER or not record.UserData:
                return
            data = ctypes.string_at(record.UserData, record.UserDataLength)
            self.on_event(header.ProcessId, header.EventDescriptor.Id,
                          header.EventDescriptor.Version, data)
        except Exception:  # noqa: BLE001 - must not raise into the ETW thread
            self.errors += 1

    def start(self) -> None:
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError("the file trace needs 64-bit Python on 64-bit Windows")
        self._lib = lib = _advapi()
        self._devices = device_map()
        props = _session_properties()
        status = lib.StartTraceW(ctypes.byref(self._session_handle), self.session,
                                 ctypes.byref(props))
        if status == ERROR_ALREADY_EXISTS:
            # A previous run died without stopping its session.
            lib.ControlTraceW(0, self.session, ctypes.byref(_session_properties()),
                              EVENT_TRACE_CONTROL_STOP)
            props = _session_properties()
            status = lib.StartTraceW(ctypes.byref(self._session_handle), self.session,
                                     ctypes.byref(props))
        if status == ERROR_ACCESS_DENIED:
            raise PermissionError("starting a file trace needs an elevated process")
        if status:
            raise ctypes.WinError(status)
        try:
            provider = GUID.parse(PROVIDER)
            status = lib.EnableTraceEx2(self._session_handle, ctypes.byref(provider),
                                        EVENT_CONTROL_CODE_ENABLE_PROVIDER,
                                        TRACE_LEVEL_INFORMATION, KEYWORDS, 0, 0, None)
            if status:
                raise ctypes.WinError(status)
            logfile = EVENT_TRACE_LOGFILEW()
            logfile.LoggerName = self.session
            logfile.ProcessTraceMode = (PROCESS_TRACE_MODE_REAL_TIME
                                        | PROCESS_TRACE_MODE_EVENT_RECORD)
            logfile.EventRecordCallback = self._callback
            handle = lib.OpenTraceW(ctypes.byref(logfile))
            if handle == INVALID_TRACE_HANDLE:
                raise ctypes.WinError(ctypes.get_last_error())
            self._trace_handle = ctypes.c_uint64(handle)
        except BaseException:
            self._stop_session()
            raise
        self._thread = threading.Thread(target=self._pump, name="writehawk-etw", daemon=True)
        self._thread.start()
        self.ready = self._wait_ready()

    def _wait_ready(self, timeout: float = 3.0) -> bool:
        """Return once the session delivers events, proven with a write of our own.

        Enabling the provider takes effect a moment after the call returns. Seen
        on Windows Server: writes made at once were missed. The marker file is
        written in a new temp folder, dropped from the totals and deleted.
        """
        folder = tempfile.mkdtemp(prefix="writehawk-ready-")
        path = os.path.join(folder, "marker")
        wanted = os.path.normcase(path)
        mine = os.getpid()
        deadline = time.monotonic() + timeout
        seen: list[int] = []
        try:
            while not seen and time.monotonic() < deadline:
                # A fresh open each round, so a create event names the file even
                # when the first ones were missed.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_BINARY)
                try:
                    os.write(fd, b"r")
                finally:
                    os.close(fd)
                self.flush(timeout=0.5, quiet=0.05)
                with self.lock:
                    seen = [f.file_id for f in self.tracker.files.values()
                            if f.pid == mine and os.path.normcase(
                                self.tracker.name_of(f.file_id) or "") == wanted]
        finally:
            with self.lock:
                for file_id in {f.file_id for f in self.tracker.files.values()
                                if os.path.normcase(self.tracker.name_of(f.file_id) or "")
                                == wanted}:
                    self.tracker.forget(file_id)
                    self.name_sources.pop(file_id, None)
            shutil.rmtree(folder, ignore_errors=True)
        return bool(seen)

    def _pump(self) -> None:
        self._lib.ProcessTrace(ctypes.byref(self._trace_handle), 1, None, None)

    def flush(self, timeout: float = 3.0, quiet: float = 0.3) -> bool:
        """Wait until everything written before this call has reached the callback.

        Each processor has its own buffer and the buffers arrive separately, so
        one event stamped after the call proves nothing about the other
        processors. The wait ends when a later event has arrived and no earlier
        one has for `quiet` seconds, with the buffers flushed again on every
        round. Returns False on `timeout`; True when not running.
        """
        if self._lib is None:
            return True
        asked = ctypes.c_int64()
        ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(asked))
        started = time.monotonic()
        self._late_arrival = started
        self._flush_mark = asked.value
        while time.monotonic() < started + timeout:
            self._lib.ControlTraceW(self._session_handle, None,
                                    ctypes.byref(_session_properties()),
                                    EVENT_TRACE_CONTROL_FLUSH)
            time.sleep(0.1)  # delivery happens on the pump thread
            if (self._last_stamp >= asked.value
                    and time.monotonic() - self._late_arrival >= quiet):
                return True
        return False

    def _stop_session(self) -> None:
        self._lib.ControlTraceW(self._session_handle, None, ctypes.byref(_session_properties()),
                                EVENT_TRACE_CONTROL_STOP)

    def stop(self) -> None:
        if self._lib is None:
            return
        self._stop_session()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        if self._trace_handle.value != INVALID_TRACE_HANDLE:
            self._lib.CloseTrace(self._trace_handle)
            self._trace_handle = ctypes.c_uint64(INVALID_TRACE_HANDLE)
        self._lib = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
