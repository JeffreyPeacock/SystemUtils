#!/usr/bin/env bash
# Report files under source-dir that have no match already in the database.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/fm-common.sh"

if [ $# -lt 1 ]; then
    echo "ERROR: Missing 'source-dir'" >&2
    echo "USAGE: $0 source-dir" >&2
    exit 1
fi
[ -d "$1" ] || { echo "ERROR: not a directory: $1" >&2; exit 1; }

fm_run scan-unique-files "$1"
