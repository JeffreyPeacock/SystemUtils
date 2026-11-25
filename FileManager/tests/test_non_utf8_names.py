"""#82 -- a file name that is not valid UTF-8 must not crash the output, and
must be reported in a form the operator can use to rename it.

Python decodes such a name with `surrogateescape`, so the byte 0x82 becomes
U+DC82. In a UTF-8 locale stdout encodes in strict mode, and a /home2 baseline
scan crashed in `_print_scan_summary` after three days, exiting 1 instead of 3.

The subprocess tests set `LC_ALL=C.UTF-8`, because the crash depends on the
locale: in the C locale Python writes stdout with `surrogateescape` and the
old code survived. A test run in the C locale would pass with the bug present.

The file names are bytes throughout: `os.fsdecode` of the bytes is what
`os.walk` hands the scanner.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.file_ops import ScanTally, VerifyTally
from src.utils import display_path, is_valid_utf8, name_to_rename, shell_quoted

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "src" / "main.py"

EXIT_INCOMPLETE = 3
BAD = b"caf\x82.txt"
BASH = shutil.which("bash")


def _bad_file(directory: Path, name: bytes = BAD, data: bytes = b"x") -> bytes:
    path = os.path.join(os.fsencode(directory), name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _run(*args, locale="C.UTF-8"):
    """Run main.py with only the locale set, as a service runs it."""
    env = {"PATH": os.environ["PATH"], "LC_ALL": locale}
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        capture_output=True, timeout=60, cwd=str(PROJECT), env=env,
    )


# --- the helpers -------------------------------------------------------------

def test_a_valid_name_is_printed_unchanged():
    assert display_path("/home2/café.txt") == "/home2/café.txt"
    assert is_valid_utf8("/home2/café.txt")


def test_a_row_with_no_path_prints_as_none():
    """#68 reads NULL-path rows; their failures reach the verify summary."""
    assert display_path(None) == "None"


def test_the_shell_form_holds_the_exact_bytes():
    path = os.fsdecode(b"/home2/" + BAD)
    assert not is_valid_utf8(path)
    assert shell_quoted(path) == "$'/home2/caf\\x82.txt'"
    assert display_path(path) == shell_quoted(path)


def test_quotes_backslashes_and_multibyte_characters_are_escaped():
    path = os.fsdecode("/a b/it's\\é".encode() + b"\x82")
    assert shell_quoted(path) == (
        "$'/a b/it\\x27s\\x5c\\xc3\\xa9\\x82'"
    )


@pytest.mark.skipif(BASH is None, reason="needs bash")
@pytest.mark.parametrize("raw", [
    b"caf\x82.txt",
    b"it's \\ \x82 \xff\xfe",
    "é".encode() + b"\x80",
    b"x\x82a",            # a hex digit right after the escape
])
def test_bash_reads_the_shell_form_back_as_the_same_bytes(raw):
    quoted = shell_quoted(os.fsdecode(raw))
    out = subprocess.run([BASH, "-c", f"printf %s {quoted}"],
                         capture_output=True, check=True).stdout
    assert out == raw


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_mv_renames_the_file_from_the_printed_form(tmp_path):
    """The owner's requirement, end to end: the printed form works in mv."""
    bad = _bad_file(tmp_path)
    quoted = shell_quoted(os.fsdecode(bad))
    subprocess.run([BASH, "-c", f"mv {quoted} cafe.txt"],
                   cwd=tmp_path, check=True)
    assert not os.path.exists(bad)
    assert (tmp_path / "cafe.txt").read_bytes() == b"x"


def test_the_name_to_rename_is_the_first_bad_component():
    d = os.fsdecode(b"/home2/dir\x82")
    assert name_to_rename(d + "/a/b.txt") == d
    assert name_to_rename("/home2/ok/" + os.fsdecode(BAD)) == (
        "/home2/ok/" + os.fsdecode(BAD))


# --- the summaries -------------------------------------------------------------

