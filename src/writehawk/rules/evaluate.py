"""Decide, for each rule, whether its cause applies to this machine.

Three questions are kept apart because they have different answers on
different machines: is the hardware there, is the installed version one that
has the problem, and is the problem happening right now.
"""
from __future__ import annotations

import glob
import os
import winreg
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..context.gpu import Gpu
from ..context.protect import path_pattern
from ..measure.rewrite import RewriteTracker
from .catalog import Rule, parse_version

NOT_APPLICABLE = "not applicable"
NOT_AFFECTED = "not affected"
FIXED = "fixed"
EXPOSED = "exposed"
UNKNOWN_VERSION = "version unknown"
MITIGATED = "mitigated"
ACTIVE = "active"

TRACE_MIN_BYTES = 256 * 1024
LOOP_MIN_RATIO = 20.0
LOOP_MIN_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Activity:
    path: str
    how: str
    """`trace`: writes seen in the file trace. `files`: size or time changed on disk."""
    bytes_written: int = 0
    rewrite_ratio: float = 0.0


@dataclass(frozen=True)
class Finding:
    rule: Rule
    status: str
    adapters: tuple[Gpu, ...]
    version_state: str
    workaround_in_place: bool
    workaround_offered: bool
    activity: tuple[Activity, ...]


def version_state(rule: Rule, release: str) -> str:
    """Where one installed release stands against the rule's version range."""
    installed = parse_version(release)
    if installed is None:
        return UNKNOWN_VERSION
    if installed >= parse_version(rule.fixed_in):
        return FIXED
    if rule.affected_from is not None and installed < parse_version(rule.affected_from):
        return NOT_AFFECTED
    return EXPOSED


def _worst(states: Iterable[str]) -> str:
    order = (EXPOSED, UNKNOWN_VERSION, FIXED, NOT_AFFECTED)
    found = set(states)
    return next(state for state in order if state in found)


def workaround_in_place(rule: Rule, read_dword: Callable[[str, str], int | None]) -> bool:
    return all(read_dword(step.key, step.name) == step.value for step in rule.steps)


def workaround_offered(rule: Rule, adapters: Iterable[Gpu]) -> bool:
    if rule.workaround_requires == "adapter_drives_no_display":
        # Unknown is not zero: without a desktop session nothing is offered.
        return all(adapter.displays == 0 for adapter in adapters)
    return True


def evaluate(rule: Rule, gpus: Iterable[Gpu], read_dword: Callable[[str, str], int | None],
             activity: Iterable[Activity] = ()) -> Finding:
    adapters = tuple(gpu for gpu in gpus if gpu.vendor == rule.vendor)
    seen = tuple(activity)
    if not adapters:
        return Finding(rule, NOT_APPLICABLE, (), NOT_APPLICABLE, False, False, ())
    versions = _worst(version_state(rule, adapter.release) for adapter in adapters)
    in_place = workaround_in_place(rule, read_dword)
    if seen:
        status = ACTIVE  # what is happening outranks what the version number promises
    elif versions in (FIXED, NOT_AFFECTED):
        status = versions
    elif in_place:
        status = MITIGATED
    else:
        status = versions
    return Finding(rule, status, adapters, versions, in_place,
                   workaround_offered(rule, adapters), seen)


# --- reading the machine --------------------------------------------------------------------

def read_dword(key: str, name: str) -> int | None:
    """A DWORD under `HKLM\\...`, or None when the key or value is absent."""
    root, _, path = key.partition("\\")
    if root.upper() != "HKLM":
        raise ValueError(f"only HKLM is read: {key!r}")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as handle:
            value, kind = winreg.QueryValueEx(handle, name)
    except OSError:
        return None
    return value if kind == winreg.REG_DWORD else None


def trace_activity(rule: Rule, tracker: RewriteTracker,
                   min_bytes: int = TRACE_MIN_BYTES) -> list[Activity]:
    """Files of this rule that the trace saw written, largest first."""
    patterns = [path_pattern(pattern) for pattern in rule.files]
    found = []
    for entry in tracker.top(limit=len(tracker.files)):
        name = tracker.name_of(entry.file_id)
        if (name and entry.bytes_written >= min_bytes
                and any(pattern.fullmatch(os.path.normcase(name)) for pattern in patterns)):
            found.append(Activity(name, "trace", entry.bytes_written, entry.rewrite_ratio))
    return found


def snapshot_files(rule: Rule) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file the rule's patterns match now."""
    found = {}
    for pattern in rule.files:
        for path in glob.glob(os.path.expandvars(pattern)):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            found[path] = (stat.st_size, stat.st_mtime_ns)
    return found


def file_activity(before: dict[str, tuple[int, int]],
                  after: dict[str, tuple[int, int]]) -> list[Activity]:
    """Files that appeared or changed between two snapshots.

    Works without elevation, and misses a rewrite that leaves size and time as
    they were; the trace is the stronger source.
    """
    return [Activity(path, "files") for path, stamp in sorted(after.items())
            if before.get(path) != stamp]


def rewrite_loops(tracker: RewriteTracker, rules: Iterable[Rule],
                  min_ratio: float = LOOP_MIN_RATIO,
                  min_bytes: int = LOOP_MIN_BYTES) -> list[Activity]:
    """Heavily rewritten files that no rule explains. Reported, never acted on."""
    known = [path_pattern(pattern) for rule in rules for pattern in rule.files]
    found = []
    for entry in tracker.top(limit=len(tracker.files), min_bytes=min_bytes):
        name = tracker.name_of(entry.file_id) or ""
        if entry.rewrite_ratio < min_ratio:
            continue
        if name and any(pattern.fullmatch(os.path.normcase(name)) for pattern in known):
            continue
        found.append(Activity(name or f"(unnamed, pid {entry.pid})", "trace",
                              entry.bytes_written, entry.rewrite_ratio))
    return found
