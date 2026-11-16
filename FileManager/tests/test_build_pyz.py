"""#52 -- the zipapp bundle builds, runs, and carries no stale bytecode.

A build script is the kind of thing that rots silently: nobody runs it between
releases, and when they finally do, the failure is on the machine where it
matters least convenient. So the gate is the artifact, not the exit status --
these tests build it and then execute it.

The `__pycache__` assertion is the one a code review cannot make. `cp -r src`
copies any .pyc alongside the source, and a zipapp serves stale bytecode
without complaint: CPython invalidates on (mtime, size), so a file rewritten
to the same length inside the same one-second tick keeps its old bytecode.
That has already produced a wrong answer in this repository.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT / "scripts" / "build-pyz.sh"


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """Build the bundle once, somewhere the repository does not keep it."""
    output = tmp_path_factory.mktemp("pyz") / "fm.pyz"
    result = subprocess.run(
        [str(BUILD_SCRIPT), str(output)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"build-pyz.sh failed ({result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert output.is_file(), f"{output} was not created"
    return output


def test_the_bundle_is_executable(built):
    assert os.access(built, os.X_OK), "a bundle without the executable bit cannot be sudo'd"


def test_the_bundle_runs_from_an_unrelated_directory(built, tmp_path):
    """Running it from inside FileManager/ would prove nothing.

    `src.` imports would resolve from the working directory rather than from
    inside the archive, which is the exact failure this is here to catch.
    """
    result = subprocess.run(
        [str(built), "help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    assert "File Manager Application" in result.stdout


def test_the_bundle_carries_no_compiled_bytecode(built):
    """Stale .pyc inside the archive is served in preference to the source."""
    stale = [name for name in zipfile.ZipFile(built).namelist()
             if name.endswith(".pyc") or "__pycache__" in name]

    assert stale == [], (
        f"{stale} are compiled files inside the bundle. CPython invalidates a "
        f".pyc on (mtime, size), so one copied in by `cp -r src` can be served "
        f"in place of changed source. Clear __pycache__ before archiving."
    )


def test_the_bundle_contains_the_source_and_an_entry_point(built):
    names = zipfile.ZipFile(built).namelist()

    assert "__main__.py" in names, "a zipapp with no __main__.py cannot run"
    assert "src/main.py" in names
    assert "src/db.py" in names


def test_the_shebang_does_not_depend_on_the_callers_path(built):
    """The whole point of the bundle.

    `sudo python src/main.py` resolves `python` from root's PATH, not from the
    pyenv shim, so it silently runs a different interpreter. A hard-coded path
    to this machine's pyenv virtualenv would be just as wrong in the other
    direction -- it would not exist on any other machine.
    """
    shebang = built.read_bytes().split(b"\n", 1)[0].decode()

    assert shebang.startswith("#!"), f"no shebang: {shebang!r}"
    assert "/usr/bin/env python3" in shebang, shebang
    assert ".pyenv" not in shebang, f"pins this machine's interpreter: {shebang}"


def test_the_build_script_is_not_committed_with_its_output(built):
    """fm.pyz is a build artifact; committing one is how it goes stale."""
    result = subprocess.run(
        ["git", "check-ignore", "FileManager/fm.pyz", "FileManager/build"],
        cwd=REPO, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, (
        "FileManager/fm.pyz and FileManager/build must be gitignored; "
        f"git check-ignore said: {result.stdout}{result.stderr}"
    )
