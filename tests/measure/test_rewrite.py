from writehawk.measure.rewrite import MAX_EXTENTS, FileWrites, RewriteTracker


def test_append_has_ratio_one():
    f = FileWrites(1, 1)
    for i in range(100):
        f.add(i * 4096, 4096)
    assert f.bytes_written == 409600
    assert f.distinct_bytes == 409600
    assert f.rewrite_ratio == 1.0
    assert len(f._starts) == 1


def test_rewrite_in_place_has_high_ratio():
    f = FileWrites(1, 1)
    for _ in range(500):
        f.add(0, 4096)
    assert f.distinct_bytes == 4096
    assert f.rewrite_ratio == 500.0


def test_overlapping_and_out_of_order_writes_merge():
    f = FileWrites(1, 1)
    f.add(100, 50)   # 100-150
    f.add(300, 50)   # 300-350
    f.add(0, 10)     # 0-10
    f.add(140, 170)  # 140-310 joins the first two
    assert list(zip(f._starts, f._ends, strict=True)) == [(0, 10), (100, 350)]
    assert f.distinct_bytes == 260


def test_zero_size_write_is_ignored():
    f = FileWrites(1, 1)
    f.add(0, 0)
    assert f.writes == 0
    assert f.rewrite_ratio == 0.0


def test_extent_cap_only_lowers_the_ratio():
    f = FileWrites(1, 1)
    for i in range(MAX_EXTENTS + 1):
        f.add(i * 100, 10)  # sparse: never merges
    assert len(f._starts) == 1
    assert f.distinct_bytes >= f.bytes_written
    assert f.rewrite_ratio <= 1.0


def test_tracker_keeps_processes_apart_and_ranks_by_bytes():
    t = RewriteTracker()
    t.add_write(10, 7, 0, 100)
    t.add_write(11, 7, 0, 100)
    t.add_write(11, 7, 0, 100)
    t.set_name(7, r"C:\x.log")
    top = t.top()
    assert [(f.pid, f.bytes_written) for f in top] == [(11, 200), (10, 100)]
    assert t.name_of(7) == r"C:\x.log"
    assert t.top(min_bytes=150) == [top[0]]


def test_forget_drops_every_total_of_one_file():
    tracker = RewriteTracker()
    tracker.add_write(1, 7, 0, 10)
    tracker.add_write(2, 7, 0, 10)
    tracker.add_write(1, 8, 0, 10)
    tracker.add_flush(7, 10)
    tracker.set_name(7, "marker")
    tracker.forget(7)
    assert [entry.file_id for entry in tracker.files.values()] == [8]
    assert tracker.flushed_bytes(7) == 0
    assert tracker.name_of(7) is None
