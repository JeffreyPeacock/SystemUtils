"""#6 -- --min-duplicates counts copies, and the boundary is exact.

`find_duplicates_with_min_count` compared with `>`, so the flag was off by one
at every value: `--min-duplicates 1` returned groups of two, `3` returned groups
of four. The flag now means "at least this many COPIES of the file", the
comparison is `>=`, and the default moved 1 -> 2 so today's output is unchanged
while every explicit value means what it says.

A two-copy group cannot tell the two readings apart -- `> 1` and `>= 2` agree
there, which is exactly why the bug survived. Every test here uses a group of
THREE so the off-by-one is visible.
"""

from __future__ import annotations

import pytest

from src.db import find_duplicates_with_min_count, store_file_info
from src.md5sum import compute_md5


@pytest.fixture
def three_and_two(db_path, dup_tree):
    """A tree recorded in the database holding one 3-copy group and 2-copy groups.

    Returns (db_path, triplet_md5, pair_md5).
    """
    third = dup_tree.volatile / "shared-one-again.txt"
    left_one, _right_one = dup_tree.duplicated[0]
    third.write_bytes(left_one.read_bytes())

    for path in [*dup_tree.all_files(), third]:
        store_file_info(db_path, str(path), compute_md5(str(path)))

    triplet_md5 = compute_md5(str(left_one))
    pair_md5 = compute_md5(str(dup_tree.duplicated[1][0]))
    assert triplet_md5 != pair_md5
    return db_path, triplet_md5, pair_md5


def test_two_returns_every_group_including_the_pairs(three_and_two):
    db_path, triplet_md5, pair_md5 = three_and_two

    duplicates = find_duplicates_with_min_count(db_path, min_count=2)

    assert len(duplicates[triplet_md5]) == 3
    assert len(duplicates[pair_md5]) == 2


def test_three_keeps_the_triplet_and_drops_the_pairs(three_and_two):
    """The boundary. Under the old `>`, min_count=3 dropped the triplet too."""
    db_path, triplet_md5, pair_md5 = three_and_two

    duplicates = find_duplicates_with_min_count(db_path, min_count=3)

    assert triplet_md5 in duplicates
    assert len(duplicates[triplet_md5]) == 3
    assert pair_md5 not in duplicates


def test_four_returns_nothing(three_and_two):
    db_path, _triplet_md5, _pair_md5 = three_and_two

    assert find_duplicates_with_min_count(db_path, min_count=4) == {}


def test_the_default_is_two_and_reports_the_pairs(three_and_two):
    """The default must not have changed what the tool prints.

    It moved 1 -> 2 alongside the comparison, so the output is identical to
    what the old default produced.
    """
    db_path, triplet_md5, pair_md5 = three_and_two

    assert find_duplicates_with_min_count(db_path) == \
        find_duplicates_with_min_count(db_path, min_count=2)


def test_one_returns_the_unique_files_too(three_and_two, dup_tree):
    """min_count=1 now means "at least one copy", which is every file.

    Not a useful setting, but it is the honest reading of the flag, and pinning
    it stops a future change quietly reverting to the `>` comparison -- under
    which this returned the two-copy groups instead.
    """
    db_path, _triplet_md5, _pair_md5 = three_and_two

    duplicates = find_duplicates_with_min_count(db_path, min_count=1)

    unique_md5s = {compute_md5(str(p)) for p in dup_tree.unique}
    assert unique_md5s <= set(duplicates)
    assert all(len(paths) == 1 for md5, paths in duplicates.items()
               if md5 in unique_md5s)


def test_cli_min_duplicates_reaches_the_query(run_cli, three_and_two):
    """The flag is wired to the same boundary, not just the function default."""
    db_path, _triplet_md5, _pair_md5 = three_and_two

    at_two = run_cli("report-duplicates", "--db-path", db_path,
                     "--min-duplicates", "2")
    at_three = run_cli("report-duplicates", "--db-path", db_path,
                       "--min-duplicates", "3")

    assert at_two.exit_code == 0 and at_three.exit_code == 0
    assert "Found 4 duplicates" in at_two.stdout   # 3 pairs + the triplet
    assert "Found 1 duplicates" in at_three.stdout
