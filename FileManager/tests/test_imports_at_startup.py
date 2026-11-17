"""No module under src/ imports anything inside a function (#54 req 7).

The reason is specific to how this is shipped. Python's zip importer reopens
the archive **by its path** every time it resolves a module, so an import
executed part-way through a run reads whatever `.pyz` is at that path at that
moment -- not the one the process started from. An unattended scan runs for
20+ hours as root, which is long enough for the file to be replaced under it,
and the failure would be a half-old half-new process producing a database
nobody could explain.

Requirement 7 was recorded as "relaxed" for a while because two report arms
imported from `src.reporting` lazily. They were hoisted in #54; this test is
what stops the exception coming back as a one-line convenience.

Parsed with `ast` rather than grepped: a regex over source text cannot tell an
import from the word "import" inside a docstring, and this file's predecessor
in spirit, tests/test_db_owns_the_connection.py, had the same choice to make.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
MODULES = sorted(SRC.glob("*.py"))


def test_the_source_directory_was_actually_found():
    """Without this, an empty MODULES would make the next test vacuous."""
    assert MODULES, f"no modules found under {SRC}"
    assert any(m.name == "main.py" for m in MODULES)


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_every_import_is_at_module_level(module: Path):
    tree = ast.parse(module.read_text(), filename=str(module))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                names = ", ".join(a.name for a in inner.names)
                offenders.append(f"{module.name}:{inner.lineno} imports "
                                 f"{names} inside {node.name}()")

    assert not offenders, (
        "imports inside a function body (#54 requirement 7):\n  "
        + "\n  ".join(offenders)
    )
