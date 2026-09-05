"""#33 -- the unique-file scan, its resume log, and audit_db's last branches.

`scan-unique-files` is the one action that writes into the directory it is
scanning: a `.processed_files.txt` resume log, read back on the next run. Its
behaviour therefore only makes sense across **two** runs, which is what most of
this file exercises.

`is_file_unique` is small and its failure mode is not an exception but a wrong
answer, so every test here asserts what it **returns**.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import db
from src.db import (
    audit_db, get_all_files_info, is_file_unique,
    scan_and_report_unique_files, store_file_info,
)
from src.md5sum import compute_md5

RESUME_LOG = ".processed_files.txt"


def _record(db_path, *paths):
    for path in paths:
        store_file_info(db_path, str(path), compute_md5(str(path)))


def _log_lines(directory: Path) -> list[tuple[str, str]]:
    text = (directory / RESUME_LOG).read_text(encoding="utf-8")
    return [tuple(line.split("\t")) for line in text.splitlines() if line]


# -- is_file_unique --------------------------------------------------------


def test_a_checksum_absent_from_the_database_is_unique(db_path, dup_tree):
    assert is_file_unique(str(dup_tree.left / "unique-left.txt"), db_path) is True


def test_a_checksum_already_recorded_is_not_unique(db_path, dup_tree):
    left, right = dup_tree.duplicated[0]
    _record(db_path, left)

    assert is_file_unique(str(right), db_path) is False


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_a_path_that_is_not_a_file_raises(db_path, dup_tree, kind):
    target = dup_tree.left / "no-such-file.txt" if kind == "missing" else dup_tree.left

    with pytest.raises(ValueError, match="Invalid file path"):
        is_file_unique(str(target), db_path)


def test_a_hashing_failure_reports_the_file_as_NOT_unique(db_path, dup_tree,
                                                          monkeypatch, caplog):
    """Pinning current behaviour, which is the wrong-answer kind of failure.

    Every exception below the `isfile` check is swallowed into `return False`,
    and False means "not unique" -- so a file that could not be read is
    classified as a duplicate of something. Anyone treating this action's
    output as "these are the files to keep" would drop the only copy.

    This test asserts what it returns rather than that it did not raise, so the
    behaviour cannot change silently. Filed separately; not fixed here, because
    changing the return contract is not a coverage ticket.
    """
    target = str(dup_tree.left / "unique-left.txt")

    def unreadable(path):
        raise OSError("I/O error")

    monkeypatch.setattr(db, "compute_md5", unreadable)

    with caplog.at_level("ERROR"):
        result = is_file_unique(target, db_path)

    assert result is False
    assert "I/O error" in caplog.text


# -- scan_and_report_unique_files ------------------------------------------


def test_scanning_something_that_is_not_a_directory_raises(db_path, dup_tree):
    with pytest.raises(ValueError, match="Invalid directory"):
        scan_and_report_unique_files(str(dup_tree.left / "unique-left.txt"), db_path)


def test_a_first_run_reports_every_file_and_writes_the_log(db_path, dup_tree):
    """An empty database means nothing has a duplicate, so all are unique."""
    unique = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    expected = {str(p) for p in dup_tree.left.iterdir() if p.name != RESUME_LOG}
    assert set(unique) == expected
    assert {path for path, _status in _log_lines(dup_tree.left)} == expected
    assert all(status == "unique" for _path, status in _log_lines(dup_tree.left))


def test_files_already_in_the_database_are_reported_not_unique(db_path, dup_tree):
    already = dup_tree.left / "shared-one.txt"
    _record(db_path, already)

    unique = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert str(already) not in unique
    statuses = dict(_log_lines(dup_tree.left))
    assert statuses[str(already)] == "not_unique"


def test_a_second_run_skips_what_the_first_recorded(db_path, dup_tree, capsys):
    """The resume log is the whole point of the action's write-into-the-tree
    behaviour, and it only shows up on the second run."""
    first = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)
    assert first, "the first run must find something, or the second proves nothing"
    capsys.readouterr()

    second = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    out = capsys.readouterr().out
    assert "Previously processed files:" in out
    assert set(second) & set(first) == set(), "a recorded file was checked again"


def test_the_resume_log_scans_itself_on_the_second_run(db_path, dup_tree):
    """A quirk worth pinning: the log is written **inside** the directory being
    scanned, so the next `os.walk` finds it and checks it like any other file.

    Not a defect to fix here -- moving the log would change where an existing
    installation resumes from -- but a surprise if you expect a second run over
    an unchanged tree to report nothing at all.
    """
    scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    second = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert second == [str(dup_tree.left / RESUME_LOG)]


def test_deleting_the_log_forces_a_full_recheck(db_path, dup_tree):
    first = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)
    (dup_tree.left / RESUME_LOG).unlink()

    again = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert set(again) == set(first)


def test_one_unreadable_file_does_not_abandon_the_scan(db_path, dup_tree,
                                                       monkeypatch, caplog):
    doomed = str(dup_tree.left / "shared-two.txt")
    real = db.is_file_unique

    def explode_on_one(file_path, path_to_db):
        if file_path == doomed:
            raise OSError("permission denied")
        return real(file_path, path_to_db)

    monkeypatch.setattr(db, "is_file_unique", explode_on_one)

    with caplog.at_level("ERROR"):
        unique = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert doomed not in unique
    assert str(dup_tree.left / "unique-left.txt") in unique
    assert "permission denied" in caplog.text


# -- audit_db's remaining branches -----------------------------------------


def test_audit_reprocesses_a_changed_file_when_not_a_dry_run(db_path, dup_tree, caplog):
    """The counterpart to the existing dry-run test: this one must actually
    call through."""
    _record(db_path, dup_tree.grows)
    dup_tree.grow()
    seen = []

    def record_call(file_path, path_to_db):
        seen.append(file_path)

    with caplog.at_level("INFO"):
        counts = audit_db(db_path, 2, record_call)

    assert seen == [str(dup_tree.grows)]
    assert counts["reprocessed"] == 1
    assert "REPROCESSING" in caplog.text


def test_audit_logs_a_worker_failure_and_keeps_going(db_path, dup_tree, caplog):
    """`future.result()` re-raises whatever the worker hit. Losing one row's
    check must not abandon the audit."""
    _record(db_path, *dup_tree.all_files())
    dup_tree.grow()

    def explode(file_path, path_to_db):
        raise RuntimeError("worker blew up")

    with caplog.at_level("ERROR"):
        counts = audit_db(db_path, 2, explode)

    assert "worker blew up" in caplog.text
    assert counts["checked"] == len(dup_tree.all_files())


def test_more_than_ten_suspect_rows_are_truncated_in_the_warning(db_path, tmp_path,
                                                                 caplog):
    """A failed mount can make thousands of rows suspect; the warning lists ten
    and says how many more."""
    volume = tmp_path / "volume"
    volume.mkdir()
    recorded = []
    for i in range(13):
        path = volume / f"file-{i:02d}.txt"
        path.write_bytes(f"contents {i}\n".encode())
        recorded.append(path)
    _record(db_path, *recorded)

    for path in recorded:
        path.unlink()
    volume.rmdir()          # the whole directory is gone: an unmounted volume

    with caplog.at_level("WARNING"):
        counts = audit_db(db_path, 2, lambda *a: None)

    assert counts["suspect"] == 13
    assert counts["removed"] == 0
    assert len(get_all_files_info(db_path)) == 13, "suspect rows must survive"
    assert "and 3 more" in caplog.text
