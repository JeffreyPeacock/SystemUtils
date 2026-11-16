#!/usr/bin/env bash
#
# Bundle FileManager into a single executable file: fm.pyz
#
# Usage (from anywhere):
#
#     FileManager/scripts/build-pyz.sh [output-path]
#
# Default output is FileManager/fm.pyz. Both it and build/ are gitignored --
# this is a build artifact, not something to commit.
#
# ---------------------------------------------------------------------------
# WHY A ZIPAPP RATHER THAN PYINSTALLER
#
# This project is standard-library only, so there are no third-party packages
# to vendor. `python -m zipapp` is in the standard library and produces a ~56K
# single file; PyInstaller would add a build dependency to a repository that
# deliberately has none, and embedding a whole interpreter buys nothing when
# python3 is already present on every machine this runs on (#52).
#
# ---------------------------------------------------------------------------
# WHY THIS EXISTS AT ALL: sudo AND THE WRONG INTERPRETER
#
# A whole-filesystem scan has to run as root -- thousands of files under
# /home2 are unreadable to an ordinary user, and a file the scanner cannot
# read contributes nothing to the database.
#
# But `sudo python src/main.py` does not do what it looks like. sudo resolves
# `python` from ROOT's PATH, not from the pyenv shim, so it silently runs a
# different interpreter or none at all. The -p shebang below is the entire
# point of this script: it pins `/usr/bin/env python3` into the archive, so
# the bundle no longer depends on the caller's PATH or on pyenv existing.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${HERE}")"           # .../FileManager
BUILD_DIR="${PROJECT_ROOT}/build/pyz"
OUTPUT="${1:-${PROJECT_ROOT}/fm.pyz}"

# The interpreter that BUILDS the archive. `pyenv exec` deliberately, for the
# same reason the wrapper scripts use it: a shell that inherited VIRTUAL_ENV
# from another project silently beats the pyenv shim, so a bare `python` can
# be a different interpreter from the one `pyenv version` reports.
#
# Note this is not the interpreter that RUNS the bundle -- that one comes from
# the -p shebang and is resolved at run time on the target machine.
if command -v pyenv >/dev/null 2>&1; then
    PY=(pyenv exec python)
elif command -v python3 >/dev/null 2>&1; then
    PY=(python3)
else
    echo "CANNOT BUILD: no usable interpreter (pyenv absent, python3 absent)" >&2
    exit 1
fi

echo "project    : ${PROJECT_ROOT}"
echo "builder    : $("${PY[@]}" -V 2>&1) ($(command -v "${PY[0]}"))"
echo "output     : ${OUTPUT}"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
cp -r "${PROJECT_ROOT}/src" "${BUILD_DIR}/"

cat > "${BUILD_DIR}/__main__.py" <<'ENTRY'
import sys

from src.main import main

sys.exit(main())
ENTRY

# Clear __pycache__ before archiving, and do not treat this as housekeeping.
# `cp -r src` copies any .pyc alongside the source, and a zipapp will serve
# stale bytecode quite happily: CPython invalidates a .pyc on (mtime, size),
# so a file rewritten to the same length inside the same one-second tick keeps
# the old bytecode. That has already produced a wrong answer in this
# repository -- a restored file still failing because the broken variant's
# .pyc was reused.
find "${BUILD_DIR}" -name '__pycache__' -type d -exec rm -rf {} +

"${PY[@]}" -m zipapp "${BUILD_DIR}" -o "${OUTPUT}" -p '/usr/bin/env python3'
chmod +x "${OUTPUT}"

# Verify the EFFECT, not the exit status of the build. A zipapp can be written
# successfully and still be unrunnable -- a missing __main__.py, an import that
# resolves from the source tree but not from inside the archive. So run the
# thing. `help` is the one action that touches no database and no filesystem.
#
# Run it from a directory unrelated to the project, because running it from
# inside FileManager/ would let `src.` imports resolve from the working
# directory rather than from the archive, which is precisely the failure this
# check exists to catch.
if ! (cd / && "${OUTPUT}" help >/dev/null); then
    echo "BUILD PROBLEM: ${OUTPUT} was written but does not run" >&2
    exit 1
fi

printf 'built      : %s (%s)\n' "${OUTPUT}" "$(du -h "${OUTPUT}" | cut -f1)"
echo 'verified   : runs from / and prints its help'
echo
echo 'Run a scan as root. Keep the database OUTSIDE every scanned tree --'
echo 'a .db inside the target is found by os.walk and scanned like any other file:'
echo
echo "    sudo ${OUTPUT} --threads 8 --db-path /var/lib/filemanager/home2.db scan /home2"
