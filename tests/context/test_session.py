import os
import time

import pytest

from writehawk.context import session


def test_idle_from_ticks_survives_the_counter_wrapping():
    assert session.idle_from_ticks(5000, 2000) == 3.0
    assert session.idle_from_ticks(1000, 0xFFFFFFFF - 999) == 2.0


def test_state_properties():
    assert session.Session(0.0, "busy").fullscreen
    assert session.Session(0.0, "d3d_fullscreen").fullscreen
    assert not session.Session(0.0, "normal").fullscreen
    assert not session.Session(0.0, "presentation").fullscreen
    assert not session.Session(0.0, "not_present").user_present
    assert session.Session(0.0, "unknown").user_present


def test_a_caller_without_a_session_gets_minus_one(monkeypatch):
    def refuse():
        raise OSError("no session")
    monkeypatch.setattr(session, "idle_seconds", refuse)
    assert session.read().idle_seconds == -1.0


def test_live_session_is_readable():
    now = session.read()
    assert now.idle_seconds >= 0
    assert now.state in (*session.STATES.values(), "unknown")


@pytest.mark.skipif(os.environ.get("WRITEHAWK_SANDBOX") != "1",
                    reason="covers the whole screen; runs only in the sandbox harness")
def test_sandbox_a_window_covering_the_screen_reads_as_fullscreen():
    tkinter = pytest.importorskip("tkinter")
    before = session.notification_state()
    root = tkinter.Tk()
    try:
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.focus_force()
        seen = before
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            root.update()
            seen = session.notification_state()
            if seen in session.FULLSCREEN_STATES:
                break
            time.sleep(0.1)
    finally:
        root.destroy()
    assert before not in session.FULLSCREEN_STATES
    assert seen in session.FULLSCREEN_STATES
