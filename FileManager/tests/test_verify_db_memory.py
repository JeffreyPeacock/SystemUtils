"""#68 -- verify-db reads the database a page at a time.

Before #68, `verify_db` read every recorded (path, md5sum) into one list, then
submitted one future per row before it collected any. Both grew with the
database: about 1.31 GiB for /home2 before the first file was hashed.

Now the rows come from `iter_recorded_checksums`, one keyset page per query,
and the pool holds at most `VERIFY_IN_FLIGHT_PER_WORKER` files per worker.

Rows are inserted with sqlite3 directly, because tens of thousands of
`store_file_info` calls open one connection each and take minutes. The test
files are not under src/, so `tests/test_db_owns_the_connection.py` does not
apply to them.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import tracemalloc

import pytest

from src import db, file_ops
from src.db import initialize_db, iter_recorded_checksums, recorded_checksums_page
from src.file_ops import VERIFY_IN_FLIGHT_PER_WORKER, verify_db

STORED = "0" * 32


def _fill(db_path, paths, md5=STORED):
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO files (md5sum, size, last_modified, path) "
            "VALUES (?, 1, 1, ?)",
            [(md5, p) for p in paths],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def empty_db(tmp_path):
    path = str(tmp_path / "pages.db")
    initialize_db(path)
    return path


def _paths(n, root="/v"):
    return [f"{root}/dir{i % 7}/file-{i:07d}.bin" for i in range(n)]


# --- the pages ----------------------------------------------------------------

@pytest.mark.parametrize("n", [0, 1, 9, 10, 11, 25, 30])
def test_every_row_is_read_once_in_path_order(empty_db, n):
    """Page size 10 and row counts on, below and past each page boundary:
    a keyset bug shows up as a lost or repeated row at a boundary."""
    paths = _paths(n)
    _fill(empty_db, paths)

    got = [p for p, _ in iter_recorded_checksums(empty_db, page_size=10)]

    assert got == sorted(paths)


def test_a_prefix_is_paged_too(empty_db):
    inside = _paths(23, root="/keep")
    _fill(empty_db, inside + _paths(17, root="/drop"))

    got = [p for p, _ in iter_recorded_checksums(empty_db, "/keep",
                                                 page_size=5)]

    assert got == sorted(inside)


def test_a_page_never_holds_more_than_its_limit(empty_db):
    _fill(empty_db, _paths(30))
    page = recorded_checksums_page(empty_db, limit=7)
    assert len(page) == 7
    rest = recorded_checksums_page(empty_db, after=page[-1][0], limit=100)
    assert len(rest) == 23
    assert rest[0][0] > page[-1][0]


def test_no_connection_is_open_while_a_row_is_handled(empty_db, monkeypatch):
    """No lazy handle escapes `with_connection`: each page is read and the
    connection closed before the generator yields from it."""
    _fill(empty_db, _paths(25))
    open_now = 0
    real = db.with_connection

    def counting(*args, **kwargs):
        nonlocal open_now
        open_now += 1
        try:
            return real(*args, **kwargs)
        finally:
            open_now -= 1

    monkeypatch.setattr(db, "with_connection", counting)
    seen = 0
    for _ in iter_recorded_checksums(empty_db, page_size=10):
        assert open_now == 0
        seen += 1
    assert seen == 25


def test_a_row_with_no_path_is_still_reported_unreadable(empty_db):
    """The schema allows a NULL path. Paging by path cannot reach one, so it
    is read separately -- before #68 verify-db reported it as unreadable, and
    dropping it silently would turn "could not check" into nothing."""
    _fill(empty_db, [None, "/v/missing"])

    tally = verify_db(empty_db, 2)

    assert tally.checked == 2
    assert tally.unreadable == 2
    assert None in [path for path, _ in tally.failures]


# --- the pool -------------------------------------------------------------------

def test_the_pool_never_holds_more_than_its_bound(empty_db, monkeypatch):
    """The futures were the second thing that grew with the database."""
    _fill(empty_db, _paths(500))
    threads = 3
    bound = threads * VERIFY_IN_FLIGHT_PER_WORKER
    submitted = 0
    finished = 0
    worst = 0
    lock = threading.Lock()
    real_submit = file_ops.ThreadPoolExecutor.submit

    def fake_verify(path, stored, tally):
        nonlocal finished
        # Slower than submitting, as hashing is. Without the bound, every row
        # is submitted before many finish.
        time.sleep(0.002)
        tally.record_match()
        with lock:
            finished += 1

    def tracking_submit(self, fn, *args, **kwargs):
        nonlocal submitted, worst
        with lock:
            submitted += 1
            # Submitted and not yet collected is at least submitted - finished.
            worst = max(worst, submitted - finished)
        return real_submit(self, fn, *args, **kwargs)

    monkeypatch.setattr(file_ops, "verify_one_recording", fake_verify)
    monkeypatch.setattr(file_ops.ThreadPoolExecutor, "submit", tracking_submit)

    tally = verify_db(empty_db, threads)

    assert tally.matched == 500
    assert worst <= bound


def test_peak_memory_does_not_grow_with_the_database(tmp_path, monkeypatch):
    """The acceptance test of #68. Three times the rows must not cost three
    times the memory. Hashing is replaced by a match, so what is measured is
    the reading and the pool, which is what grew."""
    monkeypatch.setattr(file_ops, "compute_md5", lambda path: STORED)

    def peak(n):
        path = str(tmp_path / f"rows-{n}.db")
        initialize_db(path)
        _fill(path, _paths(n))
        tracemalloc.start()
        try:
            tally = verify_db(path, 4)
            _, top = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert tally.matched == n
        return top

    small = peak(20_000)
    large = peak(60_000)

    assert large < small * 1.5, (small, large)