def test_bad_names_get_their_own_list_apart_from_read_failures():
    tally = ScanTally()
    bad_dir = os.fsdecode(b"/t/dir\x82")
    for name in ("a", "b", "c"):
        tally.record_failure(f"{bad_dir}/{name}", "encode error")
    tally.record_failure(os.fsdecode(b"/t/" + BAD), "encode error")
    tally.record_failure("/t/locked", "[Errno 13] Permission denied")

    lines = tally.summary_lines()

    assert lines[0].endswith("5 failed")
    assert ("names not valid UTF-8 (2), so 4 file(s) were not recorded; "
            "rename these to record them:") in lines
    assert "  $'/t/dir\\x82'  (3 files)" in lines
    assert "  $'/t/caf\\x82.txt'" in lines
    assert "other failures (1):" in lines
    assert "  /t/locked: [Errno 13] Permission denied" in lines
    for line in lines:
        line.encode("utf-8")


def test_without_bad_names_the_failed_list_is_unchanged():
    tally = ScanTally()
    tally.record_failure("/t/locked", "denied")
    assert tally.summary_lines()[1:] == ["failed (1):", "  /t/locked: denied"]


def test_the_verify_summary_prints_bad_names_in_shell_form():
    tally = VerifyTally()
    path = os.fsdecode(b"/t/" + BAD)
    tally.record_unreadable(path, "gone")
    tally.record_mismatch(path, "a" * 32, "b" * 32)
    lines = tally.summary_lines()
    assert lines.count("  $'/t/caf\\x82.txt'") == 1
    assert "  $'/t/caf\\x82.txt': gone" in lines
    for line in lines:
        line.encode("utf-8")


def test_the_audit_summary_prints_bad_names_in_shell_form(capsys):
    from src.main import _print_audit_summary
    counts = dict(checked=1, removed=0, reprocessed=0, skipped=0, suspect=0,
                  not_regular=0, failed=1,
                  failures=[(os.fsdecode(b"/t/" + BAD), "denied")])
    _print_audit_summary(counts)  # type: ignore[arg-type]
    assert "  $'/t/caf\\x82.txt': denied" in capsys.readouterr().out


# --- whole runs, in a UTF-8 locale -----------------------------------------------

def test_a_scan_with_a_bad_name_exits_3_and_names_it(tmp_path):
    """The /home2 crash, reproduced and fixed. It exited 1 with a traceback."""
    tree = tmp_path / "tree"
    tree.mkdir()
    _bad_file(tree)
    (tree / "ok.txt").write_text("ok")

    result = _run("--db-path", str(tmp_path / "x.db"), "scan", str(tree))

    out = result.stdout.decode("utf-8")  # strict: stdout is valid UTF-8
    assert result.returncode == EXIT_INCOMPLETE, out + result.stderr.decode()
    assert b"Traceback" not in result.stderr
    assert f"  $'{tree}/caf\\x82.txt'" in out
    assert "1 hashed, 0 skipped unchanged, 1 failed" in out


def test_the_same_scan_in_the_c_locale_gives_the_same_answer(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    _bad_file(tree)

    result = _run("--db-path", str(tmp_path / "x.db"), "scan", str(tree),
                  locale="C")

    assert result.returncode == EXIT_INCOMPLETE
    assert f"  $'{tree}/caf\\x82.txt'".encode() in result.stdout


def test_a_bad_path_on_the_command_line_survives_the_header(tmp_path):
    bad = _bad_file(tmp_path)

    result = _run("--db-path", str(tmp_path / "x.db"), "scan", bad)

    out = result.stdout.decode("utf-8")
    assert b"Traceback" not in result.stderr
    assert f"paths   : $'{tmp_path}/caf\\x82.txt'" in out
    assert result.returncode == EXIT_INCOMPLETE


def test_a_report_that_prints_a_bad_name_does_not_crash(tmp_path):
    """compare-directories hashes in-process and prints raw walk paths. No
    report prints through display_path, so this is the stdout safety net."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _bad_file(a)

    result = _run("compare-directories", "--dirA", str(a), "--dirB", str(b),
                  "--db-path", str(tmp_path / "x.db"))

    assert result.returncode == 0, result.stderr.decode()
    assert b"Traceback" not in result.stderr
    assert b"caf\\udc82.txt" in result.stdout


def test_a_valid_path_has_no_name_to_rename():
    assert name_to_rename("/home2/ok/file.txt") == "/home2/ok/file.txt"


def test_a_stdout_that_cannot_be_reconfigured_is_left_alone(monkeypatch):
    """An embedding caller may replace stdout with something that is not a
    TextIOWrapper. main() must still run and print to it."""
    import io
    from src import main as main_module
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(sys, "argv", ["main.py", "help"])
    assert main_module.main() == 0
    assert "Usage:" in buffer.getvalue()
