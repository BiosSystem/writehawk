import os

from writehawk.measure.sampler import IoCounters, ProcSample, Sampler, read_process, snapshot


def _sample(pid, created, write_bytes, write_ops, name="a.exe"):
    return ProcSample(pid, name, created, IoCounters(0, write_ops, 0, 0, write_bytes, 0))


class _Feed:
    def __init__(self, frames):
        self.frames = list(frames)
        self.now = 0.0

    def source(self):
        self.now, samples = self.frames.pop(0)
        return samples, 0

    def clock(self):
        return self.now


def test_rates_over_window():
    feed = _Feed([(0.0, [_sample(5, 1, 0, 0)]),
                  (10.0, [_sample(5, 1, 1000, 10)]),
                  (20.0, [_sample(5, 1, 5000, 20)])])
    s = Sampler(feed.source, feed.clock)
    for _ in range(3):
        s.sample()
    (short,) = s.rates(10)
    assert (short.write_bytes, short.write_ops, short.seconds) == (4000, 10, 10.0)
    assert short.write_bps == 400.0
    assert short.avg_write_size == 400.0
    (long,) = s.rates(60)
    assert (long.write_bytes, long.seconds) == (5000, 20.0)


def test_single_sample_gives_no_rate():
    feed = _Feed([(0.0, [_sample(5, 1, 0, 0)])])
    s = Sampler(feed.source, feed.clock)
    s.sample()
    assert s.rates(10) == []


def test_reused_pid_is_a_new_process():
    feed = _Feed([(0.0, [_sample(5, 1, 9_000_000, 100)]),
                  (10.0, [_sample(5, 2, 100, 1)]),
                  (20.0, [_sample(5, 2, 300, 2)])])
    s = Sampler(feed.source, feed.clock)
    for _ in range(3):
        s.sample()
    (rate,) = s.rates(60)
    assert rate.write_bytes == 200


def test_exited_process_is_dropped_and_old_samples_expire():
    frames = [(0.0, [_sample(5, 1, 0, 0), _sample(6, 1, 0, 0)])]
    frames += [(float(t), [_sample(5, 1, t, t)]) for t in (50, 100, 150)]
    feed = _Feed(frames)
    s = Sampler(feed.source, feed.clock, keep=60.0)
    for _ in range(4):
        s.sample()
    assert list(s._history) == [(5, 1)]
    assert [t for t, _ in s._history[(5, 1)]] == [100.0, 150.0]


def test_busiest_writer_first():
    feed = _Feed([(0.0, [_sample(1, 1, 0, 0), _sample(2, 1, 0, 0)]),
                  (1.0, [_sample(1, 1, 10, 1), _sample(2, 1, 99, 1)])])
    s = Sampler(feed.source, feed.clock)
    s.sample()
    s.sample()
    assert [r.pid for r in s.rates(5)] == [2, 1]


def test_live_counters_move_when_this_process_writes(tmp_path):
    created, before = read_process(os.getpid())
    (tmp_path / "x.bin").write_bytes(b"\0" * 200_000)
    created_again, after = read_process(os.getpid())
    assert created == created_again
    assert after.write_bytes - before.write_bytes >= 200_000


def test_live_snapshot_contains_this_process():
    samples, unreadable = snapshot()
    assert any(s.pid == os.getpid() for s in samples)
    assert unreadable >= 0
    assert read_process(0xFFFFFFF0) is None
