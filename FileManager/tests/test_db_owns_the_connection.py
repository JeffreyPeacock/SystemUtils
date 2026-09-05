"""#10 -- db.py is the only module that opens a SQLite connection.

Before this, `reporting.py` called `sqlite3.connect` in five functions. The
retry loop is the part that mattered: db.py's writers wait out a
`database is locked`, reporting did not, so a report run alongside a scan
raised instead of waiting. The wider cost was that connection handling lived
in two places, so a pragma or a timeout added to one was only half applied.

Three things are pinned here:

  1. no module under src/ but db.py so much as imports sqlite3
  2. `with_connection` retries a lock, and does NOT retry anything else
  3. the reporting queries actually go through it, rather than merely having
     stopped importing sqlite3
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from src import db, reporting

SRC = Path(__file__).resolve().parent.parent / "src"


def _modules_importing_sqlite3(root: Path) -> set[str]:
    """Every .py file under `root` whose AST imports sqlite3, by stem.

    Parsed rather than grepped so a mention inside a comment or a docstring --
    db.py and reporting.py both carry one explaining this rule -- is not
    mistaken for an import.
    """
    found = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] == "sqlite3" for alias in node.names):
                    found.add(path.stem)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "sqlite3":
                    found.add(path.stem)
    return found


def test_the_detector_can_fire():
    """A file that DOES import sqlite3 is reported.

    Without this, `_modules_importing_sqlite3` returning an empty set proves
    nothing -- a broken walker and a clean tree look identical.
    """
    probe = SRC.parent / "tests" / "_probe_sqlite_import.py"
    probe.write_text("import sqlite3\nfrom sqlite3 import connect\n", encoding="utf-8")
    try:
        assert "_probe_sqlite_import" in _modules_importing_sqlite3(probe.parent)
    finally:
        probe.unlink()


def test_only_db_imports_sqlite3():
    assert _modules_importing_sqlite3(SRC) == {"db"}


def test_with_connection_retries_a_locked_database(monkeypatch, db_path):
    """A lock is waited out, not raised."""
    attempts = {"n": 0}
    real_connect = sqlite3.connect

    def flaky_connect(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", flaky_connect)
    monkeypatch.setattr(db, "RETRY_DELAY", 0)

    assert db.get_all_files_info(db_path) == []
    assert attempts["n"] == 4, "the read path should have retried three times"


def test_with_connection_does_not_retry_other_errors(monkeypatch, db_path):
    """Only a lock is retried -- a malformed statement fails at once.

    Retrying a syntax error ten times only delays the report by a second, and
    hides which statement was wrong behind a lock message.
    """
    attempts = {"n": 0}

    def work(conn):
        attempts["n"] += 1
        conn.execute("SELECT nonexistent_column FROM files")

    monkeypatch.setattr(db, "RETRY_DELAY", 0)
    with pytest.raises(sqlite3.OperationalError, match="nonexistent_column"):
        db.with_connection(db_path, work)
    assert attempts["n"] == 1


def test_with_connection_gives_up_after_max_retries(monkeypatch, db_path):
    def always_locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db.sqlite3, "connect", always_locked)
    monkeypatch.setattr(db, "RETRY_DELAY", 0)

    with pytest.raises(sqlite3.OperationalError, match="after 10 retries"):
        db.get_all_files_info(db_path)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda p: reporting.report_files_with_more_than_1_duplicate(p),
                     id="report_files_with_more_than_1_duplicate"),
        pytest.param(lambda p: reporting.report_duplicate_sizes(p),
                     id="report_duplicate_sizes"),
        pytest.param(lambda p: reporting.report_prefix_count(p, "/any"),
                     id="report_prefix_count"),
        pytest.param(lambda p: reporting.report_files_for_prefix(p, "/any"),
                     id="report_files_for_prefix"),
        pytest.param(lambda p: reporting.report_duplicates_for_prefix(p, "/any"),
                     id="report_duplicates_for_prefix"),
        pytest.param(lambda p: reporting.report_duplicates(p),
                     id="report_duplicates"),
    ],
)
def test_every_reporting_query_goes_through_the_gateway(monkeypatch, db_path, call):
    """Counted at `with_connection`, so a new raw connection here would show up
    as zero rather than passing quietly."""
    seen = {"n": 0}
    real = db.with_connection

    def counting(*args, **kwargs):
        seen["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(db, "with_connection", counting)
    call(db_path)
    assert seen["n"] >= 1


def test_reporting_still_reads_what_the_scan_wrote(db_path, dup_tree):
    """The refactor did not change any answer.

    Reads through the fixture tree end to end: three duplicated pairs, two
    unique files, and a size total of (n-1) x size per group.
    """
    for path in dup_tree.all_files():
        db.store_file_info(db_path, str(path), db.compute_md5(str(path)))

    per_path = dict(db.count_duplicates_per_path(db_path))
    for left, right in dup_tree.duplicated:
        assert str(left) in per_path
        assert str(right) in per_path
    for unique in dup_tree.unique:
        assert str(unique) not in per_path

    # Four groups, not three: `volatile/grows.txt` and `volatile/touched.txt`
    # start out holding the same bytes, so they are a duplicate pair as well.
    expected_groups = len(dup_tree.duplicated) + 1
    groups = db.duplicate_group_sizes(db_path)
    assert len(groups) == expected_groups
    assert all(count == 2 for _size, count in groups)

    left_paths = db.list_paths_with_prefix(db_path, str(dup_tree.left))
    assert len(left_paths) == 4  # unique-left + three duplicated
    assert db.count_paths_with_prefix(db_path, str(dup_tree.left)) == 4

    # Nothing is duplicated *within* left/ alone.
    assert db.find_duplicates_under_prefix(db_path, str(dup_tree.left)) == {}
    # ...but the whole tree holds every pair.
    under_root = db.find_duplicates_under_prefix(db_path, str(dup_tree.root))
    assert len(under_root) == expected_groups
    assert all(len(paths) == 2 for paths in under_root.values())
