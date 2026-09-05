"""#35 -- utils, and the credential guard that had never been exercised.

`report_settings` was added by #2 to satisfy Development-Principles §2 -- a run
must record the configuration that produced it -- and shipped with no test of
its own. Its refusal branch is the case §3 names directly: a guard that has
never failed has not been shown to work. It is the whole reason this ticket is
worth more than its 21 statements.

The guard matters because of where the output goes. `report_settings` prints,
and the CLI's output is redirected into logs, so a credential passed through it
is written to disk in plain text. Refusing at the helper is deliberate: the
alternative is trusting every present and future call site to remember, which
is the same as not having a rule.
"""

from __future__ import annotations

import pytest

from src.md5sum import compute_md5
from src.utils import (
    _CREDENTIAL_NAMES, get_file_mtime_in_ms, get_files_with_md5, report_settings,
)


# -- get_files_with_md5 ----------------------------------------------------


def test_it_maps_every_file_in_the_tree_to_its_checksum(dup_tree):
    result = get_files_with_md5(str(dup_tree.left))

    assert set(result) == {str(p) for p in dup_tree.left.iterdir()}
    for path, md5sum in result.items():
        assert md5sum == compute_md5(path)


def test_duplicated_files_across_two_trees_share_a_checksum(dup_tree):
    """What `compare_directories` relies on -- the values, not the keys."""
    left = get_files_with_md5(str(dup_tree.left))
    right = get_files_with_md5(str(dup_tree.right))

    for left_path, right_path in dup_tree.duplicated:
        assert left[str(left_path)] == right[str(right_path)]
    for unique in dup_tree.unique:
        checksum = {**left, **right}[str(unique)]
        assert list({**left, **right}.values()).count(checksum) == 1


def test_an_empty_directory_maps_to_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert get_files_with_md5(str(empty)) == {}


# -- get_file_mtime_in_ms --------------------------------------------------


def test_mtime_is_milliseconds_as_an_integer(dup_tree):
    """Pinned because changing it invalidates every existing database.

    `process_file`'s skip check compares this value against the stored one, so
    a change of unit or rounding silently forces a full rehash of every
    recorded file -- and only shows up as a scan that suddenly takes hours.
    """
    import os

    target = str(dup_tree.left / "unique-left.txt")
    os.utime(target, (1_700_000_000.5, 1_700_000_000.5))

    value = get_file_mtime_in_ms(target)

    assert isinstance(value, int)
    assert value == 1_700_000_000_500


# -- report_settings: the happy path ---------------------------------------


def test_it_reports_the_name_value_and_origin_of_each_setting():
    emitted: list[str] = []

    report_settings("audit-db", [
        ("db_path", "/tmp/x.db", "set"),
        ("threads", 8, "default"),
    ], emit=emitted.append)

    assert emitted[0] == "audit-db settings:"
    assert "db_path = /tmp/x.db  (set)" in emitted[1]
    assert "threads = 8  (default)" in emitted[2]


def test_names_are_padded_to_a_common_width():
    """So the values line up in a log somebody reads under pressure."""
    emitted: list[str] = []

    report_settings("audit-db", [("a", 1, "set"), ("longer_name", 2, "set")], emit=emitted.append)

    assert emitted[1].index("=") == emitted[2].index("=")


def test_no_settings_reports_the_action_and_nothing_else():
    """`max()` over an empty sequence raises without the default= it carries."""
    emitted: list[str] = []

    report_settings("audit-db", [], emit=emitted.append)

    assert emitted == ["audit-db settings:"]


def test_it_prints_by_default(capsys):
    report_settings("audit-db", [("threads", 4, "default")])

    assert "threads = 4  (default)" in capsys.readouterr().out


# -- report_settings: the guard that had never fired -----------------------


@pytest.mark.parametrize("name", list(_CREDENTIAL_NAMES))
def test_every_listed_credential_word_is_refused(name):
    """Each word in the list, not just one of them.

    A test of `password` alone would pass against a guard that had lost every
    other entry.
    """
    with pytest.raises(ValueError, match="refusing to report setting"):
        report_settings("audit-db", [(name, "hunter2", "set")], emit=lambda _: None)


@pytest.mark.parametrize("name", [
    "API_KEY", "Secret", "db_password", "auth-token-path", "user_credentials",
])
def test_the_match_is_case_insensitive_and_matches_inside_a_longer_name(name):
    with pytest.raises(ValueError, match="refusing to report setting"):
        report_settings("audit-db", [(name, "x", "set")], emit=lambda _: None)


def test_it_refuses_before_emitting_anything():
    """The point of the guard is that the value never reaches the output.

    A guard that raised *after* the first line had already been emitted would
    still leak a credential listed second, so the ordering is the behaviour --
    not an implementation detail.
    """
    emitted: list[str] = []

    with pytest.raises(ValueError):
        report_settings("audit-db", [
            ("db_path", "/tmp/x.db", "set"),
            ("api_token", "s3cret", "set"),
        ], emit=emitted.append)

    assert emitted == [], "output was produced before the credential was rejected"


def test_the_refusal_does_not_quote_the_value():
    """The message names the setting so it can be fixed, and stops there."""
    with pytest.raises(ValueError) as caught:
        report_settings("audit-db", [("api_token", "s3cret-value", "set")],
                        emit=lambda _: None)

    assert "api_token" in str(caught.value)
    assert "s3cret-value" not in str(caught.value)


def test_an_ordinary_name_is_not_refused():
    """The guard has to be provably narrow as well as provably present."""
    emitted: list[str] = []

    report_settings("audit-db", [("dry_run", True, "set")], emit=emitted.append)

    assert "dry_run = True  (set)" in emitted[1]
