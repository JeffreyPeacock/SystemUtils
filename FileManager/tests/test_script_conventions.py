"""Invariants a reviewer cannot see in a diff -- Development-Principles §3.

File modes do not appear in a code review, so "we'll catch it in review" is not
a control here. #9 is the case in point: three wrapper scripts pointed at an
older copy of the project for months, and nothing in a diff said so.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted(
    p for p in list(REPO.glob("FileManager/*.sh")) + list(REPO.glob("scripts/**/*.sh"))
    if ".git" not in p.parts
)


def _has_shebang(path: Path) -> bool:
    with open(path, "rb") as handle:
        return handle.read(2) == b"#!"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(REPO)))
def test_shebang_matches_executable_bit(script):
    """A script that is run has both; one that is only sourced has neither.

    A shebang without the bit fails only on the machine where it matters, and a
    bit without a shebang runs under whatever shell happens to pick it up.
    """
    shebang = _has_shebang(script)
    executable = os.access(script, os.X_OK)
    assert shebang == executable, (
        f"{script.relative_to(REPO)}: shebang={shebang} executable={executable}. "
        f"Add both (it is run) or remove both (it is sourced)."
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(REPO)))
def test_script_parses(script):
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"{script.relative_to(REPO)}: {result.stderr}"


@pytest.mark.parametrize(
    "script", [p for p in SCRIPTS if p.name.startswith("fm-") and p.name != "fm-common.sh"],
    ids=lambda p: p.name,
)
def test_wrapper_does_not_hardcode_another_checkout(script):
    """#9: the wrappers used to `cd` to a fixed path that was a different copy.

    They must resolve their own location instead, so a fix landed in this
    repository actually reaches the scheduled runs.
    """
    body = script.read_text()
    assert "cd /home/" not in body, (
        f"{script.name} hard-codes an absolute directory; resolve BASH_SOURCE instead"
    )
    assert "source .venv/bin/activate" not in body, (
        f"{script.name} activates a .venv; the interpreter comes from .python-version"
    )
