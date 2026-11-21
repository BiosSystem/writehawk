"""Bytes written to a file against the distinct bytes those writes covered.

A download writes each byte once, so the two numbers match. A log that is
rewritten in place writes the same range again and again, so bytes written
runs far ahead of distinct bytes. The ratio between them is what separates
the two, and it needs the offset of every write, not just process totals.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

# Past this many separate extents the covered range is collapsed to one span.
# That can only raise distinct_bytes, so the ratio errs low, never high.
MAX_EXTENTS = 4096


@dataclass
class FileWrites:
    pid: int
    file_id: int
    writes: int = 0
    bytes_written: int = 0
    _starts: list[int] = field(default_factory=list, repr=False)
    _ends: list[int] = field(default_factory=list, repr=False)

    def add(self, offset: int, size: int) -> None:
        if size <= 0:
            return
        self.writes += 1
        self.bytes_written += size
        start, end = offset, offset + size
        lo = bisect_left(self._ends, start)
        hi = bisect_right(self._starts, end)
        if lo < hi:
            start = min(start, self._starts[lo])
            end = max(end, self._ends[hi - 1])
        self._starts[lo:hi] = [start]
        self._ends[lo:hi] = [end]
        if len(self._starts) > MAX_EXTENTS:
            self._starts = [self._starts[0]]
            self._ends = [self._ends[-1]]

    @property
    def distinct_bytes(self) -> int:
        return sum(e - s for s, e in zip(self._starts, self._ends, strict=True))

    @property
    def rewrite_ratio(self) -> float:
        distinct = self.distinct_bytes
        return self.bytes_written / distinct if distinct else 0.0


@dataclass
class FlushTotals:
    writes: int = 0
    bytes: int = 0


class RewriteTracker:
    """Per (pid, file) write totals. file_id is any stable key for the file.

    `files` holds what processes asked to write. `flushed` holds what was
    pushed from the cache to the storage stack for each file, whoever issued it.
    """

    def __init__(self) -> None:
        self.files: dict[tuple[int, int], FileWrites] = {}
        self.flushed: dict[int, FlushTotals] = {}
        self.names: dict[int, str] = {}

    def add_write(self, pid: int, file_id: int, offset: int, size: int) -> None:
        key = (pid, file_id)
        entry = self.files.get(key)
        if entry is None:
            entry = self.files[key] = FileWrites(pid, file_id)
        entry.add(offset, size)

    def add_flush(self, file_id: int, size: int) -> None:
        totals = self.flushed.get(file_id)
        if totals is None:
            totals = self.flushed[file_id] = FlushTotals()
        totals.writes += 1
        totals.bytes += size

    def flushed_bytes(self, file_id: int) -> int:
        totals = self.flushed.get(file_id)
        return totals.bytes if totals else 0

    def set_name(self, file_id: int, name: str) -> None:
        self.names[file_id] = name

    def name_of(self, file_id: int) -> str | None:
        return self.names.get(file_id)

    def top(self, limit: int = 20, min_bytes: int = 0) -> list[FileWrites]:
        rows = [f for f in self.files.values() if f.bytes_written >= min_bytes]
        rows.sort(key=lambda f: f.bytes_written, reverse=True)
        return rows[:limit]
