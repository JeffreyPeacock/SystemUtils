"""#58 -- asking for help is not an error.

`--help`, `-h` and `-?` each exited **2** and printed an argparse error
alongside the usage text. The positional `help` action exited 0. That is
backwards from every other command-line tool, and it fails any install check or
`set -e` script that assumes the convention -- which is the first thing anyone
writes.

Two causes, both present since the initial import, and fixing either alone is
not enough:

  1. `add_help=False` removed `-h`/`--help` from the parser, so they arrived as
     unrecognised arguments
  2. the `except SystemExit` around `parse_args` returned 2 for **every** exit
     code, including 0 -- so restoring `add_help=True` by itself would still
     have exited 2

The second is the one worth keeping a test on. It is the same shape as #23,
where every branch `return`ed and therefore exited 0 whatever had happened: a
handler that discards the outcome it was handed. It also matters ahead of the
`--version` action in #54, which will raise `SystemExit(0)` through exactly this
path.

Everything here runs the CLI as a **subprocess**. An in-process `main()` call
reads a returned value, which cannot distinguish a code that reached the
operating system from one that did not -- the gap #57 documents.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]

HELP_FORMS = ["help", "--help", "-h", "-?"]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "src/main.py", *args],
        cwd=PROJECT, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.parametrize("form", HELP_FORMS)
def test_every_help_form_exits_zero(form):
    result = _run(form)

    assert result.returncode == 0, (
        f"`{form}` exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("form", HELP_FORMS)
def test_every_help_form_prints_the_projects_own_usage_text(form):
    """Not argparse's generated help. `usage()` documents the actions, the
    options, the exit codes and worked examples; the generated one has none of
    that, which is why the flags are intercepted rather than registered."""
    result = _run(form)

    assert "File Manager Application" in result.stdout
    assert "Exit codes:" in result.stdout, "the exit-code table is part of the help"
    assert "scan-unique-files" in result.stdout, "the action list is part of the help"


@pytest.mark.parametrize("form", HELP_FORMS)
def test_no_help_form_writes_an_error(form):
    """`--help` used to print the usage text to stdout *and* an argparse error
    to stderr. Exiting 0 while still complaining is only half a fix."""
    result = _run(form)

    assert "error:" not in result.stderr, f"`{form}` still complains: {result.stderr}"
    assert result.stderr == "", f"`{form}` wrote to stderr: {result.stderr!r}"


def test_help_works_with_no_action_given():
    """`action` is a required positional, so a flag-only command line would trip
    the missing-argument check before argparse ever looked at the flag. That is
    why the check runs before `parse_args`."""
    result = _run("--help")

    assert result.returncode == 0
    assert "required" not in result.stderr


def test_a_help_flag_beats_an_action_on_the_same_line():
    """`scan --help` asks for help, as it does everywhere else. It must not
    start scanning, and `scan` with no path would otherwise exit 1."""
    result = _run("scan", "--help")

    assert result.returncode == 0
    assert "File Manager Application" in result.stdout


# -- the codes that must NOT have moved ------------------------------------


def test_an_unknown_action_still_exits_two():
    result = _run("no-such-action")

    assert result.returncode == 2, "an argparse rejection is 2 (#23)"


def test_a_missing_required_argument_still_exits_one():
    result = _run("scan")

    assert result.returncode == 1, "a missing or invalid argument is 1 (#23)"


def test_an_incomplete_scan_still_exits_three(tmp_path):
    """The #57 code, re-asserted here because this change rewrote the exit path
    those three codes all travel through."""
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "ok.txt").write_text("ok\n", encoding="utf-8")
    denied = tree / "denied.txt"
    denied.write_text("no\n", encoding="utf-8")
    denied.chmod(0o000)
    try:
        result = _run("--db-path", str(tmp_path / "x.db"), "scan", str(tree))
    finally:
        denied.chmod(0o644)

    assert result.returncode == 3


# -- the handler that discarded the code ------------------------------------


def test_a_zero_exit_from_the_parser_is_not_reported_as_a_rejection(monkeypatch, capsys):
    """The forward-looking half, and the cause that a subprocess cannot reach
    today: with `add_help=False` nothing inside `parse_args` currently exits 0.

    `--version` in #54 will, and the old handler would have turned it into 2.
    Simulating the exit is the only way to pin the handler before that lands --
    and a handler that flattens every outcome to one code is the defect itself,
    not the specific flag that revealed it.
    """
    import argparse

    from src import main as main_module

    def exits_zero(self):
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", exits_zero)
    monkeypatch.setattr(sys, "argv", ["main.py", "report-duplicates"])

    assert main_module.main() == 0, (
        "a parser that exited 0 was reported as an argparse rejection (2)"
    )


def test_a_nonzero_exit_from_the_parser_is_still_a_rejection(monkeypatch, capsys):
    import argparse

    from src import main as main_module

    def exits_two(self):
        raise SystemExit(2)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", exits_two)
    monkeypatch.setattr(sys, "argv", ["main.py", "report-duplicates"])

    assert main_module.main() == 2


def test_a_parser_exit_carrying_a_message_is_still_a_rejection(monkeypatch, capsys):
    """`SystemExit` can carry a string or None rather than a code.

    This records behaviour; it is **not** a gate. A type check was tried in the
    handler and removed because this test passes with or without it: in Python
    a string never equals 0, so a message-carrying exit reaches the rejection
    path either way. Kept because the behaviour is worth stating -- a reader
    should not have to work out what `exc.code == 0` does with a string -- but
    it is not evidence that any guard is load-bearing
    (docs/Development-Principles.md section 3a).
    """
    import argparse

    from src import main as main_module

    def exits_with_text(self):
        raise SystemExit("something went wrong")

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", exits_with_text)
    monkeypatch.setattr(sys, "argv", ["main.py", "report-duplicates"])

    assert main_module.main() == 2


# -- in process, for the coverage a subprocess cannot provide ---------------
#
# The subprocess tests above are the ones that prove the exit status reaches the
# operating system, which is the whole point. A subprocess runs outside coverage
# measurement though, so these call the same branch in process. Both forms are
# needed, for the reason #57's test module sets out.


@pytest.mark.parametrize("form", ["--help", "-h", "-?"])
def test_the_help_branch_returns_zero_in_process(form, monkeypatch, capsys):
    from src import main as main_module

    monkeypatch.setattr(sys, "argv", ["main.py", form])

    assert main_module.main() == 0
    assert "File Manager Application" in capsys.readouterr().out


def test_a_help_flag_after_an_action_is_still_intercepted(monkeypatch, capsys):
    """The flag is looked for anywhere in argv, not only in first position."""
    from src import main as main_module

    monkeypatch.setattr(sys, "argv", ["main.py", "scan", "/some/path", "--help"])

    assert main_module.main() == 0
    assert "File Manager Application" in capsys.readouterr().out
