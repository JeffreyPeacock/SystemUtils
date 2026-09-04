"""Shared fixtures.

Two things were stopping tests from being written, and both are here:

1. Every test had to build its own database, and the ones that existed wrote
   `test.db` into the repository working directory. Use `db_path`.

2. Anything exercising duplicate detection, the skip check, or the reporting
   queries first had to construct a tree of files with known relationships.
   That is `dup_tree`, and its shape is deliberate -- see `DuplicateTree`.

The upstream model for this is CaptureServer's `conftest.py`, but only in
shape. Roughly 120 of its 159 lines are `autouse` mocks for S3, Celery, FCM,
email and rate limiters. FileManager talks to no external service, so there is
nothing to mock; what transfers is the pattern of a fresh resource per test.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.db import initialize_db

# Content is fixed rather than random so a failure names the same bytes twice.
_UNIQUE_LEFT = b"left only, not duplicated anywhere\n"
_UNIQUE_RIGHT = b"right only, not duplicated anywhere\n"
_SHARED_ONE = b"shared payload one\n"
_SHARED_TWO = b"shared payload two, a little longer\n"
_COMMA = b"a path with a comma in it\n"
_VOLATILE = b"0123456789"


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """An initialised, empty database, one per test, outside the repository."""
    path = tmp_path / "file_manager.db"
    initialize_db(str(path))
    return str(path)


@dataclass
class DuplicateTree:
    """A file tree whose duplicate relationships are known in advance.

        <root>/left/   unique-left.txt      no counterpart
                       shared-one.txt   ─┐
                       shared-two.txt   ─┼─ byte-identical across left/right
                       with,comma.txt   ─┘
        <root>/right/  unique-right.txt     no counterpart
                       shared-one.txt
                       shared-two.txt
                       with,comma.txt
        <root>/volatile/ grows.txt          for the size half of the skip check
                         touched.txt        for the mtime half

    `with,comma.txt` is duplicated like the others AND carries a comma, so any
    test of the duplicate-group queries also exercises the `GROUP_CONCAT`
    splitting bug (#5) without needing a second fixture.

    `volatile/` exists because the skip check in `process_file` compares size
    **and** mtime: a file that changes size and a file that changes only its
    mtime take different paths through it, and both must be reachable.
    """

    root: Path
    left: Path
    right: Path
    volatile: Path
    unique: list[Path] = field(default_factory=list)
    duplicated: list[tuple[Path, Path]] = field(default_factory=list)
    comma_pair: tuple[Path, Path] | None = None
    grows: Path | None = None
    touched: Path | None = None

    # -- the two ways a file can defeat the skip check ---------------------

    def grow(self) -> Path:
        """Append to `grows.txt`, changing its size. Returns the path."""
        assert self.grows is not None
        with open(self.grows, "ab") as handle:
            handle.write(b"more")
        return self.grows

    def touch(self, when: float = 1_000_000_000.0) -> Path:
        """Change `touched.txt`'s mtime while keeping its size identical.

        Rewrites the same number of bytes, then forces the mtime, so the file
        differs from its recorded state in mtime alone. `when` is seconds since
        the epoch and defaults to a fixed past time so the value is stable.
        """
        assert self.touched is not None
        self.touched.write_bytes(_VOLATILE[::-1])  # same length, new content
        os.utime(self.touched, (when, when))
        return self.touched

    # -- convenience -------------------------------------------------------

    def all_files(self) -> list[Path]:
        out: list[Path] = list(self.unique)
        for a, b in self.duplicated:
            out.extend((a, b))
        if self.grows:
            out.append(self.grows)
        if self.touched:
            out.append(self.touched)
        return sorted(out)


@pytest.fixture
def dup_tree(tmp_path: Path) -> DuplicateTree:
    """Build the tree described by `DuplicateTree`, under pytest's tmp_path."""
    root = tmp_path / "tree"
    left, right, volatile = root / "left", root / "right", root / "volatile"
    for directory in (left, right, volatile):
        directory.mkdir(parents=True)

    tree = DuplicateTree(root=root, left=left, right=right, volatile=volatile)

    (left / "unique-left.txt").write_bytes(_UNIQUE_LEFT)
    (right / "unique-right.txt").write_bytes(_UNIQUE_RIGHT)
    tree.unique = [left / "unique-left.txt", right / "unique-right.txt"]

    for name, payload in (
        ("shared-one.txt", _SHARED_ONE),
        ("shared-two.txt", _SHARED_TWO),
        ("with,comma.txt", _COMMA),
    ):
        (left / name).write_bytes(payload)
        (right / name).write_bytes(payload)
        tree.duplicated.append((left / name, right / name))
    tree.comma_pair = (left / "with,comma.txt", right / "with,comma.txt")

    tree.grows = volatile / "grows.txt"
    tree.touched = volatile / "touched.txt"
    tree.grows.write_bytes(_VOLATILE)
    tree.touched.write_bytes(_VOLATILE)

    return tree


# -- assertion helpers -----------------------------------------------------
#
# These exist so a failure says which paths were expected in a group, rather
# than printing two unordered lists and leaving the reader to diff them.


def assert_one_group(duplicates: dict[str, list[str]], *paths: Path) -> str:
    """Assert `paths` form exactly one duplicate group. Returns its md5sum."""
    wanted = {str(p) for p in paths}
    for md5sum, members in duplicates.items():
        if set(members) == wanted:
            return md5sum
    raise AssertionError(
        f"no duplicate group matched {sorted(wanted)}\n"
        f"groups present: { {k: sorted(v) for k, v in duplicates.items()} }"
    )


def assert_not_duplicated(duplicates: dict[str, list[str]], *paths: Path) -> None:
    """Assert none of `paths` appears in any duplicate group."""
    for md5sum, members in duplicates.items():
        for path in paths:
            if str(path) in members:
                raise AssertionError(
                    f"{path} was reported as a duplicate under {md5sum} "
                    f"with {sorted(members)}"
                )


@pytest.fixture(autouse=True)
def _no_writes_into_the_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run every test from a scratch directory.

    Several code paths write relative to the *current* directory -- the default
    database is `./file_manager.db`, and `scan-unique-files` drops a
    `.processed_files.txt` resume log into whatever it is scanning. A test that
    triggers one of those used to leave the file in the working tree.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    yield
    shutil.rmtree(cwd, ignore_errors=True)


# -- invoking the CLI ------------------------------------------------------
#
# main() is 107 statements of argparse setup and dispatch, and none of it was
# reachable from a test: it reads sys.argv, prints to stdout, and lets argparse
# raise SystemExit. CaptureServer has no equivalent to copy -- its entry point
# is a FastAPI app driven through TestClient, which does not apply to a CLI.


@dataclass
class CliResult:
    """What one CLI invocation did."""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str

    def __contains__(self, text: str) -> bool:
        """`"usage" in result` searches both streams -- main() uses both."""
        return text in self.stdout or text in self.stderr


@pytest.fixture
def run_cli(capsys, monkeypatch):
    """Run `main()` with the given arguments and capture everything.

    Returns a CliResult rather than raising, because argparse exits through
    SystemExit for both success (`help`) and failure (a bad action), and a test
    that has to wrap every call in pytest.raises says less than one that
    asserts on the code.
    """
    from src import main as main_module

    def invoke(*args: str) -> CliResult:
        argv = ["main.py", *args]
        monkeypatch.setattr(sys, "argv", argv)
        code = 0
        try:
            main_module.main()
        except SystemExit as exc:  # argparse's own exit path
            code = exc.code if isinstance(exc.code, int) else 1
        captured = capsys.readouterr()
        return CliResult(argv=argv, exit_code=code,
                         stdout=captured.out, stderr=captured.err)

    return invoke


def pytest_sessionfinish(session, exitstatus):
    """Write .coverage-summary.md after every run that produced coverage.xml.

    Returns early when coverage.xml is absent, so `--no-cov` runs are unaffected.

    It writes the file and deliberately does NOT open an editor: this hook runs
    on every session, including CI and any pre-commit hook, and launching one
    would steal focus on runs nobody is watching. Read it when you want it:
    `cat FileManager/.coverage-summary.md`.
    """
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    coverage_xml = os.path.join(root, "coverage.xml")
    if not os.path.exists(coverage_xml):
        return

    script = os.path.join(root, "scripts", "coverage_summary.py")
    if not os.path.exists(script):
        print(f"\nCANNOT WRITE SUMMARY: {script} is missing")
        return

    junit = os.path.join(root, "test-results.xml")
    result = subprocess.run(
        [sys.executable, script, coverage_xml,
         os.path.join(root, ".coverage-summary.md"), junit],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Say so rather than leaving a stale summary looking current.
        print(f"\nCANNOT WRITE SUMMARY: {script} exited {result.returncode}\n{result.stderr}")
    elif result.stdout:
        print(result.stdout.rstrip())
