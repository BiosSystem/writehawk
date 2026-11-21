from test_apply import RULE, SERVICE, machine

from writehawk.act import commands, ledger
from writehawk.context import protect
from writehawk.context.gpu import Gpu
from writehawk.rules import catalog
from writehawk.rules import evaluate as ev

AMD = next(rule for rule in catalog.load() if rule.id == "amd-eeu-dump-files")


def finding(rule=RULE, vendor="nvidia", release="1.0", displays=1, system=None):
    card = Gpu("PCI\\X", "Card", vendor, 1, 2, "1.2.3.4", release, "", "", displays)
    read = (lambda key, name: None) if system is None else (
        lambda key, name: system.read(key, name).data)
    return ev.evaluate(rule, [card], read)


def run_fix(found, system, tmp_path, **options):
    settings = {"do_apply": False, "now": False, "elevated": True,
                "classify": lambda _pid: protect.OPEN, **options}
    return commands.fix(found, str(tmp_path), system, **settings)


def test_fix_is_a_dry_run_unless_asked(tmp_path):
    system = machine()
    code, lines = run_fix(finding(), system, tmp_path)
    assert code == commands.OK
    assert "Dry run: nothing was changed" in lines[-1]
    assert any("add --now" in line for line in lines)
    assert system.log == []
    assert ledger.load_all(str(tmp_path)) == []


def test_fix_applies_and_names_the_way_back(tmp_path):
    system = machine()
    code, lines = run_fix(finding(), system, tmp_path, do_apply=True)
    (entry,) = ledger.load_all(str(tmp_path))
    assert code == commands.OK
    assert lines[-1] == f"Undo with: writehawk rollback {entry.id} --apply"
    assert entry.service is None


def test_fix_refuses_without_elevation_and_changes_nothing(tmp_path):
    system = machine()
    code, lines = run_fix(finding(), system, tmp_path, do_apply=True, elevated=False)
    assert code == commands.REFUSED
    assert "elevated" in lines[-1]
    assert system.log == []


def test_fix_refuses_what_does_not_apply(tmp_path):
    system = machine()
    for found in (finding(vendor="amd"), finding(release="2.0")):
        code, _ = run_fix(found, system, tmp_path, do_apply=True)
        assert code == commands.REFUSED
    in_use = finding(AMD, "amd", "24.10.24", displays=1)
    code, lines = run_fix(in_use, system, tmp_path, do_apply=True)
    assert code == commands.REFUSED
    assert "not offered on this machine" in lines[0]
    assert system.log == []


def test_fix_says_when_the_workaround_is_already_there(tmp_path):
    system = machine()
    run_fix(finding(), system, tmp_path, do_apply=True)
    code, lines = run_fix(finding(system=system), system, tmp_path, do_apply=True)
    assert (code, lines) == (commands.OK, ["some-rule: the workaround is already in place"])
    assert len(ledger.load_all(str(tmp_path))) == 1


def test_now_is_refused_for_a_protected_or_unidentified_service_process(tmp_path):
    for verdict in (protect.PROTECTED, protect.UNKNOWN):
        system = machine()
        code, lines = run_fix(finding(), system, tmp_path, do_apply=True, now=True,
                              classify=lambda _pid, verdict=verdict: verdict)
        assert code == commands.REFUSED
        assert "Nothing was changed" in lines[-1]
        assert system.log == []


def test_now_restarts_an_ordinary_service(tmp_path):
    system = machine()
    code, _ = run_fix(finding(), system, tmp_path, do_apply=True, now=True)
    assert code == commands.OK
    assert system.log[-2:] == [("stop", SERVICE), ("start", SERVICE)]


def test_rollback_picks_the_newest_open_entry_and_is_a_dry_run_first(tmp_path):
    system = machine()
    run_fix(finding(), system, tmp_path, do_apply=True)
    folder = str(tmp_path)
    options = {"force": False, "elevated": True}
    code, lines = commands.rollback(ledger.load_all(folder), None, folder, system,
                                    do_apply=False, **options)
    assert code == commands.OK
    assert "Dry run" in lines[-1]
    assert any("delete key HKLM\\SOFTWARE\\Some if empty" in line for line in lines)
    code, lines = commands.rollback(ledger.load_all(folder), None, folder, system,
                                    do_apply=True, **options)
    assert (code, lines[-1]) == (commands.OK, "Rolled back.")
    code, lines = commands.rollback(ledger.load_all(folder), None, folder, system,
                                    do_apply=True, **options)
    assert (code, lines) == (commands.REFUSED, ["No ledger entry to roll back."])
    code, lines = commands.rollback(ledger.load_all(folder), "nope", folder, system,
                                    do_apply=True, **options)
    assert lines == ["No ledger entry nope."]


def test_status_says_whether_each_value_still_holds(tmp_path):
    system = machine()
    assert commands.status([], system) == ["No changes have been made by this tool."]
    run_fix(finding(), system, tmp_path, do_apply=True)
    system.set_start_type(SERVICE, 3)
    lines = commands.status(ledger.load_all(str(tmp_path)), system)
    assert "applied" in lines[0]
    assert lines[1].endswith("Off = 1: still set")
    assert lines[2].endswith("Start = 4: changed since by something else")
