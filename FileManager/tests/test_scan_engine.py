"""#32 -- the scan engine: dispatch, the threaded walk, and the skip check.

`file_ops` is where a scan actually happens, and it was the least covered module
in the project. Two paths here are worth more than their line counts:

**The sentinel shutdown.** `scan_dir` puts one empty string per worker on the
queue and each consumer breaks on it without re-posting. Get that wrong and a
scan does not fail, it *hangs*. The `timeout = 60` setting in `pytest.ini`
(pytest-timeout, method `thread`) is what turns that into a red build: it dumps
a traceback for every thread -- naming the consumers blocked in `queue.get()` --
and kills the process. Nothing in this file should try to be cleverer than
that; the reasoning for why the two obvious stdlib alternatives do not work is
recorded beside the setting.

**The skip check.** `process_file` returns without hashing when the recorded
size and mtime both match, which is what makes rescanning a large tree cheap.
Its two halves are covered here by counting calls to `compute_md5` -- asserting
on the stored row cannot tell "skipped" from "rehashed to the same value".
"""

from __future__ import annotations

import os

import pytest

from src import file_ops
from src.db import get_all_files_info, get_file_info, get_md5_by_path
from src.md5sum import compute_md5


@pytest.fixture
def count_hashes(monkeypatch):
    """Count compute_md5 calls made through file_ops, still hashing for real."""
    calls: list[str] = []
    real = file_ops.compute_md5

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(file_ops, "compute_md5", counting)
    return calls


# -- scan() dispatch -------------------------------------------------------


def test_scan_walks_a_directory(db_path, dup_tree):
    file_ops.scan(str(dup_tree.left), db_path, 2)

    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert recorded == {str(p) for p in dup_tree.left.iterdir()}


def test_scan_records_a_single_file(db_path, dup_tree):
    target = dup_tree.left / "unique-left.txt"

    file_ops.scan(str(target), db_path, 4)

    assert [row[0] for row in get_all_files_info(db_path)] == [str(target)]


def test_scan_of_a_missing_path_records_nothing_and_says_so(db_path, tmp_path, caplog):
    missing = tmp_path / "no-such-directory"

    with caplog.at_level("ERROR"):
        file_ops.scan(str(missing), db_path, 4)

    assert get_all_files_info(db_path) == []
    assert f"Invalid path: {missing}" in caplog.text


# -- scan_dir: it must terminate, and record everything --------------------


@pytest.mark.parametrize("num_threads", [1, 4])
def test_scan_dir_terminates_and_records_every_file(db_path, dup_tree,
                                                    num_threads):
    """One sentinel per worker, and the count of workers is the variable.

    Run with one worker and with four: a shutdown that posts too few sentinels
    hangs only when there is more than one consumer, so a single-threaded test
    alone would not catch it.
    """
    file_ops.scan_dir(str(dup_tree.root), db_path, num_threads)

    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert recorded == {str(p) for p in dup_tree.all_files()}


def test_scan_dir_survives_a_file_that_cannot_be_processed(db_path, dup_tree,
                                                           monkeypatch,
                                                           caplog):
    """One bad file must not take the scan down with it.

    The consumer catches per file precisely so a permission error on one path
    does not abandon the rest of the tree.
    """
    doomed = str(dup_tree.left / "shared-one.txt")
    real = file_ops.process_file

    def explode_on_one(file_path, db):
        if file_path == doomed:
            raise OSError("permission denied")
        return real(file_path, db)

    monkeypatch.setattr(file_ops, "process_file", explode_on_one)

    with caplog.at_level("ERROR"):
        file_ops.scan_dir(str(dup_tree.root), db_path, 4)

    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert doomed not in recorded
    assert recorded == {str(p) for p in dup_tree.all_files()} - {doomed}
    assert "permission denied" in caplog.text


# -- the skip check, both halves -------------------------------------------


def test_process_file_hashes_a_file_it_has_not_seen(db_path, dup_tree, count_hashes):
    target = dup_tree.left / "unique-left.txt"

    file_ops.process_file(str(target), db_path)

    assert count_hashes == [str(target)]
    assert get_md5_by_path(db_path, str(target)) == compute_md5(str(target))


def test_process_file_skips_when_size_and_mtime_both_match(db_path, dup_tree,
                                                           count_hashes, capsys):
    """The half that makes a rescan cheap. Counted, not inferred: rehashing an
    unchanged file stores the same row, so the database cannot tell you which
    happened."""
    target = str(dup_tree.left / "unique-left.txt")
    file_ops.process_file(target, db_path)
    capsys.readouterr()
    count_hashes.clear()

    file_ops.process_file(target, db_path)

    assert count_hashes == [], "an unchanged file was hashed a second time"
    assert capsys.readouterr().out == ".", "the skip marker is what the scan prints"


def test_process_file_rehashes_when_the_size_changed(db_path, dup_tree, count_hashes):
    target = str(dup_tree.grows)
    file_ops.process_file(target, db_path)
    before = get_md5_by_path(db_path, target)
    count_hashes.clear()

    dup_tree.grow()
    file_ops.process_file(target, db_path)

    assert count_hashes == [target]
    assert get_md5_by_path(db_path, target) != before
    assert get_file_info(db_path, target)[0] == os.path.getsize(target)


def test_process_file_rehashes_when_only_the_mtime_changed(db_path, dup_tree,
                                                           count_hashes):
    """Same size, new mtime. Half the skip check is the mtime comparison, and a
    change to how mtime is stored would silently disable it."""
    target = str(dup_tree.touched)
    file_ops.process_file(target, db_path)
    before_size = get_file_info(db_path, target)[0]
    count_hashes.clear()

    dup_tree.touch()

    assert os.path.getsize(target) == before_size, "the fixture must keep the size"
    file_ops.process_file(target, db_path)

    assert count_hashes == [target]
    assert get_file_info(db_path, target)[1] == int(os.path.getmtime(target) * 1000)


# -- the other two entry points --------------------------------------------


def test_process_files_concurrently_records_all_of_them(db_path, dup_tree):
    paths = [str(p) for p in dup_tree.all_files()]

    file_ops.process_files_concurrently(paths, db_path, 4)

    assert {row[0] for row in get_all_files_info(db_path)} == set(paths)


def test_process_files_concurrently_logs_one_failure_and_finishes(db_path, dup_tree,
                                                                  caplog):
    paths = [str(p) for p in dup_tree.all_files()]
    paths.append(str(dup_tree.root / "does-not-exist.txt"))

    with caplog.at_level("ERROR"):
        file_ops.process_files_concurrently(paths, db_path, 4)

    assert {row[0] for row in get_all_files_info(db_path)} == set(paths[:-1])
    assert "does-not-exist.txt" in caplog.text


def test_check_file_prints_every_path_sharing_the_checksum(db_path, dup_tree, capsys):
    left, right = dup_tree.duplicated[0]
    for path in (left, right):
        file_ops.process_file(str(path), db_path)
    capsys.readouterr()

    file_ops.check_file(str(left), db_path)

    out = capsys.readouterr().out
    assert f"Duplicate found for {left}:" in out
    assert str(left) in out and str(right) in out


def test_check_file_says_nothing_when_the_checksum_is_unknown(db_path, dup_tree, capsys):
    file_ops.check_file(str(dup_tree.left / "unique-left.txt"), db_path)

    assert capsys.readouterr().out == ""
