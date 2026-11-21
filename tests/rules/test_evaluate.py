import os

import pytest

from writehawk.context.gpu import Gpu
from writehawk.measure.rewrite import RewriteTracker
from writehawk.rules import catalog
from writehawk.rules import evaluate as ev

RULES = {rule.id: rule for rule in catalog.load()}
NVIDIA = RULES["nvidia-nvtopps-log-rewrite"]
AMD = RULES["amd-eeu-dump-files"]
LOG = os.path.expandvars("%ProgramData%\\NVIDIA Corporation\\nvtopps\\nct\\nvlog.nvlgstg")


def card(vendor, release, displays=1):
    return Gpu("PCI\\X", "Card", vendor, 1, 2, "1.2.3.4", release, "", "", displays)


def nothing_set(_key, _name):
    return None


def everything_set(rule):
    wanted = {(step.key, step.name): step.value for step in rule.steps}
    return lambda key, name: wanted.get((key, name))


@pytest.mark.parametrize(("release", "state"), [
    ("621.24", ev.EXPOSED), ("621.14", ev.EXPOSED), ("621.35", ev.FIXED), ("630.1", ev.FIXED),
    ("610.99", ev.NOT_AFFECTED), ("", ev.UNKNOWN_VERSION)])
def test_version_state(release, state):
    assert ev.version_state(NVIDIA, release) == state


def test_an_unknown_first_affected_version_leaves_every_older_release_exposed():
    assert ev.version_state(AMD, "24.10.24") == ev.EXPOSED
    assert ev.version_state(AMD, "26.11.1") == ev.FIXED


def test_a_rule_is_skipped_when_its_hardware_is_absent():
    finding = ev.evaluate(NVIDIA, [card("amd", "24.10.24")], everything_set(NVIDIA),
                          [ev.Activity(LOG, "trace", 1 << 30, 5000.0)])
    assert finding.status == ev.NOT_APPLICABLE
    assert finding.activity == ()


def test_status_follows_version_then_workaround():
    assert ev.evaluate(NVIDIA, [card("nvidia", "621.24")], nothing_set).status == ev.EXPOSED
    assert ev.evaluate(NVIDIA, [card("nvidia", "621.35")], nothing_set).status == ev.FIXED
    assert ev.evaluate(NVIDIA, [card("nvidia", "600.1")], nothing_set).status == ev.NOT_AFFECTED
    assert ev.evaluate(NVIDIA, [card("nvidia", "")], nothing_set).status == ev.UNKNOWN_VERSION
    mitigated = ev.evaluate(NVIDIA, [card("nvidia", "621.24")], everything_set(NVIDIA))
    assert mitigated.status == ev.MITIGATED
    assert mitigated.workaround_in_place


def test_writes_seen_outrank_what_the_version_promises():
    seen = [ev.Activity(LOG, "trace", 1 << 20, 256.0)]
    finding = ev.evaluate(NVIDIA, [card("nvidia", "621.35")], nothing_set, seen)
    assert finding.status == ev.ACTIVE
    assert finding.version_state == ev.FIXED


def test_two_adapters_of_one_vendor_take_the_worse_version():
    cards = [card("nvidia", "621.35"), card("nvidia", "621.24")]
    assert ev.evaluate(NVIDIA, cards, nothing_set).status == ev.EXPOSED


def test_a_workaround_with_a_side_effect_is_offered_only_for_an_unused_adapter():
    assert ev.evaluate(AMD, [card("amd", "24.10.24", displays=0)], nothing_set).workaround_offered
    assert not ev.evaluate(AMD, [card("amd", "24.10.24", displays=1)],
                           nothing_set).workaround_offered
    assert not ev.evaluate(AMD, [card("amd", "24.10.24", displays=None)],
                           nothing_set).workaround_offered
    assert ev.evaluate(NVIDIA, [card("nvidia", "621.24", displays=2)],
                       nothing_set).workaround_offered


def tracker_with(*files):
    tracker = RewriteTracker()
    for file_id, (name, writes) in enumerate(files, start=1):
        for _ in range(writes):
            tracker.add_write(100, file_id, 0, 4096)
        if name:
            tracker.set_name(file_id, name)
    return tracker


def test_trace_activity_matches_the_rule_files_only():
    tracker = tracker_with((LOG.upper(), 200), ("C:\\Other\\nvlog.nvlgstg", 200), (LOG + ".bak", 3))
    (found,) = ev.trace_activity(NVIDIA, tracker)
    assert found.path == LOG.upper()
    assert found.bytes_written == 200 * 4096
    assert found.rewrite_ratio == 200.0
    assert ev.trace_activity(AMD, tracker) == []


def test_trace_activity_ignores_a_trickle():
    assert ev.trace_activity(NVIDIA, tracker_with((LOG, 10))) == []


def test_file_activity_reports_new_and_changed_files():
    before = {"a": (10, 1), "b": (10, 1), "gone": (1, 1)}
    after = {"a": (10, 1), "b": (10, 2), "c": (5, 3)}
    assert [item.path for item in ev.file_activity(before, after)] == ["b", "c"]


def test_snapshot_files_follows_the_patterns(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITEHAWK_TEST_ROOT", str(tmp_path))
    rule = catalog.parse(catalog.resources.files("writehawk.rules").joinpath("catalog.json")
                         .read_text("utf-8").replace("%ProgramData%", "%WRITEHAWK_TEST_ROOT%"))[0]
    folder = tmp_path / "NVIDIA Corporation" / "nvtopps" / "nct"
    folder.mkdir(parents=True)
    assert ev.snapshot_files(rule) == {}
    (folder / "nvlog.nvlgstg").write_bytes(b"x" * 100)
    before = ev.snapshot_files(rule)
    assert [size for size, _ in before.values()] == [100]
    (folder / "nvlog.nvlgstg").write_bytes(b"x" * 300)
    (found,) = ev.file_activity(before, ev.snapshot_files(rule))
    assert found.how == "files"


def test_rewrite_loops_reports_only_heavy_unexplained_rewrites():
    tracker = tracker_with(("C:\\App\\state.db", 3000), (LOG, 3000), ("C:\\App\\small.db", 100),
                           (None, 3000))
    for index in range(3000):  # an append: large but never rewritten
        tracker.add_write(100, 9, index * 4096, 4096)
    tracker.set_name(9, "C:\\App\\big.log")
    found = ev.rewrite_loops(tracker, RULES.values())
    assert sorted(item.path for item in found) == ["(unnamed, pid 100)", "C:\\App\\state.db"]


def test_read_dword_reads_hklm_only():
    assert ev.read_dword("HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
                         "No Such Value") is None
    assert ev.read_dword("HKLM\\SOFTWARE\\No Such Key Here", "x") is None
    with pytest.raises(ValueError, match="HKLM"):
        ev.read_dword("HKCU\\Software", "x")
