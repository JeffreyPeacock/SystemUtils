"""#74 -- only regular files are read or recorded, and a symlink is never followed.

A baseline scan of `/home2` hung for 36 hours. One worker was reading a copy of
`/dev/random` in a backed-up postfix chroot; it never reaches end of file. A
second worker was asleep in `open()`, the way a FIFO blocks until a writer
appears. `os.walk` lists both under `files`, and every action that walks a tree
opened whatever it was given.

The fixture tree holds what a root backup holds: a FIFO, a socket, a symlink to
a file, a symlink to a directory and a broken symlink, beside two regular
files. A FIFO and a socket can be made without root. A device file cannot, so
those tests make a regular file *report* `S_IFCHR` or `S_IFBLK` through a
patched `os.lstat`. If the check is missing, that file is hashed and recorded
for real, so the test fails rather than hangs.

A hang is still the failure mode if every layer of the check goes. The
`timeout = 60` in `pytest.ini` turns it into a red build with every thread's
stack; it is left as it is.
"""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

import pytest

from src import file_ops, md5sum, reporting
from src.db import (
    audit_db, get_all_files_info, is_file_unique, scan_and_report_unique_files,
    store_file_info,
)
from src.md5sum import compute_md5
from src.regular_files import (
    NotARegularFile, SkippedEntries, file_kind, require_regular_file,
    walk_regular_files,
)
from src.utils import get_files_with_md5


def _make_socket(path: Path) -> None:
    """Bind a Unix socket at `path`. A relative name is used because a
    socket's address is limited to about 107 bytes and tmp_path can be longer."""
    cwd = os.getcwd()
    os.chdir(path.parent)
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.bind(path.name)
    finally:
        os.chdir(cwd)


@pytest.fixture
def mixed_tree(tmp_path):
    """Two regular files, and one of each entry a root backup brings with it."""
    root = tmp_path / "tree"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (root / "a.txt").write_text("alpha\n")
    (sub / "b.txt").write_text("beta\n")
    os.mkfifo(root / "fifo")
    _make_socket(root / "sock")
    (root / "link-to-file").symlink_to(root / "a.txt")
    (root / "link-to-dir").symlink_to(sub, target_is_directory=True)
    (root / "broken-link").symlink_to(root / "no-such-target")
    return root


def _regular(tree: Path) -> set[str]:
    return {str(tree / "a.txt"), str(tree / "sub" / "b.txt")}


MIXED_SKIPS = {"fifo": 1, "socket": 1, "symlink": 3}


def _recorded(db_path) -> set[str]:
    return {row[0] for row in get_all_files_info(db_path)}


@pytest.fixture
def pretend_devices(monkeypatch):
    """Make chosen regular files report a device type through os.lstat."""
    real_lstat = os.lstat
    fakes: dict[str, int] = {}

    def lstat(path, *args, **kwargs):
        st = real_lstat(path, *args, **kwargs)
        kind = fakes.get(os.fspath(path))
        if kind is None:
            return st
        return os.stat_result((kind | 0o644,) + tuple(st)[1:10])

    monkeypatch.setattr(os, "lstat", lstat)
    return fakes


# -- the definition ------------------------------------------------------------


@pytest.mark.parametrize("mode, kind", [
    (stat.S_IFREG, "regular file"),
    (stat.S_IFLNK, "symlink"),
    (stat.S_IFDIR, "directory"),
    (stat.S_IFCHR, "char device"),
    (stat.S_IFBLK, "block device"),
    (stat.S_IFIFO, "fifo"),
    (stat.S_IFSOCK, "socket"),
    (0, "other"),
])
def test_file_kind_names_every_type(mode, kind):
    assert file_kind(mode) == kind


def test_the_walk_yields_regular_files_and_counts_everything_else(mixed_tree):
    skipped = SkippedEntries()

    yielded = set(walk_regular_files(str(mixed_tree), skipped))

    assert yielded == _regular(mixed_tree)
    assert dict(skipped.by_kind) == MIXED_SKIPS


def test_the_walk_still_yields_a_path_it_cannot_lstat(tmp_path, monkeypatch):
    """Dropping it would turn "could not check" into "not there"."""
    (tmp_path / "x.txt").write_text("x")
    real_lstat = os.lstat

    def failing(path, *args, **kwargs):
        if os.fspath(path).endswith("x.txt"):
            raise PermissionError("denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", failing)

    assert list(walk_regular_files(str(tmp_path), SkippedEntries())) == [
        str(tmp_path / "x.txt")]


def test_require_regular_file_refuses_a_symlink_to_a_regular_file(mixed_tree):
    with pytest.raises(NotARegularFile) as exc:
        require_regular_file(str(mixed_tree / "link-to-file"))
    assert exc.value.kind == "symlink"


# -- compute_md5: the last line, used by every action --------------------------


def test_compute_md5_refuses_a_fifo_without_opening_it(mixed_tree, monkeypatch):
    """Not opened at all: opening a device can have effects of its own (a tape
    drive rewinds), so the descriptor recheck below is the second line only."""
    opened: list[str] = []
    real_open = os.open

    def spy(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)

    with pytest.raises(NotARegularFile) as exc:
        compute_md5(str(mixed_tree / "fifo"))
    assert exc.value.kind == "fifo"
    assert opened == []


