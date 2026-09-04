#!/usr/bin/env bash
#
# Pre-commit hook: run the gate for whichever utility has staged changes, and
# REFUSE THE COMMIT if it fails.
#
# Install (from the repository root):
#
#     ln -sf ../../scripts/pre-commit-hook.sh .git/hooks/pre-commit
#
# A symlink rather than a copy, so edits here take effect without reinstalling.
# Remove it with `rm .git/hooks/pre-commit`.
#
# ---------------------------------------------------------------------------
# WHY IT BLOCKS RATHER THAN WARNS
#
# Decided by the repository owner on 2026-09-04 (#16): a failing hook fails the
# commit.
#
# The gate costs about 2.3 seconds -- pytest with coverage, plus mypy -- so
# blocking is nearly free, and a broken commit never enters the history, which
# keeps `git bisect` meaningful and avoids "fix the previous commit" noise.
#
# The argument against, recorded so nobody has to re-derive it: a blocking hook
# is the kind people learn to reflexively `--no-verify` past, and CI already
# gates every push and pull request, so this is not the last line of defence.
# It was chosen anyway because this repository's own workflow permits committing
# documentation directly to `main`, and those commits get no PR gate at all.
#
# The escape hatch is deliberate and normal: `git commit --no-verify` for
# work-in-progress on a branch. Use it rather than weakening the hook.
#
# ---------------------------------------------------------------------------
# WHAT IT DOES NOT DO
#
# It tests the WORKING TREE, not the staged snapshot. If you stage part of a
# change, the hook can pass while the commit itself is broken. Testing the
# index properly means stashing the unstaged remainder and restoring it
# afterwards, and a stash/restore that goes wrong inside a hook can lose work --
# a worse failure than the one it prevents. CaptureServer's hook has the same
# limitation. If this ever bites, fix it with `git worktree add` on a temporary
# checkout of the index, not with `git stash`.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
# shellcheck source=lib/common.sh
source "${REPO_ROOT}/scripts/lib/common.sh"

# A utility is any top-level directory carrying its own pytest.ini.
utilities_with_staged_changes() {
    local staged util
    staged="$(git diff --cached --name-only)"
    [ -n "${staged}" ] || return 0
    while IFS= read -r path; do
        util="${path%%/*}"
        [ "${util}" = "${path}" ] && continue          # a repo-root file
        [ -f "${REPO_ROOT}/${util}/pytest.ini" ] || continue
        printf '%s\n' "${util}"
    done <<< "${staged}" | sort -u
}

# True when every staged file under this utility is documentation.
only_docs_staged() {
    local util="$1" total docs
    total=$(git diff --cached --name-only -- "${util}" | grep -c . || true)
    docs=$(git diff --cached --name-only -- "${util}" | grep -cE '\.(md|txt)$' || true)
    [ "${total}" -gt 0 ] && [ "${total}" -eq "${docs}" ]
}

mapfile -t UTILITIES < <(utilities_with_staged_changes)

if [ ${#UTILITIES[@]} -eq 0 ]; then
    # Nothing staged, or nothing staged inside a utility -- a repo-root README
    # or a .claude/ change. There is no suite to run; that is not a failure.
    exit 0
fi

FAILED=()
for util in "${UTILITIES[@]}"; do
    if only_docs_staged "${util}"; then
        info "${util}: documentation only — skipping the suite"
        continue
    fi

    section "${util}"
    cd "${REPO_ROOT}/${util}"

    # `pyenv exec` rather than a bare `python`: a shell that inherited
    # VIRTUAL_ENV from another project silently beats the pyenv shim.
    if command -v pyenv >/dev/null 2>&1; then
        PY=(pyenv exec python)
    else
        command -v python3 >/dev/null 2>&1 \
            || fail "${util}: no usable interpreter (pyenv absent, python3 absent)"
        PY=(python3)
    fi

    # pytest.ini enforces the coverage floor, so a coverage regression fails
    # here too. That is intended: the floor is a ratchet, and a commit that
    # lowers coverage should be a deliberate act, not a silent one.
    if "${PY[@]}" -m pytest -q; then
        ok "${util}: tests pass"
    else
        warn "${util}: tests FAILED"
        FAILED+=("${util}: pytest")
    fi

    if "${PY[@]}" -m mypy src/; then
        ok "${util}: mypy clean"
    else
        warn "${util}: mypy FAILED"
        FAILED+=("${util}: mypy")
    fi

    cd "${REPO_ROOT}"
done

if [ ${#FAILED[@]} -gt 0 ]; then
    section 'commit refused'
    for entry in "${FAILED[@]}"; do
        printf '  %s\n' "${entry}" >&2
    done
    warn 'Fix the above, or commit work-in-progress with: git commit --no-verify'
    exit 1
fi

ok 'pre-commit gate passed'
exit 0
