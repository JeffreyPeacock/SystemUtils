#!/usr/bin/env bash
# Re-verify every recorded path.
#
# Defaults to --dry-run, because this action DELETES rows and an unmounted
# volume used to take its whole subtree with it (#2). Pass --commit to act.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/fm-common.sh"

case "${1:-}" in
    --commit)  shift ;;
    -h|--help) echo "usage: $0 [--commit] [extra main.py args...]"; exit 0 ;;
    *)         set -- --dry-run "$@"
               echo "NOTE: dry run. Re-run with --commit to remove rows." >&2 ;;
esac

fm_run audit-db "$@"
