"""The build refuses to stamp provenance it cannot stand behind (#62).

`scripts/stamp_build_info.py` is the one place that decides what a bundle will
say about itself for the rest of its life, so every one of its refusals is
tested here by driving it against throwaway git repositories rather than this
one. Three outcomes, and the third is the point: a tree whose state **cannot be
read** is not a clean tree.

These are subprocess tests on purpose -- the script is what `build-pyz.sh`
invokes, and a function call would not prove the script's exit status, which is
what `set -e` in the build reacts to. They contribute no coverage of `src/`,
which is correct: the script lives in `scripts/` and is not measured.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
STAMPER = PROJECT / "scripts" / "stamp_build_info.py"


def run_stamper(out: Path, root: Path, **env_overrides: str):
    """Invoke the stamper exactly as build-pyz.sh does."""
    env = {**os.environ}
    env.pop("FM_ALLOW_DIRTY", None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(STAMPER), str(out), str(root)],
        capture_output=True, text=True, timeout=60, env=env,
    )


def git(repo: Path, *args: str) -> str:
    """Run git in `repo` and fail the test loudly if it could not."""
    result = subprocess.run(
        ("git", "-C", str(repo), *args),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed in {repo}: {result.stderr}"
    )
    return result.stdout.strip()


@pytest.fixture
def clean_repo(tmp_path) -> Path:
    """A one-commit git repository with nothing uncommitted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "thing.py").write_text("x = 1\n")
    git(repo, "add", "thing.py")
    git(repo, "commit", "-qm", "first")
    assert git(repo, "status", "--porcelain") == "", "fixture is not clean"
    return repo


def stamped_values(path: Path) -> dict:
    """Read the generated module back as data, without importing it."""
    namespace: dict = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    return namespace


def test_a_clean_tree_is_stamped_with_its_commit(clean_repo, tmp_path):
    out = tmp_path / "build_info.py"
    result = run_stamper(out, clean_repo)

    assert result.returncode == 0, result.stderr
    assert out.is_file()
    values = stamped_values(out)
    assert values["COMMIT"] == git(clean_repo, "rev-parse", "HEAD")
    assert values["DIRTY"] is False
    assert values["BUILD_TIME"]


def test_the_recorded_commit_is_a_full_hash(clean_repo, tmp_path):
    """The consumer's installer greps for 40 hex characters."""
    out = tmp_path / "build_info.py"
    assert run_stamper(out, clean_repo).returncode == 0
    commit = stamped_values(out)["COMMIT"]
    assert len(commit) == 40, commit
    assert all(c in "0123456789abcdef" for c in commit), commit


def test_a_dirty_tree_is_refused_and_nothing_is_written(clean_repo, tmp_path):
    """The refusal #54 asked for, and the file must not appear anyway."""
    (clean_repo / "thing.py").write_text("x = 2  # uncommitted\n")
    out = tmp_path / "build_info.py"

    result = run_stamper(out, clean_repo)

    assert result.returncode == 1
    assert not out.exists(), "a refused build still wrote its provenance"
    assert "CANNOT STAMP" in result.stderr
    assert "thing.py" in result.stderr, "the refusal does not say what is dirty"


def test_an_untracked_file_also_counts_as_dirty(clean_repo, tmp_path):
    """--porcelain lists untracked files, and they are part of the source."""
    (clean_repo / "new_module.py").write_text("y = 1\n")
    result = run_stamper(tmp_path / "build_info.py", clean_repo)
    assert result.returncode == 1
    assert "new_module.py" in result.stderr


def test_allow_dirty_builds_but_records_the_truth(clean_repo, tmp_path):
    """The override exists, and it costs the artifact its clean claim."""
    (clean_repo / "thing.py").write_text("x = 2  # uncommitted\n")
    out = tmp_path / "build_info.py"

    result = run_stamper(out, clean_repo, FM_ALLOW_DIRTY="1")

    assert result.returncode == 0, result.stderr
    values = stamped_values(out)
    assert values["DIRTY"] is True
    assert values["COMMIT"] == git(clean_repo, "rev-parse", "HEAD")


def test_allow_dirty_must_be_exactly_one(clean_repo, tmp_path):
    """A truthy-looking value is not the opt-in. Only "1" is."""
    (clean_repo / "thing.py").write_text("x = 2\n")
    for value in ("", "0", "yes", "true", "TRUE"):
        result = run_stamper(tmp_path / "build_info.py", clean_repo,
                             FM_ALLOW_DIRTY=value)
        assert result.returncode == 1, f"FM_ALLOW_DIRTY={value!r} opted in"


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path):
    """Not "clean by default" -- git could not answer, so the build stops."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    out = tmp_path / "build_info.py"

    result = run_stamper(out, not_a_repo)

    assert result.returncode == 1
    assert not out.exists()
    assert "CANNOT STAMP" in result.stderr
    assert "clean" not in result.stderr.lower(), (
        "a refusal that mentions being clean invites exactly the misreading "
        "this test exists to prevent"
    )


def test_git_missing_from_path_is_refused(clean_repo, tmp_path):
    """The other way the question cannot be asked: no git at all."""
    out = tmp_path / "build_info.py"
    result = run_stamper(out, clean_repo, PATH="/nonexistent/bin")

    assert result.returncode == 1
    assert not out.exists()
    assert "CANNOT STAMP" in result.stderr


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores the mode bits that make git status fail here",
)
def test_a_tree_whose_state_cannot_be_read_is_refused(clean_repo, tmp_path):
    """The third outcome, reached where the other refusals do not reach it.

    This one needed hunting for. When git cannot be consulted at all,
    `rev-parse HEAD` already fails and the stamper returns before it ever asks
    about the tree state -- so the `status is None` branch looked guarded and
    was not: deleting it broke no test. Measured on 2026-11-17.

    An unreadable `.git/index` separates the two calls: `rev-parse` reads refs
    and still answers, `git status` opens the index and exits 128. That is the
    state this branch exists for, and now something fails if it goes away.
    """
    (clean_repo / ".git" / "index").chmod(0o000)
    out = tmp_path / "build_info.py"
    try:
        result = run_stamper(out, clean_repo)
    finally:
        (clean_repo / ".git" / "index").chmod(0o644)

    assert result.returncode == 1, (
        "a tree state that could not be read was accepted as a build input"
    )
    assert not out.exists()
    assert "unknown" in result.stderr.lower()


def test_the_wrong_number_of_arguments_exits_two(tmp_path):
    """Same convention as the CLI: 2 means the invocation was rejected."""
    result = subprocess.run(
        [sys.executable, str(STAMPER)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    assert "stamp_build_info.py" in result.stderr


def test_the_generated_module_is_importable_and_data_only(clean_repo, tmp_path):
    """It is exec'd inside the archive, so it must not need anything."""
    out = tmp_path / "build_info.py"
    assert run_stamper(out, clean_repo).returncode == 0
    text = out.read_text()
    assert "import" not in text, "build_info.py must stay data only"
    assert set(stamped_values(out)) >= {"COMMIT", "BUILD_TIME", "DIRTY"}
