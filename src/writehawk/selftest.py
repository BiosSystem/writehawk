"""`writehawk selftest`: does each part of the tool work on this machine?

Every check is read-only, except the file trace checks, which write and delete
a small file in a new temp folder. The output names the Windows build and
nothing that identifies the machine, so it can be pasted into a public report.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__
from .context import drivers, gpu, protect, session, storage
from .measure.diskstat import read_counters, volume_device
from .measure.filetrace import FileTrace, is_elevated
from .measure.rewrite import RewriteTracker
from .measure.sampler import list_processes, read_process
from .rules import catalog

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


class Skip(Exception):  # noqa: N818 - reads as "raise Skip(reason)"
    pass


def windows_name(build: int, product_type: int) -> str:
    """Product type 1 is a workstation; 2 and 3 are servers."""
    if product_type != 1:
        return "Windows Server"
    return "Windows 11" if build >= 22000 else "Windows 10"


def describe_system() -> str:
    version = sys.getwindowsversion()
    name = windows_name(version.build, version.product_type)
    python = ".".join(str(part) for part in sys.version_info[:3])
    bits = "64-bit" if sys.maxsize > 2**32 else "32-bit"
    return (f"writehawk {__version__}, {name} build {version.major}.{version.minor}."
            f"{version.build}, Python {python} {bits}")


def run_checks(checks: list[tuple[str, Callable[[], str]]]) -> list[Result]:
    results = []
    for name, check in checks:
        try:
            results.append(Result(name, PASS, check()))
        except Skip as reason:
            results.append(Result(name, SKIP, str(reason)))
        except Exception as error:  # noqa: BLE001 - any failure is the answer here
            results.append(Result(name, FAIL, f"{type(error).__name__}: {error}"))
    return results


def format_results(system: str, results: list[Result]) -> str:
    lines = [system, ""]
    lines.extend(f"{r.status}  {r.name}: {r.detail}" for r in results)
    counts = {status: sum(1 for r in results if r.status == status)
              for status in (PASS, FAIL, SKIP)}
    lines.extend(["", f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped"])
    if any(r.status == SKIP and "administrator" in r.detail for r in results):
        lines.append("Run it again from an administrator terminal to include the skipped trace "
                     "checks.")
    return "\n".join(lines)


# --- the checks ------------------------------------------------------------------------------

def _processes() -> str:
    found = list_processes()
    if not found:
        raise RuntimeError("no processes listed")
    return f"{len(found)} processes listed"


def _own_counters() -> str:
    if read_process(os.getpid()) is None:
        raise RuntimeError("could not read this process's own I/O counters")
    return "read for this process"


def _volume_counters() -> str:
    device = volume_device(tempfile.gettempdir())
    counters = read_counters(device)
    return f"{device[-2:]} has {counters.write_count} writes counted since boot"


def _graphics() -> str:
    found = gpu.gpus()
    vendors = sorted({g.vendor for g in found})
    return f"{len(found)} found ({', '.join(vendors) or 'none'})"


def _display_paths() -> str:
    active = gpu.active_adapters()
    if active is None:
        raise Skip("no desktop session to ask")
    return f"{len(active)} active"


def _volumes() -> str:
    found = storage.volumes()
    system = os.environ.get("SYSTEMDRIVE", "C:").upper()
    if not any(v.root.upper().startswith(system) for v in found):
        raise RuntimeError(f"system drive {system} not listed")
    return f"{len(found)} listed, media: {', '.join(sorted({v.media for v in found}))}"


def _session() -> str:
    now = session.read()
    return f"state {now.state}"


def _signatures() -> str:
    image = os.path.expandvars("%SystemRoot%\\System32\\csrss.exe")
    found = protect.signature_of(image)
    if not found.valid:
        raise RuntimeError(f"csrss.exe signature: {found.status}")
    return f"csrss.exe signed by {found.signer}"


def _catalog() -> str:
    return f"{len(catalog.load())} rules loaded"


def _delivery() -> str:
    facts = drivers.read()
    return f"vendor updaters checked for {len(facts.updaters)} vendors"


def _need_elevation() -> None:
    if not is_elevated():
        raise Skip("needs an administrator terminal")


def _rewrite(fd: int, times: int) -> None:
    for _ in range(times):
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, b"w" * 4096)


def _file_trace() -> str:
    _need_elevation()
    with tempfile.TemporaryDirectory(prefix="writehawk-selftest-") as folder:
        # realpath: the trace reports long names, and TEMP can be a short 8.3 path.
        path = os.path.realpath(os.path.join(folder, "loop.bin"))
        tracker = RewriteTracker()
        with FileTrace(tracker, session="writehawk-selftest") as trace:
            if not trace.ready:
                raise RuntimeError("the trace started but delivered no events within 10 s")
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
            try:
                _rewrite(fd, 50)
            finally:
                os.close(fd)
            if not trace.flush():
                raise RuntimeError("the trace did not deliver its events in time")
        mine = [f for f in tracker.files.values()
                if f.pid == os.getpid() and os.path.normcase(tracker.name_of(f.file_id) or "")
                == os.path.normcase(path)]
        if not mine:
            raise RuntimeError(f"the test file was not seen ({trace.events} events)")
        if mine[0].writes != 50 or mine[0].rewrite_ratio != 50.0:
            raise RuntimeError(f"expected 50 writes at ratio 50, saw {mine[0].writes} at "
                               f"{mine[0].rewrite_ratio}")
        return f"50 rewrites seen, ratio 50, named ({trace.events} events)"


def _handle_naming() -> str:
    _need_elevation()
    with tempfile.TemporaryDirectory(prefix="writehawk-selftest-") as folder:
        path = os.path.realpath(os.path.join(folder, "early.bin"))
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
        try:
            os.write(fd, b"w" * 4096)
            tracker = RewriteTracker()
            with FileTrace(tracker, session="writehawk-selftest") as trace:
                _rewrite(fd, 50)
                trace.resolve_names()
        finally:
            os.close(fd)
        mine = [f for f in tracker.files.values() if f.pid == os.getpid() and f.writes == 50]
        if not mine:
            raise RuntimeError("the writes were not seen")
        name = tracker.name_of(mine[0].file_id)
        if os.path.normcase(name or "") != os.path.normcase(path):
            raise RuntimeError(f"named {name!r}")
        return "a file opened before the trace was named"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("process list", _processes),
    ("process write counters", _own_counters),
    ("volume write counters", _volume_counters),
    ("graphics cards and drivers", _graphics),
    ("active displays", _display_paths),
    ("volumes and media type", _volumes),
    ("idle and fullscreen state", _session),
    ("signature check", _signatures),
    ("rule catalog", _catalog),
    ("driver update facts", _delivery),
    ("file trace", _file_trace),
    ("naming files opened earlier", _handle_naming),
]
