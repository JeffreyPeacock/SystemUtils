"""Every run says when it ran, as what, and from which code (#54 req 10).

The requirement exists because output is read from a log days later. Three
things therefore have to hold, and each has its own test here: the timestamp
carries its **zone**, the header is on **stdout** so it survives the
`2>/dev/null` a scheduled scan uses, and it names the **version** so the log can
be tied to the code that produced it.

`help` and `--version` must NOT print it. They are questions about the tool, not
runs of it, and the build script verifies the artifact by grepping `--version`
output -- a header in front of that is a build failure.
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

# The format #54 requirement 10 names: date, clock, then a zone abbreviation.
STARTED = re.compile(
    r"^started +: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [A-Z]{2,5}$", re.M
)


def run_action(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    code = main_module.main()
    return code, capsys.readouterr().out


def test_a_run_prints_a_header_before_its_output(monkeypatch, capsys, tmp_path):
    code, out = run_action(
        monkeypatch, capsys,
        "--db-path", str(tmp_path / "db.db"), "report-duplicate-sizes",
    )
    assert code == 0
    assert out.splitlines()[0] == "FileManager run"


def test_the_timestamp_carries_its_zone(monkeypatch, capsys, tmp_path):
    """A bare clock time has already been read against the wrong zone here."""
    _, out = run_action(
        monkeypatch, capsys,
        "--db-path", str(tmp_path / "db.db"), "report-duplicate-sizes",
    )
    assert STARTED.search(out), out


def test_the_header_names_every_field_the_requirement_asks_for(
    monkeypatch, capsys, tmp_path
):
    db = tmp_path / "db.db"
    _, out = run_action(
        monkeypatch, capsys, "--db-path", str(db), "--threads", "6",
        "report-duplicate-sizes",
    )
    assert "version :" in out
    assert "action  : report-duplicate-sizes" in out
    assert f"db      : {db}" in out
    assert "threads : 6" in out


def test_the_header_is_on_stdout_not_stderr(tmp_path):
    """It has to survive the one redirection every scheduled run uses."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--db-path", str(tmp_path / "db.db"),
         "report-duplicate-sizes"],
        capture_output=True, text=True, timeout=60, cwd=str(PROJECT),
    )
    assert result.returncode == 0, result.stderr
    assert "FileManager run" in result.stdout
    assert "FileManager run" not in result.stderr


def test_the_header_precedes_the_database_being_created(
    monkeypatch, capsys, tmp_path
):
    """Printed before the first side effect, so an interrupted run still said
    what it was going to do."""
    db = tmp_path / "subdir" / "db.db"
    db.parent.mkdir()
    assert not db.exists()
    code, out = run_action(
        monkeypatch, capsys, "--db-path", str(db), "report-duplicate-sizes",
    )
    assert code == 0
    # The header names the path it is about to create, and the row for `db`
    # appears before any report output.
    assert out.index("FileManager run") < out.index("No duplicate files")


def test_a_scan_header_names_the_paths(monkeypatch, capsys, tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("a")
    _, out = run_action(
        monkeypatch, capsys, "--db-path", str(tmp_path / "db.db"),
        "scan", str(tree),
    )
    assert f"paths   : {tree}" in out


def test_an_action_without_a_path_says_so_rather_than_printing_none(
    monkeypatch, capsys, tmp_path
):
    """`paths : None` would read as a path literally named None."""
    _, out = run_action(
        monkeypatch, capsys,
        "--db-path", str(tmp_path / "db.db"), "report-duplicate-sizes",
    )
    assert "paths   : (none given)" in out
    assert "paths   : None" not in out


@pytest.mark.parametrize("form", ["help", "--help", "-h", "-?"])
def test_help_prints_no_header(monkeypatch, capsys, form):
    _, out = run_action(monkeypatch, capsys, form)
    assert "FileManager run" not in out
    assert "Actions:" in out


def test_version_prints_no_header(monkeypatch, capsys):
    """The build greps this output; a header in front of it breaks the build."""
    _, out = run_action(monkeypatch, capsys, "--version")
    assert "FileManager run" not in out
    assert out.startswith("FileManager\n")


def test_a_rejected_command_line_prints_no_header(monkeypatch, capsys):
    """Nothing ran, so there is no run to head."""
    monkeypatch.setattr(sys, "argv", ["main.py", "not-an-action"])
    code = main_module.main()
    assert code == 2
    assert "FileManager run" not in capsys.readouterr().out


def test_a_missing_required_argument_prints_no_header(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "scan"])
    code = main_module.main()
    assert code == 1
    assert "FileManager run" not in capsys.readouterr().out


# --- the version line, in each of its forms -------------------------------

def test_the_version_line_marks_a_source_checkout():
    assert "(source checkout" in version.one_line()


def test_the_version_line_for_a_clean_bundle(monkeypatch):
    monkeypatch.setattr(build_info, "COMMIT", "b" * 40)
    monkeypatch.setattr(build_info, "BUILD_TIME", "2026-11-17 13:00:00 MST")
    monkeypatch.setattr(build_info, "DIRTY", False)
    line = version.one_line()
    assert line.startswith("b" * 40)
    assert "bundle" in line and "clean" in line


def test_the_version_line_for_a_bundle_built_dirty(monkeypatch):
    monkeypatch.setattr(build_info, "COMMIT", "c" * 40)
    monkeypatch.setattr(build_info, "BUILD_TIME", "2026-11-17 13:00:00 MST")
    monkeypatch.setattr(build_info, "DIRTY", True)
    assert "built dirty" in version.one_line()


def test_the_version_line_never_implies_clean_when_unrecorded(monkeypatch):
    monkeypatch.setattr(build_info, "COMMIT", "d" * 40)
    monkeypatch.setattr(build_info, "BUILD_TIME", None)
    monkeypatch.setattr(build_info, "DIRTY", None)
    line = version.one_line()
    assert "cannot determine" in line
    assert "clean" not in line