def test_compute_md5_rechecks_the_descriptor(mixed_tree, monkeypatch):
    """The race: a path checked as regular and then replaced by a FIFO. With
    the up-front check disabled, O_NONBLOCK keeps the open from blocking and
    fstat refuses what was opened."""
    monkeypatch.setattr(md5sum, "require_regular_file", lambda path: None)

    with pytest.raises(NotARegularFile) as exc:
        compute_md5(str(mixed_tree / "fifo"))
    assert exc.value.kind == "fifo"


def test_compute_md5_will_not_open_through_a_symlink(mixed_tree, monkeypatch):
    """The same race with a symlink: O_NOFOLLOW refuses it (ELOOP)."""
    monkeypatch.setattr(md5sum, "require_regular_file", lambda path: None)

    with pytest.raises(OSError):
        compute_md5(str(mixed_tree / "link-to-file"))


# -- scan ------------------------------------------------------------------------


def test_scan_records_only_the_regular_files(db_path, mixed_tree):
    tally = file_ops.scan(str(mixed_tree), db_path, 2)

    assert _recorded(db_path) == _regular(mixed_tree)
    assert dict(tally.not_regular.by_kind) == MIXED_SKIPS
    assert (tally.hashed, tally.failed) == (2, 0), "a skip is not a failure"


def test_no_other_entry_reaches_process_file(db_path, mixed_tree, monkeypatch):
    """The walk filters before the queue. process_file refuses too, so without
    this spy a missing walk check would still pass every other test."""
    seen: list[str] = []
    real = file_ops.process_file

    def spy(path, db):
        seen.append(path)
        return real(path, db)

    monkeypatch.setattr(file_ops, "process_file", spy)

    file_ops.scan(str(mixed_tree), db_path, 2)

    assert set(seen) == _regular(mixed_tree)


def test_scan_skips_char_and_block_devices(db_path, tmp_path, pretend_devices):
    tree = tmp_path / "dev"
    tree.mkdir()
    for name in ("random", "sda", "real.txt"):
        (tree / name).write_text(name)
    pretend_devices[str(tree / "random")] = stat.S_IFCHR
    pretend_devices[str(tree / "sda")] = stat.S_IFBLK

    tally = file_ops.scan(str(tree), db_path, 2)

    assert _recorded(db_path) == {str(tree / "real.txt")}
    assert dict(tally.not_regular.by_kind) == {"char device": 1, "block device": 1}


def test_the_summary_reports_the_skips_by_kind(db_path, mixed_tree):
    tally = file_ops.scan(str(mixed_tree), db_path, 2)

    assert tally.summary_lines() == [
        "scan complete: 2 hashed, 0 skipped unchanged, 0 failed",
        "skipped 5 not regular file(s), not read: fifo 1, socket 1, symlink 3",
    ]


def test_each_skipped_path_is_logged(db_path, mixed_tree, caplog):
    with caplog.at_level("INFO"):
        file_ops.scan(str(mixed_tree), db_path, 2)

    assert f"NOT REGULAR (fifo), skipped: {mixed_tree / 'fifo'}" in caplog.text
    assert f"NOT REGULAR (symlink), skipped: {mixed_tree / 'link-to-dir'}" in caplog.text


@pytest.mark.parametrize("name, kind", [
    ("link-to-file", "symlink"),
    ("link-to-dir", "symlink"),
    ("fifo", "fifo"),
])
def test_a_command_line_path_that_is_not_regular_is_a_failure(db_path, mixed_tree,
                                                              name, kind):
    """The operator asked for this path, and the scan did not cover it, so it
    is a failure (exit 3) rather than a skip. Not even a symlink named on the
    command line is followed."""
    target = mixed_tree / name

    tally = file_ops.scan(str(target), db_path, 2)

    assert _recorded(db_path) == set()
    assert tally.failures == [
        (str(target), f"not a regular file or directory ({kind})")]


def test_process_file_refuses_a_symlink_that_matches_its_stored_row(db_path,
                                                                    mixed_tree):
    """A row an older version recorded by following the link. Its stored
    (size, mtime) match the target, so without the check first the skip check
    would report it as 'skipped' and keep it."""
    link = str(mixed_tree / "link-to-file")
    store_file_info(db_path, link, "0" * 32)

    with pytest.raises(NotARegularFile):
        file_ops.process_file(link, db_path)


def test_scan_file_and_the_concurrent_path_count_a_refusal(db_path, mixed_tree):
    """The second layer: a path that reaches process_file anyway is counted
    as not regular, not as a failure."""
    fifo = str(mixed_tree / "fifo")

    tally = file_ops.scan_file(fifo, db_path)
    file_ops.process_files_concurrently([fifo], db_path, 2, tally)

    assert dict(tally.not_regular.by_kind) == {"fifo": 2}
    assert tally.failed == 0


