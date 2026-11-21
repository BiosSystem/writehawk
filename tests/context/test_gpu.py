from writehawk.context import gpu

NV = "PCI\\VEN_10DE&DEV_1F02&SUBSYS_00000000&REV_A1\\4&1&0&0009"
AMD = "PCI\\VEN_1002&DEV_13C0&SUBSYS_00000000&REV_CB\\4&2&0&0041"
VALUES = {
    NV: {"DeviceDesc": "@oem1.inf,%dev%;Card One", "DriverDesc": "Card One",
         "DriverVersion": "32.0.15.6094", "ProviderName": "NVIDIA", "DriverDate": "8-1-2024"},
    AMD: {"DeviceDesc": "@oem2.inf,%dev%;Card Two", "DriverVersion": "32.0.11024.2",
          "RadeonSoftwareVersion": "24.10.24"},
}


def test_parse_ids():
    assert gpu.parse_ids(NV) == (0x10DE, 0x1F02)
    assert gpu.parse_ids("pci\\ven_8086&dev_a780") == (0x8086, 0xA780)
    assert gpu.parse_ids("ROOT\\BASICDISPLAY\\0000") == (None, None)


def test_clean_description():
    assert gpu.clean_description("@oem98.inf,%dev.1f02%;Some Adapter") == "Some Adapter"
    assert gpu.clean_description("Plain Name") == "Plain Name"


def test_nvidia_release():
    assert gpu.nvidia_release("32.0.15.6094") == "560.94"
    assert gpu.nvidia_release("31.0.15.3623") == "536.23"
    assert not gpu.nvidia_release("")
    assert not gpu.nvidia_release("1.2")


def test_instance_from_adapter_path():
    path = ("\\\\?\\PCI#VEN_10DE&DEV_1F02&SUBSYS_00000000&REV_A1#4&1&0&0009#"
            "{5b45201d-f2f2-4f3b-85bb-30ff1f953599}")
    assert gpu.instance_from_adapter_path(path) == NV
    assert gpu.instance_from_adapter_path("ROOT#X#0000") == "ROOT\\X\\0000"


def test_an_adapter_without_an_active_path_drives_no_display():
    first, second = gpu.build([NV, AMD], VALUES.__getitem__, [NV.lower(), NV])
    assert (first.vendor, first.displays, first.release) == ("nvidia", 2, "560.94")
    assert (second.vendor, second.displays, second.release) == ("amd", 0, "24.10.24")
    assert first.name == "Card One"
    assert second.name == "Card Two"


def test_unreadable_display_paths_are_not_reported_as_zero():
    (only,) = gpu.build([NV], VALUES.__getitem__, None)
    assert only.displays is None


def test_a_device_off_the_pci_bus_has_no_vendor():
    (only,) = gpu.build(["ROOT\\BASICDISPLAY\\0000"], lambda _: {}, [])
    assert (only.vendor, only.vendor_id, only.name, only.driver_version) == ("other", None, "", "")


def test_live_adapters_are_readable():
    found = gpu.gpus()
    ids = {item.instance_id.upper() for item in found}
    assert all(item.instance_id for item in found)
    active = gpu.active_adapters()
    if active is not None:
        known = [instance for instance in active if instance.upper() in ids]
        assert sum(item.displays for item in found) == len(known)
