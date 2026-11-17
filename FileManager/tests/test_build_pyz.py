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
    output = tmp_path_factory.mktemp("pyz") / "FileManager.pyz"
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


def test_the_shebang_is_exactly_what_the_consumer_asserts_on(built):
    """Fixed by agreement, not by taste (#54).

    The Desktop-Ops installer runs `head -1` on the artifact and compares. Each
    part of this string is load-bearing:

      `-I` is isolated mode -- it ignores PYTHONPATH, the user site directory
      and the script's directory. For a root-run executable that is the
      difference between reading only its own code and picking up whatever an
      ordinary user left on PYTHONPATH.

      `/usr/bin/python3` is absolute rather than `/usr/bin/env python3`,
      because the two cannot be combined with an option: Linux passes
      everything after the interpreter path as ONE argument, so
      `#!/usr/bin/env python3 -I` hands env the single argument "python3 -I".

      Exactly ONE option, for the same reason -- `-I -B` arrives as one string
      and python exits 2 with `Unknown option: - `.
    """
    shebang = built.read_bytes().split(b"\n", 1)[0].decode()

    assert shebang == "#!/usr/bin/python3 -I", (
        f"shebang is {shebang!r}; the consumer's installer asserts on "
        f"'#!/usr/bin/python3 -I' exactly (#54)"
    )


def test_the_bundle_ignores_a_poisoned_pythonpath(built, tmp_path):
    """What `-I` buys, asserted rather than assumed.

    The consumer runs this as root from an arbitrary environment. Without
    isolated mode a stray PYTHONPATH entry -- or a module dropped in the
    executable's own directory -- is on the import path of a root process.
    """
    result = subprocess.run(
        [str(built), "help"],
        cwd=tmp_path, timeout=60, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    assert "File Manager Application" in result.stdout


def test_the_artifact_lands_where_the_installer_looks(built):
    """The default path is part of the contract, so a default-path build is
    what gets checked -- `built` overrides it, which would hide a change."""
    result = subprocess.run(
        [str(BUILD_SCRIPT)], capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr

    expected = PROJECT / "dist" / "FileManager.pyz"
    assert expected.is_file(), (
        f"default build did not produce {expected}; the Desktop-Ops installer "
        f"reads that path (#54)"
    )
    assert expected.read_bytes().split(b"\n", 1)[0].decode() == "#!/usr/bin/python3 -I"


def test_the_build_output_is_not_committable():
    """The artifact is built, never committed; a committed one goes stale.

    Checks paths INSIDE the ignored directories, not the directory names.
    `dist/` and `build/` carry a trailing slash, so those patterns match only a
    real directory -- `git check-ignore FileManager/dist` exits 1 in a fresh
    clone where nothing has been built yet, which would make this test pass or
    fail depending on whether a build happened to have run first.
    """
    targets = ["FileManager/dist/FileManager.pyz", "FileManager/build/pyz"]
    result = subprocess.run(
        ["git", "check-ignore", *targets],
        cwd=REPO, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, (
        f"{targets} must be gitignored; git check-ignore reported: "
        f"{result.stdout}{result.stderr}"
    )


def test_the_bundle_records_rows_and_reports_an_incomplete_scan(built, tmp_path):
    """#57 through the artifact: row count and exit status asserted together.

    The unit tests in `test_scan_failure_counts.py` run `src/main.py`. This runs
    the thing that will actually be invoked under sudo, which is a different
    program: a different interpreter (`/usr/bin/python3`, pinned by the
    shebang), isolated mode, and imports resolved from inside the archive. A
    scan that could not read part of the tree has to exit 3 there too, or the
    unattended root scan this bundle exists for is back to reporting success
    over a partial index.
    """
    import sqlite3
    from contextlib import closing

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "readable.txt").write_text("readable\n", encoding="utf-8")
    denied = tree / "denied.txt"
    denied.write_text("denied\n", encoding="utf-8")
    denied.chmod(0o000)
    db = tmp_path / "bundle.db"

    try:
        result = subprocess.run(
            [str(built), "--db-path", str(db), "scan", str(tree)],
            cwd="/", capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
        )
    finally:
        denied.chmod(0o644)

    assert result.returncode == 3, (
        f"the bundle exited {result.returncode} on a tree it could not fully "
        f"read\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # `with sqlite3.connect(...)` commits but does not close the handle.
    with closing(sqlite3.connect(db)) as conn:
        rows = [r[0] for r in conn.execute("SELECT path FROM files")]
    assert rows == [str(tree / "readable.txt")], (
        "the readable file must still be recorded -- a non-zero exit does not "
        "mean discarding the work that succeeded"
    )
    assert "1 hashed, 0 skipped unchanged, 1 failed" in result.stdout
    assert str(denied) in result.stdout


def test_the_bundle_exits_zero_on_a_tree_it_could_read(built, tmp_path):
    """The other half: an exit code that is always non-zero carries nothing."""
    import sqlite3
    from contextlib import closing

    tree = tmp_path / "clean"
    tree.mkdir()
    (tree / "a.txt").write_text("a\n", encoding="utf-8")
    (tree / "b.txt").write_text("b\n", encoding="utf-8")
    db = tmp_path / "clean.db"

    result = subprocess.run(
        [str(built), "--db-path", str(db), "scan", str(tree)],
        cwd="/", capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "2 hashed, 0 skipped unchanged, 0 failed" in result.stdout
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT count(*) FROM files").fetchone()[0] == 2


@pytest.mark.parametrize("form", ["help", "--help", "-h", "-?"])
def test_the_bundle_answers_every_help_form_with_zero(built, form):
    """#58, through the artifact a consumer's installer actually probes.

    An install check that runs `FileManager.pyz --help` is the first thing
    anyone writes, and it exited 2. Asserted here as well as in
    `test_help_flags.py` because this runs under the pinned `/usr/bin/python3`
    in isolated mode, which is a different program from `python src/main.py`.
    """
    result = subprocess.run(
        [str(built), form],
        cwd="/", capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, (
        f"`FileManager.pyz {form}` exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "File Manager Application" in result.stdout
    assert result.stderr == "", f"it also complained: {result.stderr!r}"
