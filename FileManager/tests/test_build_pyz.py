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

import contextlib
import os
import re
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest

from src.version import git_env

REPO = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT / "scripts" / "build-pyz.sh"


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """Build the bundle once, somewhere the repository does not keep it."""
    output = tmp_path_factory.mktemp("pyz") / "FileManager.pyz"
    # FM_ALLOW_DIRTY because this fixture tests the ARCHIVE, not the
    # cleanliness policy. The build refuses a dirty tree (#62), and a developer
    # with edits in progress is the normal case -- without this the whole
    # module would fail for a reason unrelated to what it asserts. The refusal
    # itself is tested directly, against throwaway repositories, in
    # tests/test_stamp_build_info.py.
    result = subprocess.run(
        [str(BUILD_SCRIPT), str(output)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "FM_ALLOW_DIRTY": "1"},
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
    # FM_ALLOW_DIRTY for the same reason as the `built` fixture: this asserts
    # on the default OUTPUT PATH, not on the state of the checkout running it.
    result = subprocess.run(
        [str(BUILD_SCRIPT)], capture_output=True, text=True, timeout=120,
        env={**os.environ, "FM_ALLOW_DIRTY": "1"},
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
        cwd=REPO, capture_output=True, text=True, timeout=30, env=git_env(),
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


def test_the_bundle_names_the_commit_it_was_built_from(built, tmp_path):
    """#54 requirement 9, measured on the artifact rather than on src/.

    The consumer's installer runs exactly this before putting the file in
    place, from an arbitrary directory with a poisoned PYTHONPATH, so that is
    how it is run here. A bundle that answers "source checkout" has not been
    stamped and is not installable, which is a separate failure from printing
    no commit at all -- both are asserted.
    """
    result = subprocess.run(
        [str(built), "--version"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, result.stderr
    commit_lines = [l for l in result.stdout.splitlines()
                    if l.startswith("commit")]
    assert len(commit_lines) == 1, result.stdout
    assert re.match(r"^commit +: +[0-9a-f]{40}$", commit_lines[0]), \
        commit_lines[0]
    assert "source checkout" not in result.stdout, (
        "the archive was not stamped -- src/build_info.py inside it still "
        "holds the committed None values"
    )
    assert "zipapp bundle" in result.stdout


def test_the_bundle_reports_the_tree_state_it_was_built_from(built, tmp_path):
    """The `built` fixture passes FM_ALLOW_DIRTY, so this says what it must.

    A developer's tree is normally dirty, so the fixture opts in and the
    artifact then reports it. The assertion is that the field is one of the
    three answers and never silently absent -- not that it says "clean", which
    would make this test depend on the state of the checkout running it.
    """
    result = subprocess.run(
        [str(built), "--version"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )
    tree_lines = [l for l in result.stdout.splitlines() if l.startswith("tree")]
    assert len(tree_lines) == 1, result.stdout
    value = tree_lines[0].split(":", 1)[1].strip()
    assert value in ("clean", "dirty at build time") or "CANNOT" in value, value


def test_the_bundle_prints_the_run_header(built, tmp_path):
    """#54 requirement 10, measured on the artifact.

    The header is the only record of what an unattended run was configured to
    do, and it has to survive `2>/dev/null`, so it is read from stdout here
    while stderr is captured separately and checked not to carry it.
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("a")
    result = subprocess.run(
        [str(built), "--db-path", str(tmp_path / "db.db"), "--threads", "3",
         "scan", str(tree)],
        capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "FileManager run"
    assert re.search(
        r"^started +: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [A-Z]{2,5}$",
        result.stdout, re.M,
    ), result.stdout
    assert "threads : 3" in result.stdout
    assert "FileManager run" not in result.stderr
    # A bundle must report itself as one here too, not as a source checkout.
    assert "bundle" in result.stdout


def test_the_bundle_answers_the_consumers_whole_acceptance_sequence(
    built, tmp_path
):
    """#54 requirement 12, in the order and the conditions it specifies.

    Build the archive, then from a working directory outside the repository
    with PYTHONPATH pointing at junk, run `--version`, `--help` and a `scan` of
    `test_data` into a temporary database; assert the exit codes and the rows.

    The individual behaviours have their own tests above. This one exists
    because the consumer runs them as a sequence against one artifact, and a
    requirement written as a sequence is worth checking as one.

    The expected row count is computed from the fixture rather than written
    down: a hard-coded number would silently stop matching the day a file is
    added to `test_data/data`, and `assert expected` fails loudly if the
    fixture is ever empty -- an empty expectation would make every assertion
    below pass without testing anything.
    """
    env = {**os.environ, "PYTHONPATH": "/nonexistent/should/not/matter"}
    fixture = PROJECT / "test_data" / "data"
    db = tmp_path / "acceptance.db"

    def bundle(*args):
        return subprocess.run(
            [str(built), *args], capture_output=True, text=True,
            timeout=300, cwd=str(tmp_path), env=env,
        )

    version_run = bundle("--version")
    assert version_run.returncode == 0, version_run.stderr
    assert re.search(r"^commit +: +[0-9a-f]{40}$", version_run.stdout, re.M)

    help_run = bundle("--help")
    assert help_run.returncode == 0, help_run.stderr
    assert "File Manager Application" in help_run.stdout

    expected = sorted(
        str(p) for p in fixture.rglob("*") if p.is_file()
    )
    assert expected, f"{fixture} holds no files; the assertion would be empty"

    scan_run = bundle("--db-path", str(db), "--threads", "4",
                      "scan", str(fixture))
    assert scan_run.returncode == 0, (
        f"exit {scan_run.returncode}\nstdout:\n{scan_run.stdout}\n"
        f"stderr:\n{scan_run.stderr}"
    )

    assert db.is_file(), "the scan recorded nothing at all"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        recorded = sorted(row[0] for row in
                          conn.execute("SELECT path FROM files"))
    assert recorded == expected, (
        f"{len(recorded)} rows recorded, {len(expected)} files in the fixture"
    )

    # Every row carries a checksum: a row with a NULL md5 is a recorded file
    # that was never actually hashed, which is the failure #57 was about.
    with contextlib.closing(sqlite3.connect(db)) as conn:
        unhashed = conn.execute(
            "SELECT COUNT(*) FROM files WHERE md5sum IS NULL OR md5sum = ''"
        ).fetchone()[0]
    assert unhashed == 0, f"{unhashed} rows have no checksum"


def test_the_bundle_names_its_commit_with_no_git_available(built, tmp_path):
    """The embedded value is genuinely used -- nothing is looked up at run time.

    This is #54 requirement 8 in practice. `src/version.py` derives
    `SOURCE_ROOT` from `__file__`, which inside an archive is a path like
    `/…/FileManager.pyz/src/version.py` and names no directory that exists. It
    is computed but must stay **inert**: a bundle takes the commit from
    `build_info`, so it never consults git and never touches that path.

    Running with PATH stripped is the way to prove it. If a later change made
    `--version` fall back to asking git, this is the test that would catch it,
    where every other version test would still pass on a machine that has git.
    """
    result = subprocess.run(
        [str(built), "--version"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
        env={"PATH": "/nonexistent/bin", "HOME": str(tmp_path),
             "PYTHONPATH": "/nonexistent/should/not/matter"},
    )

    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert re.search(r"^commit +: +[0-9a-f]{40}$", result.stdout, re.M), \
        result.stdout
    assert "CANNOT DETERMINE" not in result.stdout, (
        "the bundle fell back to asking git instead of reading its own "
        "embedded provenance"
    )
    assert "source checkout" not in result.stdout
