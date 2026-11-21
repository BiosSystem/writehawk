import os

import pytest

from writehawk.measure.diskstat import read_counters, volume_device


def test_volume_device():
    assert volume_device(r"c:\Users\x") == r"\\.\C:"
    with pytest.raises(ValueError):
        volume_device(r"\\server\share\x")


def test_live_counters_do_not_go_backwards(tmp_path):
    device = volume_device(str(tmp_path))
    before = read_counters(device)
    path = tmp_path / "x.bin"
    with open(path, "wb") as f:
        f.write(os.urandom(1 << 20))
        f.flush()
        os.fsync(f.fileno())
    after = read_counters(device)
    assert after.bytes_written - before.bytes_written >= 1 << 20
    assert after.write_count > before.write_count


def test_missing_device_raises():
    with pytest.raises(OSError):
        read_counters(r"\\.\PhysicalDrive99")
