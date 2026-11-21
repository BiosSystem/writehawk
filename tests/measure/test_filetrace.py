import ctypes
import os
import struct
import subprocess
import sys
import time

import pytest

from writehawk.measure import filetrace as ft
from writehawk.measure import handles
from writehawk.measure.rewrite import RewriteTracker


def _wide(text):
    return (text + "\0").encode("utf-16-le")


def _write_v1(offset, obj, key, size, *, flags=0, thread=77):
    return struct.pack("<QQQQIIII", offset, 0xAA, obj, key, thread, size, flags, 0)


def test_struct_sizes_match_the_x64_sdk():
    assert ctypes.sizeof(ft.WNODE_HEADER) == 48
    assert ctypes.sizeof(ft.EVENT_TRACE_PROPERTIES) == 120
    assert ctypes.sizeof(ft.EVENT_TRACE) == 88
    assert ctypes.sizeof(ft.TRACE_LOGFILE_HEADER) == 280
    assert ctypes.sizeof(ft.EVENT_HEADER) == 80
    assert ctypes.sizeof(ft.EVENT_RECORD) == 112
    assert ctypes.sizeof(ft.EVENT_TRACE_LOGFILEW) == 448


def test_parse_write_both_versions():
    v0 = struct.pack("<QQQQQII", 8192, 0xAA, 0xBB, 0x10, 0x20, 4096, 0)
    assert ft.parse_write(0, v0) == (8192, 0x10, 0x20, 4096, 0, 0xBB)
    v1 = _write_v1(8192, 0x10, 0x20, 4096, flags=0x60043)
    assert ft.parse_write(1, v1) == (8192, 0x10, 0x20, 4096, 0x60043, 77)


def test_parse_create_both_versions():
    name = r"\Device\HarddiskVolume3\a.log"
    v0 = struct.pack("<QQQIII", 1, 2, 0x10, 0, 0, 0) + _wide(name)
    v1 = struct.pack("<QQIIII", 1, 0x10, 2, 0, 0, 0) + _wide(name)
    assert ft.parse_create(0, v0) == (0x10, name)
    assert ft.parse_create(1, v1) == (0x10, name)


def test_parse_name():
    assert ft.parse_name(struct.pack("<Q", 0x20) + _wide(r"\Device\X\b")) == (0x20, r"\Device\X\b")


def test_dos_path():
    devices = {r"\Device\HarddiskVolume3": "C:", r"\Device\HarddiskVolume30": "E:"}
    assert ft.dos_path(r"\Device\HarddiskVolume3\a\b.log", devices) == r"C:\a\b.log"
    assert ft.dos_path(r"\Device\HarddiskVolume30\x", devices) == r"E:\x"
    assert ft.dos_path(r"\Device\Mup\server\x", devices) == r"\Device\Mup\server\x"


def test_events_feed_the_tracker_and_name_the_file():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    trace._devices = {r"\Device\HarddiskVolume3": "C:"}
    create = struct.pack("<QQIIII", 1, 0x10, 2, 0, 0, 0) + _wide(r"\Device\HarddiskVolume3\a.log")
    trace.on_event(500, ft.EVENT_CREATE, 1, create)
    for _ in range(40):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
    trace.on_event(500, 15, 1, b"")  # a read: counted, otherwise ignored
    (entry,) = tracker.top()
    assert (entry.pid, entry.bytes_written, entry.rewrite_ratio) == (500, 40 * 4096, 40.0)
    assert tracker.name_of(entry.file_id) == r"C:\a.log"
    assert trace.events == 42


def test_paging_writes_count_as_flushed_not_as_rewrites():
    # Flag values as seen live: 0x60043 for a flush in the caller, 0x60003 for the lazy writer.
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    for _ in range(10):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096, flags=0x60043))
    trace.on_event(4, ft.EVENT_WRITE, 1, _write_v1(0, 0x11, 0x20, 4096, flags=0x60003))
    (entry,) = tracker.top()
    assert (entry.pid, entry.writes, entry.rewrite_ratio) == (500, 10, 10.0)
    assert tracker.flushed_bytes(entry.file_id) == 11 * 4096
    assert tracker.flushed_bytes(entry.file_id + 1) == 0


def test_fast_io_retry_is_counted_once():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096, flags=0x60A00))
    assert tracker.top()[0].writes == 1
    assert trace.retries == 1


