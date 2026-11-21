"""What the user sees while a command works: named steps and a countdown bar.

Everything goes to standard error and only when that is a terminal. A
scheduled task, a pipe or a test capturing output sees nothing, and standard
output stays clean for `report`.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO

FULL, EMPTY = "█", "░"
TICK = 0.2


class Progress:
    def __init__(self, stream: TextIO | None = None, enabled: bool | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, width: int = 24) -> None:
        self.stream = stream if stream is not None else sys.stderr
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.clock = clock
        self.sleep = sleep
        self.width = width
        self.full, self.empty = FULL, EMPTY
        try:
            (FULL + EMPTY).encode(getattr(self.stream, "encoding", None) or "ascii")
        except (UnicodeEncodeError, LookupError):
            self.full, self.empty = "#", "-"
        self._last = 0

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def step(self, text: str) -> None:
        """Start a named step. `done` ends the line."""
        if self.enabled:
            self._write(f"{text} ...")

    def done(self, note: str = "done") -> None:
        if self.enabled:
            self._write(f" {note}\n")

    def bar(self, label: str, fraction: float, left: float) -> str:
        filled = max(0, min(self.width, round(self.width * fraction)))
        bar = self.full * filled + self.empty * (self.width - filled)
        return f"{label}  {bar}  {max(0, round(left)):>3} s left"

    def _draw(self, line: str) -> None:
        pad = max(0, self._last - len(line))
        self._write("\r" + line + " " * pad)
        self._last = len(line)

    def wait(self, seconds: float, label: str) -> None:
        """Sleep for `seconds`, drawing a bar that fills up. Without a terminal, just sleep."""
        if not self.enabled:
            self.sleep(seconds)
            return
        start = self.clock()
        while True:
            spent = self.clock() - start
            if spent >= seconds:
                break
            self._draw(self.bar(label, spent / seconds if seconds else 1.0, seconds - spent))
            self.sleep(min(TICK, seconds - spent))
        self._draw(self.bar(label, 1.0, 0).replace("    0 s left", "  done"))
        self._write("\n")
        self._last = 0