def test_scan_dir_report_records_only_the_regular_files(db_path, mixed_tree, caplog):
    with caplog.at_level("WARNING"):
        reporting.scan_dir_report(str(mixed_tree), db_path, 2)

    assert _recorded(db_path) == _regular(mixed_tree)
    assert "skipped 5 not regular file(s)" in caplog.text


def test_scan_dir_report_counts_a_refusal_from_process_file(db_path, mixed_tree,
                                                            monkeypatch, caplog):
    def refuse(path, db):
        raise NotARegularFile(path, "fifo")

    monkeypatch.setattr(reporting, "process_file", refuse)
    with caplog.at_level("WARNING"):
        reporting.scan_dir_report(str(mixed_tree), db_path, 1)

    assert "fifo 3" in caplog.text, "two refused files plus the walk's own fifo"


# -- audit-db: such rows do not belong in the database ------------------------


@pytest.fixture
def recorded_non_regular(db_path, mixed_tree):
    """Rows for a symlink and a FIFO, as an older version could leave them,
    and one for a regular file."""
    for name in ("link-to-file", "fifo", "a.txt"):
        store_file_info(db_path, str(mixed_tree / name), "0" * 32)
    return mixed_tree


def test_audit_removes_rows_that_are_not_regular_files(db_path, recorded_non_regular):
    counts = audit_db(db_path, 2, file_ops.process_file)

    assert counts["not_regular"] == 2
    assert counts["removed"] == 0, "counted apart from deleted files"
    assert _recorded(db_path) == {str(recorded_non_regular / "a.txt")}


def test_audit_dry_run_counts_them_and_keeps_them(db_path, recorded_non_regular):
    counts = audit_db(db_path, 2, file_ops.process_file, dry_run=True)

    assert counts["not_regular"] == 2
    assert len(_recorded(db_path)) == 3


@pytest.mark.skipif(os.geteuid() == 0, reason="root can search a mode-000 directory")
def test_audit_keeps_a_row_it_cannot_check(db_path, tmp_path):
    """os.path.exists() returned False for a directory the auditor could not
    search, so the row was removed as if the file had been deleted. lstat
    raises instead: the row is kept and the audit exits 3."""
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "still-here.txt"
    target.write_text("present")
    store_file_info(db_path, str(target), compute_md5(str(target)))

    locked.chmod(0)
    try:
        counts = audit_db(db_path, 2, file_ops.process_file)
    finally:
        locked.chmod(0o755)

    assert (counts["removed"], counts["failed"]) == (0, 1)
    assert _recorded(db_path) == {str(target)}


# -- verify-db, uniqueness, compare ---------------------------------------------


def test_verify_does_not_open_a_recorded_fifo_or_symlink(db_path, recorded_non_regular):
    tally = file_ops.verify_db(db_path, 2)

    assert tally.unreadable == 2, "not verified is not a pass"
    messages = dict(tally.failures)
    assert messages[str(recorded_non_regular / "fifo")] == (
        "not a regular file (fifo); audit-db removes the row")
    assert "symlink" in messages[str(recorded_non_regular / "link-to-file")]
    assert _recorded(db_path) == {str(recorded_non_regular / n)
                                  for n in ("link-to-file", "fifo", "a.txt")}, \
        "verify never writes"


@pytest.mark.parametrize("name", ["fifo", "link-to-file", "sock"])
def test_is_file_unique_refuses_what_is_not_a_regular_file(db_path, mixed_tree, name):
    with pytest.raises(ValueError, match="Invalid file path"):
        is_file_unique(str(mixed_tree / name), db_path)


def test_scan_unique_files_reads_only_regular_files(db_path, mixed_tree, caplog):
    with caplog.at_level("WARNING"):
        unique = scan_and_report_unique_files(str(mixed_tree), db_path, 2)

    assert set(unique) == _regular(mixed_tree)
    assert "skipped 5 not regular file(s)" in caplog.text


def test_compare_directories_reads_only_regular_files(mixed_tree, caplog):
    with caplog.at_level("WARNING"):
        checksums = get_files_with_md5(str(mixed_tree))

    assert set(checksums) == _regular(mixed_tree)
    assert "skipped 5 not regular file(s)" in caplog.text


# -- the CLI -----------------------------------------------------------------------


def test_cli_scan_exits_0_and_prints_the_skips(run_cli, db_path, mixed_tree):
    result = run_cli("--db-path", db_path, "scan", str(mixed_tree))

    assert result.exit_code == 0
    assert "skipped 5 not regular file(s), not read: fifo 1, socket 1, symlink 3" \
        in result.stdout


def test_cli_check_file_on_a_fifo_exits_1(run_cli, db_path, mixed_tree, caplog):
    """An invalid argument, so 1 (#23) -- before #74 this action hung."""
    result = run_cli("--db-path", db_path, "check-file", str(mixed_tree / "fifo"))

    assert result.exit_code == 1
    assert "not a regular file (fifo)" in caplog.text


def test_cli_audit_summary_names_the_count(run_cli, db_path, recorded_non_regular):
    result = run_cli("--db-path", db_path, "audit-db")

    assert "not regular 2" in result.stdout
