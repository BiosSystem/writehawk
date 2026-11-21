import json
import os
import subprocess
import sys

import pytest

import writehawk
from writehawk import cli
from writehawk.context.drivers import DriverDelivery
from writehawk.context.gpu import Gpu
from writehawk.context.session import Session
from writehawk.context.storage import Volume
from writehawk.measure.sampler import ProcRate
from writehawk.rules import catalog
from writehawk.rules import evaluate as ev


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"writehawk {writehawk.__version__}"


def test_a_command_is_required():
    with pytest.raises(SystemExit) as stop:
        cli.main([])
    assert stop.value.code == 2


def test_format_top_ranks_and_drops_idle_processes():
    rates = [ProcRate(10, "busy.exe", 2.0, 4096 * 100, 100, 0),
             ProcRate(11, "idle.exe", 2.0, 0, 0, 0)]
    text = cli.format_top(rates, limit=5)
    assert "busy.exe" in text and "idle.exe" not in text
    assert "200.0" in text  # KB/s


def test_live_top_runs(capsys):
    assert cli.main(["top", "--seconds", "0.2"]) == 0
    assert "write KB/s" in capsys.readouterr().out


def test_module_entry_point_runs_from_a_checkout():
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    out = subprocess.run([sys.executable, "-m", "writehawk", "--version"], capture_output=True,
                         check=False, text=True, env=dict(os.environ, PYTHONPATH=src))
    assert out.returncode == 0 and out.stdout.startswith("writehawk ")


def test_format_context_says_which_adapter_drives_no_display():
    gpus = [Gpu("PCI\\A", "Card One", "nvidia", 0x10DE, 1, "32.0.15.6094", "560.94", "", "", 2),
            Gpu("PCI\\B", "Card Two", "amd", 0x1002, 2, "", "", "", "", 0),
            Gpu("PCI\\C", "Card Three", "intel", 0x8086, 3, "1.2.3.4", "", "", "", None)]
    volumes = [Volume("C:\\", "NTFS", (0,), "ssd", "nvme", True, False, "Some Disk")]
    counts = {"protected": 9, "open": 120, "unknown": 3}
    lines = cli.format_context(gpus, volumes, Session(12.4, "busy"), counts).splitlines()
    assert "32.0.15.6094 (560.94)" in lines[1]
    assert lines[1].endswith("drives 2 displays")
    assert "driver unknown" in lines[2]
    assert lines[2].endswith("drives no display")
    assert lines[3].endswith("displays unknown")
    assert lines[5].split() == ["C:", "NTFS", "ssd", "nvme", "disk", "0", "trim", "Some", "Disk"]
    assert lines[7].strip() == "idle 12 s, state busy, fullscreen"
    assert lines[9].strip() == "9 protected, 120 not protected, 3 could not be identified"
    assert "treated as protected" in lines[10]


def test_count_processes():
    kinds = {1: "protected", 2: "open", 3: "open"}
    assert cli.count_processes(kinds, kinds.get) == {"protected": 1, "open": 2, "unknown": 0}


def test_live_context_runs(capsys):
    assert cli.main(["context"]) == 0
    out = capsys.readouterr().out
    assert "display adapters" in out
    assert "volumes" in out
    assert "session" in out
    assert "processes" in out


def _card(vendor, release, displays):
    return Gpu("PCI\\X", "Some Card", vendor, 1, 2, "1.2.3.4", release, "", "", displays)