def test_irp_writes_that_are_not_retries_all_count():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    irp = _write_v1(0, 0x10, 0x20, 4096, flags=0x60A00)
    trace.on_event(500, ft.EVENT_WRITE, 1, irp)  # no fast write before it
    trace.on_event(500, ft.EVENT_WRITE, 1, irp)  # rewrite on the IRP path
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
    other_thread = _write_v1(0, 0x10, 0x20, 4096, flags=0x60A00, thread=78)
    trace.on_event(500, ft.EVENT_WRITE, 1, other_thread)
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(4096, 0x10, 0x20, 4096))
    other_offset = _write_v1(8192, 0x10, 0x20, 4096, flags=0x60A00)
    trace.on_event(500, ft.EVENT_WRITE, 1, other_offset)
    assert tracker.top()[0].writes == 6
    assert trace.retries == 0


def test_name_event_names_a_file_opened_before_the_trace():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    name = struct.pack("<Q", 0x20) + _wide(r"\Device\X\old.log")
    trace.on_event(4, ft.EVENT_NAME_CREATE, 0, name)
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x99, 0x20, 100))
    assert tracker.name_of(tracker.top()[0].file_id) == r"\Device\X\old.log"


def test_a_reused_file_key_is_a_new_file_after_name_delete():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    key = struct.pack("<Q", 0x20)
    trace.on_event(500, ft.EVENT_NAME_CREATE, 0, key + _wide(r"\Device\X\app.log"))
    for _ in range(5):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
    trace.on_event(500, ft.EVENT_NAME_DELETE, 0, key + _wide(r"\Device\X\app.log"))
    trace.on_event(500, ft.EVENT_NAME_CREATE, 0, key + _wide(r"\Device\X\app.1.log"))
    for _ in range(3):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x11, 0x20, 4096))
    trace.on_event(4, ft.EVENT_WRITE, 1, _write_v1(0, 0x12, 0x20, 4096, flags=0x60003))
    first, second = tracker.top()
    assert (first.writes, tracker.name_of(first.file_id)) == (5, r"\Device\X\app.log")
    assert (second.writes, tracker.name_of(second.file_id)) == (3, r"\Device\X\app.1.log")
    assert tracker.flushed_bytes(first.file_id) == 0
    assert tracker.flushed_bytes(second.file_id) == 4096


def test_the_source_of_each_name_is_recorded():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    trace.on_event(500, ft.EVENT_NAME_CREATE, 0, struct.pack("<Q", 0x20) + _wide("a.log"))
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x10, 0x20, 4096))
    trace.on_event(500, ft.EVENT_CREATE, 1,
                   struct.pack("<QQ", 0, 0x11) + b"\0" * 16 + _wide("b.log"))
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x11, 0x21, 4096))
    by_name = {tracker.name_of(file_id): source
               for file_id, source in trace.name_sources.items()}
    assert by_name == {"a.log": ("name-event", 0x10, 0x20),
                       "b.log": ("create-event", 0x11, 0x21)}


def test_a_paging_write_is_not_named_from_a_stale_file_object():
    # Seen live: the cache's file object got the address of an object that a
    # failed open had used moments before, and the file took that open's name.
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    trace.on_event(500, ft.EVENT_CREATE, 1,
                   struct.pack("<QQ", 0, 0x99) + bytes(16) + _wide("other.txt"))
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x77, 0x20, 4096))
    trace.on_event(4, ft.EVENT_WRITE, 1, _write_v1(0, 0x99, 0x20, 4096, flags=0x60003))
    (entry,) = tracker.top()
    assert tracker.name_of(entry.file_id) is None
    assert tracker.flushed_bytes(entry.file_id) == 4096
    assert trace.resolve_names(resolver=lambda wanted: {(500, 0x77): "real.log"}) == 1
    assert tracker.name_of(entry.file_id) == "real.log"


def test_unnamed_file_is_named_through_the_writer_handle():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    for _ in range(20):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x77, 0x20, 4096))
    trace.on_event(4, ft.EVENT_WRITE, 1, _write_v1(0, 0x88, 0x20, 4096, flags=0x60003))
    asked = []

    def resolver(wanted):
        asked.append(wanted)
        return {(500, 0x77): r"C:\logs\old.log"}

    assert trace.resolve_names(resolver=resolver) == 1
    assert asked == [{(500, 0x77)}]  # the writer's file object, not the lazy writer's
    assert tracker.name_of(tracker.top()[0].file_id) == r"C:\logs\old.log"
    assert trace.name_sources[tracker.top()[0].file_id] == ("handles", 0x77, 0)
    assert trace.resolve_names(resolver=lambda wanted: asked.append(wanted) or {}) == 0
    assert asked[-1] == set()  # nothing left to ask


