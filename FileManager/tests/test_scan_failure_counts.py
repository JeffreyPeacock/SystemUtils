"""#57 -- a scan that could not read part of the tree says so, and exits non-zero.

Before this, a scan recorded the files it could read, logged one ERROR line per
file it could not, and exited **0**. Measured on the built bundle: a two-file
tree with one file at mode 000 produced one database row and exit 0.

The reason that is a defect and not a missing feature is that the gap is
unrecoverable afterwards. The database looks identical whether a file was absent
from the tree or merely unreadable, so a later `audit-db` finds nothing to
report and a duplicate report over the partial set is internally consistent.
Nothing in the recorded data says a file was skipped. For a checksum baseline
whose whole purpose is detecting later change, a silent gap reads as a file that
never existed.

Two things are pinned here, and the second is the one that matters:

  1. the counts are produced, and they reach **stdout** so they survive
     `2>/dev/null` and are the last thing in a redirected log
  2. the **exit status changes**, asserted together with the row count, through
     a real subprocess -- `tests/conftest.py` calls `main()` in process, which
     cannot observe an exit status at all, and that is precisely how this
     behaviour survived this long
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from src import file_ops

PROJECT = Path(__file__).resolve().parents[1]

EXIT_INCOMPLETE = 3


@pytest.fixture
def partial_tree(tmp_path: Path) -> Path:
    """A tree with one readable file and one that cannot be opened."""
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "readable.txt").write_text("readable\n", encoding="utf-8")
    denied = tree / "denied.txt"
    denied.write_text("denied\n", encoding="utf-8")
    denied.chmod(0o000)
    yield tree
    # Restore the mode so pytest's own tmp_path cleanup can remove it.
    denied.chmod(0o644)


def _rows(db: Path) -> list[str]:
    """`with sqlite3.connect(...)` commits; it does not close. Hence closing()."""
    with closing(sqlite3.connect(db)) as conn:
        return [r[0] for r in conn.execute("SELECT path FROM files ORDER BY path")]


# -- the tally itself ------------------------------------------------------


def test_the_tally_counts_each_outcome_separately():
    tally = file_ops.ScanTally()
    tally.record_outcome('hashed')
    tally.record_outcome('skipped')
    tally.record_outcome('skipped')
    tally.record_failure("/nope", OSError("boom"))

    assert (tally.hashed, tally.skipped, tally.failed) == (1, 2, 1)
    assert tally.checked == 3, "checked counts what was looked at, not what failed"
    assert tally.failures == [("/nope", "boom")]


def test_a_clean_tally_reports_zero_failures_and_lists_nothing():
    tally = file_ops.ScanTally()
    tally.record_outcome('hashed')

    lines = tally.summary_lines()

    assert lines == ["scan complete: 1 hashed, 0 skipped unchanged, 0 failed"], (
        "a clean run must not print a failures block"
    )


def test_a_long_failure_list_is_truncated_with_a_count():
    """A scan of millions of files on a failing disk must not bury the counts
    under its own error list."""
    tally = file_ops.ScanTally()
    for i in range(file_ops.MAX_FAILURES_LISTED + 5):
        tally.record_failure(f"/path/{i}", OSError("nope"))

    lines = tally.summary_lines()
    listed = [line for line in lines if line.startswith("  /path/")]

    assert len(listed) == file_ops.MAX_FAILURES_LISTED
    assert lines[0].endswith(f"{file_ops.MAX_FAILURES_LISTED + 5} failed")
    assert "and 5 more" in lines[-1]


def test_every_file_in_a_concurrent_scan_lands_in_exactly_one_bucket(tmp_path, db_path):
    """One tally, `--threads` consumers, and every file counted once.

    This is the arithmetic gate, and it is worth more than it looks: the
    recording calls sit in the consumer's try/except/finally, which is also
    where #43's sentinel shutdown lives. Recording an outcome twice, or dropping
    one on the path that re-raises, both show up here as checked + failed not
    adding up to the number of files.

    **It is not a test of the lock.** `ScanTally` takes a lock for each update,
    and on a GIL build no test can tell that apart from not taking one: with the
    lock removed, 32 threads making 50,000 unsynchronised increments each, at a
    1 ns switch interval, lost zero. Measured on 2026-11-16 against CPython
    3.14.7 and /usr/bin/python3 3.12.3, both GIL builds. The lock is there for a
    free-threaded build, where that stops being true, and it is held by
    reasoning rather than by a failing test -- which is the honest way to say it
    (docs/Development-Principles.md section 3a).
    """
    tree = tmp_path / "many"
    tree.mkdir()
    for i in range(200):
        (tree / f"f{i:03d}.txt").write_text(f"body {i}\n", encoding="utf-8")

    tally = file_ops.scan(str(tree), db_path, 8)

    assert tally.hashed == 200, f"hashed {tally.hashed} of 200"
    assert tally.failed == 0, f"failures: {tally.failures[:3]}"
    assert tally.checked + tally.failed == 200, (
        "every file must land in exactly one bucket -- no double counting, "
        "and nothing dropped"
    )


# -- the scan paths --------------------------------------------------------


def test_an_unreadable_file_is_counted_as_failed_not_skipped(partial_tree, db_path):
    """The distinction the old code could not make: a file it chose not to hash
    and a file it could not hash both produced nothing."""
    tally = file_ops.scan(str(partial_tree), db_path, 2)

    assert tally.failed == 1, "the unreadable file must be counted"
    assert tally.hashed == 1, "the readable file must still be recorded"
    assert tally.skipped == 0, "an unreadable file is not an unchanged file"
    failed_paths = [path for path, _ in tally.failures]
    assert failed_paths == [str(partial_tree / "denied.txt")]
    assert "Permission denied" in tally.failures[0][1]


def test_a_fully_readable_tree_reports_no_failures(dup_tree, db_path):
    tally = file_ops.scan(str(dup_tree.left), db_path, 2)

    assert tally.failed == 0
    assert tally.failures == []
    assert tally.hashed > 0, "the fixture tree is not empty"


def test_a_second_scan_counts_the_unchanged_files_as_skipped(dup_tree, db_path):
    """The skip check is what makes a rescan cheap; it must not be confused
    with a failure, in either direction."""
    first = file_ops.scan(str(dup_tree.left), db_path, 2)
    second = file_ops.scan(str(dup_tree.left), db_path, 2)

    assert second.skipped == first.hashed
    assert second.hashed == 0
    assert second.failed == 0


def test_a_path_that_is_neither_a_file_nor_a_directory_is_a_failure(tmp_path, db_path):
    """A path given on the command line that does not exist means the scan did
    not cover what it was asked to cover. That is the same kind of gap as an
    unreadable file, and it used to be an ERROR log line and nothing else."""
    missing = tmp_path / "not-there"

    tally = file_ops.scan(str(missing), db_path, 2)

    assert tally.failed == 1
    assert tally.failures == [(str(missing), "not a file or directory")]


def test_one_tally_spans_several_paths(partial_tree, dup_tree, db_path):
    """`scan a,b` is one scan and gets one answer about completeness."""
    tally = file_ops.ScanTally()
    file_ops.scan(str(dup_tree.left), db_path, 2, tally)
    file_ops.scan(str(partial_tree), db_path, 2, tally)

    assert tally.failed == 1
    assert tally.hashed >= 2


def test_process_file_reports_which_outcome_it_took(tmp_path, db_path):
    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")

    assert file_ops.process_file(str(target), db_path) == 'hashed'
    assert file_ops.process_file(str(target), db_path) == 'skipped'


def test_process_files_concurrently_counts_failures(partial_tree, db_path):
    paths = sorted(str(p) for p in partial_tree.iterdir())

    tally = file_ops.process_files_concurrently(paths, db_path, 4)

    assert tally.failed == 1
    assert tally.hashed == 1


# -- the exit status, through a real process -------------------------------


def test_the_cli_exits_non_zero_and_still_records_what_it_could(partial_tree, tmp_path):
    """The load-bearing test. Row count and exit status asserted together.

    Run as a subprocess on purpose. `run_cli` in conftest.py calls `main()` in
    process and reads its return value, which cannot distinguish a returned code
    from one that reached the operating system -- and `sys.exit(main())` is the
    line that connects them. A test that cannot see $? is how a tool shipped for
    this long reporting success over a partial index.
    """
    db = tmp_path / "scan.db"

    result = subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db),
         "scan", str(partial_tree)],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == EXIT_INCOMPLETE, (
        f"a scan that could not read part of the tree exited "
        f"{result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert _rows(db) == [str(partial_tree / "readable.txt")], (
        "the readable file must still be recorded -- exiting non-zero does not "
        "mean abandoning the work that succeeded"
    )
    assert "1 hashed, 0 skipped unchanged, 1 failed" in result.stdout
    assert str(partial_tree / "denied.txt") in result.stdout


def test_a_clean_scan_still_exits_zero(dup_tree, tmp_path):
    """The other half. An exit code that is always non-zero carries no
    information, and a detector that cannot stay quiet is not a detector."""
    db = tmp_path / "clean.db"

    result = subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db),
         "scan", str(dup_tree.left)],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "0 failed" in result.stdout
    assert "failed (" not in result.stdout, "a clean run lists no failures"
    assert len(_rows(db)) > 0


def test_the_summary_reaches_stdout_not_the_log_stream(partial_tree, tmp_path):
    """The counts are the result of the run, not a diagnostic. All the logging
    goes to stderr, so a summary written there would vanish under the
    `2>/dev/null` that a scheduled scan uses to suppress the per-file lines."""
    db = tmp_path / "streams.db"

    result = subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db),
         "scan", str(partial_tree)],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )

    assert "1 failed" in result.stdout
    assert "scan complete" not in result.stderr


def test_the_exit_code_distinguishes_a_partial_scan_from_a_bad_command_line(tmp_path):
    """3 is not 1 and not 2. A caller has to tell "recorded nothing, the command
    was wrong" from "recorded most of the tree and skipped the rest"."""
    db = tmp_path / "codes.db"

    missing_arg = subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db), "scan"],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )
    rejected = subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db), "no-such-action"],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )

    assert missing_arg.returncode == 1, "a missing path is still 1 (#23)"
    assert rejected.returncode == 2, "an argparse rejection is still 2 (#23)"