def test_format_scan_explains_each_status():
    rules = {rule.id: rule for rule in catalog.load()}
    nvidia, amd = rules["nvidia-nvtopps-log-rewrite"], rules["amd-eeu-dump-files"]
    seen = [ev.Activity("C:\\x\\nvlog.nvlgstg", "trace", 2 << 20, 512.0)]
    active = ev.evaluate(nvidia, [_card("nvidia", "621.24", 2)], lambda *_: None, seen)
    in_use = ev.evaluate(amd, [_card("amd", "24.10.24", 1)], lambda *_: None)
    absent = ev.evaluate(amd, [_card("nvidia", "621.24", 2)], lambda *_: None)
    delivery = DriverDelivery({"nvidia": ("NVIDIA App",), "amd": ()}, False, "", False)
    text = cli.format_scan([active, in_use, absent], None, delivery)
    assert "nvidia-nvtopps-log-rewrite: ACTIVE" in text
    assert "driver 621.24 (affected from 621.14, fixed in 621.35)" in text
    assert "writing now: C:\\x\\nvlog.nvlgstg, 2048 KB, rewritten 512x" in text
    assert "workaround: available, not documented by the vendor" in text
    assert "amd-eeu-dump-files: EXPOSED" in text
    assert "(first affected version not known, fixed in 26.11.1)" in text
    assert "workaround: not offered on this machine" in text
    assert "amd-eeu-dump-files: NOT APPLICABLE" in text
    assert "not checked, the file trace needs an elevated terminal" in text
    assert text.count("why the fix may not have reached this machine:") == 2
    assert "No AMD update program is installed" in text
    assert "No NVIDIA update program" not in text


def test_format_scan_lists_unexplained_loops():
    loops = [ev.Activity("C:\\App\\state.db", "trace", 12 << 20, 3000.0)]
    delivery = DriverDelivery({}, False, "", None)
    assert "C:\\App\\state.db: 12.0 MB, rewritten 3000x" in cli.format_scan(
        [], loops, delivery)
    assert "none seen" in cli.format_scan([], [], delivery)


def test_live_scan_runs(capsys):
    assert cli.main(["scan", "--seconds", "0.2"]) in (0, 1)
    out = capsys.readouterr().out
    assert "nvidia-nvtopps-log-rewrite:" in out
    assert "amd-eeu-dump-files:" in out


def test_live_fix_is_a_dry_run_and_writes_no_ledger(tmp_path, capsys):
    folder = tmp_path / "ledger"
    for rule in catalog.load():
        assert cli.main(["fix", rule.id, "--ledger-dir", str(folder)]) in (0, 1)
    out = capsys.readouterr().out
    assert "Applied" not in out
    assert not folder.exists()


def test_fix_with_an_unknown_rule_lists_the_known_ones(capsys):
    assert cli.main(["fix", "no-such-rule"]) == 1
    assert "nvidia-nvtopps-log-rewrite" in capsys.readouterr().out


def test_live_status_and_rollback_with_an_empty_ledger(tmp_path, capsys):
    folder = str(tmp_path / "ledger")
    assert cli.main(["status", "--ledger-dir", folder]) == 0
    assert cli.main(["rollback", "--ledger-dir", folder]) == 1
    out = capsys.readouterr().out
    assert "No changes have been made by this tool." in out
    assert "No ledger entry to roll back." in out


def test_live_report_is_json_without_machine_identifiers(tmp_path, capsys):
    out = tmp_path / "sub" / "report.json"
    assert cli.main(["report", "--seconds", "0.2", "--out", str(out),
                     "--ledger-dir", str(tmp_path / "ledger")]) == 0
    assert capsys.readouterr().out == ""
    text = out.read_text(encoding="utf-8")
    document = json.loads(text)
    assert document["format"] == 1
    assert {item["rule"] for item in document["findings"]} >= {"amd-eeu-dump-files"}
    assert document["changes_made"] == []
    assert "instance_id" not in text
    assert "PCI\\\\VEN_" not in text
    assert not list(tmp_path.glob("sub/*.tmp"))


def test_live_report_prints_when_no_file_is_given(tmp_path, capsys):
    assert cli.main(["report", "--seconds", "0.1", "--ledger-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["tool_version"] == writehawk.__version__


def test_watch_status_reads_only(capsys):
    assert cli.main(["watch", "status"]) == 0
    assert "scheduled report is" in capsys.readouterr().out
