"""#75 -- a walk that stops early must neither hang the scan nor hide the gap.

`scan_dir` and `scan_dir_report` each walk the tree on a producer thread, which
puts one shutdown sentinel per worker after the last path. If the walk raised
before that loop, no sentinel was put. Every worker then waited in `get()`
forever, the `ThreadPoolExecutor` block waited for the workers, and the scan
never returned. The exception went to `threading.excepthook` on stderr and
nowhere else.

Putting the sentinels in `finally` stops the hang, but it is only half the
fix. Alone, it lets the scan return normally after walking part of the tree
and report the result as complete with exit 0, which is the problem #57 fixed
for unreadable files. So each test here checks both halves: the scan returns,
and the stopped walk is reported as a failure.

The walk is made to fail by patching `walk_regular_files` with a generator
that yields one real file and then raises. If the `finally` is lost, the test
hangs and the `timeout = 60` in `pytest.ini` reports every thread's stack.
"""

from __future__ import annotations

import logging

import pytest

from src import file_ops, reporting
from src.db import get_all_files_info

EXIT_INCOMPLETE = 3


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    for name in ("first.txt", "second.txt"):
        (root / name).write_text(name)
    return root


def _walk_that_stops_after_one(module, monkeypatch, tree):
    """Make the walk yield first.txt, then raise as if the producer broke."""
    first = str(tree / "first.txt")

    def broken_walk(top, skipped):
        yield first
        raise RuntimeError("simulated walk failure")

    monkeypatch.setattr(module, "walk_regular_files", broken_walk)
    return first


def _recorded(db_path):
    return {row[0] for row in get_all_files_info(db_path)}


# -- scan_dir ------------------------------------------------------------------


@pytest.mark.parametrize("num_threads", [1, 4])
def test_scan_dir_returns_and_reports_the_stopped_walk(db_path, tree, monkeypatch,
                                                       num_threads):
    first = _walk_that_stops_after_one(file_ops, monkeypatch, tree)

    tally = file_ops.scan_dir(str(tree), db_path, num_threads)

    assert _recorded(db_path) == {first}, "what was walked is still recorded"
    assert tally.failures == [
        (str(tree), "walk stopped early: simulated walk failure")]


def test_the_stopped_walk_is_logged_with_its_traceback(db_path, tree, monkeypatch,
                                                       caplog):
    _walk_that_stops_after_one(file_ops, monkeypatch, tree)

    with caplog.at_level(logging.ERROR):
        file_ops.scan_dir(str(tree), db_path, 2)

    [record] = [r for r in caplog.records if "stopped early" in r.getMessage()]
    assert record.exc_info is not None, "the traceback is what makes it fixable"


def test_cli_scan_exits_3_when_the_walk_stops_early(run_cli, db_path, tree,
                                                    monkeypatch):
    _walk_that_stops_after_one(file_ops, monkeypatch, tree)

    result = run_cli("--db-path", db_path, "scan", str(tree))

    assert result.exit_code == EXIT_INCOMPLETE
    assert "walk stopped early: simulated walk failure" in result.stdout


# -- scan_dir_report -------------------------------------------------------------


@pytest.mark.parametrize("num_threads", [1, 4])
def test_scan_dir_report_returns_false_when_the_walk_stops(db_path, tree,
                                                           monkeypatch, num_threads):
    first = _walk_that_stops_after_one(reporting, monkeypatch, tree)

    assert reporting.scan_dir_report(str(tree), db_path, num_threads) is False
    assert _recorded(db_path) == {first}


def test_scan_dir_report_returns_true_when_the_walk_finishes(db_path, tree):
    assert reporting.scan_dir_report(str(tree), db_path, 2) is True


def test_cli_scan_dir_report_exits_3_when_the_walk_stops(run_cli, db_path, tree,
                                                         monkeypatch):
    _walk_that_stops_after_one(reporting, monkeypatch, tree)

    result = run_cli("--db-path", db_path, "scan-dir-report", str(tree))

    assert result.exit_code == EXIT_INCOMPLETE


def test_cli_scan_dir_report_exits_0_when_the_walk_finishes(run_cli, db_path, tree):
    result = run_cli("--db-path", db_path, "scan-dir-report", str(tree))

    assert result.exit_code == 0
