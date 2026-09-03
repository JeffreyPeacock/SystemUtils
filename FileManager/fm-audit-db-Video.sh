#!/bin/bash
cd /home/jeffp/Workspace/FileManager
source .venv/bin/activate
set -x
python src/main.py --threads 8 --db-path /home/public/Video.db audit-db


