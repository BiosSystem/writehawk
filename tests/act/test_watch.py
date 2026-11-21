import pytest

from writehawk.act import watch


def test_task_command_quotes_both_paths():
    command = watch.task_command("C:\\Program Files\\Py\\python.exe", "C:\\Out Dir\\r.json", 30)
    assert command == ('"C:\\Program Files\\Py\\python.exe" -m writehawk report --seconds 30 '
                       '--out "C:\\Out Dir\\r.json"')


def test_create_arguments():
    arguments = watch.create_arguments("x", 6)
    assert arguments[:5] == ["schtasks", "/create", "/f", "/tn", watch.TASK_NAME]
    assert arguments[arguments.index("/mo") + 1] == "6"
    assert arguments[-1] == "x"
    for bad in (0, 24):
        with pytest.raises(ValueError, match="hours"):
            watch.create_arguments("x", bad)
