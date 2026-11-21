"""Measure what a rewrite loop and an append cost, side by side.

    writehawk probe

Runs three writers of the same volume against a temp file and prints, for
each: the process write counter, how much the file grew, and how much the
volume's write counter moved. Elevated, it also runs the file trace and prints
the rewrite ratio taken from write offsets and the bytes flushed to the test
file itself (the volume column also includes file system log and metadata).

The volume counter includes everything else writing to that volume, so an idle
baseline over the same settle time is printed first. On a busy system volume
the noise can exceed the workload; use `--dir` to run on a quiet volume.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

from .diskstat import read_counters, volume_device
from .filetrace import FileTrace, is_elevated
from .rewrite import RewriteTracker
from .sampler import read_process

BLOCK = 4096
MODES = {
    # name: (rewrite in place, fsync every write, write count)
    "rewrite-buffered": (True, False, 5000),
    "rewrite-flushed": (True, True, 1500),
    "append-buffered": (False, False, 5000),
}
SETTLE = 8.0  # seconds for the lazy writer to flush cached pages


def write_loop(path: str, rewrite: bool, flush: bool, count: int) -> dict:
    block = os.urandom(BLOCK)
    before = read_process(os.getpid())[1]
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
    try:
        for _ in range(count):
            if rewrite:
                os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, block)
            if flush:
                os.fsync(fd)
    finally:
        os.close(fd)
    after = read_process(os.getpid())[1]
    return {"pid": os.getpid(), "counter_bytes": after.write_bytes - before.write_bytes,
            "counter_ops": after.write_ops - before.write_ops}


def _run_mode(mode: str, path: str, device: str) -> dict:
    if os.path.exists(path):
        os.remove(path)
    disk_before = read_counters(device).bytes_written
    # The child must find this package even when it was never installed.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        filter(None, [root, os.environ.get("PYTHONPATH")])))
    out = subprocess.run([sys.executable, "-m", "writehawk.measure.probe", "--child", mode, path],
                         capture_output=True, text=True, check=True, env=env)
    result = json.loads(out.stdout)
    time.sleep(SETTLE)
    result["disk_bytes"] = read_counters(device).bytes_written - disk_before
    result["file_bytes"] = os.path.getsize(path)
    return result


def run(parent: str | None = None) -> int:
    """`parent` is where the scratch folder is made; default is the temp folder.

    Point it at a quiet volume for a cleaner volume column.
    """
    folder = tempfile.mkdtemp(prefix="writehawk-probe-", dir=parent)
    device = volume_device(folder)
    tracker = RewriteTracker()
    trace = FileTrace(tracker) if is_elevated() else None
    if trace:
        trace.start()
    try:
        start = read_counters(device).bytes_written
        time.sleep(SETTLE)
        idle = read_counters(device).bytes_written - start
        rows = []
        for mode in MODES:
            path = os.path.join(folder, mode + ".bin")
            row = _run_mode(mode, path, device)
            row["mode"] = mode
            rows.append(row)
            os.remove(path)
    finally:
        if trace:
            trace.stop()
        os.rmdir(folder)

    mb = 1 / (1024 * 1024)
    print(f"volume {device}, idle baseline over {SETTLE:.0f}s: {idle * mb:.2f} MB written")
    print(f"{'mode':<18}{'counter MB':>11}{'file MB':>9}{'volume MB':>11}"
          f"{'traced ratio':>14}{'flushed MB':>12}")
    for row in rows:
        ratio = flushed = "n/a"
        if trace:
            mine = [f for f in tracker.files.values() if f.pid == row["pid"]]
            if mine:
                data_file = max(mine, key=lambda f: f.bytes_written)
                ratio = f"{data_file.rewrite_ratio:.1f}x"
                flushed = f"{tracker.flushed_bytes(data_file.file_id) * mb:.2f}"
        print(f"{row['mode']:<18}{row['counter_bytes'] * mb:>11.2f}{row['file_bytes'] * mb:>9.2f}"
              f"{row['disk_bytes'] * mb:>11.2f}{ratio:>14}{flushed:>12}")
    if trace:
        print(f"trace: {trace.events} events, {trace.errors} callback errors, "
              f"{trace.retries} fast I/O retries dropped")
    else:
        print("trace: skipped, not elevated")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        rewrite, flush, count = MODES[sys.argv[2]]
        print(json.dumps(write_loop(sys.argv[3], rewrite, flush, count)))
        sys.exit(0)
    sys.exit(run())
