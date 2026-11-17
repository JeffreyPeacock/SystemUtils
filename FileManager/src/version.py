"""Answer "which code is this?" for a bundle and for a source checkout.

A zipapp has no git repository to consult: it is one file, installed root-owned
outside any checkout, and zip entries carry file mtimes so two builds of the
same commit differ byte for byte. A checksum of the `.pyz` therefore identifies
a *build*, not a source revision -- which is why the commit is embedded at build
time rather than looked up at run time (#62, #54 requirement 9).

Run from a source checkout there is no embedded value, and this module says so
plainly instead of printing nothing or a placeholder hash. An un-rebuilt bundle
and a source run must not look alike; that confusion is exactly what #57 fixed
in the scan counts, in a different place.

Every git question has three outcomes here, not two: the answer, the other
answer, and **could not ask** -- git missing, not a repository, the command
failing. The third is reported as `CANNOT DETERMINE` and never silently becomes
`clean` (`docs/Development-Principles.md` on a check that cannot run).
"""

import subprocess
from pathlib import Path

from src import build_info

NAME = 'FileManager'
UNKNOWN = 'CANNOT DETERMINE'

#: The one definition of how this project writes a timestamp. **With the zone**,
#: which is the whole requirement (#54 requirement 10): output is read from a log
#: days later, and a bare clock time has already been read against the wrong zone
#: here. `scripts/stamp_build_info.py` imports this rather than keeping a second
#: copy -- the build time and the run header are the same kind of fact, and two
#: format strings is how they come to disagree.
TIME_FORMAT = '%Y-%m-%d %H:%M:%S %Z'

#: The dirty check is scoped to this directory -- the source the artifact is
#: built from. An edit to a repo-root README does not make a bundle's source
#: dirty, and claiming it did would train the reader to pass FM_ALLOW_DIRTY.
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _git(root: Path, *args: str) -> str | None:
    """Run git in `root` and return its stdout, or None if it could not run.

    None means the question could not be answered. It is never conflated with
    an empty answer: `git status --porcelain` prints nothing for a clean tree
    and also prints nothing when it cannot read the repository, so the two are
    distinguished by the return code and by this function's None, not by the
    emptiness of the output.
    """
    try:
        result = subprocess.run(
            ('git', '-C', str(root), *args),
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def live_commit(root: Path) -> str:
    """The commit of the working checkout, or CANNOT DETERMINE with a reason."""
    commit = _git(root, 'rev-parse', 'HEAD')
    if commit is None:
        return f'{UNKNOWN}: git could not be consulted at {root}'
    return commit


def live_tree_state(root: Path) -> str:
    """'clean', 'dirty', or CANNOT DETERMINE -- scoped to `root`."""
    status = _git(root, 'status', '--porcelain', '--', str(root))
    if status is None:
        return f'{UNKNOWN}: git could not be consulted at {root}'
    return 'clean' if status == '' else 'dirty'


def describe(root: Path | None = None) -> list[str]:
    """The lines `--version` prints: a header, then one labelled field each.

    One field per line, labelled, so a log is greppable -- the consumer's
    installer reads the commit with `--version | grep '^commit'` rather than
    parsing a single packed line whose shape would then be a contract.
    """
    root = SOURCE_ROOT if root is None else root
    lines = [NAME]

    if build_info.COMMIT is None:
        # Not a build. Read the live state and label it as such.
        fields = [
            ('commit', live_commit(root)),
            ('built', 'not a build -- source checkout, values read live'),
            ('tree', live_tree_state(root)),
            ('source', str(root)),
        ]
    else:
        if build_info.DIRTY is None:
            tree = f'{UNKNOWN}: the build did not record a tree state'
        else:
            tree = 'dirty at build time' if build_info.DIRTY else 'clean'
        fields = [
            ('commit', build_info.COMMIT),
            ('built', build_info.BUILD_TIME or f'{UNKNOWN}: no build time recorded'),
            ('tree', tree),
            ('source', 'zipapp bundle'),
        ]

    width = max(len(label) for label, _ in fields)
    lines.extend(f'{label.ljust(width)} : {value}' for label, value in fields)
    return lines


def one_line(root: Path | None = None) -> str:
    """The version as a single line, for the run header.

    `describe()` is the answer to "what is this?" asked directly; this is the
    same fact folded into one line of a log, where six lines of provenance in
    front of every run would be read once and skipped forever after.
    """
    if build_info.COMMIT is None:
        root = SOURCE_ROOT if root is None else root
        return f'{live_commit(root)} (source checkout, {live_tree_state(root)})'

    if build_info.DIRTY is None:
        state = f'tree state {UNKNOWN.lower()}'
    else:
        state = 'built dirty' if build_info.DIRTY else 'clean'
    built = build_info.BUILD_TIME or UNKNOWN.lower()
    return f'{build_info.COMMIT} (bundle, built {built}, {state})'
