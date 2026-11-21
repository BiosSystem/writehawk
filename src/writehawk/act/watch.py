"""A scheduled task that writes the report on a schedule.

It reports and nothing else: the task runs `writehawk report`, which is
read-only. Applying a workaround stays a deliberate act at a terminal.
"""
from __future__ import annotations

import os
import subprocess
import sys

TASK_NAME = "writehawk report"
MIN_HOURS, MAX_HOURS = 1, 23


def default_report_path() -> str:
    return os.path.expandvars("%ProgramData%\\writehawk\\report.json")


def task_command(python: str, out: str, seconds: int) -> str:
    return f'"{python}" -m writehawk report --seconds {seconds} --out "{out}"'


def create_arguments(command: str, hours: int) -> list[str]:
    if not MIN_HOURS <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be {MIN_HOURS} to {MAX_HOURS}")
    # SYSTEM with highest privileges: the file trace needs elevation, and the
    # task must run whether or not anyone is logged on.
    return ["schtasks", "/create", "/f", "/tn", TASK_NAME, "/ru", "SYSTEM", "/rl", "HIGHEST",
            "/sc", "HOURLY", "/mo", str(hours), "/tr", command]


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(arguments, capture_output=True, text=True, check=False,
                              timeout=60)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(arguments, 1, "", "schtasks did not answer in time")


def install(hours: int, out: str, seconds: int = 60) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = _run(create_arguments(task_command(sys.executable, out, seconds), hours))
    return done.returncode == 0, (done.stdout or done.stderr).strip()


def installed() -> bool:
    return _run(["schtasks", "/query", "/tn", TASK_NAME]).returncode == 0


def remove() -> tuple[bool, str]:
    if not installed():
        return True, "not installed"
    done = _run(["schtasks", "/delete", "/f", "/tn", TASK_NAME])
    return done.returncode == 0, (done.stdout or done.stderr).strip()


def run_now() -> bool:
    return _run(["schtasks", "/run", "/tn", TASK_NAME]).returncode == 0
