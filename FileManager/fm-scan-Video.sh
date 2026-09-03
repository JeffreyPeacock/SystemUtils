#!/bin/sh
cd /home/jeffp/Workspace/FileManager
source .venv/bin/activate
set -x
python src/main.py --threads 8 --db-path /home/public/Video.db scan \
    /home/public/Video,/mnt/attached/VIDEO/01/Video,/mnt/attached/VIDEO/02/Video,/mnt/internal/BACKUP/01/Video,/mnt/internal/BACKUP/02/Video


