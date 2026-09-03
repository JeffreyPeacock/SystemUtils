"""#2 -- audit-db must not treat an unmounted volume as a mass deletion.

`audit_db` removes the row for any recorded path that no longer exists. A
volume that fails to mount makes every path beneath it look deleted, so one
pass empties the whole subtree. These tests pin the two halves of the fix:
a dry run changes nothing, and a missing *directory* is not a missing *file*.
"""

import os

import pytest

from src.db import audit_db, get_all_files_info, looks_like_a_missing_volume, store_file_info
from src.md5sum import compute_md5


def _noop_process_file(file_path, db_path):
    pass


def _record_tree(db_path, tree):
    for path in tree.all_files():
        store_file_info(db_path, str(path), compute_md5(str(path)))


def _paths(db_path):
    return {row[0] for row in get_all_files_info(db_path)}


def test_a_deleted_file_is_removed(db_path, dup_tree):
    """The normal case must keep working: file gone, parent intact -> row goes."""
    _record_tree(db_path, dup_tree)
    victim = dup_tree.left / "unique-left.txt"
    victim.unlink()

    counts = audit_db(db_path, 2, _noop_process_file)

    assert counts['removed'] == 1
    assert counts['suspect'] == 0
    assert str(victim) not in _paths(db_path)


def test_a_missing_directory_is_suspect_not_deleted(db_path, dup_tree):
    """The #2 case: the whole directory is gone, so the rows are kept."""
    _record_tree(db_path, dup_tree)
    before = _paths(db_path)
    # Simulate the volume failing to mount: the tree is simply not there.
    for path in sorted(dup_tree.left.iterdir()):
        path.unlink()
    dup_tree.left.rmdir()

    counts = audit_db(db_path, 2, _noop_process_file)

    assert counts['removed'] == 0
    assert counts['suspect'] == 4  # three duplicated + one unique, all under left/
    assert _paths(db_path) == before, "no row may be removed when the directory is gone"


def test_prune_missing_dirs_opts_back_in(db_path, dup_tree):
    """The escape hatch, for a directory that really was deleted."""
    _record_tree(db_path, dup_tree)
    for path in sorted(dup_tree.left.iterdir()):
        path.unlink()
    dup_tree.left.rmdir()

    counts = audit_db(db_path, 2, _noop_process_file, prune_missing_dirs=True)

    assert counts['suspect'] == 0
    assert counts['removed'] == 4
    assert not any(p.startswith(str(dup_tree.left) + os.sep) for p in _paths(db_path))


def test_dry_run_changes_nothing(db_path, dup_tree):
    _record_tree(db_path, dup_tree)
    before = _paths(db_path)
    victim = dup_tree.left / "unique-left.txt"
    victim.unlink()

    counts = audit_db(db_path, 2, _noop_process_file, dry_run=True)

    assert counts['removed'] == 1, "it must still REPORT the row it would remove"
    assert _paths(db_path) == before, "a dry run must not delete anything"


def test_dry_run_does_not_reprocess(db_path, dup_tree):
    """A changed file is reported, not rehashed."""
    _record_tree(db_path, dup_tree)
    dup_tree.grow()
    calls = []

    counts = audit_db(db_path, 2, lambda p, d: calls.append(p), dry_run=True)

    assert counts['reprocessed'] == 1
    assert calls == [], "dry run must not call process_file"


def test_exclude_prefix_still_skips(db_path, dup_tree):
    _record_tree(db_path, dup_tree)
    for path in sorted(dup_tree.left.iterdir()):
        path.unlink()
    dup_tree.left.rmdir()

    counts = audit_db(db_path, 2, _noop_process_file,
                      exclude_prefix=[str(dup_tree.left)])

    assert counts['skipped'] == 4
    assert counts['suspect'] == 0


@pytest.mark.parametrize("scenario", ["file gone, dir intact", "dir gone too"])
def test_looks_like_a_missing_volume_distinguishes_the_two(dup_tree, scenario):
    victim = dup_tree.left / "unique-left.txt"
    victim.unlink()
    if scenario == "dir gone too":
        for path in sorted(dup_tree.left.iterdir()):
            path.unlink()
        dup_tree.left.rmdir()
        assert looks_like_a_missing_volume(str(victim)) is True
    else:
        assert looks_like_a_missing_volume(str(victim)) is False
