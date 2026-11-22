"""#69 -- the database's directory is checked before anything opens it.

Before #69, a `--db-path` whose parent directory did not exist died inside
sqlite3 with `unable to open database file` and a six-frame traceback, and
exited 1 -- Python's status for an uncaught exception, which this tool's
contract defines as "a required argument was missing or invalid". The argument
was fine. The owner chose 5 for "the environment the run needs is not there".

Each outcome has its own test because each has a different fix, and the point
of the ticket is that they stop collapsing into one another:

  missing           -> create the directory (and the tool must NOT create it)
  not a directory   -> the path is wrong
  not writable      -> a permission problem, not a missing directory
  cannot check      -> an ancestor cannot be searched; reported as itself,
                       not as "does not exist", which os.path.isdir would say

The permission tests skip as root, because root passes every mode check and
the condition cannot be produced.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.db import initialize_db

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "src" / "main.py"

EXIT_ENVIRONMENT = 5

as_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root passes every permission check"
)


@pytest.fixture
def locked(tmp_path):
    """Directories whose mode is changed by the test, restored afterwards so
    tmp_path can be cleaned up."""
    changed: list[Path] = []

    def lock(path: Path, mode: int) -> Path:
        path.chmod(mode)
        changed.append(path)
        return path

    yield lock
    for path in changed:
        path.chmod(0o755)


def test_a_missing_directory_exits_5_and_names_it(run_cli, tmp_path):
    missing = tmp_path / "var" / "lib" / "filemanager"
    result = run_cli("report-duplicate-sizes",
                     "--db-path", str(missing / "home2.db"))

    assert result.exit_code == EXIT_ENVIRONMENT
    assert f"database directory does not exist: {missing}" in result.stdout
    assert f"mkdir -p {missing}" in result.stdout
    assert "Traceback" not in result


def test_a_missing_directory_is_not_created(run_cli, tmp_path):
    """Where the index lives is an operational decision. A typo in a path
    must not invent a directory."""
    missing = tmp_path / "typo"
    run_cli("report-duplicate-sizes", "--db-path", str(missing / "x.db"))
    assert not missing.exists()


def test_the_header_is_printed_before_the_refusal(run_cli, tmp_path):
    """The log of a refused run still says which database was meant."""
    db = tmp_path / "missing" / "x.db"
    result = run_cli("report-duplicate-sizes", "--db-path", str(db))
    assert result.stdout.index(f"db      : {db}") < result.stdout.index("Error:")


def test_a_parent_that_is_a_file_is_not_a_directory(run_cli, tmp_path):
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("x")
    result = run_cli("report-duplicate-sizes",
                     "--db-path", str(a_file / "x.db"))

    assert result.exit_code == EXIT_ENVIRONMENT
    assert f"database directory is not a directory: {a_file}" in result.stdout
    assert "does not exist" not in result.stdout


def test_a_file_above_the_directory_means_it_does_not_exist(run_cli, tmp_path):
    """stat raises NotADirectoryError when a component higher up is a file.
    The directory named does not exist, and creating the path is the fix."""
    a_file = tmp_path / "plain"
    a_file.write_text("x")
    wanted = a_file / "sub"
    result = run_cli("report-duplicate-sizes",
                     "--db-path", str(wanted / "x.db"))

    assert result.exit_code == EXIT_ENVIRONMENT
    assert f"database directory does not exist: {wanted}" in result.stdout


@as_root
def test_an_unwritable_directory_is_not_reported_as_missing(
        run_cli, tmp_path, locked):
    ro = tmp_path / "ro"
    ro.mkdir()
    locked(ro, 0o555)
    result = run_cli("report-duplicate-sizes", "--db-path", str(ro / "x.db"))

    assert result.exit_code == EXIT_ENVIRONMENT
    assert f"database directory is not writable by uid {os.geteuid()}" in result.stdout
    assert "does not exist" not in result.stdout
    assert not (ro / "x.db").exists()


@as_root
def test_an_existing_database_in_a_read_only_directory_still_reports(
        run_cli, tmp_path, locked):
    """Writability matters only when the file has to be created. Refusing a
    read-only report off an existing index would break a run that worked."""
    ro = tmp_path / "ro"
    ro.mkdir()
    db = ro / "x.db"
    initialize_db(str(db))
    locked(ro, 0o555)

    result = run_cli("report-duplicate-sizes", "--db-path", str(db))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Error:" not in result.stdout


@as_root
def test_an_unsearchable_ancestor_is_cannot_check_not_missing(
        run_cli, tmp_path, locked):
    """The three-outcome rule: "could not check" must not collapse into "does
    not exist". os.path.isdir answers False here, which is the bug this test
    exists to keep out."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    locked(outer, 0o000)

    result = run_cli("report-duplicate-sizes", "--db-path", str(inner / "x.db"))

    assert result.exit_code == EXIT_ENVIRONMENT
    assert f"cannot check database directory {inner}:" in result.stdout
    assert "Permission denied" in result.stdout
    assert "does not exist" not in result.stdout


def test_a_healthy_directory_has_no_problem(tmp_path):
    from src import main as main_module
    assert main_module._database_directory_problem(str(tmp_path / "x.db")) is None


def test_a_bare_filename_checks_the_current_directory(tmp_path, monkeypatch):
    """`--db-path` omitted means ./file_manager.db, whose dirname is ''."""
    monkeypatch.chdir(tmp_path)
    from src import main as main_module
    assert main_module._database_directory_problem("file_manager.db") is None


def test_the_process_exit_status_is_5(tmp_path):
    """The in-process tests read main()'s return value. This one reads $?,
    which is what a caller under set -e actually sees."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--db-path",
         str(tmp_path / "missing" / "x.db"), "report-duplicate-sizes"],
        capture_output=True, text=True, timeout=60, cwd=str(PROJECT),
    )
    assert result.returncode == EXIT_ENVIRONMENT, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
