#!/usr/bin/env bash
#
# Regenerate the numbered fixture files. Run from the directory to fill:
#
#   cd test_data/data       && ../bin/generate-files.sh
#   cd test_data/duplicate_data && ../bin/generate-files.sh
#
# data/ and duplicate_data/ must stay a byte-identical pair, file for file --
# that pairing IS the duplicate-detection fixture. Regenerating one without
# the other breaks tests with a FileNotFoundError that names nothing useful.

set -euo pipefail

for i in $(seq -w 1 20); do
    uuid > "test-file-${i}.txt"
done
