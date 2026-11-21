"""The write pattern of a known cause, replayed where its files really live.

The real bugs cannot be produced on demand, so a child process rewrites a
file at the path the rule names. That writes under %ProgramData%, which is
why it runs only inside the sandbox harness.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

from writehawk.context.gpu import Gpu
from writehawk.measure import filetrace as ft
from writehawk.measure.rewrite import RewriteTracker
from writehawk.rules import catalog
from writehawk.rules import evaluate as ev

WRITER = """
import os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT | os.O_BINARY)
for _ in range(400):
    os.lseek(fd, 0, 0)
    os.write(fd, b"x" * 4096)
os.close(fd)
"""


def card(vendor, release):
    return Gpu("PCI\\X", "Card", vendor, 1, 2, "1.2.3.4", release, "", "", 1)


@pytest.mark.skipif(os.environ.get("WRITEHAWK_SANDBOX") != "1" or not ft.is_elevated(),
                    reason="writes under ProgramData: runs only inside tools/sandbox")
def test_sandbox_the_nvidia_rule_matches_its_write_pattern():
    rule = next(rule for rule in catalog.load() if rule.id == "nvidia-nvtopps-log-rewrite")
    # The vendor folder can exist without the vendor's hardware (it did in the
    # sandbox), so only the folders made here are removed afterwards.
    folder = os.path.expandvars("%ProgramData%\\NVIDIA Corporation\\nvtopps\\nct")
    assert not os.path.exists(os.path.dirname(folder)), "a real nvtopps folder is present"
    made = []
    path = folder
    while not os.path.exists(path):
        made.append(path)
        path = os.path.dirname(path)
    os.makedirs(folder)
    log = os.path.join(folder, "nvlog.nvlgstg")
    try:
        before = ev.snapshot_files(rule)
        tracker = RewriteTracker()
        with ft.FileTrace(tracker, session="writehawk-test") as trace:
            time.sleep(0.3)
            subprocess.run([sys.executable, "-c", WRITER, log], check=True)
            trace.resolve_names()
        traced = ev.trace_activity(rule, tracker)
        changed = ev.file_activity(before, ev.snapshot_files(rule))
    finally:
        shutil.rmtree(made[-1])

    assert [os.path.normcase(item.path) for item in traced] == [os.path.normcase(log)]
    assert traced[0].rewrite_ratio == 400.0
    assert [item.path for item in changed] == [log]

    def nothing_set(_key, _name):
        return None

    affected = ev.evaluate(rule, [card("nvidia", "621.24")], nothing_set, traced)
    assert affected.status == ev.ACTIVE
    quiet_and_fixed = ev.evaluate(rule, [card("nvidia", "621.35")], nothing_set)
    assert quiet_and_fixed.status == ev.FIXED
    other_hardware = ev.evaluate(rule, [card("amd", "24.10.24")], nothing_set, traced)
    assert other_hardware.status == ev.NOT_APPLICABLE
    # The same writes are not also reported as an unexplained loop.
    assert not any("nvlog" in loop.path for loop in ev.rewrite_loops(tracker, [rule], 20.0, 0))
