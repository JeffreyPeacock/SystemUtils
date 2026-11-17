#!/usr/bin/env bash
#
# Bundle FileManager into a single executable file: dist/FileManager.pyz
#
# Usage (from anywhere):
#
#     FileManager/scripts/build-pyz.sh [output-path]
#
# Default output is FileManager/dist/FileManager.pyz.
#
# The NAME is the repository owner's choice (2026-11-16): `fm` was too short to
# recognise in a process list or a log. #54 had specified `filemanager.pyz`;
# the change is recorded on that ticket, because the Desktop-Ops installer
# reads this path and a silent rename breaks it. dist/ and build/ are
# gitignored -- this is a build artifact, not something to commit.
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
# point of this script: it pins the interpreter into the archive, so the bundle
# no longer depends on the caller's PATH or on pyenv existing.
#
# THE SHEBANG IS `#!/usr/bin/python3 -I`, AND EACH PART MATTERS:
#
#   -I is isolated mode: it ignores PYTHONPATH, the user site directory, and
#   the script's directory. For a root-run executable that is the difference
#   between reading only its own code and picking up whatever an ordinary user
#   left on PYTHONPATH. Verified: with -I, `PYTHONPATH=/nonexistent` changes
#   nothing and sys.path[0] is the archive itself.
#
#   /usr/bin/python3 is absolute, NOT `/usr/bin/env python3`, because the two
#   cannot be combined with an option. Linux passes everything after the
#   interpreter path to it as ONE argument, so `#!/usr/bin/env python3 -I`
#   hands env the single argument "python3 -I" and fails.
#
#   EXACTLY ONE option, for the same reason. Measured: a shebang of
#   `/usr/bin/python3 -I -B` dies with `Unknown option: - ` and exit 2, because
#   "-I -B" arrives as one string.
#
# Fixed by agreement with the Desktop-Ops consumer (#54), whose installer
# asserts on `head -1`.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${HERE}")"           # .../FileManager
BUILD_DIR="${PROJECT_ROOT}/build/pyz"
OUTPUT="${1:-${PROJECT_ROOT}/dist/FileManager.pyz}"

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

# Record what this archive was built from, into the COPY of src/ -- never into
# the checkout. The committed src/build_info.py holds None for every field, and
# that None is how --version knows it is not running from a bundle (#62).
#
# This refuses a dirty tree, and refuses just as hard when git cannot be
# consulted at all: a bundle that names a commit it does not contain is worse
# than one that admits it does not know. FM_ALLOW_DIRTY=1 overrides, and the
# artifact then reports "dirty at build time" for the rest of its life.
if ! "${PY[@]}" "${HERE}/stamp_build_info.py" "${BUILD_DIR}/src/build_info.py"; then
    echo "BUILD STOPPED: the build provenance could not be recorded (above)." >&2
    echo "  A bundle whose --version cannot name its commit is not installable;" >&2
    echo "  the consumer's installer reads it before putting the file in place (#54)." >&2
    exit 1
fi

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

mkdir -p "$(dirname "${OUTPUT}")"
"${PY[@]}" -m zipapp "${BUILD_DIR}" -o "${OUTPUT}" -p '/usr/bin/python3 -I'
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
# PYTHONPATH is poisoned on purpose: the consumer runs this as root from an
# arbitrary environment (#54), and -I is what makes that safe. If the shebang
# ever loses -I, this is the line that notices.
if ! (cd / && PYTHONPATH=/nonexistent/should/not/matter "${OUTPUT}" help >/dev/null); then
    echo "BUILD PROBLEM: ${OUTPUT} was written but does not run" >&2
    exit 1
fi

# --version has to work from the installed artifact, not just in a test: it is
# the consumer's gate before installing (#54 requirement 9). Checked here for
# the same reason the help run is -- verify the effect, not the exit status of
# the build. A 40-character hex commit, or this is not installable.
if ! version_out="$(cd / && PYTHONPATH=/nonexistent/should/not/matter "${OUTPUT}" --version)"; then
    echo "BUILD PROBLEM: ${OUTPUT} could not answer --version at all." >&2
    exit 1
fi
if ! printf '%s\n' "${version_out}" | grep -qE '^commit +: +[0-9a-f]{40}$'; then
    echo "BUILD PROBLEM: --version did not report an embedded commit." >&2
    printf '  got:\n%s\n' "${version_out}" >&2
    exit 1
fi
if printf '%s\n' "${version_out}" | grep -q 'source checkout'; then
    echo "BUILD PROBLEM: the archive reports itself as a source checkout," >&2
    echo "  which means src/build_info.py was not stamped into it." >&2
    exit 1
fi

shebang="$(head -1 "${OUTPUT}")"
if [ "${shebang}" != '#!/usr/bin/python3 -I' ]; then
    echo "BUILD PROBLEM: shebang is '${shebang}', expected '#!/usr/bin/python3 -I'" >&2
    echo "  The consumer's installer asserts on this exact line (#54)." >&2
    exit 1
fi

printf 'built      : %s (%s)\n' "${OUTPUT}" "$(du -h "${OUTPUT}" | cut -f1)"
printf 'version    : %s\n' "$(printf '%s\n' "${version_out}" | tr '\n' ' ')"
echo 'verified   : runs from /, prints its help, and names its commit'
echo
echo 'Run a scan as root. Keep the database OUTSIDE every scanned tree --'
echo 'a .db inside the target is found by os.walk and scanned like any other file:'
echo
echo "    sudo ${OUTPUT} --threads 8 --db-path /var/lib/filemanager/home2.db scan /home2"
