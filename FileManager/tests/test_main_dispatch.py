"""#36 -- every remaining arm of main()'s dispatch chain.

`main` is an argparse dispatcher: one `elif` per action, no logic beyond
argument validation. That shape makes it cheap to cover and expensive to leave
uncovered, because it is the layer standing between a command line and every
action that deletes rows. A typo in an arm -- the wrong function, the wrong
argument order -- is invisible to a reviewer and silent at runtime until the
action does the wrong thing.

`tests/test_main_cli.py` already covers argument validation and the actions
reached by #13's fixture. This file covers the arms nothing invoked.

Two boundaries are deliberate:

  `--use-gui` asserts the dispatch *call*, patched. Opening a Tkinter window in
  CI tests the library, which is the same line `.coveragerc` draws around
  gui.py; #3 is the ticket that moves the testable logic out of the widget.

Two things stay uncovered, named here rather than pragma'd away:

  `sys.exit(main())` under `if __name__ == "__main__"` runs only when the file
  is executed as a script. Reaching it needs a subprocess, which coverage would
  not attribute here anyway. One statement.

  The fall-through from the last `elif` to `return 0` is unreachable: argparse
  rejects anything outside `choices`, and every choice has an arm. It shows as
  a partial branch because `--cov-branch` cannot know that. Do not add a test
  that forces it -- it would assert on a state the CLI cannot produce.
"""

from __future__ import annotations

import pytest

from src import main as main_module
from src.db import get_all_files_info, store_file_info
from src.md5sum import compute_md5


def _record(db_path, *paths):
    for path in paths:
        store_file_info(db_path, str(path), compute_md5(str(path)))


def _settings(stdout: str) -> str:
    """The settings block with runs of spaces collapsed.

    `report_settings` pads names to the longest one in the batch, so the exact
    column depends on which settings that action happens to report. Asserting
    on the padding would make these tests fail when an unrelated flag is added,
    which says nothing about the arm under test.
    """
    return " ".join(stdout.split())


# -- the scanning arms -----------------------------------------------------


def test_check_file_reports_a_recorded_duplicate(run_cli, db_path, dup_tree):
    left, right = dup_tree.duplicated[0]
    _record(db_path, left, right)

    result = run_cli("check-file", str(left), "--db-path", db_path)

    assert result.exit_code == 0
    assert f"Duplicate found for {left}:" in result.stdout
    assert str(right) in result.stdout


def test_scan_dir_report_arm_scans_and_returns(run_cli, db_path, dup_tree):
    """Reaches reporting.scan_dir_report, which until #43 never returned."""
    result = run_cli("scan-dir-report", str(dup_tree.left),
                     "--db-path", db_path, "--threads", "2")

    assert result.exit_code == 0
    recorded = {row[0] for row in get_all_files_info(db_path)}
    assert recorded == {str(p) for p in dup_tree.left.iterdir()}


def test_scan_unique_files_arm_prints_what_it_found(run_cli, db_path, dup_tree):
    result = run_cli("scan-unique-files", str(dup_tree.left),
                     "--db-path", db_path, "--threads", "2")

    assert result.exit_code == 0
    assert "Unique files:" in result.stdout
    assert str(dup_tree.left / "unique-left.txt") in result.stdout


# -- report-duplicates, all three shapes -----------------------------------


def test_report_duplicates_with_a_prefix_uses_the_prefix_query(run_cli, db_path,
                                                               dup_tree):
    """The --prefix arm is a different function from the default one."""
    _record(db_path, *dup_tree.left.iterdir(), *dup_tree.right.iterdir())

    scoped = run_cli("report-duplicates", "--db-path", db_path,
                     "--prefix", str(dup_tree.left))
    whole = run_cli("report-duplicates", "--db-path", db_path,
                    "--prefix", str(dup_tree.root))

    assert scoped.exit_code == 0
    assert "Found 0 duplicates" in scoped.stdout, "nothing under left/ duplicates itself"
    assert f"Found {len(dup_tree.duplicated)} duplicates" in whole.stdout


def test_min_duplicates_1_counts_single_files_but_does_not_print_them(run_cli,
                                                                      db_path,
                                                                      dup_tree):
    """The `len(paths) > 1` filter in the print loop is not dead code.

    Since #6 made the comparison inclusive, `--min-duplicates 1` means "at
    least one copy", which is every file -- so the mapping handed to the loop
    contains single-path entries the filter then skips. The count line reports
    all of them; only the listing is filtered. Nothing else reaches that
    branch, because every other route produces groups of two or more.
    """
    left, right = dup_tree.duplicated[0]
    lone = dup_tree.unique[0]
    _record(db_path, left, right, lone)

    result = run_cli("report-duplicates", "--db-path", db_path,
                     "--min-duplicates", "1")

    assert result.exit_code == 0
    assert "Found 2 duplicates" in result.stdout, "the lone file is counted"
    assert str(left) in result.stdout and str(right) in result.stdout
    assert str(lone) not in result.stdout, "a single-path group must not be listed"