# -- audit-db gets the same treatment -------------------------------------


def test_audit_db_counts_a_row_it_could_not_read(partial_tree, db_path, tmp_path):
    """audit-db had the same shape: it logged per-row problems, reported
    `Error processing file info` without naming the row, and returned counts
    with nowhere for a failure to go."""
    from src.db import audit_db

    # Record the readable file, then make it unreadable and change its size so
    # the audit has to rehash it rather than skipping on (size, mtime).
    readable = partial_tree / "readable.txt"
    file_ops.scan(str(readable), db_path, 1)
    readable.write_text("a longer body than before\n", encoding="utf-8")
    readable.chmod(0o000)
    try:
        counts = audit_db(db_path, 2, file_ops.process_file)
    finally:
        readable.chmod(0o644)

    assert counts['failed'] == 1, f"counts were {counts}"
    assert counts['failures'][0][0] == str(readable)
    assert "Permission denied" in counts['failures'][0][1]


def test_audit_db_on_a_readable_database_reports_no_failures(dup_tree, db_path):
    from src.db import audit_db

    file_ops.scan(str(dup_tree.left), db_path, 2)

    counts = audit_db(db_path, 2, file_ops.process_file)

    assert counts['failed'] == 0
    assert counts['failures'] == []


def test_the_cli_exits_non_zero_when_the_audit_could_not_read_a_row(
        partial_tree, tmp_path):
    db = tmp_path / "audit.db"
    readable = partial_tree / "readable.txt"

    subprocess.run(
        [sys.executable, "src/main.py", "--db-path", str(db),
         "scan", str(readable)],
        cwd=PROJECT, capture_output=True, text=True, timeout=60, check=True,
    )
    readable.write_text("a longer body than before\n", encoding="utf-8")
    readable.chmod(0o000)
    try:
        result = subprocess.run(
            [sys.executable, "src/main.py", "--db-path", str(db), "audit-db"],
            cwd=PROJECT, capture_output=True, text=True, timeout=60,
        )
    finally:
        readable.chmod(0o644)

    assert result.returncode == EXIT_INCOMPLETE, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "failed 1" in result.stdout
    assert str(readable) in result.stdout


