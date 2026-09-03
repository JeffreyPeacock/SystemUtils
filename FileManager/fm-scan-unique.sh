#!/bin/bash
if [ -z "$1" ]; then
    echo "ERROR: Missing 'source-dir'"
    echo "USAGE: $0 source-dir"
    exit 1
fi

cd /home/jeffp/Workspace/FileManager
source .venv/bin/activate
set -x
python src/main.py --threads 8 --db-path /home/public/Video.db scan-unique-files $1


