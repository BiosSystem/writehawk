import os
import struct

from writehawk.context import storage


def extents(*disks):
    raw = struct.pack("<I4x", len(disks))
    for disk in disks:
        raw += struct.pack("<I4xqq", disk, 0, 1 << 30)
    return raw


def descriptor(bus, removable, vendor, product):
    head = 40
    strings = vendor + b"\0" + product + b"\0"
    vendor_at = head if vendor else 0
    product_at = head + len(vendor) + 1
    return struct.pack("<IIBBBBIIIII", 40, head + len(strings), 0, 0, removable, 0, vendor_at,
                       product_at, 0, 0, bus) + b"\0" * 8 + strings


def test_parse_extents():
    assert storage.parse_extents(extents(2)) == (2,)
    assert storage.parse_extents(extents(1, 3, 1)) == (1, 3)
    assert storage.parse_extents(b"") == ()
    assert storage.parse_extents(extents(1, 2)[:40]) == (1,)  # cut short


def test_parse_descriptor():
    raw = descriptor(17, 0, b"", b"Some Disk 1TB  ")
    assert storage.parse_descriptor(raw) == ("nvme", False, "Some Disk 1TB")
    raw = descriptor(7, 1, b"Maker   ", b"Stick")
    assert storage.parse_descriptor(raw) == ("usb", True, "Maker Stick")
    assert storage.parse_descriptor(descriptor(99, 0, b"", b"x"))[0] == "unknown"
    assert storage.parse_descriptor(b"\0" * 8) == ("unknown", False, "")


def test_parse_flag_and_media_type():
    assert storage.parse_flag(struct.pack("<II?", 12, 12, True)) is True
    assert storage.parse_flag(struct.pack("<II?", 12, 12, False)) is False
    assert storage.parse_flag(b"") is None
    assert storage.media_type(True) == "hdd"
    assert storage.media_type(False) == "ssd"
    assert storage.media_type(None) == "unknown"


def test_live_system_volume_has_a_disk_and_a_file_system():
    system = os.environ["SYSTEMDRIVE"].upper() + "\\"
    found = {volume.root.upper(): volume for volume in storage.volumes()}
    assert system in found
    assert found[system].disks
    assert found[system].filesystem
    assert found[system].media in ("ssd", "hdd", "unknown")


def test_a_drive_letter_that_does_not_exist_reads_as_unknown():
    letters = {root[0].upper() for root, _ in storage.roots()}
    free = next(letter for letter in "ZYXWVUTSRQ" if letter not in letters)
    volume = storage.read_volume(free + ":\\")
    assert volume.disks == ()
    assert (volume.media, volume.bus, volume.filesystem) == ("unknown", "unknown", "")
