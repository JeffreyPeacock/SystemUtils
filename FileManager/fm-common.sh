# Shared setup for the fm-*.sh wrappers. Sourced, never executed -- so no
# shebang and no executable bit (docs/Development-Principles.md section 3).
#
# These scripts used to begin:
#
#     cd /home/jeffp/Workspace/FileManager
#     source .venv/bin/activate
#
# That path is a symlink to an OLDER COPY of this project, so the wrappers ran
# code from a different checkout -- a fix landed in this repository had no
# effect on the scheduled scans, silently (#9). And the .venv predates the
# pyenv-virtualenv setup: the interpreter now comes from .python-version.

set -euo pipefail

# Resolve this project from the script's own location, never from a fixed path.
FM_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$FM_DIR"

# The interpreter is whatever .python-version selects. `pyenv exec` is used
# rather than a bare `python` because a shell that inherited VIRTUAL_ENV from
# another project silently wins over the pyenv shim -- so `python` can be a
# completely different interpreter from the one `pyenv version` reports.
if command -v pyenv >/dev/null 2>&1; then
    FM_PYTHON=(pyenv exec python)
else
    echo "pyenv not found; falling back to python3 on PATH ($(command -v python3 || echo none))" >&2
    command -v python3 >/dev/null 2>&1 || { echo "no usable interpreter" >&2; exit 1; }
    FM_PYTHON=(python3)
fi

# Where the database lives. Override per invocation: FM_DB=/tmp/x.db ./fm-...
FM_DB="${FM_DB:-/home/public/Video.db}"
FM_THREADS="${FM_THREADS:-8}"

fm_run() {
    echo "FileManager: ${FM_DIR}"
    echo "interpreter: $("${FM_PYTHON[@]}" --version 2>&1)"
    echo "database   : ${FM_DB}"
    echo "threads    : ${FM_THREADS}"
    set -x
    "${FM_PYTHON[@]}" src/main.py --threads "${FM_THREADS}" --db-path "${FM_DB}" "$@"
}