def test_resolve_names_skips_small_files_named_files_and_closed_files():
    tracker = RewriteTracker()
    trace = ft.FileTrace(tracker)
    trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x71, 0x21, 100))      # small
    for _ in range(10):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x72, 0x22, 4096))  # closed below
    create = struct.pack("<QQIIII", 1, 0x73, 2, 0, 0, 0) + _wide(r"\Device\X\named.log")
    trace.on_event(500, ft.EVENT_CREATE, 1, create)
    for _ in range(10):
        trace.on_event(500, ft.EVENT_WRITE, 1, _write_v1(0, 0x73, 0x23, 4096))  # named
    trace.on_event(500, ft.EVENT_NAME_DELETE, 0, struct.pack("<Q", 0x22) + _wide("x"))
    asked = []
    assert trace.resolve_names(min_bytes=1000, resolver=lambda w: asked.append(w) or {}) == 0
    assert asked == [set()]


def test_device_map_has_the_system_drive():
    assert os.environ["SYSTEMDRIVE"].upper() in ft.device_map().values()


def test_start_without_elevation_says_so():
    if ft.is_elevated():
        pytest.skip("elevated")
    with pytest.raises(PermissionError):
        ft.FileTrace(RewriteTracker(), session="writehawk-test").start()


def test_live_trace_sees_a_rewrite_loop(tmp_path):
    if not ft.is_elevated():
        pytest.skip("needs elevation to start a trace session")
    tracker = RewriteTracker()
    path = tmp_path / "loop.bin"
    with ft.FileTrace(tracker, session="writehawk-test") as trace:
        time.sleep(0.5)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
        for _ in range(300):
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"x" * 4096)
        os.close(fd)
        assert trace.flush()  # a fixed sleep here was seen to be too short once
    mine = [f for f in tracker.files.values()
            if f.pid == os.getpid() and (tracker.name_of(f.file_id) or "").endswith("loop.bin")]
    assert trace.errors == 0
    assert mine, f"no write events for {path} among {trace.events} events"
    assert mine[0].rewrite_ratio >= 250


def test_live_flush_and_append_are_not_double_counted(tmp_path):
    if not ft.is_elevated():
        pytest.skip("needs elevation to start a trace session")
    tracker = RewriteTracker()
    with ft.FileTrace(tracker, session="writehawk-test") as trace:
        time.sleep(0.5)
        fd = os.open(tmp_path / "flushed.bin", os.O_RDWR | os.O_CREAT | os.O_BINARY)
        for _ in range(100):
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"x" * 4096)
            os.fsync(fd)
        os.close(fd)
        fd = os.open(tmp_path / "appended.bin", os.O_RDWR | os.O_CREAT | os.O_BINARY)
        for _ in range(500):
            os.write(fd, b"x" * 4096)
        os.close(fd)
        assert trace.flush()
    assert trace.errors == 0
    by_name = {os.path.basename(tracker.name_of(f.file_id) or ""): f
               for f in tracker.files.values() if f.pid == os.getpid()}
    flushed, appended = by_name["flushed.bin"], by_name["appended.bin"]
    assert flushed.writes == 100
    assert flushed.rewrite_ratio == 100.0
    assert tracker.flushed_bytes(flushed.file_id) >= 100 * 4096
    assert appended.writes == 500
    assert appended.rewrite_ratio == 1.0



def test_live_trace_names_a_file_opened_before_it_started(tmp_path):
    if not ft.is_elevated():
        pytest.skip("needs elevation to start a trace session")
    fd = os.open(tmp_path / "early.bin", os.O_RDWR | os.O_CREAT | os.O_BINARY)
    os.write(fd, b"x" * 4096)
    tracker = RewriteTracker()
    with ft.FileTrace(tracker, session="writehawk-test") as trace:
        time.sleep(0.5)
        for _ in range(50):
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"x" * 4096)
        assert trace.flush()
        mine = [f for f in tracker.files.values() if f.pid == os.getpid() and f.writes == 50]
        assert mine, "the writes were not seen"
        assert tracker.name_of(mine[0].file_id) is None  # no event names it
        trace.resolve_names()
    os.close(fd)
    assert tracker.name_of(mine[0].file_id) == str(tmp_path / "early.bin")


