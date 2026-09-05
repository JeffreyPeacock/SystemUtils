"""#34 -- every reporting action, and #43 -- scan_dir_report never returned.

`report_duplicate_sizes` had its own file already (`test_reporting_sizes.py`,
from #4 and #22); everything else in the module was unreached. That mattered:
both defects there were found only when a test finally ran the function.

The same held here. Writing the termination test for `scan_dir_report` showed
it **never returns at all** -- its consumer breaks on the shutdown sentinel
without calling `task_done()`, so the closing `file_queue.join()` waits forever
on one unfinished task per worker (#43). The `timeout` in `pytest.ini` is what
makes that a red build rather than a hung one.
"""

from __future__ import annotations

import pytest

from src import reporting
from src.db import get_all_files_info, store_file_info
from src.md5sum import compute_md5


def _record(db_path, *paths):
    for path in paths:
        store_file_info(db_path, str(path), compute_md5(str(path)))


# -- scan_dir_report: it must terminate (#43) ------------------------------


@pytest.mark.parametrize("num_threads", [1, 4])
def test_scan_dir_report_terminates_and_records_every_file(db_path, dup_tree,
                                                           num_threads):
    """The regression this pins is a hang, not a wrong answer.

    One sentinel per worker goes onto the queue and each must be marked done,
    or `file_queue.join()` never releases. Parametrised across worker counts
    because the number of stranded tasks is the number of workers -- a
    single-worker run still hangs, but a four-worker run is where the arithmetic
    is obvious.
    """
    reporting.scan_dir_report(str(dup_tree.left), db_path, num_threads)

    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert recorded == {str(p) for p in dup_tree.left.iterdir()}


def test_scan_dir_report_prints_the_paths_sharing_a_checksum(db_path, dup_tree, capsys):
    """It reports a duplicate only once a second copy is in the database, which
    is why the whole tree is scanned rather than one side of it."""
    reporting.scan_dir_report(str(dup_tree.root), db_path, 4)

    out = capsys.readouterr().out
    left, right = dup_tree.duplicated[0]
    assert "Duplicate found for" in out
    assert str(left) in out and str(right) in out


def test_scan_dir_report_survives_a_file_it_cannot_process(db_path, dup_tree,
                                                           monkeypatch, caplog):
    doomed = str(dup_tree.left / "shared-one.txt")
    real = reporting.process_file

    def explode_on_one(file_path, path_to_db):
        if file_path == doomed:
            raise OSError("permission denied")
        return real(file_path, path_to_db)

    monkeypatch.setattr(reporting, "process_file", explode_on_one)

    with caplog.at_level("ERROR"):
        reporting.scan_dir_report(str(dup_tree.left), db_path, 4)

    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert doomed not in recorded
    assert recorded == {str(p) for p in dup_tree.left.iterdir()} - {doomed}
    assert "permission denied" in caplog.text


# -- report_duplicates -----------------------------------------------------


def test_report_duplicates_returns_the_groups(db_path, dup_tree):
    left, right = dup_tree.duplicated[0]
    _record(db_path, left, right)

    groups = reporting.report_duplicates(db_path)

    assert list(groups.values()) == [[str(left), str(right)]]


def test_report_duplicates_returns_an_empty_mapping_when_there_are_none(db_path,
                                                                       dup_tree):
    _record(db_path, *dup_tree.unique)

    assert reporting.report_duplicates(db_path) == {}


# -- report_files_with_more_than_1_duplicate -------------------------------


def test_files_with_more_than_1_duplicate_lists_each_path(db_path, dup_tree, capsys):
    left, right = dup_tree.duplicated[0]
    _record(db_path, left, right, *dup_tree.unique)

    reporting.report_files_with_more_than_1_duplicate(db_path)

    out = capsys.readouterr().out
    assert "Files with more than 1 duplicate:" in out
    assert str(left) in out and str(right) in out
    for unique in dup_tree.unique:
        assert str(unique) not in out


def test_files_with_more_than_1_duplicate_says_so_when_there_are_none(db_path,
                                                                     dup_tree,
                                                                     capsys):
    _record(db_path, *dup_tree.unique)

    reporting.report_files_with_more_than_1_duplicate(db_path)

    assert "No files with more than 1 duplicate found." in capsys.readouterr().out


# -- the prefix reports ----------------------------------------------------


def test_report_prefix_count_counts_only_the_matching_side(db_path, dup_tree, capsys):
    _record(db_path, *[p for pair in dup_tree.duplicated for p in pair])

    reporting.report_prefix_count(db_path, str(dup_tree.left))

    assert f"'{dup_tree.left}': 3" in capsys.readouterr().out


def test_report_prefix_count_reports_zero_rather_than_nothing(db_path, dup_tree,
                                                              capsys):
    reporting.report_prefix_count(db_path, str(dup_tree.left))

    assert f"'{dup_tree.left}': 0" in capsys.readouterr().out


def test_report_files_for_prefix_returns_the_matching_paths(db_path, dup_tree):
    _record(db_path, *dup_tree.left.iterdir(), *dup_tree.right.iterdir())

    files = reporting.report_files_for_prefix(db_path, str(dup_tree.left))

    assert set(files) == {str(p) for p in dup_tree.left.iterdir()}


def test_report_duplicates_for_prefix_only_groups_within_the_prefix(db_path, dup_tree):
    """Nothing under left/ duplicates anything else under left/, so restricting
    to that prefix must report nothing even though the tree is full of pairs."""
    _record(db_path, *dup_tree.left.iterdir(), *dup_tree.right.iterdir())

    assert reporting.report_duplicates_for_prefix(db_path, str(dup_tree.left)) == {}

    whole_tree = reporting.report_duplicates_for_prefix(db_path, str(dup_tree.root))
    assert len(whole_tree) == len(dup_tree.duplicated)


# -- compare_directories ---------------------------------------------------


def test_compare_directories_names_what_is_unique_to_each_side(dup_tree, capsys):
    """It ignores the database entirely and hashes both trees in full. Pinned
    as it stands, before anyone replaces the O(n*m) `md5 not in values()` scan
    -- the point of the test is that the answer must not change."""
    reporting.compare_directories(str(dup_tree.left), str(dup_tree.right))

    out = capsys.readouterr().out
    side_a, side_b = out.split("Files unique to dirB:")

    assert str(dup_tree.left / "unique-left.txt") in side_a
    assert str(dup_tree.right / "unique-right.txt") in side_b
    # Everything duplicated across the two sides appears on neither list.
    for left, right in dup_tree.duplicated:
        assert str(left) not in out
        assert str(right) not in out


def test_compare_directories_reports_both_sides_empty_when_they_match(tmp_path,
                                                                     capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    for directory in (a, b):
        directory.mkdir()
        (directory / "same.txt").write_bytes(b"identical\n")

    reporting.compare_directories(str(a), str(b))

    out = capsys.readouterr().out
    assert out == "Files unique to dirA:\n\nFiles unique to dirB:\n"
