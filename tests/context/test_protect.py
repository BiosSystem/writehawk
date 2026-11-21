import os
import shutil

import pytest

from writehawk.context import protect
from writehawk.context.protect import Entry, ProtectedList, Signature
from writehawk.measure.filetrace import is_elevated
from writehawk.measure.sampler import list_processes

CSRSS = os.path.expandvars("%SystemRoot%\\System32\\csrss.exe")
GOOD = Signature("embedded", "Good Signer")


def listed(tmp_path, signature, name="tool.exe"):
    image = tmp_path / name
    image.write_bytes(b"x")
    entries = [Entry(str(image), ("Good Signer",))]
    return str(image), ProtectedList(entries, signature=signature)


def test_path_pattern_is_exact_and_ignores_case():
    pattern = protect.path_pattern("C:\\Dir\\Tool.exe")
    assert pattern.fullmatch(protect.normalize("c:\\dir\\TOOL.EXE"))
    assert not pattern.fullmatch(protect.normalize("C:\\Dir\\Tool.exe.bak"))
    assert not pattern.fullmatch(protect.normalize("C:\\Other\\Dir\\Tool.exe"))
    assert pattern.fullmatch(protect.normalize("C:\\Dir\\Sub\\..\\Tool.exe"))


def test_a_star_covers_one_folder_and_no_more():
    pattern = protect.path_pattern("C:\\App\\*\\Tool.exe")
    assert pattern.fullmatch(protect.normalize("C:\\App\\1.2.3\\Tool.exe"))
    assert not pattern.fullmatch(protect.normalize("C:\\App\\Tool.exe"))
    assert not pattern.fullmatch(protect.normalize("C:\\App\\1.2.3\\bin\\Tool.exe"))


def test_listed_path_with_listed_signer_is_protected(tmp_path):
    image, protected = listed(tmp_path, lambda _: GOOD)
    assert protected.is_protected_image(image)
    assert protected.is_protected_image(image.upper())


@pytest.mark.parametrize("found", [
    Signature("embedded", "Someone Else"), Signature("unsigned", ""), Signature("invalid", ""),
    Signature("unreadable", ""), Signature("invalid", "Good Signer")])
def test_listed_path_without_a_valid_listed_signature_is_not_protected(tmp_path, found):
    image, protected = listed(tmp_path, lambda _: found)
    assert not protected.is_protected_image(image)


def test_the_signature_of_an_unlisted_path_is_never_asked_for(tmp_path):
    def refuse(path):
        raise AssertionError(path)
    _, protected = listed(tmp_path, refuse)
    assert not protected.is_protected_image(str(tmp_path / "other.exe"))


def test_a_replaced_file_is_checked_again(tmp_path):
    answers = [GOOD, Signature("unsigned", "")]
    calls = []

    def signature(path):
        calls.append(path)
        return answers[len(calls) - 1]
    image, protected = listed(tmp_path, signature)
    assert protected.is_protected_image(image)
    assert protected.is_protected_image(image)
    assert len(calls) == 1
    with open(image, "wb") as replaced:
        replaced.write(b"something else")
    assert not protected.is_protected_image(image)
    assert len(calls) == 2


def test_classify(tmp_path):
    image, _ = listed(tmp_path, lambda _: GOOD)
    paths = {10: image, 11: str(tmp_path / "other.exe"), 12: None}
    protected = ProtectedList([Entry(image, ("Good Signer",))], signature=lambda _: GOOD,
                              locate=paths.get)
    assert protected.classify(10) == protect.PROTECTED
    assert protected.classify(11) == protect.OPEN
    assert protected.classify(12) == protect.UNKNOWN
    assert protected.classify(4) == protect.PROTECTED
    assert protected.classify(0) == protect.PROTECTED


def test_live_signature_of_a_system_image():
    found = protect.signature_of(CSRSS)
    assert found.valid
    assert found.signer in protect.WINDOWS_SIGNERS


def test_live_unsigned_file_has_no_signer(tmp_path):
    image = tmp_path / "plain.exe"
    image.write_bytes(b"MZ" + b"\0" * 200)
    found = protect.signature_of(str(image))
    assert not found.valid
    assert not found.signer


def test_live_a_copy_of_a_protected_image_is_not_protected(tmp_path):
    protected = ProtectedList()
    copy = str(tmp_path / "csrss.exe")
    shutil.copy(CSRSS, copy)
    assert protected.is_protected_image(CSRSS)
    assert protect.signature_of(copy).valid  # still signed, only the path is wrong
    assert not protected.is_protected_image(copy)


def test_live_a_file_that_borrows_a_protected_name_is_not_protected(tmp_path):
    fake = tmp_path / "System32" / "csrss.exe"
    fake.parent.mkdir()
    fake.write_bytes(b"MZ" + b"\0" * 200)
    assert not ProtectedList().is_protected_image(str(fake))


def test_live_own_process_is_open_and_its_image_is_found():
    assert protect.image_path(os.getpid()) is not None
    assert ProtectedList().classify(os.getpid()) == protect.OPEN


def test_live_a_process_that_does_not_exist_is_unknown():
    assert ProtectedList().classify(0x7FFFFFF0) == protect.UNKNOWN


@pytest.mark.skipif(not is_elevated(), reason="system processes can be opened only elevated")
def test_live_elevated_system_processes_are_protected():
    protected = ProtectedList()
    seen = {name.lower(): protected.classify(pid) for pid, name in list_processes()}
    for name in ("csrss.exe", "services.exe", "lsass.exe", "winlogon.exe"):
        assert seen.get(name) == protect.PROTECTED, (name, seen.get(name))
    # Not every installation runs it, and its folder carries a version number.
    assert seen.get("msmpeng.exe", protect.PROTECTED) == protect.PROTECTED
