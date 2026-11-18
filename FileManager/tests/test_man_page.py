"""The markdown copy of the manual says what the troff source says.

`man/filemanager.1` is the manual. `man/filemanager.md` is a rendering of it
produced by `scripts/render_man.py`, committed so it can be read in an editor
or on GitHub without troff. Two copies of one document is how they come to
disagree, so the first test here is the gate: the committed markdown must be
byte-identical to a fresh render of the troff.

**The gate is normally invisible.** `tests/conftest.py` regenerates the
markdown after every test session, so the ordinary sequence -- edit the troff,
run the suite -- leaves the file current. The gate catches the case where that
did not happen: a `--no-cov` loop that never reached session finish, a
hand-edit of the generated file, or a commit of the troff without the markdown.

The refusal tests exist because `render_man.py`'s promise is that it never
guesses. A renderer that dropped the macros it did not recognise would produce
a markdown file that looks complete and is quietly missing a section, and
nothing in a diff would say so. These prove the refusal fires, and that a
refused render leaves the previous file untouched rather than half-written.

Subprocess tests here contribute no coverage of `src/`, which is correct --
`scripts/` is not measured. The in-process tests import the renderer by path
because `scripts/` is not a package.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
RENDERER = PROJECT / "scripts" / "render_man.py"
TROFF = PROJECT / "man" / "filemanager.1"
MARKDOWN = PROJECT / "man" / "filemanager.md"

REGENERATE = "python scripts/render_man.py"


def load_renderer():
    """Import `scripts/render_man.py` by path -- `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("render_man", RENDERER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    return load_renderer()


def run_renderer(*args: str):
    """Invoke the script the way conftest and a developer both do."""
    return subprocess.run(
        [sys.executable, str(RENDERER), *args],
        capture_output=True, text=True, timeout=60,
    )


# -- the gate --------------------------------------------------------------


def test_the_sources_exist():
    """Fail loudly rather than skipping. A missing manual is not a pass."""
    assert TROFF.is_file(), f"{TROFF} is missing"
    assert MARKDOWN.is_file(), f"{MARKDOWN} is missing -- run `{REGENERATE}`"
    assert RENDERER.is_file(), f"{RENDERER} is missing"


def test_the_committed_markdown_is_a_current_render(renderer):
    """The committed markdown matches the troff it claims to render."""
    fresh = renderer.render(TROFF.read_text(encoding="utf-8"))
    committed = MARKDOWN.read_text(encoding="utf-8")
    if fresh != committed:
        fresh_lines = fresh.splitlines()
        committed_lines = committed.splitlines()
        first = next(
            (i for i, (a, b) in enumerate(zip(fresh_lines, committed_lines))
             if a != b),
            min(len(fresh_lines), len(committed_lines)),
        )
        raise AssertionError(
            f"man/filemanager.md is not a current render of man/filemanager.1.\n"
            f"Run `{REGENERATE}` and commit the result.\n"
            f"First difference at line {first + 1}:\n"
            f"  committed: "
            f"{committed_lines[first] if first < len(committed_lines) else '<end of file>'!r}\n"
            f"  expected:  "
            f"{fresh_lines[first] if first < len(fresh_lines) else '<end of file>'!r}"
        )


def test_rendering_is_deterministic(renderer):
    """Two renders of one input are identical.

    The gate above compares bytes, so a renderer that varied -- a timestamp, a
    set iteration order -- would fail on every run for no reason and get
    deleted. This pins that it cannot.
    """
    source = TROFF.read_text(encoding="utf-8")
    assert renderer.render(source) == renderer.render(source)


def test_every_heading_in_the_troff_reaches_the_markdown():
    """An independent check that no section was dropped.

    Deliberately does not use the renderer: the byte comparison above would
    pass happily if the renderer itself silently lost a section, because both
    sides would be missing it. This reads the headings out of the troff and
    looks for them in the markdown.
    """
    # `\\-` is expanded here rather than by importing the renderer's escape
    # table. The duplication is the point: a check that shares the renderer's
    # code cannot catch the renderer being wrong.
    headings = [
        line.split(None, 1)[1].strip().strip('"').replace("\\-", "-")
        for line in TROFF.read_text(encoding="utf-8").splitlines()
        if line.startswith((".SH ", ".SS "))
    ]
    assert len(headings) >= 15, f"only found {len(headings)} headings in the troff"

    markdown = MARKDOWN.read_text(encoding="utf-8")
    missing = [h for h in headings if h not in markdown]
    assert not missing, (
        f"these sections of the manual are not in the markdown: {missing}\n"
        f"Run `{REGENERATE}`."
    )


# -- the refusals ----------------------------------------------------------


def test_an_unknown_macro_is_refused(renderer):
    page = ".TH T 1\n.SH NAME\nt \\- t\n.XY something\n"
    with pytest.raises(renderer.UnsupportedTroff) as caught:
        renderer.render(page)
    assert ".XY" in str(caught.value)
    assert "line 4" in str(caught.value)


def test_an_unknown_escape_is_refused(renderer):
    page = ".TH T 1\n.SH NAME\nbroken \\(xx escape\n"
    with pytest.raises(renderer.UnsupportedTroff) as caught:
        renderer.render(page)
    assert "line 3" in str(caught.value)


def test_a_code_block_with_no_end_is_refused(renderer):
    page = ".TH T 1\n.SH EXAMPLES\n.EX\nsomething\n"
    with pytest.raises(renderer.UnsupportedTroff):
        renderer.render(page)


def test_a_refused_render_leaves_the_previous_file_untouched(tmp_path):
    """Nothing is written when the render is refused.

    The effect is what is checked, not the exit status: a half-written markdown
    file that looks finished is worse than no file at all, because the next
    reader believes it.
    """
    source = tmp_path / "bad.1"
    source.write_text(".TH T 1\n.SH NAME\n.XY no such macro\n", encoding="utf-8")
    target = tmp_path / "out.md"
    target.write_text("PREVIOUS CONTENT\n", encoding="utf-8")

    result = run_renderer(str(source), str(target))

    assert result.returncode == 2, result.stderr
    assert "CANNOT RENDER" in result.stderr
    assert target.read_text(encoding="utf-8") == "PREVIOUS CONTENT\n"


def test_an_unreadable_source_is_reported(tmp_path):
    result = run_renderer(str(tmp_path / "nothing.1"), str(tmp_path / "out.md"))
    assert result.returncode == 1, result.stderr
    assert "CANNOT RENDER" in result.stderr
    assert not (tmp_path / "out.md").exists()


def test_the_script_writes_the_markdown(tmp_path):
    """The success path, so the refusal tests above are not the only evidence
    the script runs at all."""
    target = tmp_path / "written.md"
    result = run_renderer(str(TROFF), str(target))

    assert result.returncode == 0, result.stderr
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == MARKDOWN.read_text(encoding="utf-8")
