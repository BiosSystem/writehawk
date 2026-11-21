"""Apply and roll back against the real registry and service manager.

Creates a registry key and a service, so it runs only inside the sandbox
harness. The check is the one the roadmap asks for: an export taken before
must equal the export taken after the rollback.
"""
import json
import os
import subprocess
import winreg

import pytest

from writehawk.act import apply as act
from writehawk.act import ledger, regvalues, services
from writehawk.measure.filetrace import is_elevated
from writehawk.rules import catalog

ROOT = "HKLM\\SOFTWARE\\writehawk-test"
SERVICE = "writehawk-test-service"

pytestmark = pytest.mark.skipif(
    os.environ.get("WRITEHAWK_SANDBOX") != "1" or not is_elevated(),
    reason="changes the registry and services: runs only inside tools/sandbox")


def rule(steps):
    return catalog.parse(json.dumps({"format": 1, "rules": [{
        "id": "live-rule", "vendor": "nvidia", "title": "t", "summary": "s",
        "sources": ["https://example.org/report"], "affected_from": None, "fixed_in": "2.0",
        "files": ["%ProgramData%\\Some\\*"], "processes": ["some.exe"],
        "workaround": {"vendor_documented": False, "requires": None, "note": "n",
                       "steps": steps}}]}))[0]


def export(key, path):
    done = subprocess.run(["reg", "export", key, str(path), "/y"], capture_output=True,
                          check=False)
    return path.read_bytes() if done.returncode == 0 else b"(no such key)"


def service_config():
    return subprocess.run(["sc", "qc", SERVICE], capture_output=True, check=True).stdout


@pytest.fixture
def scratch_key():
    subprocess.run(["reg", "delete", ROOT, "/f"], capture_output=True, check=False)
    subprocess.run(["reg", "add", ROOT + "\\Existing", "/v", "Number", "/t", "REG_DWORD", "/d",
                    "7", "/f"], capture_output=True, check=True)
    subprocess.run(["reg", "add", ROOT + "\\Existing", "/v", "Text", "/t", "REG_SZ", "/d",
                    "keep me", "/f"], capture_output=True, check=True)
    yield ROOT
    subprocess.run(["reg", "delete", ROOT, "/f"], capture_output=True, check=False)


@pytest.fixture
def scratch_service():
    subprocess.run(["sc", "delete", SERVICE], capture_output=True, check=False)
    subprocess.run(["sc", "create", SERVICE, "binPath=", "C:\\Windows\\System32\\cmd.exe /c exit",
                    "start=", "demand"], capture_output=True, check=True)
    yield SERVICE
    subprocess.run(["sc", "delete", SERVICE], capture_output=True, check=False)


def test_sandbox_registry_values_come_back_byte_for_byte(scratch_key, tmp_path):
    steps = [
        {"type": "registry_dword", "key": ROOT + "\\Existing", "name": "Number", "value": 1},
        {"type": "registry_dword", "key": ROOT + "\\Existing", "name": "Text", "value": 1},
        {"type": "registry_dword", "key": ROOT + "\\Existing", "name": "New", "value": 1},
        {"type": "registry_dword", "key": ROOT + "\\Made\\Deeper", "name": "Flag", "value": 1}]
    folder = str(tmp_path / "ledger")
    before = export(ROOT, tmp_path / "before.reg")
    entry = act.apply(rule(steps), folder, act.System())
    assert all(regvalues.read(step["key"], step["name"]).data == 1 for step in steps)
    assert regvalues.read(ROOT + "\\Existing", "Text").kind == winreg.REG_DWORD
    assert export(ROOT, tmp_path / "applied.reg") != before
    (saved,) = ledger.load_all(folder)
    assert saved.id == entry.id
    assert act.rollback(saved, folder, act.System()) == []
    assert export(ROOT, tmp_path / "after.reg") == before
    assert not regvalues.key_exists(ROOT + "\\Made")


def test_sandbox_service_start_type_comes_back(scratch_service, tmp_path):
    steps = [{"type": "service_start", "service": SERVICE, "start": 4}]
    folder = str(tmp_path / "ledger")
    key = "HKLM\\SYSTEM\\CurrentControlSet\\Services\\" + SERVICE
    before = (service_config(), export(key, tmp_path / "before.reg"))
    assert services.start_type(SERVICE) == 3
    act.apply(rule(steps), folder, act.System())
    assert services.start_type(SERVICE) == 4
    assert service_config() != before[0]
    assert act.rollback(ledger.load_all(folder)[0], folder, act.System()) == []
    assert services.start_type(SERVICE) == 3
    assert (service_config(), export(key, tmp_path / "after.reg")) == before


def test_sandbox_rollback_refuses_a_value_changed_since(scratch_key, tmp_path):
    steps = [{"type": "registry_dword", "key": ROOT + "\\Existing", "name": "Number",
              "value": 1}]
    folder = str(tmp_path / "ledger")
    entry = act.apply(rule(steps), folder, act.System())
    subprocess.run(["reg", "add", ROOT + "\\Existing", "/v", "Number", "/t", "REG_DWORD", "/d",
                    "9", "/f"], capture_output=True, check=True)
    assert len(act.rollback(entry, folder, act.System())) == 1
    assert regvalues.read(ROOT + "\\Existing", "Number").data == 9
    assert act.rollback(entry, folder, act.System(), force=True) == []
    assert regvalues.read(ROOT + "\\Existing", "Number").data == 7


def _stoppable_service():
    for name in ("Themes", "Spooler", "SysMain", "W32Time", "DPS"):
        try:
            if services.state(name)[0] == services.RUNNING:
                return name
        except OSError:
            continue
    return None


def test_sandbox_now_stops_a_running_service_and_rollback_starts_it_again(tmp_path):
    name = _stoppable_service()
    if name is None:
        pytest.skip("no running service from the candidate list in this machine")
    live = catalog.parse(json.dumps({"format": 1, "rules": [{
        "id": "live-now", "vendor": "nvidia", "title": "t", "summary": "s",
        "sources": ["https://example.org/report"], "affected_from": None, "fixed_in": "2.0",
        "files": ["%ProgramData%/Some/*"], "processes": ["some.exe"],
        "workaround": {"vendor_documented": False, "requires": None, "note": "n",
                       "takes_effect": {"service": name, "action": "stop"},
                       "steps": [{"type": "service_start", "service": name, "start": 4}]}}]}))[0]
    folder = str(tmp_path / "ledger")
    before = subprocess.run(["sc", "qc", name], capture_output=True, check=True).stdout
    entry = act.apply(live, folder, act.System(), now=True)
    try:
        assert entry.service.was_running
        assert services.state(name)[0] == services.STOPPED
        assert services.start_type(name) == 4
    finally:
        problems = act.rollback(ledger.load_all(folder)[0], folder, act.System())
    assert problems == []
    assert services.state(name)[0] == services.RUNNING
    assert subprocess.run(["sc", "qc", name], capture_output=True, check=True).stdout == before
