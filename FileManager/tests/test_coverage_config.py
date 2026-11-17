"""#51 -- nothing is excluded from measurement, and the guard for the next one works.

From #45 until #51 this file pinned a single exclusion: `src/gui.py`, a Tkinter
widget tree that could not be unit-tested without asserting on the library, and
that while measured capped the total near 88% against the 95% in
`docs/REQUIREMENTS.txt`. The GUI is now a separate application (#53), so the
omit list is empty.

An empty list is the easy case to get wrong. Every loop over "each omitted
file" now iterates nothing and passes without testing anything, which looks
exactly like a working guard -- `docs/Development-Principles.md` §3a. So the
machinery is exercised against **synthetic** configs instead, where an omission
can actually be made to exist, and only one assertion is made about the live
configuration: that it omits nothing.

What is pinned:

  1. the live `.coveragerc` omits nothing, and the first exclusion cannot be
     slipped in as a one-line config change -- it has to edit a test named for
     the rule
  2. the omit list lives in `.coveragerc` and nowhere else; the summary script
     reads it rather than keeping a second copy free to disagree
  3. an omission *with* a reason renders that reason into the report
  4. an omission *without* a reason renders a visible warning rather than
     vanishing
"""

from __future__ import annotations

import configparser
import importlib.util
from pathlib import Path

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

# A coverage.xml small enough to read, in the shape the renderer walks: one
# class, one fully covered line, no branches.
MINIMAL_COVERAGE_XML = """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="src">
      <classes>
        <class filename="src/kept.py" name="kept.py">
          <lines><line number="1" hits="1"/></lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def _omit_lines() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    return [line.strip() for line in parser.get("run", "omit", fallback="").splitlines()
            if line.strip()]


def _render(tmp_path, omitted, reasons) -> str:
    """Run the real renderer with a synthetic omit list, return the report."""
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(MINIMAL_COVERAGE_XML, encoding="utf-8")
    output = tmp_path / "summary.md"

    original_omitted, original_reasons = summary.omitted_files, summary.EXCLUSION_REASONS
    original_argv = __import__("sys").argv
    try:
        summary.omitted_files = lambda root: omitted
        summary.EXCLUSION_REASONS = reasons
        __import__("sys").argv = ["coverage_summary.py", str(coverage_xml), str(output)]
        summary.main()
    finally:
        summary.omitted_files, summary.EXCLUSION_REASONS = original_omitted, original_reasons
        __import__("sys").argv = original_argv

    return output.read_text(encoding="utf-8")


# -- the live configuration -------------------------------------------------


def test_coveragerc_exists():
    assert COVERAGERC.is_file(), (
        "coverage.py does not read pytest.ini; the omit list needs .coveragerc"
    )


def test_the_live_config_omits_nothing():
    """The first exclusion has to come through this test, not past it.

    If you are here because you added an omission: record the reason in
    EXCLUSION_REASONS, open a ticket, and change this test deliberately. That
    sequence is the control -- an omit list is the easiest place in a repository
    to make a number say whatever you want.
    """
    assert _omit_lines() == [], (
        f".coveragerc omits {_omit_lines()}. Coverage is measured over all of "
        f"src/ as of #51. See the checklist in .coveragerc before adding to it."
    )


def test_the_live_summary_has_no_exclusions_section():
    """Nothing omitted means nothing to disclose, and the report says so by
    staying silent rather than printing an empty heading."""
    rendered = (ROOT / ".coverage-summary.md").read_text(encoding="utf-8")

    assert "## Excluded from measurement" not in rendered


def test_no_recorded_reason_outlives_the_omission_it_explained():
    """A reason for a file nobody omits any more is stale documentation that
    reads as current policy."""
    orphans = [name for name in summary.EXCLUSION_REASONS
               if name not in [summary.module_name(e) for e in _omit_lines()]]

    assert orphans == [], (
        f"{orphans} have reasons in EXCLUSION_REASONS but are not omitted in "
        f".coveragerc. Remove the reason, or restore the omission."
    )


# -- the machinery, against configs where an omission exists ----------------


def test_the_omit_list_is_read_from_coveragerc_not_duplicated(tmp_path):
    """One definition. Two lists that must agree is how they stop agreeing."""
    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit =\n    src/alpha.py\n    src/beta.py\n", encoding="utf-8"
    )

    assert summary.omitted_files(str(tmp_path)) == ["alpha", "beta"]


def test_a_missing_coveragerc_reads_as_no_omissions(tmp_path):
    assert summary.omitted_files(str(tmp_path)) == []


def test_an_omission_with_a_reason_renders_that_reason(tmp_path):
    rendered = _render(
        tmp_path,
        omitted=["mystery"],
        reasons={"mystery": "Because of a specific recorded thing."},
    )

    assert "## Excluded from measurement" in rendered
    assert "`mystery`" in rendered
    assert "Because of a specific recorded thing." in rendered
    assert "never a way to move a number" in rendered


def test_an_omission_without_a_reason_is_reported_loudly(tmp_path):
    """The detector proven to fire.

    Without this, an unexplained omission could drop out of the report a human
    actually reads, and nothing would say so.
    """
    rendered = _render(tmp_path, omitted=["mystery"], reasons={})

    assert "`mystery`" in rendered
    assert "excluded with no reason recorded" in rendered
    assert "EXCLUSION_REASONS" in rendered


def test_an_omission_that_is_not_taking_effect_is_reported(tmp_path):
    """Catches .coveragerc saying one thing while the report shows another --
    the omit silently not applying, which would otherwise look like success."""
    rendered = _render(
        tmp_path,
        omitted=["kept"],          # 'kept' IS in MINIMAL_COVERAGE_XML, so it was measured
        reasons={"kept": "a reason"},
    )

    assert "still appears in the measured table" in rendered
