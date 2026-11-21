import msvcrt
import os
import struct

from writehawk.measure import handles


def _table(entries):
    body = b"".join(struct.pack("<QQQIHHII", obj, pid, handle, 0, 0, 0, 0, 0)
                    for obj, pid, handle in entries)
    return struct.pack("<QQ", len(entries), 0) + body


def test_parse_handle_table_matches_pid_and_object():
    table = _table([(0xAAA, 10, 0x44), (0xBBB, 10, 0x48), (0xAAA, 11, 0x50)])
    assert handles.parse_handle_table(table, {(10, 0xBBB), (11, 0xAAA), (12, 0xAAA)}) == {
        (10, 0xBBB): 0x48, (11, 0xAAA): 0x50}


def test_parse_handle_table_ignores_a_truncated_tail():
    table = _table([(0xAAA, 10, 0x44), (0xBBB, 10, 0x48)])[:-8]
    assert handles.parse_handle_table(table, {(10, 0xAAA), (10, 0xBBB)}) == {(10, 0xAAA): 0x44}


def test_strip_prefix():
    assert handles.strip_prefix("\\\\?\\C:\\a\\b.log") == "C:\\a\\b.log"
    assert handles.strip_prefix("\\\\?\\UNC\\srv\\share\\b.log") == "\\\\srv\\share\\b.log"
    assert handles.strip_prefix("C:\\plain") == "C:\\plain"


def test_resolve_nothing_is_a_no_op():
    assert handles.resolve(set()) == {}


def test_live_handle_table_lists_this_process():
    table = handles.read_handle_table()
    count = struct.unpack_from("<Q", table)[0]
    assert count > 100
    pids = {struct.unpack_from("<Q", table, 16 + i * 40 + 8)[0] for i in range(min(count, 500000))}
    assert os.getpid() in pids


def test_live_path_of_own_file_handle(tmp_path):
    path = tmp_path / "held.bin"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
    try:
        assert handles.path_of_handle(os.getpid(), msvcrt.get_osfhandle(fd)) == str(path)
    finally:
        os.close(fd)


def test_live_path_of_a_pipe_handle_is_none():
    read_fd, write_fd = os.pipe()
    try:
        assert handles.path_of_handle(os.getpid(), msvcrt.get_osfhandle(write_fd)) is None
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_path_of_handle_in_a_missing_process_is_none():
    assert handles.path_of_handle(0xFFFFFFF0, 4) is None
