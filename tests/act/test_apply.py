import json
import os
import winreg

import pytest

from writehawk.act import apply as act
from writehawk.act import ledger, services
from writehawk.act.regvalues import ABSENT, Value
from writehawk.rules import catalog

SERVICE = "Some Service"
SERVICE_KEY = "HKLM\\SYSTEM\\CurrentControlSet\\Services\\" + SERVICE
RULE_TEXT = json.dumps({"format": 1, "rules": [{
    "id": "some-rule", "vendor": "nvidia", "title": "t", "summary": "s",
    "sources": ["https://example.org/report"], "affected_from": None, "fixed_in": "2.0",
    "files": ["%ProgramData%\\Some\\*"], "processes": ["some.exe"],
    "workaround": {
        "vendor_documented": False, "requires": None, "note": "n",
        "takes_effect": {"service": SERVICE, "action": "restart"},
        "steps": [
            {"type": "registry_dword", "key": "HKLM\\SOFTWARE\\Some\\Deep\\Key", "name": "Off",
             "value": 1},
            {"type": "service_start", "service": SERVICE, "start": 4}]}}]})
(RULE,) = catalog.parse(RULE_TEXT)


class FakeSystem:
    def __init__(self, values=None, keys=("HKLM\\SOFTWARE",), running=True):
        self.values = dict(values or {})
        self.keys = set(keys)
        self.running = running
        self.log = []

    def read(self, key, name):
        return self.values.get((key, name), ABSENT)

    def write(self, key, name, value):
        self.log.append(("write", key, name, value.exists))
        if value.exists:
            self.values[key, name] = value
            parts = key.split("\\")
            self.keys.update("\\".join(parts[:count]) for count in range(2, len(parts) + 1))
        else:
            self.values.pop((key, name), None)

    def missing_keys(self, key):
        parts = key.split("\\")
        paths = ["\\".join(parts[:count]) for count in range(2, len(parts) + 1)]
        return [path for path in paths if path not in self.keys]

    def delete_key_if_empty(self, key):
        if any(k == key for k, _ in self.values) or any(
                other.startswith(key + "\\") for other in self.keys):
            return False
        self.keys.discard(key)
        return True

    def set_start_type(self, service, value):
        self.log.append(("start type", service, value))
        key = "HKLM\\SYSTEM\\CurrentControlSet\\Services\\" + service
        self.values[key, "Start"] = Value(True, winreg.REG_DWORD, value)

    def service_state(self, _service):
        return (services.RUNNING if self.running else services.STOPPED), 0

    def stop_service(self, service):
        self.log.append(("stop", service))
        self.running = False
        return True

    def start_service(self, service):
        self.log.append(("start", service))
        self.running = True
        return True


def machine(**extra):
    values = {(SERVICE_KEY, "Start"): Value(True, winreg.REG_DWORD, 2)}
    values.update(extra.pop("values", {}))
    return FakeSystem(values, keys=("HKLM\\SOFTWARE", SERVICE_KEY), **extra)


def test_plan_reads_and_changes_nothing():
    system = machine()
    changes = act.plan(RULE, system)
    assert system.log == []
    assert [change.prior_exists for change in changes] == [False, True]
    assert changes[0].created_keys == ["HKLM\\SOFTWARE\\Some", "HKLM\\SOFTWARE\\Some\\Deep",
                                       "HKLM\\SOFTWARE\\Some\\Deep\\Key"]
    text = "\n".join(act.describe(changes))
    assert "create HKLM\\SOFTWARE\\Some\\Deep\\Key\\Off = 1" in text
    assert "creates key HKLM\\SOFTWARE\\Some\\Deep" in text
    assert f"set {SERVICE_KEY}\\Start from 2 to 4" in text


def test_the_ledger_is_on_disk_before_the_first_change(tmp_path):
    system = machine()
    seen = []
    write = system.write

    def checked(key, name, value):
        (saved,) = ledger.load_all(str(tmp_path))
        seen.append((saved.state, [change.applied for change in saved.changes]))
        write(key, name, value)

    system.write = checked
    act.apply(RULE, str(tmp_path), system)
    assert seen == [(ledger.PLANNED, [False, False])]


