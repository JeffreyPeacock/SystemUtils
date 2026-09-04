#!/usr/bin/env bash
# Scan every Video tree into the database.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/fm-common.sh"

FM_VIDEO_DIRS="${FM_VIDEO_DIRS:-/home/public/Video,/mnt/attached/VIDEO/01/Video,/mnt/attached/VIDEO/02/Video,/mnt/internal/BACKUP/01/Video,/mnt/internal/BACKUP/02/Video}"

fm_run scan "$FM_VIDEO_DIRS"
