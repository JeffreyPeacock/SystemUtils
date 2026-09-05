"""#4 and #22 -- report_duplicate_sizes, both defects in one function.

#4  the total was halved, which is exact for a pair and wrong above it
#22 SUM over no rows is NULL, and the division came before the guard
"""

import pytest

from src.db import store_file_info
from src.md5sum import compute_md5
from src import db
from src.reporting import report_duplicate_sizes


def _record(db, path):
    store_file_info(db, str(path), compute_md5(str(path)))


def test_empty_database_says_so_instead_of_crashing(db_path, capsys):
    """#22: this used to raise TypeError on None / 2."""
    report_duplicate_sizes(db_path)
    assert "No duplicate files found." in capsys.readouterr().out


def test_a_database_with_no_duplicates_says_so(db_path, dup_tree, capsys):
    """Unique files only -- still nothing reclaimable."""
    for path in dup_tree.unique:
        _record(db_path, path)

    report_duplicate_sizes(db_path)

    assert "No duplicate files found." in capsys.readouterr().out


def test_a_pair_reclaims_one_copy(db_path, dup_tree, capsys):
    left, right = dup_tree.duplicated[0]
    for path in (left, right):
        _record(db_path, path)
    one_copy = left.stat().st_size

    report_duplicate_sizes(db_path)

    out = capsys.readouterr().out
    assert f"{one_copy / 1024 ** 2:.2f} MB" in out


def test_three_copies_reclaim_two_not_one(db_path, tmp_path, capsys):
    """#4: the halving understated this by 25%.

    Three identical copies means two are redundant. The old code summed all
    three and divided by two, reporting 1.5 copies' worth.

    The payload is 512 KB deliberately. The dup_tree fixture's files are a few
    dozen bytes, and at that size both the right answer and the old wrong one
    format as "0.00 MB" -- the test passes either way and proves nothing. A
    test that cannot distinguish the values it is asserting on is not a test.
    """
    payload = b"x" * (512 * 1024)
    copies = []
    for i in range(3):
        path = tmp_path / f"copy-{i}.bin"
        path.write_bytes(payload)
        copies.append(path)
        _record(db_path, path)
    one_copy = len(payload)

    report_duplicate_sizes(db_path)

    out = capsys.readouterr().out
    expected = 2 * one_copy / 1024 ** 2           # 1.00 MB
    halved = (3 * one_copy / 2) / 1024 ** 2       # 0.75 MB, the old answer
    assert f"{expected:.2f} MB" in out, (
        f"three copies should reclaim two, i.e. {expected:.2f} MB; got: {out!r}"
    )
    assert f"{halved:.2f} MB" not in out, "the old halving is still in effect"


def test_two_separate_groups_are_added_together(db_path, dup_tree, capsys):
    (a_left, a_right) = dup_tree.duplicated[0]
    (b_left, b_right) = dup_tree.duplicated[1]
    for path in (a_left, a_right, b_left, b_right):
        _record(db_path, path)
    expected = (a_left.stat().st_size + b_left.stat().st_size) / 1024 ** 2

    report_duplicate_sizes(db_path)

    assert f"{expected:.2f} MB" in capsys.readouterr().out


# -- the GB and TB branches ------------------------------------------------
#
# These cannot be reached with real files: the smallest total that prints in GB
# is a gibibyte of duplicates, and in TB a tebibyte. The function reads only
# `size` and `COUNT(*)` out of the table, so synthetic rows exercise exactly the
# code path a real multi-terabyte library would -- and the alternative is
# leaving the unit-selection arithmetic, which is what a human reads off the
# screen, untested at two of its three settings.


def _fake_group(db_path, md5sum, size, copies):
    """Record `copies` rows sharing one checksum, at a declared size."""
    def work(conn):
        for i in range(copies):
            conn.execute(
                "INSERT INTO files (path, md5sum, size, last_modified) "
                "VALUES (?, ?, ?, ?)",
                (f"/synthetic/{md5sum}/copy-{i}", md5sum, size, 0),
            )
    db.with_connection(db_path, work, commit=True, description="seed a fake group")


def test_a_gibibyte_of_duplicates_reports_in_GB(db_path, capsys):
    _fake_group(db_path, "a" * 32, size=3 * 1024 ** 3, copies=2)

    report_duplicate_sizes(db_path)

    assert "3.00 GB" in capsys.readouterr().out


def test_a_tebibyte_of_duplicates_reports_in_TB(db_path, capsys):
    _fake_group(db_path, "b" * 32, size=2 * 1024 ** 4, copies=3)

    report_duplicate_sizes(db_path)

    # Three copies of 2 TiB reclaims two of them.
    assert "4.00 TB" in capsys.readouterr().out
