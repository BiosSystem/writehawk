import io

from writehawk.progress import Progress


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Terminal(io.StringIO):
    encoding = "utf-8"  # what a Windows console reports to Python

    def isatty(self):
        return True


class OldTerminal(Terminal):
    encoding = "ascii"


def test_nothing_is_written_without_a_terminal():
    stream = io.StringIO()
    fake = FakeTime()
    shown = Progress(stream, clock=fake.clock, sleep=fake.sleep)
    assert not shown.enabled
    shown.step("Looking")
    shown.done()
    shown.wait(3, "Watching")
    assert stream.getvalue() == ""
    assert fake.slept == [3]


def test_a_terminal_gets_steps_and_a_bar_that_fills():
    stream = Terminal()
    fake = FakeTime()
    shown = Progress(stream, clock=fake.clock, sleep=fake.sleep, width=10)
    assert shown.enabled
    shown.step("Looking at the graphics cards")
    shown.done("2 found")
    shown.wait(1, "Watching")
    text = stream.getvalue()
    assert text.startswith("Looking at the graphics cards ... 2 found\n")
    frames = text.split("\n", 1)[1].split("\r")[1:]
    assert len(frames) == 6  # five ticks of 0.2 s, then the finished bar
    assert frames[0].startswith("Watching  " + "░" * 10 + "    1 s left")
    assert frames[-1].rstrip("\n").rstrip() == "Watching  " + "█" * 10 + "  done"
    assert sum(fake.slept) == 1


def test_a_stream_that_cannot_show_blocks_gets_plain_characters():
    shown = Progress(OldTerminal(), width=4)
    assert shown.bar("x", 0.5, 2) == "x  ##--    2 s left"


def test_a_shorter_line_clears_what_a_longer_one_left():
    stream = Terminal()
    fake = FakeTime()
    shown = Progress(stream, clock=fake.clock, sleep=fake.sleep, width=4)
    shown._draw("a long line here")
    shown._draw("short")
    assert stream.getvalue().endswith("\rshort" + " " * 11)
