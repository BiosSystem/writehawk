import pytest

from writehawk import cli, selftest
from writehawk.measure.filetrace import is_elevated


def test_windows_name():
    assert selftest.windows_name(19045, 1) == "Windows 10"
    assert selftest.windows_name(26100, 1) == "Windows 11"
    assert selftest.windows_name(20348, 3) == "Windows Server"
    assert selftest.windows_name(17763, 2) == "Windows Server"


def test_run_checks_sorts_pass_fail_and_skip():
    def broken():
        raise OSError("no such thing")

    def later():
        raise selftest.Skip("needs an administrator terminal")

    results = selftest.run_checks([("good", lambda: "fine"), ("bad", broken), ("later", later)])
    assert [(r.status, r.detail) for r in results] == [
        ("PASS", "fine"), ("FAIL", "OSError: no such thing"),
        ("SKIP", "needs an administrator terminal")]
    text = selftest.format_results("system line", results)
    assert text.splitlines()[0] == "system line"
    assert "FAIL  bad: OSError: no such thing" in text
    assert "1 passed, 1 failed, 1 skipped" in text
    assert "Run it again from an administrator terminal" in text


def test_a_skip_for_another_reason_does_not_ask_for_an_administrator():
    results = selftest.run_checks([("displays", lambda: (_ for _ in ()).throw(
        selftest.Skip("no desktop session to ask")))])
    assert "administrator" not in selftest.format_results("system", results)


def test_describe_system_names_windows_and_python_only():
    text = selftest.describe_system()
    assert text.startswith("writehawk ")
    assert "Windows" in text
    assert "Python 3." in text


def test_live_selftest_passes_every_check_it_can_run(capsys):
    code = cli.main(["selftest"])
    out = capsys.readouterr().out
    assert "FAIL" not in out, out
    assert code == 0
    if not is_elevated():
        # A service account (as on a CI runner) also has no desktop to read displays from.
        assert "SKIP  file trace: needs an administrator terminal" in out
        assert "SKIP  naming files opened earlier: needs an administrator terminal" in out
        assert "Run it again from an administrator terminal" in out


@pytest.mark.parametrize("name", [name for name, _ in selftest.CHECKS])
def test_every_check_has_a_distinct_name(name):
    assert [n for n, _ in selftest.CHECKS].count(name) == 1
