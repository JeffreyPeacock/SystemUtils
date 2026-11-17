"""What --version says, in a bundle and in a checkout (#62, #54 requirement 9).

The thing being protected is not the wording, it is the refusal to guess. A
bundle must name the commit embedded in it; a source checkout must say it is a
source checkout; and a git question that cannot be answered must print
CANNOT DETERMINE rather than a placeholder a reader would believe.

Both forms of test appear here deliberately. In-process calls to `main()`
provide the coverage and can read the printed text; the subprocess calls prove
the exit status, which an in-process return value cannot (the suite would pass
on a `main()` that returned 0 while `sys.exit` reported otherwise). Neither
alone is enough -- the same pairing as tests/test_help_flags.py.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from src import build_info, main as main_module, version

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "src" / "main.py"

FULL_HASH = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture
def as_a_bundle(monkeypatch):
    """Pretend this process is a stamped archive."""
    monkeypatch.setattr(build_info, "COMMIT", "a" * 40)
    monkeypatch.setattr(build_info, "BUILD_TIME", "2026-11-17 13:00:00 MST")
    monkeypatch.setattr(build_info, "DIRTY", False)


def field(lines: list[str], label: str) -> str:
    """The value of one labelled line, by the label the consumer greps for."""
    for line in lines:
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no {label!r} line in {lines!r}")


# --- the committed module is the unbuilt answer ----------------------------

def test_the_committed_build_info_claims_nothing():
    """COMMIT is None in the checkout, and that None is load-bearing."""
    assert build_info.COMMIT is None
    assert build_info.BUILD_TIME is None
    assert build_info.DIRTY is None


def test_a_source_checkout_says_it_is_not_a_build():
    lines = version.describe()
    assert lines[0] == "FileManager"
    assert "source checkout" in field(lines, "built")


def test_a_source_checkout_reads_its_commit_from_git():
    """This repository is a git checkout, so the live read must succeed."""
    assert FULL_HASH.match(field(version.describe(), "commit"))


# --- a bundle reports what was embedded ------------------------------------

def test_a_bundle_reports_the_embedded_commit(as_a_bundle):
    lines = version.describe()
    assert field(lines, "commit") == "a" * 40
    assert field(lines, "built") == "2026-11-17 13:00:00 MST"
    assert field(lines, "tree") == "clean"
    assert field(lines, "source") == "zipapp bundle"


def test_a_bundle_built_dirty_keeps_saying_so(as_a_bundle, monkeypatch):
    monkeypatch.setattr(build_info, "DIRTY", True)
    assert field(version.describe(), "tree") == "dirty at build time"


def test_a_bundle_with_no_recorded_tree_state_does_not_claim_clean(
    as_a_bundle, monkeypatch
):
    """The field exists but was never set: that is not a clean tree."""
    monkeypatch.setattr(build_info, "DIRTY", None)
    tree = field(version.describe(), "tree")
    assert version.UNKNOWN in tree
    assert tree != "clean"


def test_a_bundle_with_no_recorded_build_time_says_so(as_a_bundle, monkeypatch):
    monkeypatch.setattr(build_info, "BUILD_TIME", None)
    assert version.UNKNOWN in field(version.describe(), "built")


# --- git that cannot answer ------------------------------------------------

def test_git_that_cannot_run_is_not_a_clean_tree(monkeypatch):
    """The whole point. An OSError must not read as "nothing changed"."""
    def explode(*args, **kwargs):
        raise OSError("git is not here")
    monkeypatch.setattr(version.subprocess, "run", explode)

    lines = version.describe()
    assert version.UNKNOWN in field(lines, "commit")
    assert version.UNKNOWN in field(lines, "tree")
    assert field(lines, "tree") != "clean"


def test_a_git_subprocess_error_is_also_unknown(monkeypatch):
    def explode(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=10)
    monkeypatch.setattr(version.subprocess, "run", explode)
    assert version.UNKNOWN in version.live_commit(PROJECT)


def test_a_nonzero_git_exit_is_unknown(monkeypatch):
    """Not a repository: git prints to stderr and exits non-zero."""
    monkeypatch.setattr(
        version.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "fatal: no"),
    )
    assert version.UNKNOWN in version.live_commit(PROJECT)
    assert version.UNKNOWN in version.live_tree_state(PROJECT)


def test_an_empty_porcelain_is_clean_and_a_populated_one_is_dirty(monkeypatch):
    """Emptiness means clean ONLY once the call is known to have succeeded."""
    monkeypatch.setattr(
        version.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    assert version.live_tree_state(PROJECT) == "clean"

    monkeypatch.setattr(
        version.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, " M src/db.py\n", ""),
    )
    assert version.live_tree_state(PROJECT) == "dirty"


def test_describe_accepts_an_explicit_root(tmp_path):
    """Needed by the tests above and by anything verifying another checkout."""
    lines = version.describe(tmp_path)
    assert field(lines, "source") == str(tmp_path)
    assert version.UNKNOWN in field(lines, "commit")


# --- the CLI arm -----------------------------------------------------------

def test_version_returns_zero_in_process(monkeypatch, capsys):
    """In-process, so this line of main() is measured."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--version"])
    assert main_module.main() == 0
    assert "FileManager" in capsys.readouterr().out


def test_version_needs_no_action(monkeypatch, capsys):
    """`action` is a required positional; --version must still work alone.

    This is why the flag is matched against sys.argv before parse_args, the
    same reason as the help flags (#58).
    """
    monkeypatch.setattr(sys, "argv", ["main.py", "--version"])
    assert main_module.main() == 0
    assert "commit" in capsys.readouterr().out


def test_version_wins_over_an_otherwise_invalid_command_line(
    monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["main.py", "--version", "--threads", "4"])
    assert main_module.main() == 0
    assert "FileManager" in capsys.readouterr().out


def test_help_wins_when_both_are_given(monkeypatch, capsys):
    """Documented precedence: someone asking both wants the usage text."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--help", "--version"])
    assert main_module.main() == 0
    assert "Actions:" in capsys.readouterr().out


def test_version_exits_zero_as_a_process():
    """The status itself, which an in-process return cannot establish."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--version"],
        capture_output=True, text=True, timeout=60, cwd=str(PROJECT),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("FileManager")
    assert result.stderr == ""


def test_the_commit_line_is_greppable_as_the_installer_greps_it():
    """The consumer reads `--version | grep '^commit'`. Keep that shape."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--version"],
        capture_output=True, text=True, timeout=60, cwd=str(PROJECT),
    )
    commit_lines = [l for l in result.stdout.splitlines()
                    if l.startswith("commit")]
    assert len(commit_lines) == 1, result.stdout
    assert re.match(r"^commit +: +[0-9a-f]{40}$", commit_lines[0])
