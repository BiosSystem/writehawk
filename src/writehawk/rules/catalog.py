"""The rule catalog: what is known about each cause, as data.

A rule carries its sources, the versions it affects, the files and processes
that show it, and the steps of a workaround. Nothing here looks at the machine
or changes it; `evaluate` does the first and `writehawk.act` the second.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources

FORMAT = 1
REGISTRY_DWORD = "registry_dword"
SERVICE_START = "service_start"
SERVICES_KEY = "HKLM\\SYSTEM\\CurrentControlSet\\Services\\"
REQUIREMENTS = (None, "adapter_drives_no_display")
_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    """One registry value a workaround sets. A service start type is one too."""
    kind: str
    key: str
    name: str
    value: int


@dataclass(frozen=True)
class Rule:
    id: str
    vendor: str
    title: str
    summary: str
    sources: tuple[str, ...]
    affected_from: str | None
    """First affected vendor release, or None when it is not known."""
    fixed_in: str
    fix_note: str
    delivery_note: str
    """How the fix reaches users, when that is not automatic."""
    delivery_source: str
    files: tuple[str, ...]
    """Path patterns of the files the cause writes. `*` is one path component."""
    processes: tuple[str, ...]
    workaround_documented: bool
    """True only when the vendor itself documents the workaround."""
    workaround_requires: str | None
    workaround_note: str
    steps: tuple[Step, ...]
    now_service: str = ""
    """Service to stop or restart for the workaround to take effect before a reboot."""
    now_action: str = ""


def parse_version(text: str) -> tuple[int, ...] | None:
    """`621.35` -> `(621, 35)`. None for anything that is not dotted numbers."""
    parts = text.strip().split(".")
    if not text.strip() or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _step(raw: dict) -> Step:
    kind = raw.get("type")
    if kind == REGISTRY_DWORD:
        key, name, value = raw["key"], raw["name"], raw["value"]
    elif kind == SERVICE_START:
        key, name, value = SERVICES_KEY + raw["service"], "Start", raw["start"]
        if value not in (2, 3, 4):
            raise CatalogError(f"service start type must be 2, 3 or 4, not {value!r}")
    else:
        raise CatalogError(f"unknown step type {kind!r}")
    if not key.upper().startswith("HKLM\\"):
        raise CatalogError(f"step key must be under HKLM: {key!r}")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise CatalogError(f"step value must be a 32-bit number: {value!r}")
    return Step(kind, key, name, value)


def _rule(raw: dict) -> Rule:
    try:
        workaround = raw["workaround"]
        rule = Rule(
            id=raw["id"], vendor=raw["vendor"], title=raw["title"], summary=raw["summary"],
            sources=tuple(raw["sources"]), affected_from=raw["affected_from"],
            fixed_in=raw["fixed_in"], fix_note=raw.get("fix_note", ""),
            delivery_note=raw.get("delivery_note", ""),
            delivery_source=raw.get("delivery_source", ""),
            files=tuple(raw["files"]), processes=tuple(raw["processes"]),
            workaround_documented=workaround["vendor_documented"],
            workaround_requires=workaround["requires"], workaround_note=workaround["note"],
            steps=tuple(_step(step) for step in workaround["steps"]),
            now_service=workaround.get("takes_effect", {}).get("service", ""),
            now_action=workaround.get("takes_effect", {}).get("action", ""))
    except KeyError as missing:
        raise CatalogError(f"rule {raw.get('id', '?')!r} lacks {missing}") from None
    if not _ID.fullmatch(rule.id):
        raise CatalogError(f"bad rule id {rule.id!r}")
    if not rule.sources:
        raise CatalogError(f"rule {rule.id} has no source")
    if parse_version(rule.fixed_in) is None:
        raise CatalogError(f"rule {rule.id}: fixed_in is not a version")
    if rule.affected_from is not None and parse_version(rule.affected_from) is None:
        raise CatalogError(f"rule {rule.id}: affected_from is not a version")
    if rule.now_action not in ("", "stop", "restart") or bool(rule.now_action) != bool(
            rule.now_service):
        raise CatalogError(f"rule {rule.id}: takes_effect needs a service and stop or restart")
    if rule.workaround_requires not in REQUIREMENTS:
        raise CatalogError(f"rule {rule.id}: unknown requirement {rule.workaround_requires!r}")
    if not isinstance(rule.workaround_documented, bool):
        raise CatalogError(f"rule {rule.id}: vendor_documented must be true or false")
    return rule


def parse(text: str) -> list[Rule]:
    data = json.loads(text)
    if data.get("format") != FORMAT:
        raise CatalogError(f"catalog format {data.get('format')!r} is not {FORMAT}")
    rules = [_rule(raw) for raw in data["rules"]]
    ids = [rule.id for rule in rules]
    if len(set(ids)) != len(ids):
        raise CatalogError("duplicate rule id")
    return rules


def load() -> list[Rule]:
    """The catalog shipped with the package."""
    return parse(resources.files(__package__).joinpath("catalog.json").read_text("utf-8"))