def test_use_gui_hands_the_groups_to_the_viewer_without_opening_one(run_cli, db_path,
                                                                    dup_tree,
                                                                    monkeypatch):
    """Asserts the dispatch, not the widget.

    Opening a Tkinter window in CI would test the library rather than this
    line, which is the same boundary .coveragerc draws around gui.py.
    """
    left, right = dup_tree.duplicated[0]
    _record(db_path, left, right)
    handed: list[dict] = []
    monkeypatch.setattr(main_module, "show_duplicates_gui", handed.append)

    result = run_cli("report-duplicates", "--db-path", db_path, "--use-gui")

    assert result.exit_code == 0
    assert len(handed) == 1
    assert list(handed[0].values()) == [[str(left), str(right)]]


def test_use_gui_is_capped_at_a_hundred_groups(run_cli, db_path, monkeypatch):
    """The cap is the reason the GUI arm is not just a call.

    Built with synthetic rows: 101 real duplicate pairs would be 202 files to
    hash for one assertion about a slice.
    """
    from src import db as db_module

    def work(conn):
        for i in range(101):
            for copy in range(2):
                conn.execute(
                    "INSERT INTO files (path, md5sum, size, last_modified) "
                    "VALUES (?, ?, ?, ?)",
                    (f"/synthetic/{i:03d}/copy-{copy}", f"{i:032d}", 10, 0),
                )
    db_module.with_connection(db_path, work, commit=True, description="seed groups")

    handed: list[dict] = []
    monkeypatch.setattr(main_module, "show_duplicates_gui", handed.append)

    result = run_cli("report-duplicates", "--db-path", db_path, "--use-gui")

    assert "Found 101 duplicates" in result.stdout, "the count is not truncated"
    assert len(handed[0]) == 100, "only the display is capped, at 100"


# -- audit-db, and the settings report that precedes it --------------------


def test_audit_db_arm_reports_its_settings_before_running(run_cli, db_path, dup_tree):
    """Development-Principles section 2: a destructive run states its
    configuration first. This arm is where that happens, and nothing reached it."""
    _record(db_path, *dup_tree.all_files())

    result = run_cli("audit-db", "--db-path", db_path, "--threads", "2", "--dry-run")

    assert result.exit_code == 0
    assert "audit-db settings:" in result.stdout
    settings = _settings(result.stdout)
    assert "dry_run = True (set)" in settings
    assert "prune_missing_dirs = False (default)" in settings


def test_the_origin_column_distinguishes_a_set_flag_from_its_default(run_cli, db_path):
    """`--threads 2` and a defaulted 2 print the same value; only the origin
    tells them apart, which is the entire point of recording it."""
    explicit = run_cli("audit-db", "--db-path", db_path, "--threads", "4", "--dry-run")
    implicit = run_cli("audit-db", "--db-path", db_path, "--dry-run")

    assert "threads = 4 (set)" in _settings(explicit.stdout)
    assert "threads = 4 (default)" in _settings(implicit.stdout)


def test_audit_db_exclude_prefix_is_split_on_commas(run_cli, db_path, dup_tree):
    _record(db_path, *dup_tree.all_files())

    result = run_cli("audit-db", "--db-path", db_path, "--dry-run",
                     "--exclude-prefix", f"{dup_tree.left},{dup_tree.right}")

    assert result.exit_code == 0
    assert f"exclude_prefix = ['{dup_tree.left}', '{dup_tree.right}'] (set)" \
        in _settings(result.stdout)


# -- the prefix and comparison arms ----------------------------------------


def test_report_prefix_count_arm_prints_the_count(run_cli, db_path, dup_tree):
    _record(db_path, *dup_tree.left.iterdir())

    result = run_cli("report-prefix-count", "--db-path", db_path,
                     "--prefix", str(dup_tree.left))

    assert result.exit_code == 0
    assert f"'{dup_tree.left}': 4" in result.stdout


def test_report_files_for_prefix_arm_lists_the_paths(run_cli, db_path, dup_tree):
    _record(db_path, *dup_tree.left.iterdir(), *dup_tree.right.iterdir())

    result = run_cli("report-files-for-prefix", "--db-path", db_path,
                     "--prefix", str(dup_tree.left))

    assert result.exit_code == 0
    assert f"Files with prefix '{dup_tree.left}':" in result.stdout
    for path in dup_tree.left.iterdir():
        assert str(path) in result.stdout
    assert str(dup_tree.right / "unique-right.txt") not in result.stdout


def test_compare_directories_arm_names_both_sides(run_cli, dup_tree):
    result = run_cli("compare-directories",
                     "--dirA", str(dup_tree.left), "--dirB", str(dup_tree.right))

    assert result.exit_code == 0
    assert "Files unique to dirA:" in result.stdout
    assert str(dup_tree.left / "unique-left.txt") in result.stdout
    assert str(dup_tree.right / "unique-right.txt") in result.stdout
