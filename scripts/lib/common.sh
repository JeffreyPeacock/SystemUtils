# Shared output helpers. Sourced, never executed -- so no shebang and no
# executable bit (see docs/Development-Principles.md section 3).
#
# A slimmed port of SAMD21-LoRa-ProRF's scripts/lib/common.sh. That version
# also carries serial-port discovery, board selection and flock helpers for a
# microcontroller; none of it applies here, and copying it would have meant
# maintaining 200 lines nothing calls.

if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RESET=$'\033[0m'
else
    C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_RESET=''
fi

info()    { printf '%s\n' "$*"; }
dim()     { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
step()    { printf '%s==>%s %s\n' "$C_BOLD" "$C_RESET" "$*"; }
ok()      { printf '%s  ok%s  %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()    { printf '%s warn%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail()    { printf '%s fail%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
die()     { fail "$@"; }
section() { printf '\n== %s ==\n' "$*"; }
need()    { command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed"; }

# FAILURES is a counter the caller maintains; report_result summarises it.
FAILURES="${FAILURES:-0}"
report_result() {
    section 'result'
    if [[ ${FAILURES} -eq 0 ]]; then ok 'all checks passed'; return 0; fi
    printf '%s fail%s %s\n' "$C_RED" "$C_RESET" "${FAILURES} check(s) failed" >&2
    return 1
}

SCRIPTS_DIR="${SCRIPTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPTS_DIR}/.." && pwd)}"
