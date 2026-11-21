"""The record of what was changed, written before the change is made.

One JSON file per applied workaround. An entry holds everything needed to
undo it: the prior state of each value, the keys that had to be created, and
what was done to a service. Rollback reads nothing else.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

FORMAT = 1
PLANNED = "planned"
APPLIED = "applied"
ROLLED_BACK = "rolled back"
PARTIAL = "partly rolled back"


def default_folder() -> str:
    return os.path.expandvars("%ProgramData%\\writehawk\\ledger")


@dataclass
class Change:
    kind: str
    key: str
    name: str
    value: int
    prior_exists: bool
    prior_kind: int
    prior_data: object
    created_keys: list[str] = field(default_factory=list)
    applied: bool = False
    restored: bool = False


@dataclass
class ServiceAction:
    service: str
    action: str
    """`stop` or `restart`."""
    was_running: bool = False
    done: bool = False
    undone: bool = False


@dataclass
class Entry:
    id: str
    rule_id: str
    created: str
    state: str = PLANNED
    changes: list[Change] = field(default_factory=list)
    service: ServiceAction | None = None
    format: int = FORMAT


def save(entry: Entry, folder: str) -> str:
    """Write the entry so that it is on disk before the caller goes on."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, entry.id + ".json")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(asdict(entry), handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def _entry(raw: dict) -> Entry:
    if raw.get("format") != FORMAT:
        raise ValueError(f"ledger format {raw.get('format')!r} is not {FORMAT}")
    service = raw.get("service")
    return Entry(id=raw["id"], rule_id=raw["rule_id"], created=raw["created"],
                 state=raw["state"], changes=[Change(**change) for change in raw["changes"]],
                 service=ServiceAction(**service) if service else None)


def load(path: str) -> Entry:
    with open(path, encoding="utf-8") as handle:
        return _entry(json.load(handle))


def load_all(folder: str) -> list[Entry]:
    """Every entry, oldest first. A file that cannot be read is skipped."""
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".json"))
    except FileNotFoundError:
        return []
    entries = []
    for name in names:
        try:
            entries.append(load(os.path.join(folder, name)))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return entries
