"""What `audit_db` returns matches what `AuditCounts` declares (#60).

mypy is the real gate here, and as of #60 it is one: `src.db` left the
`check_untyped_defs` opt-out list, so a wrong value type or an undeclared key in
that dict is now reported. Two mutations were used to confirm that -- assigning
a str to `failed` and adding a key that does not exist -- and both were silent
under the previous configuration.

This module covers the one way the two could still drift apart: a `type: ignore`
on the offending line. That is a deliberate act rather than an oversight, so it
deserves a second check that does not depend on the type checker running at all,
and this one compares the declared fields against the keys a real audit actually
returns.
"""

from __future__ import annotations

import pytest

from src.db import AuditCounts, audit_db, initialize_db, store_file_info
from src.file_ops import process_file
from src.md5sum import compute_md5


@pytest.fixture
def audited(tmp_path):
    """Run a real audit over one recorded file and return its counts."""
    db_path = str(tmp_path / "audit.db")
    initialize_db(db_path)

    target = tmp_path / "recorded.txt"
    target.write_text("content")
    store_file_info(db_path, str(target), compute_md5(str(target)))

    return audit_db(db_path, 2, process_file)


def test_the_declared_fields_are_exactly_the_keys_returned(audited):
    """Neither side may grow a field the other does not know about."""
    declared = set(AuditCounts.__annotations__)
    returned = set(audited)
    assert returned == declared, (
        f"only declared: {sorted(declared - returned)}; "
        f"only returned: {sorted(returned - declared)}"
    )


def test_every_counter_is_an_int_and_failures_is_a_list(audited):
    """The heterogeneity that made `dict[str, int]` wrong in the first place."""
    for field in ("checked", "removed", "reprocessed", "skipped", "suspect",
                  "not_regular", "failed"):
        assert isinstance(audited[field], int), field
    assert isinstance(audited["failures"], list)


def test_failures_is_present_even_when_nothing_failed(audited):
    """It is in the initial literal, not bolted on at the end.

    A total TypedDict is only honest if the dict really is complete from the
    start; `failures` being absent on the happy path would mean every caller
    had to use .get() and the type would be lying.
    """
    assert audited["failed"] == 0
    assert audited["failures"] == []


def test_the_type_is_not_a_plain_dict_annotation():
    """Guards against a revert to dict[str, Any], which #61 put in as a patch."""
    assert hasattr(AuditCounts, "__annotations__")
    assert AuditCounts.__total__ is True
    assert "Any" not in str(AuditCounts.__annotations__.values())