def test_live_trace_names_a_file_held_open_by_another_process(tmp_path):
    if not ft.is_elevated():
        pytest.skip("needs elevation to start a trace session")
    path = tmp_path / "service.log"
    code = ("import os,sys,time\n"
            "fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT|os.O_BINARY)\n"
            "print('open',flush=True)\n"
            "sys.stdin.readline()\n"
            "[(os.lseek(fd,0,0),os.write(fd,b'x'*4096)) for _ in range(80)]\n"
            "print('written',flush=True)\n"
            "sys.stdin.readline()\n")
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "open"
        tracker = RewriteTracker()
        with ft.FileTrace(tracker, session="writehawk-test") as trace:
            time.sleep(0.5)
            child.stdin.write("go\n")
            child.stdin.flush()
            assert child.stdout.readline().strip() == "written"
            trace.resolve_names()  # straight after the writes: relies on flush
            seen = [(f.pid, f.writes, tracker.name_of(f.file_id), trace._unnamed.get(f.file_id))
                    for f in tracker.files.values() if f.writes >= 40]
        theirs = [f for f in tracker.files.values() if f.pid == child.pid and f.writes == 80]
        assert theirs, f"child {child.pid} not seen; files with 40+ writes: {seen}"
        assert tracker.name_of(theirs[0].file_id) == str(path), seen
        assert theirs[0].rewrite_ratio == 80.0
    finally:
        child.stdin.close()
        child.wait(timeout=10)


SYSTEM_WRITER = """
import os, sys, time
folder = sys.argv[1]
fd = os.open(os.path.join(folder, "service.log"), os.O_RDWR | os.O_CREAT | os.O_BINARY)
open(os.path.join(folder, "ready"), "w").close()
deadline = time.time() + 90
while not os.path.exists(os.path.join(folder, "go")) and time.time() < deadline:
    time.sleep(0.1)
for _ in range(80):
    os.lseek(fd, 0, 0)
    os.write(fd, b"x" * 4096)
open(os.path.join(folder, "written"), "w").close()
while not os.path.exists(os.path.join(folder, "stop")) and time.time() < deadline:
    time.sleep(0.1)
"""


def _wait_for(path, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


def test_sandbox_trace_names_a_file_held_open_by_a_system_process(tmp_path):
    # Registers a scheduled task that runs as SYSTEM, so it runs only in the sandbox.
    if os.environ.get("WRITEHAWK_SANDBOX") != "1" or not ft.is_elevated():
        pytest.skip("changes the system: runs only inside tools/sandbox")
    script = tmp_path / "writer.py"
    script.write_text(SYSTEM_WRITER)
    task = "writehawk-test-writer"
    command = f'"{sys.executable}" "{script}" "{tmp_path}"'
    subprocess.run(["schtasks", "/create", "/f", "/tn", task, "/ru", "SYSTEM", "/sc", "once",
                    "/st", "23:59", "/tr", command], check=True, capture_output=True)
    try:
        subprocess.run(["schtasks", "/run", "/tn", task], check=True, capture_output=True)
        assert _wait_for(tmp_path / "ready"), "the SYSTEM task did not start"
        tracker = RewriteTracker()
        seen = []
        with ft.FileTrace(tracker, session="writehawk-test") as trace:
            deliver = trace.on_event

            def spy(pid, event_id, version, data):
                if event_id == ft.EVENT_WRITE:
                    _, obj, key, _, flags, _ = ft.parse_write(version, data)
                    row = (pid, "write", hex(obj), hex(key), hex(flags))
                elif event_id in (ft.EVENT_CREATE, ft.EVENT_CREATE_NEW_FILE):
                    obj, name = ft.parse_create(version, data)
                    row = (pid, f"create{event_id}", hex(obj), name[-24:])
                else:
                    key, name = ft.parse_name(data)
                    row = (pid, f"name{event_id}", hex(key), name[-24:])
                if not seen or seen[-1][0] != row:
                    seen.append([row, 0])
                seen[-1][1] += 1
                deliver(pid, event_id, version, data)

            trace.on_event = spy
            time.sleep(0.5)
            (tmp_path / "go").touch()
            assert _wait_for(tmp_path / "written")
            trace.resolve_names()  # straight after the writes: relies on flush
            why = {pair: handles.diagnose(*pair) for pair in trace._unnamed.values()}
        mine = os.getpid()
        theirs = [f for f in tracker.files.values() if f.writes == 80 and f.pid != mine]
        assert theirs, "the SYSTEM writer was not seen"
        source, obj, key = trace.name_sources.get(theirs[0].file_id, ("none", 0, 0))
        why["named by"] = f"{source}, object {obj:#x}, key {key:#x}"
        why["writer"] = theirs[0].pid
        folder = tmp_path.name[-24:]
        for row, count in seen:  # shown by pytest only when the test fails
            if (row[0] == theirs[0].pid or folder[-8:] in str(row[-1])
                    or hex(obj) in row or hex(key) in row):
                print(count, *row)
        assert tracker.name_of(theirs[0].file_id) == str(tmp_path / "service.log"), why
    finally:
        (tmp_path / "stop").touch()
        subprocess.run(["schtasks", "/delete", "/f", "/tn", task], check=False,
                       capture_output=True)
