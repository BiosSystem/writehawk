"""Why a published fix may not have reached this machine.

A vendor shipping a fix and a machine receiving it are separate events. This
turns what the catalog knows about how a fix is delivered, and what
`context.drivers` read from the machine, into plain reasons.
"""
from __future__ import annotations

from ..context.drivers import DriverDelivery
from .evaluate import EXPOSED, UNKNOWN_VERSION, Finding

VENDOR_NAMES = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
PROVIDER_WORDS = {"nvidia": ("nvidia",), "amd": ("advanced micro devices", "amd"),
                  "intel": ("intel",)}


def reasons(finding: Finding, delivery: DriverDelivery) -> list[str]:
    """Empty when the installed version already has the fix or the rule does not apply."""
    if finding.version_state not in (EXPOSED, UNKNOWN_VERSION):
        return []
    rule = finding.rule
    vendor = VENDOR_NAMES.get(rule.vendor, rule.vendor)
    found = []
    if rule.delivery_note:
        found.append(rule.delivery_note)
    if not delivery.updaters.get(rule.vendor):
        found.append(f"No {vendor} update program is installed, so nothing on this machine "
                     f"asks {vendor} for new drivers.")
    for adapter in finding.adapters:
        provider = adapter.driver_provider
        if provider and not any(word in provider.lower()
                                for word in PROVIDER_WORDS.get(rule.vendor, ())):
            found.append(f"The driver of {adapter.name} was supplied by {provider}, not by "
                         f"{vendor}, so {vendor}'s releases do not replace it on their own.")
    if delivery.windows_update_excludes_drivers:
        found.append("Windows Update is set by policy not to deliver drivers.")
    if delivery.portable:
        maker = f" from {delivery.system_maker}" if delivery.system_maker else ""
        found.append(f"This is a portable machine{maker}. Graphics vendors point notebook "
                     "owners to the maker's own driver, which usually appears later.")
    return found