def test_apply_then_rollback_restores_everything(tmp_path):
    system = machine()
    before = (dict(system.values), set(system.keys))
    entry = act.apply(RULE, str(tmp_path), system, now=True, clock=lambda: 0)
    assert entry.id == "19700101-000000-some-rule"
    assert system.values["HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off"].data == 1
    assert system.values[SERVICE_KEY, "Start"].data == 4
    assert system.log[-2:] == [("stop", SERVICE), ("start", SERVICE)]
    (saved,) = ledger.load_all(str(tmp_path))
    assert saved.state == ledger.APPLIED
    assert act.rollback(saved, str(tmp_path), system) == []
    assert (system.values, system.keys) == before
    assert ledger.load_all(str(tmp_path))[0].state == ledger.ROLLED_BACK
    assert system.log[-2:] == [("stop", SERVICE), ("start", SERVICE)]


def test_a_value_that_was_already_set_is_left_alone_and_never_undone(tmp_path):
    already = {("HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off"): Value(True, winreg.REG_DWORD, 1)}
    system = machine(values=already)
    system.keys.update(act.plan(RULE, machine())[0].created_keys)
    entry = act.apply(RULE, str(tmp_path), system)
    assert [change.applied for change in entry.changes] == [False, True]
    act.rollback(entry, str(tmp_path), system)
    assert system.values["HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off"].data == 1


def test_a_prior_value_of_another_type_comes_back_as_it_was(tmp_path):
    text = {("HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off"): Value(True, winreg.REG_SZ, "no")}
    system = machine(values=text)
    entry = act.apply(RULE, str(tmp_path), system)
    act.rollback(ledger.load_all(str(tmp_path))[0], str(tmp_path), system)
    assert entry.changes[0].prior_data == "no"
    assert system.values["HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off"] == Value(True, winreg.REG_SZ,
                                                                           "no")


def test_rollback_leaves_a_value_someone_else_changed(tmp_path):
    system = machine()
    entry = act.apply(RULE, str(tmp_path), system)
    system.values[SERVICE_KEY, "Start"] = Value(True, winreg.REG_DWORD, 3)
    problems = act.rollback(entry, str(tmp_path), system)
    assert len(problems) == 1
    assert "Start is no longer 4" in problems[0]
    assert system.values[SERVICE_KEY, "Start"].data == 3
    assert ("HKLM\\SOFTWARE\\Some\\Deep\\Key", "Off") not in system.values
    assert entry.state == ledger.PARTIAL
    assert act.rollback(entry, str(tmp_path), system, force=True) == []
    assert system.values[SERVICE_KEY, "Start"].data == 2


def test_a_created_key_that_gained_content_is_kept(tmp_path):
    system = machine()
    entry = act.apply(RULE, str(tmp_path), system)
    system.values["HKLM\\SOFTWARE\\Some\\Deep", "Theirs"] = Value(True, winreg.REG_DWORD, 7)
    act.rollback(entry, str(tmp_path), system)
    assert "HKLM\\SOFTWARE\\Some\\Deep\\Key" not in system.keys
    assert "HKLM\\SOFTWARE\\Some\\Deep" in system.keys
    assert "HKLM\\SOFTWARE\\Some" in system.keys


def test_a_stopped_service_is_not_started_by_apply_or_rollback(tmp_path):
    system = machine(running=False)
    entry = act.apply(RULE, str(tmp_path), system, now=True)
    act.rollback(entry, str(tmp_path), system)
    assert not [item for item in system.log if item[0] in ("stop", "start")]


def test_a_second_rollback_changes_nothing(tmp_path):
    system = machine()
    entry = act.apply(RULE, str(tmp_path), system)
    act.rollback(entry, str(tmp_path), system)
    count = len(system.log)
    assert act.rollback(ledger.load_all(str(tmp_path))[0], str(tmp_path), system) == []
    assert len(system.log) == count


def test_an_unreadable_ledger_file_is_skipped(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "other.json").write_text(json.dumps({"format": 99}), encoding="utf-8")
    assert ledger.load_all(str(tmp_path)) == []
    assert ledger.load_all(str(tmp_path / "missing")) == []


def test_takes_effect_must_be_stop_or_restart():
    with pytest.raises(catalog.CatalogError):
        catalog.parse(RULE_TEXT.replace('"restart"', '"delete"'))


def test_ledger_files_are_plain_json(tmp_path):
    entry = act.apply(RULE, str(tmp_path), machine())
    with open(os.path.join(tmp_path, entry.id + ".json"), encoding="utf-8") as handle:
        raw = json.load(handle)
    assert raw["rule_id"] == "some-rule"
    assert raw["changes"][1]["prior_data"] == 2
