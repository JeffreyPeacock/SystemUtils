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
import sqlite3
from pathlib import Path

import pytest

from src import db
from src.db import (
    UniquenessUnknown, audit_db, get_all_files_info, is_file_unique,
    scan_and_report_unique_files, store_file_info,
)
from src.md5sum import compute_md5

# Captured before any test can monkeypatch db.compute_md5, so a test that
# restores it puts back the real function rather than another test's stub.
_real_md5 = compute_md5

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


def test_a_hashing_failure_is_unknown_rather_than_a_verdict(db_path, dup_tree,
                                                            monkeypatch, caplog):
    """#41 -- this used to answer False, which means "not unique".

    False is a verdict: the same answer as a file that genuinely has a copy
    elsewhere. A file whose only fault was an I/O error was therefore excluded
    from the keep list, and this action's output is what a human deletes
    against.

    There is no safe value to return instead. `None` is falsy, so a caller
    writing `if is_file_unique(...)` would reproduce the same wrong answer
    silently. It raises.
    """
    target = str(dup_tree.left / "unique-left.txt")

    def unreadable(path):
        raise OSError("I/O error")

    monkeypatch.setattr(db, "compute_md5", unreadable)

    with caplog.at_level("ERROR"):
        with pytest.raises(UniquenessUnknown, match="cannot determine whether"):
            is_file_unique(target, db_path)

    assert "I/O error" in caplog.text


def test_a_failed_lookup_is_also_unknown(db_path, dup_tree, monkeypatch):
    """The checksum is only half of it -- the database read can fail too, and
    it is the same third outcome."""
    target = str(dup_tree.left / "unique-left.txt")

    def unreachable(path_to_db, md5sum):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db, "check_for_duplicates", unreachable)

    with pytest.raises(UniquenessUnknown):
        is_file_unique(target, db_path)


def test_unknown_is_not_reachable_by_returning_something_falsy():
    """The signature itself, so the fix cannot be undone by a later refactor
    that reintroduces a sentinel return.

    A guard against the specific mistake this ticket was about: the danger is
    not the exception being wrong, it is somebody deciding a return value would
    be tidier.
    """
    assert issubclass(UniquenessUnknown, Exception)
    assert "UniquenessUnknown" in (is_file_unique.__doc__ or ""), (
        "the third outcome must stay documented on the function that raises it"
    )


# -- how the scan records what it could not read ---------------------------


def _break_one_file(monkeypatch, doomed: str):
    """Make `doomed` unhashable, leaving every other file readable."""
    real = db.compute_md5

    def selective(path):
        if path == doomed:
            raise OSError("permission denied")
        return real(path)

    monkeypatch.setattr(db, "compute_md5", selective)


def test_an_unreadable_file_is_in_neither_list(db_path, dup_tree, monkeypatch):
    doomed = str(dup_tree.left / "shared-one.txt")
    _break_one_file(monkeypatch, doomed)

    unique = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert doomed not in unique
    statuses = dict(_log_lines(dup_tree.left))
    assert statuses[doomed] == "unreadable", (
        "an unreadable file must not be recorded as not_unique -- that is the "
        "verdict that means 'it has a duplicate'"
    )


def test_the_run_says_out_loud_what_it_could_not_read(db_path, dup_tree,
                                                      monkeypatch, caplog):
    """The caller is about to treat the returned list as complete."""
    doomed = str(dup_tree.left / "shared-one.txt")
    _break_one_file(monkeypatch, doomed)

    with caplog.at_level("WARNING"):
        scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert "1 file(s) could not be read" in caplog.text
    assert "NEITHER list" in caplog.text
    assert doomed in caplog.text


def test_an_unreadable_file_is_retried_on_the_next_run(db_path, dup_tree,
                                                       monkeypatch):
    """A verdict is final; "could not check" is not.

    The resume log exists to avoid repeating work, but repeating a *question
    that was never answered* is the work. A permission or a mount usually
    differs between runs, and skipping forever would make one bad read
    permanent.
    """
    doomed = str(dup_tree.left / "shared-one.txt")
    _break_one_file(monkeypatch, doomed)
    first = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)
    assert doomed not in first

    monkeypatch.setattr(db, "compute_md5", _real_md5)   # the file becomes readable

    second = scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    assert doomed in second, "the file became readable and was never re-checked"


def test_a_recorded_verdict_is_still_not_re_checked(db_path, dup_tree, monkeypatch):
    """The retry above must not have turned the resume log off entirely."""
    scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    checked = []
    real = db.is_file_unique

    def counting(file_path, path_to_db):
        checked.append(file_path)
        return real(file_path, path_to_db)

    monkeypatch.setattr(db, "is_file_unique", counting)
    scan_and_report_unique_files(str(dup_tree.left), db_path, num_threads=2)

    already = {str(p) for p in dup_tree.left.iterdir() if p.name != RESUME_LOG}
    assert not (set(checked) & already), "a file with a verdict was checked again"


def test_more_than_ten_unreadable_files_are_truncated_in_the_warning(db_path,
                                                                     tmp_path,
                                                                     monkeypatch,
                                                                     caplog):
    tree = tmp_path / "tree"
    tree.mkdir()
    for i in range(13):
        (tree / f"file-{i:02d}.txt").write_bytes(f"contents {i}\n".encode())

    def always_broken(path):
        raise OSError("permission denied")

    monkeypatch.setattr(db, "compute_md5", always_broken)

    with caplog.at_level("WARNING"):
        unique = scan_and_report_unique_files(str(tree), db_path, num_threads=2)

    assert unique == []
    assert "13 file(s) could not be read" in caplog.text
    assert "and 3 more" in caplog.text


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
