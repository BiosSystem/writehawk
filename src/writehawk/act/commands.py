"""What `fix`, `rollback` and `status` do, apart from argument parsing and printing.

Each function returns an exit code and the lines to print, and takes the
system as a parameter, so the decisions can be tested without a machine.
"""
from __future__ import annotations

import winreg
from collections.abc import Callable

from ..context import protect
from ..rules import evaluate as ev
from . import apply as act
from . import ledger, services

OK, REFUSED = 0, 1


def _not_wanted(finding: ev.Finding) -> list[str]:
    """Why this workaround should not be applied here. Empty when it may be."""
    rule = finding.rule
    if finding.status == ev.NOT_APPLICABLE:
        return [f"{rule.id} does not apply: no {rule.vendor} display adapter here"]
    if finding.version_state in (ev.FIXED, ev.NOT_AFFECTED) and finding.status != ev.ACTIVE:
        return [f"{rule.id}: the installed driver is {finding.version_state}; "
                "there is nothing to work around"]
    if not finding.workaround_offered:
        return [f"{rule.id}: the workaround is not offered on this machine.",
                rule.workaround_note]
    return []


def fix(finding: ev.Finding, folder: str, system: act.System, *, do_apply: bool, now: bool,
        elevated: bool, classify: Callable[[int], str]) -> tuple[int, list[str]]:
    rule = finding.rule
    refusal = _not_wanted(finding)
    if refusal:
        return REFUSED, refusal
    changes = act.plan(rule, system)
    if all(act.already_set(change) for change in changes):
        return OK, [f"{rule.id}: the workaround is already in place"]
    lines = [f"{rule.id}: {rule.workaround_note}"]
    if not rule.workaround_documented:
        lines.append("The vendor does not document this workaround.")
    lines.extend("  " + line for line in act.describe(changes))
    if now and rule.now_service:
        lines.append(f"  {rule.now_action} service {rule.now_service}")
    elif rule.now_service:
        lines.append(f"  takes effect when service {rule.now_service} next starts; "
                     "add --now to do that immediately")
    if not do_apply:
        return OK, [*lines, "Dry run: nothing was changed. Add --apply to make the change."]
    if not elevated:
        return REFUSED, [*lines, "Applying needs an elevated terminal. Nothing was changed."]
    if now and rule.now_service:
        state, pid = system.service_state(rule.now_service)
        if state == services.RUNNING and classify(pid) != protect.OPEN:
            return REFUSED, [*lines, f"Service {rule.now_service} runs in a process that is "
                             "protected or could not be identified. Nothing was changed; "
                             "apply without --now and restart the machine instead."]
    entry = act.apply(rule, folder, system, now=now)
    return OK, [*lines, f"Applied. Ledger entry {entry.id}.",
                f"Undo with: writehawk rollback {entry.id} --apply"]


def pick(entries: list[ledger.Entry], entry_id: str | None) -> ledger.Entry | None:
    """The named entry, or the newest one that still has something to undo."""
    open_states = (ledger.APPLIED, ledger.PARTIAL, ledger.PLANNED)
    for entry in reversed(entries):
        if entry.id == entry_id or (entry_id is None and entry.state in open_states):
            return entry
    return None


def rollback(entries: list[ledger.Entry], entry_id: str | None, folder: str,
             system: act.System, *, do_apply: bool, force: bool,
             elevated: bool) -> tuple[int, list[str]]:
    entry = pick(entries, entry_id)
    if entry is None:
        return REFUSED, ["No ledger entry to roll back." if entry_id is None
                         else f"No ledger entry {entry_id}."]
    pending = [change for change in entry.changes if change.applied and not change.restored]
    lines = [f"{entry.id} ({entry.state})"]
    for change in reversed(pending):
        target = f"{change.key}\\{change.name}"
        if change.prior_exists:
            lines.append(f"  restore {target} to {change.prior_data!r}")
        else:
            lines.append(f"  delete {target}")
            lines.extend(f"  delete key {key} if empty" for key in reversed(change.created_keys))
    if not pending:
        return OK, [*lines, "  nothing left to undo"]
    if not do_apply:
        return OK, [*lines, "Dry run: nothing was changed. Add --apply to roll back."]
    if not elevated:
        return REFUSED, [*lines, "Rolling back needs an elevated terminal. Nothing was changed."]
    problems = act.rollback(entry, folder, system, force=force)
    if problems:
        return REFUSED, [*lines, *problems,
                         "Rolled back in part. Add --force to overwrite the values above."]
    return OK, [*lines, "Rolled back."]


def status(entries: list[ledger.Entry], system: act.System) -> list[str]:
    if not entries:
        return ["No changes have been made by this tool."]
    lines = []
    for entry in entries:
        lines.append(f"{entry.id}  {entry.state}  ({entry.created})")
        for change in entry.changes:
            if not change.applied or change.restored:
                continue
            current = system.read(change.key, change.name)
            holds = (current.exists and current.kind == winreg.REG_DWORD
                     and current.data == change.value)
            lines.append(f"  {change.key}\\{change.name} = {change.value}: "
                         f"{'still set' if holds else 'changed since by something else'}")
    return lines
