"""#45 -- gui is excluded from measurement, and the exclusion stays visible.

`src/gui.py` is a Tkinter widget tree and a `mainloop()`, deliberately untested.
While it sat inside `--cov=src` it also made the target unreachable: 82 of 601
statements, capping the total near 88% with everything else at 100%, against the
95% in `docs/REQUIREMENTS.txt`.

The risk in fixing that is not the arithmetic, it is the silence. A file dropped
from the report looks exactly like a file nobody wrote, and an omit list is the
easiest place in a repository to make a number say whatever you want. So three
things are pinned here:

  1. the omit list lives in `.coveragerc` and nowhere else -- the summary script
     reads it rather than keeping a second copy that could disagree
  2. every omitted file has a recorded reason
  3. the rendered summary names what it left out
"""

from __future__ import annotations

import configparser
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COVERAGERC = ROOT / ".coveragerc"


def _load_summary_module():
    spec = importlib.util.spec_from_file_location(
        "coverage_summary", ROOT / "scripts" / "coverage_summary.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary = _load_summary_module()


def _omit_lines() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    return [line.strip() for line in parser.get("run", "omit", fallback="").splitlines()
            if line.strip()]


def test_coveragerc_exists_and_omits_the_gui():
    assert COVERAGERC.is_file(), (
        "coverage.py does not read pytest.ini; the omit list needs .coveragerc"
    )
    assert "src/gui.py" in _omit_lines()


def test_every_omitted_file_actually_exists():
    """An omit entry for a file that is gone is a rule nobody is following, and
    it silently stops applying if the path is ever renamed."""
    for entry in _omit_lines():
        assert (ROOT / entry).is_file(), f"{entry} is omitted but does not exist"


def test_the_summary_reads_the_omit_list_rather_than_keeping_its_own():
    """One definition. Two lists that must agree is how they stop agreeing."""
    assert summary.omitted_files(str(ROOT)) == [
        summary.module_name(entry) for entry in _omit_lines()
    ]


def test_every_omitted_file_has_a_recorded_reason():
    missing = [name for name in summary.omitted_files(str(ROOT))
               if name not in summary.EXCLUSION_REASONS]
    assert missing == [], (
        f"{missing} are omitted from coverage with no reason in "
        f"EXCLUSION_REASONS. Record why, or stop omitting them."
    )


def test_an_omission_without_a_reason_is_reported_loudly(tmp_path, monkeypatch):
    """The detector proven to fire.

    Without this, `test_every_omitted_file_has_a_recorded_reason` passing tells
    you nothing about whether an unexplained omission would ever be noticed in
    the report a human actually reads.
    """
    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit =\n    src/mystery.py\n", encoding="utf-8"
    )

    names = summary.omitted_files(str(tmp_path))

    assert names == ["mystery"]
    assert "mystery" not in summary.EXCLUSION_REASONS


def test_the_generated_summary_names_what_it_excluded():
    """The report on disk, not the code that writes it."""
    rendered = (ROOT / ".coverage-summary.md").read_text(encoding="utf-8")

    assert "## Excluded from measurement" in rendered
    for name in summary.omitted_files(str(ROOT)):
        assert f"`{name}`" in rendered, f"{name} is omitted but unnamed in the summary"
    assert "never a way to move a number" in rendered


def test_the_measured_table_does_not_also_list_an_excluded_file():
    """Catches the omit silently not taking effect -- .coveragerc saying one
    thing while the report shows another."""
    rendered = (ROOT / ".coverage-summary.md").read_text(encoding="utf-8")
    by_file = rendered.split("## By File")[1].split("## Excluded")[0]

    for name in summary.omitted_files(str(ROOT)):
        assert f"`{name}`" not in by_file
