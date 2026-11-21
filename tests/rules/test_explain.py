from writehawk.context import drivers
from writehawk.context.drivers import DriverDelivery
from writehawk.context.gpu import Gpu
from writehawk.rules import catalog, explain
from writehawk.rules import evaluate as ev

RULES = {rule.id: rule for rule in catalog.load()}
NVIDIA = RULES["nvidia-nvtopps-log-rewrite"]
AMD = RULES["amd-eeu-dump-files"]
QUIET = DriverDelivery({"nvidia": ("NVIDIA App",), "amd": ("AMD Software",)}, False, "", False)


def finding(rule, vendor, release, provider):
    card = Gpu("PCI\\X", "Some Card", vendor, 1, 2, "1.2.3.4", release, provider, "", 1)
    return ev.evaluate(rule, [card], lambda *_: None)


def test_no_reasons_once_the_fixed_version_is_installed():
    assert explain.reasons(finding(NVIDIA, "nvidia", "621.35", "NVIDIA"), QUIET) == []
    assert explain.reasons(finding(NVIDIA, "amd", "1.0", "x"), QUIET) == []


def test_a_manual_only_fix_is_the_first_reason_given():
    (only,) = explain.reasons(finding(NVIDIA, "nvidia", "621.24", "NVIDIA"), QUIET)
    assert "downloaded and installed by hand" in only


def test_machine_facts_add_their_own_reasons():
    facts = DriverDelivery({"amd": ()}, True, "Some Maker", True)
    found = explain.reasons(finding(AMD, "amd", "24.10.24", "Microsoft"), facts)
    text = "\n".join(found)
    assert "Optional" in found[0]
    assert "No AMD update program is installed" in text
    assert "supplied by Microsoft, not by AMD" in text
    assert "policy not to deliver drivers" in text
    assert "portable machine from Some Maker" in text


def test_the_vendor_as_provider_is_not_a_reason():
    found = explain.reasons(
        finding(AMD, "amd", "24.10.24", "Advanced Micro Devices, Inc."), QUIET)
    assert len(found) == 1


def test_match_updaters():
    found = drivers.match_updaters(["NVIDIA App 11.0", "NVIDIA Container", "AMD Software",
                                    "Something Else"])
    assert found["nvidia"] == ("NVIDIA App 11.0",)
    assert found["amd"] == ("AMD Software",)
    assert found["intel"] == ()


def test_battery_from_flag():
    assert drivers.battery_from_flag(128) is False
    assert drivers.battery_from_flag(1) is True
    assert drivers.battery_from_flag(255) is None


def test_live_delivery_facts_are_readable():
    facts = drivers.read()
    assert set(facts.updaters) == set(drivers.UPDATERS)
    assert facts.portable in (True, False, None)
