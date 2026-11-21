import json

import pytest

from writehawk.rules import catalog
from writehawk.rules.catalog import CatalogError

RULE = {
    "id": "some-rule", "vendor": "nvidia", "title": "t", "summary": "s",
    "sources": ["https://example.org/report"], "affected_from": "1.2", "fixed_in": "1.5",
    "files": ["%ProgramData%\\Some\\*"], "processes": ["some.exe"],
    "workaround": {"vendor_documented": False, "requires": None, "note": "n", "steps": [
        {"type": "registry_dword", "key": "HKLM\\SOFTWARE\\Some", "name": "Off", "value": 1},
        {"type": "service_start", "service": "Some Service", "start": 4}]},
}


def text(**changes):
    return json.dumps({"format": 1, "rules": [{**RULE, **changes}]})


def test_parse_version():
    assert catalog.parse_version("621.35") == (621, 35)
    assert catalog.parse_version("26.11.1") > catalog.parse_version("24.10.24")
    assert catalog.parse_version("621.4") < catalog.parse_version("621.35")
    assert catalog.parse_version("") is None
    assert catalog.parse_version("24.Q3") is None


def test_a_rule_is_read_with_its_steps():
    (rule,) = catalog.parse(text())
    first, second = rule.steps
    assert (first.key, first.name, first.value) == ("HKLM\\SOFTWARE\\Some", "Off", 1)
    assert second.key == "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Some Service"
    assert (second.name, second.value) == ("Start", 4)
    assert rule.workaround_documented is False


@pytest.mark.parametrize("changes", [
    {"sources": []},
    {"fixed_in": "soon"},
    {"affected_from": "old"},
    {"id": "Has Spaces"},
    {"workaround": {**RULE["workaround"], "requires": "a full moon"}},
    {"workaround": {**RULE["workaround"], "vendor_documented": "yes"}},
    {"workaround": {**RULE["workaround"], "steps": [{"type": "run", "command": "x"}]}},
    {"workaround": {**RULE["workaround"], "steps": [
        {"type": "registry_dword", "key": "HKCU\\Software\\X", "name": "a", "value": 1}]}},
    {"workaround": {**RULE["workaround"], "steps": [
        {"type": "registry_dword", "key": "HKLM\\X", "name": "a", "value": "1"}]}},
    {"workaround": {**RULE["workaround"], "steps": [
        {"type": "service_start", "service": "S", "start": 0}]}},
])
def test_a_malformed_rule_is_refused(changes):
    with pytest.raises(CatalogError):
        catalog.parse(text(**changes))


def test_a_missing_field_names_the_rule():
    raw = {key: value for key, value in RULE.items() if key != "files"}
    with pytest.raises(CatalogError, match="some-rule"):
        catalog.parse(json.dumps({"format": 1, "rules": [raw]}))


def test_duplicate_ids_and_other_formats_are_refused():
    with pytest.raises(CatalogError):
        catalog.parse(json.dumps({"format": 1, "rules": [RULE, RULE]}))
    with pytest.raises(CatalogError):
        catalog.parse(json.dumps({"format": 2, "rules": []}))


def test_the_shipped_catalog_loads_and_every_rule_has_a_source():
    rules = catalog.load()
    assert {rule.id for rule in rules} >= {"nvidia-nvtopps-log-rewrite", "amd-eeu-dump-files"}
    for rule in rules:
        assert all(source.startswith("https://") for source in rule.sources)
        assert rule.steps
        assert rule.files
