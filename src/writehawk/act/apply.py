"""Apply a rule's workaround and undo it.

Order of work when applying: read the prior state, write the ledger entry,
then change one value at a time and save the entry after each. A crash at any
point leaves an entry that says exactly which values were changed.
"""
from __future__ import annotations

import time
import winreg
from collections.abc import Callable

from ..rules.catalog import SERVICE_START, SERVICES_KEY, Rule
from . import ledger, regvalues, services
from .ledger import Change, Entry, ServiceAction
from .regvalues import Value


class System:
    """The calls that touch the machine, in one place so tests can replace them."""
    read = staticmethod(regvalues.read)
    write = staticmethod(regvalues.write)
    missing_keys = staticmethod(regvalues.missing_keys)
    delete_key_if_empty = staticmethod(regvalues.delete_key_if_empty)
    set_start_type = staticmethod(services.set_start_type)
    service_state = staticmethod(services.state)
    stop_service = staticmethod(services.stop)
    start_service = staticmethod(services.start)


def _service_of(change: Change) -> str:
    return change.key[len(SERVICES_KEY):]


def plan(rule: Rule, system: System) -> list[Change]:
    """What applying the rule would change. Reads only."""
    changes = []
    for step in rule.steps:
        prior = system.read(step.key, step.name)
        changes.append(Change(kind=step.kind, key=step.key, name=step.name, value=step.value,
                              prior_exists=prior.exists, prior_kind=prior.kind,
                              prior_data=prior.data,
                              created_keys=system.missing_keys(step.key)))
    return changes


def already_set(change: Change) -> bool:
    return (change.prior_exists and change.prior_kind == winreg.REG_DWORD
            and change.prior_data == change.value)


def describe(changes: list[Change]) -> list[str]:
    lines = []
    for change in changes:
        target = f"{change.key}\\{change.name}"
        if already_set(change):
            lines.append(f"leave {target} at {change.value}: already set")
        elif change.prior_exists:
            lines.append(f"set {target} from {change.prior_data!r} to {change.value}")
        else:
            lines.append(f"create {target} = {change.value}")
            lines.extend(f"  creates key {key}" for key in change.created_keys)
    return lines


def new_id(rule: Rule, clock: Callable[[], float] = time.time) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(clock())) + "-" + rule.id


def apply(rule: Rule, folder: str, system: System, now: bool = False,
          clock: Callable[[], float] = time.time) -> Entry:
    """Apply the workaround. With `now`, also stop or restart the rule's service."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))
    entry = Entry(id=new_id(rule, clock), rule_id=rule.id, created=stamp,
                  changes=plan(rule, system))
    if now and rule.now_service:
        running = system.service_state(rule.now_service)[0] == services.RUNNING
        entry.service = ServiceAction(rule.now_service, rule.now_action, was_running=running)
    ledger.save(entry, folder)  # on disk before anything is touched
    for change in entry.changes:
        if already_set(change):
            continue
        if change.kind == SERVICE_START:
            system.set_start_type(_service_of(change), change.value)
        else:
            system.write(change.key, change.name, Value(True, winreg.REG_DWORD, change.value))
        change.applied = True
        ledger.save(entry, folder)
    if entry.service and entry.service.was_running:
        system.stop_service(entry.service.service)
        if entry.service.action == "restart":
            system.start_service(entry.service.service)
        entry.service.done = True
    entry.state = ledger.APPLIED
    ledger.save(entry, folder)
    return entry


def _restore(change: Change, system: System) -> None:
    prior = Value(change.prior_exists, change.prior_kind, change.prior_data)
    if change.kind == SERVICE_START and prior.exists:
        system.set_start_type(_service_of(change), prior.data)
    else:
        system.write(change.key, change.name, prior)
    for key in reversed(change.created_keys):
        if not system.delete_key_if_empty(key):
            break  # something else lives there now; leave it and its parents


def rollback(entry: Entry, folder: str, system: System, force: bool = False) -> list[str]:
    """Undo an entry from its own content. Returns what could not be undone.

    A value that no longer holds what was written has been changed by someone
    else since; it is left alone unless `force` is given.
    """
    problems = []
    for change in reversed(entry.changes):
        if not change.applied or change.restored:
            continue
        current = system.read(change.key, change.name)
        ours = current.exists and current.kind == winreg.REG_DWORD and current.data == change.value
        if not ours and not force:
            problems.append(f"{change.key}\\{change.name} is no longer {change.value}; "
                            "left as it is")
            continue
        _restore(change, system)
        change.restored = True
        ledger.save(entry, folder)
    action = entry.service
    if action and action.done and not action.undone and not problems:
        if action.action == "restart":
            system.stop_service(action.service)
        system.start_service(action.service)
        action.undone = True
    entry.state = ledger.PARTIAL if problems else ledger.ROLLED_BACK
    ledger.save(entry, folder)
    return problems
