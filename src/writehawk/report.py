"""Everything the tool knows about the machine, as one JSON document.

Meant to be attached to a bug report, so it leaves out what identifies a
machine: device instance ids, disk serial numbers (never read), the system
maker and the names of installed programs. File paths of observed writes are
included and can contain a user name; read the file before sharing it.
"""
from __future__ import annotations

from collections.abc import Iterable

from . import __version__
from .act.ledger import Entry
from .context.drivers import DriverDelivery
from .context.gpu import Gpu
from .context.session import Session
from .context.storage import Volume
from .rules import explain
from .rules.evaluate import Activity, Finding

FORMAT = 1


def _activity(item: Activity) -> dict:
    return {"path": item.path, "seen_by": item.how, "bytes_written": item.bytes_written,
            "rewrite_ratio": round(item.rewrite_ratio, 1)}


def _finding(finding: Finding, delivery: DriverDelivery) -> dict:
    return {
        "rule": finding.rule.id,
        "status": finding.status,
        "version_state": finding.version_state,
        "installed_releases": [adapter.release for adapter in finding.adapters],
        "fixed_in": finding.rule.fixed_in,
        "workaround_in_place": finding.workaround_in_place,
        "workaround_offered": finding.workaround_offered,
        "activity": [_activity(item) for item in finding.activity],
        "why_fix_is_missing": explain.reasons(finding, delivery),
    }


def build(*, elevated: bool, seconds: float, gpus: Iterable[Gpu], volumes: Iterable[Volume],
          session: Session, processes: dict[str, int], findings: Iterable[Finding],
          loops: Iterable[Activity] | None, delivery: DriverDelivery,
          entries: Iterable[Entry], created: str) -> dict:
    return {
        "format": FORMAT,
        "tool_version": __version__,
        "created": created,
        "elevated": elevated,
        "watched_seconds": seconds,
        "display_adapters": [
            {"name": g.name, "vendor": g.vendor, "vendor_id": g.vendor_id,
             "device_id": g.device_id, "driver_version": g.driver_version,
             "release": g.release, "driver_provider": g.driver_provider,
             "driver_date": g.driver_date, "displays": g.displays} for g in gpus],
        "volumes": [
            {"root": v.root, "filesystem": v.filesystem, "media": v.media, "bus": v.bus,
             "trim": v.trim, "removable": v.removable, "disks": list(v.disks)}
            for v in volumes],
        "session": {"idle_seconds": round(session.idle_seconds), "state": session.state},
        "processes": processes,
        "driver_delivery": {
            "updaters_installed": {vendor: bool(names)
                                   for vendor, names in delivery.updaters.items()},
            "windows_update_excludes_drivers": delivery.windows_update_excludes_drivers,
            "portable": delivery.portable},
        "findings": [_finding(finding, delivery) for finding in findings],
        # None means the trace did not run, which is different from "none found".
        "unknown_rewrite_loops": None if loops is None else [_activity(i) for i in loops],
        "changes_made": [{"id": entry.id, "rule": entry.rule_id, "state": entry.state}
                         for entry in entries],
    }