# -- the paths a subprocess test cannot reach ------------------------------
#
# The subprocess tests above are the ones that prove the exit status reaches the
# operating system, and that is the whole point of #57 -- but a subprocess runs
# outside coverage measurement, so it contributes nothing to the report. These
# call the same code in process. Both forms are needed: in-process can see the
# returned value but not $?, and a subprocess can see $? but not the lines.


def test_one_failure_is_listed_without_an_and_more_line():
    """failed > 0 with nothing truncated -- the common case, and the one
    between the two the other tests cover."""
    tally = file_ops.ScanTally()
    tally.record_failure("/only/one", OSError("[Errno 13] Permission denied"))

    lines = tally.summary_lines()

    assert lines[0] == "scan complete: 0 hashed, 0 skipped unchanged, 1 failed"
    assert lines[1] == "failed (1):"
    assert lines[2] == "  /only/one: [Errno 13] Permission denied"
    assert len(lines) == 3, f"an 'and N more' line appeared for one failure: {lines}"


def test_scanning_a_single_unreadable_file_counts_it(partial_tree, db_path):
    """`scan /path/to/one/file` takes the scan_file branch, not scan_dir. The
    two have separate error handling and only one of them was exercised."""
    denied = partial_tree / "denied.txt"

    tally = file_ops.scan(str(denied), db_path, 1)

    assert tally.failed == 1
    assert tally.hashed == 0
    assert tally.failures[0][0] == str(denied)
    assert "Permission denied" in tally.failures[0][1]


