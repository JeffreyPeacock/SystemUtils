#!/usr/bin/env python3
"""Write build provenance into the copy of `src/` that will be archived.

Called by `scripts/build-pyz.sh` after it copies `src/` into `build/pyz/` and
before `python -m zipapp` runs, so the archive carries the commit it was built
from (#62, #54 requirement 9). The committed `src/build_info.py` holds None for
every field; this script replaces that copy, never the one in the checkout.

**It refuses to stamp a dirty tree.** #54 asks for that, and the reason is that
a bundle built from uncommitted edits names a commit that does not contain the
code inside it -- the single worst answer `--version` could give, because it is
confidently wrong rather than unknown. `FM_ALLOW_DIRTY=1` overrides, and then
the artifact says `dirty at build time` whenever it is asked.

**A git check that cannot run is not a clean tree.** Three outcomes, and the
third refuses rather than stamping an unverified claim: `git status --porcelain`
prints nothing for a clean tree *and* nothing when it cannot read the
repository, so emptiness alone proves nothing (`docs/Development-Principles.md`).

Usage:

    stamp_build_info.py <output-file> [<source-root>]

`<source-root>` defaults to this script's `FileManager/` directory and is the
scope of the dirty check -- the source the artifact is built from, so an edit to
a repo-root README does not refuse the build.
"""

import datetime
import os
import subprocess
import sys
from pathlib import Path

# The timestamp format is defined once, in src/version.py, and imported here
# rather than copied: the build time this script records and the header every
# run prints are the same kind of fact, and two format strings is how they come
# to disagree. This script is invoked by path from build-pyz.sh, so the project
# root is not on sys.path yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.version import TIME_FORMAT, git_env  # noqa: E402

ALLOW_DIRTY_ENV = 'FM_ALLOW_DIRTY'

TEMPLATE = '''\
"""Build provenance, written by scripts/stamp_build_info.py. Do not edit.

Generated for a build; the committed copy of this module holds None for every
field. See src/version.py for what is done with these values.
"""

COMMIT: str | None = {commit!r}
BUILD_TIME: str | None = {build_time!r}
DIRTY: bool | None = {dirty!r}
'''


def git(root: Path, *args: str) -> str | None:
    """git stdout, or None when the question could not be asked at all.

    The environment is scrubbed of `GIT_*` by `git_env()`: an inherited
    `GIT_DIR` or `GIT_INDEX_FILE` overrides `-C <root>`, so the tree state
    recorded in the artifact would be some other repository's (#71). This
    script runs from a build, and a build can be driven from a git hook.
    """
    try:
        result = subprocess.run(
            ('git', '-C', str(root), *args),
            capture_output=True, text=True, timeout=10, env=git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__, file=sys.stderr)
        return 2

    out = Path(argv[1])
    root = Path(argv[2]).resolve() if len(argv) == 3 \
        else Path(__file__).resolve().parent.parent

    commit = git(root, 'rev-parse', 'HEAD')
    if commit is None:
        print(f'CANNOT STAMP: git could not be consulted at {root}.',
              file=sys.stderr)
        print('  Needed: a git checkout and git on PATH. Refusing to record a '
              'build with no provenance.', file=sys.stderr)
        return 1

    status = git(root, 'status', '--porcelain', '--', str(root))
    if status is None:
        print(f'CANNOT STAMP: git status failed at {root}, so the tree state '
              'is unknown.', file=sys.stderr)
        print('  An unknown tree state is not a clean one. Refusing.',
              file=sys.stderr)
        return 1

    dirty = status != ''
    if dirty and os.environ.get(ALLOW_DIRTY_ENV) != '1':
        print(f'CANNOT STAMP: {root} has uncommitted changes, so the commit '
              f'{commit[:12]} does not describe the code being archived.',
              file=sys.stderr)
        print('  Commit them, or set FM_ALLOW_DIRTY=1 to build anyway -- the '
              'artifact will then report "dirty at build time".',
              file=sys.stderr)
        for line in status.splitlines()[:10]:
            print(f'    {line}', file=sys.stderr)
        return 1

    built = datetime.datetime.now().astimezone().strftime(TIME_FORMAT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.format(commit=commit, build_time=built,
                                   dirty=dirty))
    state = 'dirty' if dirty else 'clean'
    print(f'stamped    : {commit[:12]} {built} ({state})')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
