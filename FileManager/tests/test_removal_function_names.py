"""#7 -- one name, one behaviour, for record removal.

`src/db.py` and `src/file_ops.py` each defined a function called
`remove_record`. db.py's deleted one exact path; file_ops.py's took a REGEX and
deleted every matching row. main.py imported the file_ops one, so the CLI
action was regex-based while the usage text described exact-path removal, and a
reader grepping the name found the wrong definition about half the time.

Both behaviours are real and both are still used -- audit_db calls the
exact-path one internally -- so the fix is distinct names, not a deletion:

    db.remove_record_by_path      one exact path, returns 0 or 1
    db.remove_records_by_regex    re.fullmatch against the whole path

The two printing wrappers in file_ops.py are gone with the ambiguity; main.py
prints the count, which is what the tests at the bottom of this file pin.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src import db, file_ops
from src.db import get_all_files_info, store_file_info
from src.md5sum import compute_md5

SRC = Path(__file__).resolve().parent.parent / "src"


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_the_detector_can_fire():
    """A module that DOES define `remove_record` is reported.

    Otherwise an empty result below proves nothing: a broken walker and a clean
    tree look the same.
    """
    probe = Path(__file__).parent / "_probe_remove_record.py"
    probe.write_text("def remove_record(a, b):\n    return 0\n", encoding="utf-8")
    try:
        assert "remove_record" in _function_names(probe)
    finally:
        probe.unlink()


def test_no_module_defines_the_ambiguous_name():
    offenders = {path.name for path in sorted(SRC.rglob("*.py"))
                 if "remove_record" in _function_names(path)}
    assert offenders == set(), (
        f"{sorted(offenders)} still define a bare `remove_record`; the two "
        f"behaviours must be named apart"
    )


def test_the_two_behaviours_live_in_db_under_distinct_names():
    assert callable(db.remove_record_by_path)
    assert callable(db.remove_records_by_regex)
    # file_ops no longer re-exports either under a different name.
    assert not hasattr(file_ops, "remove_record")
    assert not hasattr(file_ops, "remove_record_by_path")


def test_remove_record_by_path_is_literal(db_path, dup_tree):
    """The name now says it: an exact path, and a sibling sharing its prefix
    survives."""
    target = dup_tree.left / "unique-left.txt"
    sibling = dup_tree.left / "unique-left.txt.bak"
    sibling.write_bytes(b"a sibling whose path starts with the target's\n")
    for path in (target, sibling):
        store_file_info(db_path, str(path), compute_md5(str(path)))

    assert db.remove_record_by_path(db_path, str(target)) == 1

    assert {row[0] for row in get_all_files_info(db_path)} == {str(sibling)}


def test_remove_records_by_regex_needs_a_whole_path_match(db_path, dup_tree):
    left = dup_tree.left / "unique-left.txt"
    right = dup_tree.right / "unique-right.txt"
    for path in (left, right):
        store_file_info(db_path, str(path), compute_md5(str(path)))

    # A prefix alone matches nothing -- re.fullmatch, not re.match (#1).
    assert db.remove_records_by_regex(db_path, re.escape(str(dup_tree.left))) == 0
    assert db.remove_records_by_regex(
        db_path, re.escape(str(dup_tree.left)) + "/.*") == 1

    assert {row[0] for row in get_all_files_info(db_path)} == {str(right)}


@pytest.mark.parametrize("regex", [False, True])
def test_the_cli_still_reports_what_it_removed(run_cli, db_path, dup_tree, regex):
    """The count used to be printed by the file_ops wrappers. They are gone, so
    this pins that main.py prints it instead rather than removing rows in
    silence."""
    target = dup_tree.left / "unique-left.txt"
    store_file_info(db_path, str(target), compute_md5(str(target)))

    if regex:
        result = run_cli("remove-record", re.escape(str(target)),
                         "--regex", "--db-path", db_path)
        assert "1 record" in result.stdout
    else:
        result = run_cli("remove-record", str(target), "--db-path", db_path)
        assert "Removed the record" in result.stdout

    assert result.exit_code == 0
    assert get_all_files_info(db_path) == []


def test_the_cli_says_so_when_nothing_matched(run_cli, db_path, dup_tree):
    result = run_cli("remove-record", str(dup_tree.left / "never-recorded.txt"),
                     "--db-path", db_path)

    assert result.exit_code == 0
    assert "Nothing removed" in result.stdout


def test_the_usage_text_describes_the_wired_behaviour(run_cli):
    """The ticket's second half: help said exact-path while the CLI ran regex."""
    result = run_cli("help")

    assert "remove-record" in result.stdout
    assert "Remove the record for exactly the specified path." in result.stdout
    assert "--regex" in result.stdout
    assert "WHOLE path" in result.stdout