def test_the_scan_action_returns_the_incomplete_code(partial_tree, tmp_path, run_cli):
    """In process, so the returned value itself is asserted. The subprocess
    test asserts that `sys.exit(main())` turns it into a real exit status."""
    db = tmp_path / "inproc.db"

    result = run_cli("--db-path", str(db), "scan", str(partial_tree))

    assert result.exit_code == EXIT_INCOMPLETE
    assert "1 failed" in result.stdout


def test_the_audit_action_returns_the_incomplete_code_and_names_the_row(
        partial_tree, tmp_path, run_cli):
    readable = partial_tree / "readable.txt"
    db = tmp_path / "inproc-audit.db"

    assert run_cli("--db-path", str(db), "scan", str(readable)).exit_code == 0
    readable.write_text("a longer body than before\n", encoding="utf-8")
    readable.chmod(0o000)
    try:
        result = run_cli("--db-path", str(db), "audit-db")
    finally:
        readable.chmod(0o644)

    assert result.exit_code == EXIT_INCOMPLETE
    assert "failed 1" in result.stdout
    assert str(readable) in result.stdout


def test_a_long_audit_failure_list_is_truncated(capsys):
    """The audit summary's own truncation. Reaching it through a real audit
    would mean making 21 rows unreadable; the printer is the unit under test."""
    from src import main as main_module

    counts = {'checked': 30, 'removed': 0, 'reprocessed': 0, 'skipped': 0,
              'suspect': 0, 'not_regular': 0, 'failed': 25,
              'failures': [(f"/path/{i}", "Permission denied") for i in range(25)]}

    main_module._print_audit_summary(counts)
    out = capsys.readouterr().out

    assert "failed 25" in out
    assert out.count("Permission denied") == 20, "the list must stop at 20"
    assert "and 5 more" in out
