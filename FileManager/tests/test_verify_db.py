"""verify-db reads the stored checksum back, which nothing else did (#50).

`scan` and `audit-db` both decide what to do from `(size, mtime)` and skip when
they match -- so they skip exactly the files whose contents were in question.
Bit rot, a bad sector and a failing cable all rewrite bytes without touching
either. `test_scan_and_audit_both_miss_corruption_in_place` records that
baseline behaviour deliberately: it is the reason this action exists, and if it
ever starts failing, this module's premise has changed.

Three outcomes throughout, never two: match, **mismatch**, and could-not-read.
An unreadable file is not a pass -- its stored checksum is still unverified, and
calling that fine is the failure the ticket is about.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src import file_ops
from src.db import get_md5_by_path, initialize_db, iter_recorded_checksums
from src.file_ops import VerifyTally, scan, verify_db, verify_one_recording

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "src" / "main.py"

EXIT_INCOMPLETE = 3
EXIT_MISMATCH = 4


def corrupt_in_place(path: Path) -> None:
    """Rewrite a file's contents keeping its size AND its mtime.

    Both halves matter. A different size or a newer mtime is a change `scan`
    already notices; silent corruption looks exactly like this.
    """
    before = path.stat()
    replacement = bytes((b + 1) % 256 for b in path.read_bytes())
    assert len(replacement) == before.st_size
    path.write_bytes(replacement)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert after.st_size == before.st_size, "the fixture changed the size"
    assert after.st_mtime_ns == before.st_mtime_ns, "the fixture changed mtime"


@pytest.fixture
def scanned(tmp_path):
    """A recorded tree of three files and the database holding it."""
    tree = tmp_path / "tree"
    tree.mkdir()
    for name, text in (("a.txt", "aaaa"), ("b.txt", "bbbb"), ("c.txt", "cccc")):
        (tree / name).write_text(text)
    db_path = str(tmp_path / "verify.db")
    initialize_db(db_path)
    scan(str(tree), db_path, 2)
    assert len(list(iter_recorded_checksums(db_path))) == 3
    return tree, db_path


# --- the finding -----------------------------------------------------------

def test_corruption_in_place_is_detected(scanned):
    tree, db_path = scanned
    corrupt_in_place(tree / "b.txt")

    tally = verify_db(db_path, 2)

    assert tally.mismatched == 1
    assert tally.matched == 2
    assert tally.unreadable == 0
    path, stored, actual = tally.mismatches[0]
    assert path == str(tree / "b.txt")
    assert stored != actual


def test_scan_and_audit_both_miss_corruption_in_place(scanned):
    """The premise of #50, kept as a test rather than a claim in a comment.

    If either of these starts catching it, verify-db's reason for existing has
    changed and this module should be re-read before being trusted.
    """
    tree, db_path = scanned
    stored_before = get_md5_by_path(db_path, str(tree / "b.txt"))
    corrupt_in_place(tree / "b.txt")

    rescan = scan(str(tree), db_path, 2)
    assert rescan.hashed == 0, "scan rehashed something; the premise changed"
    assert rescan.failed == 0
    assert get_md5_by_path(db_path, str(tree / "b.txt")) == stored_before

    assert verify_db(db_path, 2).mismatched == 1


def test_the_stored_checksum_is_never_overwritten(scanned):
    """A verify that repairs the baseline destroys the only evidence, and
    passes the second time it runs."""
    tree, db_path = scanned
    stored_before = get_md5_by_path(db_path, str(tree / "b.txt"))
    corrupt_in_place(tree / "b.txt")

    first = verify_db(db_path, 2)
    second = verify_db(db_path, 2)

    assert first.mismatched == 1
    assert second.mismatched == 1, "the second run passed; the row was rewritten"
    assert get_md5_by_path(db_path, str(tree / "b.txt")) == stored_before


def test_an_intact_tree_matches_everything(scanned):
    _, db_path = scanned
    tally = verify_db(db_path, 2)
    assert (tally.matched, tally.mismatched, tally.unreadable) == (3, 0, 0)


# --- could-not-read is its own outcome -------------------------------------

@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can read a mode-000 file, so there is nothing to detect",
)
def test_an_unreadable_file_is_not_a_pass(scanned):
    tree, db_path = scanned
    (tree / "b.txt").chmod(0o000)
    try:
        tally = verify_db(db_path, 2)
    finally:
        (tree / "b.txt").chmod(0o644)

    assert tally.unreadable == 1
    assert tally.matched == 2
    assert tally.mismatched == 0
    assert tally.checked == 3, "the unreadable file fell out of the count"


def test_a_vanished_file_is_unreadable_not_a_match(scanned):
    tree, db_path = scanned
    (tree / "b.txt").unlink()

    tally = verify_db(db_path, 2)

    assert tally.unreadable == 1
    assert tally.matched == 2
    assert "b.txt" in tally.failures[0][0]


def test_an_error_that_is_not_an_oserror_is_still_not_a_pass(
    scanned, monkeypatch
):
    """compute_md5 raising anything at all lands in the unreadable bucket."""
    _, db_path = scanned

    def explode(path):
        raise RuntimeError("something unexpected")
    monkeypatch.setattr(file_ops, "compute_md5", explode)

    tally = verify_db(db_path, 2)
    assert tally.unreadable == 3
    assert tally.matched == 0


def test_an_exception_escaping_the_worker_is_still_not_a_pass(
    scanned, monkeypatch
):
    """The pool's own error path: not reachable through compute_md5, which
    catches everything, so it is driven directly."""
    _, db_path = scanned

    def explode(path, stored, tally):
        raise RuntimeError("escaped the worker")
    monkeypatch.setattr(file_ops, "verify_one_recording", explode)

    tally = verify_db(db_path, 2)
    assert tally.unreadable == 3
    assert tally.matched == 0


# --- precedence ------------------------------------------------------------

def test_a_mismatch_outranks_an_unreadable_file(scanned):
    """Both are failures; one is a wrong answer already in the database."""
    tree, db_path = scanned
    corrupt_in_place(tree / "a.txt")
    (tree / "b.txt").unlink()

    tally = verify_db(db_path, 2)
    assert tally.mismatched == 1
    assert tally.unreadable == 1


# --- scoping ---------------------------------------------------------------

def test_a_prefix_limits_what_is_verified(tmp_path):
    """Verifying 1.7 TiB takes hours, so a run has to be able to be smaller."""
    left = tmp_path / "left"
    right = tmp_path / "right"
    for d in (left, right):
        d.mkdir()
        (d / "f.txt").write_text(d.name)
    db_path = str(tmp_path / "verify.db")
    initialize_db(db_path)
    # One call per path: splitting the comma-separated list is main()'s job,
    # not scan()'s.
    scan(str(left), db_path, 2)
    scan(str(right), db_path, 2)

    corrupt_in_place(right / "f.txt")

    scoped = verify_db(db_path, 2, prefix=str(left))
    assert scoped.checked == 1
    assert scoped.mismatched == 0, "a prefix run reached outside its prefix"

    everything = verify_db(db_path, 2)
    assert everything.checked == 2
    assert everything.mismatched == 1


def test_iter_recorded_checksums_orders_by_path(tmp_path):
    """Two runs over one prefix report in the same order, so output diffs."""
    tree = tmp_path / "tree"
    tree.mkdir()
    for name in ("c.txt", "a.txt", "b.txt"):
        (tree / name).write_text(name)
    db_path = str(tmp_path / "db.db")
    initialize_db(db_path)
    scan(str(tree), db_path, 2)

    paths = [p for p, _ in iter_recorded_checksums(db_path)]
    assert paths == sorted(paths)


# --- the tally -------------------------------------------------------------

def test_every_file_lands_in_exactly_one_bucket(tmp_path):
    """A concurrent verify loses nothing and counts nothing twice.

    Not a test of the lock -- both interpreters here are GIL builds, and 32
    threads of unsynchronised increments were measured losing zero (#57). This
    fires on a double-count or a dropped outcome, which is what it is for.
    """
    tree = tmp_path / "many"
    tree.mkdir()
    for i in range(120):
        (tree / f"f{i:03d}.txt").write_text(str(i))
    db_path = str(tmp_path / "db.db")
    initialize_db(db_path)
    scan(str(tree), db_path, 8)

    tally = verify_db(db_path, 8)

    assert tally.matched == 120
    assert tally.checked == 120
    assert tally.mismatched == 0 and tally.unreadable == 0


def test_the_summary_truncates_a_long_list_and_says_how_many_are_left():
    tally = VerifyTally()
    for i in range(file_ops.MAX_FAILURES_LISTED + 5):
        tally.record_mismatch(f"/p/{i}", "stored", "actual")
        tally.record_unreadable(f"/q/{i}", "boom")

    text = "\n".join(tally.summary_lines())
    assert "... and 5 more" in text
    assert text.count("stored stored") == file_ops.MAX_FAILURES_LISTED


def test_the_summary_names_both_checksums():
    tally = VerifyTally()
    tally.record_mismatch("/p/x", "aaa", "bbb")
    text = "\n".join(tally.summary_lines())
    assert "stored aaa" in text
    assert "actual bbb" in text


def test_a_clean_summary_is_one_line():
    tally = VerifyTally()
    tally.record_match()
    assert len(tally.summary_lines()) == 1
    assert "MISMATCHED" in tally.summary_lines()[0]


def test_verify_one_recording_labels_each_outcome(tmp_path):
    good = tmp_path / "g.txt"
    good.write_text("x")
    from src.md5sum import compute_md5
    tally = VerifyTally()
    assert verify_one_recording(str(good), compute_md5(str(good)), tally) \
        == 'matched'
    assert verify_one_recording(str(good), "not-the-checksum", tally) \
        == 'mismatched'
    assert verify_one_recording(str(tmp_path / "gone.txt"), "x", tally) \
        == 'unreadable'


def test_a_tally_can_be_passed_in_and_accumulates(scanned):
    _, db_path = scanned
    tally = VerifyTally()
    verify_db(db_path, 2, tally=tally)
    verify_db(db_path, 2, tally=tally)
    assert tally.matched == 6


# --- exit codes, as a process ---------------------------------------------

def run_cli(db_path, *args):
    return subprocess.run(
        [sys.executable, str(MAIN), "--db-path", str(db_path), "--threads", "2",
         *args],
        capture_output=True, text=True, timeout=120, cwd=str(PROJECT),
    )


def test_a_clean_verify_exits_zero(scanned):
    _, db_path = scanned
    result = run_cli(db_path, "verify-db")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 MISMATCHED" in result.stdout


def test_a_mismatch_exits_four(scanned):
    """4, not 3: 3 means part of the answer is unknown, 4 means it is known
    and bad."""
    tree, db_path = scanned
    corrupt_in_place(tree / "b.txt")

    result = run_cli(db_path, "verify-db")

    assert result.returncode == EXIT_MISMATCH, result.stdout
    assert "1 MISMATCHED" in result.stdout
    assert str(tree / "b.txt") in result.stdout


def test_an_unreadable_file_alone_exits_three(scanned):
    tree, db_path = scanned
    (tree / "b.txt").unlink()
    result = run_cli(db_path, "verify-db")
    assert result.returncode == EXIT_INCOMPLETE, result.stdout


def test_both_together_exit_four(scanned):
    tree, db_path = scanned
    corrupt_in_place(tree / "a.txt")
    (tree / "b.txt").unlink()
    result = run_cli(db_path, "verify-db")
    assert result.returncode == EXIT_MISMATCH, result.stdout


def test_the_report_survives_stderr_being_discarded(scanned):
    """A scheduled verify uses 2>/dev/null, like the scans do."""
    tree, db_path = scanned
    corrupt_in_place(tree / "b.txt")
    result = run_cli(db_path, "verify-db")
    assert "MISMATCHED" in result.stdout
    assert "verify complete" in result.stdout


def test_the_run_records_its_configuration(scanned):
    """report_settings, per Development-Principles section 2."""
    _, db_path = scanned
    result = run_cli(db_path, "verify-db")
    assert "verify-db settings:" in result.stdout
    assert "prefix  = (every recorded path)  (default)" in result.stdout


# --- the same arm in-process, for coverage --------------------------------
#
# The subprocess tests above establish the exit STATUS, which an in-process
# return value cannot. These establish the coverage and read the printed text,
# which a subprocess cannot contribute. Both forms are needed; dropping either
# leaves a hole that looks like a passing suite (the same pairing as #57).

def run_main(monkeypatch, capsys, db_path, *args):
    monkeypatch.setattr(sys, "argv",
                        ["main.py", "--db-path", str(db_path),
                         "--threads", "2", *args])
    from src import main as main_module
    code = main_module.main()
    return code, capsys.readouterr().out


def test_in_process_a_clean_verify_returns_zero(scanned, monkeypatch, capsys):
    _, db_path = scanned
    code, out = run_main(monkeypatch, capsys, db_path, "verify-db")
    assert code == 0
    assert "verify complete: checked 3, 3 matched, 0 MISMATCHED" in out


def test_in_process_a_mismatch_returns_four_and_names_the_file(
    scanned, monkeypatch, capsys
):
    tree, db_path = scanned
    corrupt_in_place(tree / "b.txt")

    code, out = run_main(monkeypatch, capsys, db_path, "verify-db")

    assert code == EXIT_MISMATCH
    assert "1 MISMATCHED" in out
    assert str(tree / "b.txt") in out
    assert "stored " in out and "actual " in out


def test_in_process_an_unreadable_file_returns_three(
    scanned, monkeypatch, capsys
):
    tree, db_path = scanned
    (tree / "b.txt").unlink()

    code, out = run_main(monkeypatch, capsys, db_path, "verify-db")

    assert code == EXIT_INCOMPLETE
    assert "1 unreadable" in out
    assert "unreadable (1):" in out


def test_in_process_a_prefix_scopes_the_run(scanned, monkeypatch, capsys):
    tree, db_path = scanned
    corrupt_in_place(tree / "b.txt")

    code, out = run_main(monkeypatch, capsys, db_path, "verify-db",
                         "--prefix", str(tree / "a"))

    assert code == 0, out
    assert "checked 1" in out
    assert f"prefix  = {tree / 'a'}  (set)" in out


def test_in_process_the_header_and_the_settings_are_both_printed(
    scanned, monkeypatch, capsys
):
    _, db_path = scanned
    _, out = run_main(monkeypatch, capsys, db_path, "verify-db")
    assert out.splitlines()[0] == "FileManager run"
    assert "action  : verify-db" in out
    assert "verify-db settings:" in out


def test_the_unreadable_list_truncates_in_the_printed_report(
    monkeypatch, capsys
):
    """The unreadable branch of summary_lines, through the printer."""
    from src.main import _print_verify_summary
    tally = VerifyTally()
    for i in range(file_ops.MAX_FAILURES_LISTED + 3):
        tally.record_unreadable(f"/q/{i}", "boom")

    _print_verify_summary(tally)
    out = capsys.readouterr().out

    assert "unreadable (23):" in out
    assert "... and 3 more" in out
