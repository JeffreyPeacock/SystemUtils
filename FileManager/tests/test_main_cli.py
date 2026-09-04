"""#13 -- main.py's argument validation and dispatch.

main.py is 17% of the statements in src/ and was 9% covered, so the 95% target
in docs/REQUIREMENTS.txt was arithmetically out of reach. The parts worth
covering are the ones that silently do the wrong thing: the validation branches
that print an error and return, and --db-path resolution.
"""

import os

import pytest


# -- help and usage --------------------------------------------------------


def test_help_action_prints_usage(run_cli):
    result = run_cli("help")
    assert result.exit_code == 0
    assert "File Manager Application" in result
    assert "remove-record" in result


@pytest.mark.xfail(
    reason="#23 -- main() swallows argparse's SystemExit and returns, so the "
           "process exits 0 and no caller can detect a bad invocation",
    strict=True,
)
def test_unknown_action_is_rejected(run_cli):
    result = run_cli("not-an-action")
    assert result.exit_code != 0


# -- the validation branches ----------------------------------------------


@pytest.mark.parametrize("action", ["scan", "check-file", "scan-dir-report",
                                    "remove-record", "get-file-info"])
def test_actions_requiring_a_path_say_so(run_cli, action):
    """Each of these returns early with a message rather than crashing."""
    result = run_cli(action)
    assert "<path> argument is required" in result


def test_report_prefix_count_requires_prefix(run_cli, db_path):
    result = run_cli("report-prefix-count", "--db-path", db_path)
    assert "--prefix argument is required" in result


def test_report_files_for_prefix_requires_prefix(run_cli, db_path):
    result = run_cli("report-files-for-prefix", "--db-path", db_path)
    assert "--prefix argument is required" in result


@pytest.mark.parametrize("extra", [[], ["--dirA", "/tmp"], ["--dirB", "/tmp"]])
def test_compare_directories_requires_both_dirs(run_cli, extra):
    result = run_cli("compare-directories", *extra)
    assert "--dirA and --dirB arguments are required" in result


# -- --db-path resolution --------------------------------------------------


@pytest.mark.xfail(
    reason="#22 -- report-duplicate-sizes divides None by 2 on a database with "
           "no duplicates, so this reaches the action and raises TypeError",
    raises=TypeError,
    strict=True,
)
def test_db_path_defaults_into_the_current_directory(run_cli, tmp_path):
    """Omitted --db-path means ./file_manager.db.

    The autouse fixture runs each test from a scratch cwd, so this proves the
    default without writing into the repository.
    """
    run_cli("report-duplicate-sizes")
    assert os.path.exists("file_manager.db")


@pytest.mark.xfail(
    reason="#22 -- report-duplicate-sizes divides None by 2 on a database with "
           "no duplicates, so this reaches the action and raises TypeError",
    raises=TypeError,
    strict=True,
)
def test_db_path_naming_a_directory_gets_the_filename_appended(run_cli, tmp_path):
    target = tmp_path / "dbdir"
    target.mkdir()
    run_cli("report-duplicate-sizes", "--db-path", str(target))
    assert (target / "file_manager.db").exists(), (
        "a --db-path naming an existing directory should gain file_manager.db"
    )


@pytest.mark.xfail(
    reason="#22 -- report-duplicate-sizes divides None by 2 on a database with "
           "no duplicates, so this reaches the action and raises TypeError",
    raises=TypeError,
    strict=True,
)
def test_db_path_naming_a_file_is_used_as_given(run_cli, tmp_path):
    target = tmp_path / "explicit.db"
    run_cli("report-duplicate-sizes", "--db-path", str(target))
    assert target.exists()


# -- dispatch reaches the real actions -------------------------------------


@pytest.mark.xfail(
    reason="#21 -- get_file_info_action reads file_info[2] but get_file_info "
           "selects only two columns, so the action always raises IndexError",
    raises=IndexError,
    strict=True,
)
def test_get_file_info_reports_a_recorded_file(run_cli, db_path, dup_tree):
    from src.db import store_file_info
    from src.md5sum import compute_md5

    path = dup_tree.left / "unique-left.txt"
    store_file_info(db_path, str(path), compute_md5(str(path)))

    result = run_cli("get-file-info", str(path), "--db-path", db_path)

    assert str(path) in result
    assert compute_md5(str(path)) in result


def test_get_file_info_on_an_unknown_path_says_so(run_cli, db_path):
    result = run_cli("get-file-info", "/nowhere/at/all", "--db-path", db_path)
    assert "No information found" in result


def test_scan_then_report_duplicates_finds_the_pair(run_cli, db_path, dup_tree):
    left, right = dup_tree.duplicated[0]
    run_cli("scan", f"{left},{right}", "--db-path", db_path)

    result = run_cli("report-duplicates", "--db-path", db_path)

    assert str(left) in result
    assert str(right) in result


def test_remove_record_dispatch_is_literal_by_default(run_cli, db_path, dup_tree):
    """#1's fix, reached through the CLI rather than the function."""
    from src.db import get_all_files_info, store_file_info
    from src.md5sum import compute_md5

    target = dup_tree.left / "unique-left.txt"
    sibling = dup_tree.left / "unique-left.txt.bak"
    sibling.write_bytes(b"a sibling whose path starts with the target's\n")
    for path in (target, sibling):
        store_file_info(db_path, str(path), compute_md5(str(path)))

    run_cli("remove-record", str(target), "--db-path", db_path)

    remaining = {row[0] for row in get_all_files_info(db_path)}
    assert remaining == {str(sibling)}


def test_remove_record_regex_flag_takes_a_pattern(run_cli, db_path, dup_tree):
    import re
    from src.db import get_all_files_info, store_file_info
    from src.md5sum import compute_md5

    for path in (dup_tree.left / "unique-left.txt", dup_tree.right / "unique-right.txt"):
        store_file_info(db_path, str(path), compute_md5(str(path)))

    run_cli("remove-record", re.escape(str(dup_tree.left)) + "/.*",
            "--regex", "--db-path", db_path)

    remaining = {row[0] for row in get_all_files_info(db_path)}
    assert remaining == {str(dup_tree.right / "unique-right.txt")}
