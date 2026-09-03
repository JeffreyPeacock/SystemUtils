# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI tool that recursively walks directories, computes an MD5 checksum for every
file, and stores `(md5sum, size, last_modified, path)` in a SQLite database. The
database is then queried to find duplicate files across separate filesystems and
mount points. `doc/REQUIREMENTS.txt` is the original specification; a fair amount
of it (notably the "full featured graphical user-interface" and 95% coverage) is
not implemented.

Python 3.12, stdlib only. `requirements.txt` lists `argparse` and `logging`, both
of which are already in the standard library — there are no third-party runtime
dependencies. The `.venv` contains Jupyter and other packages that nothing in
`src/` uses.

The git repository root is the *parent* directory,
`~/Workspace/JeffreyPeacock.com/SystemUtils`, not this one. Paths in git
commands are therefore prefixed with `FileManager/`. The `.gitignore` in this
directory still governs this subtree, since gitignore patterns resolve relative
to the file that declares them.

## Commands

All commands run from the repository root. `src/main.py` prepends the repository
root to `sys.path`, and every module imports its siblings as `src.<module>`, so
running from anywhere else breaks the imports.

```sh
source .venv/bin/activate

# Scan (comma-separated list of directories and/or files)
python src/main.py --threads 8 --db-path /path/to/db.db scan /dir/one,/dir/two

# Re-verify every recorded path; drop rows for files that no longer exist
python src/main.py --threads 8 --db-path /path/to/db.db audit-db \
    --exclude-prefix /mnt/offline,/mnt/other

python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 1
python src/main.py --db-path /path/to/db.db report-duplicate-sizes
python src/main.py help          # full action/option list

# Tests
python -m pytest tests/ -q
python -m pytest tests/test_md5sum.py -q                       # one module
python -m pytest tests/test_md5sum.py::TestComputeMD5 -q           # one class
python -m coverage run -m pytest tests/ && python -m coverage report
```

There is no linter, formatter, or pytest configuration in the repository.

## Current broken state

`tests/test_db.py` and `tests/test_audit_db.py` fail at import: they reference
`remove_file_info` and `remove_files_by_regex`, which do not exist. The functions
in `src/db.py` are named `remove_record` and `remove_records_by_regex`. Only
`tests/test_md5sum.py` and `tests/test_get_file_mtime_in_ms.py` collect and pass
(10 tests).

The `fm-*.sh` wrapper scripts `cd /home/jeffp/Workspace/FileManager`, which is a
symlink to a *different, older copy* of this repository
(`~/Workspace/File-Manager/github-copilot/FileManager`). They do not run the code
in this directory.

## Architecture

`src/main.py` is an argparse dispatcher — one `elif` per action — and holds no
logic beyond argument validation. Everything below it is a flat module layer with
no classes:

- `src/db.py` — every `sqlite3` call that writes, plus the duplicate-finding
  queries. Owns the schema and the lock-retry behavior.
- `src/file_ops.py` — directory walking and the decision of whether a file needs
  hashing. `process_file` is the core routine.
- `src/reporting.py` — read-only queries that print to stdout. Note that it also
  opens its own `sqlite3` connections rather than going through `db.py`.
- `src/gui.py` — a Tkinter duplicate browser, reached only via
  `report-duplicates --use-gui`. It writes `rm_commands.txt` rather than deleting
  anything itself.
- `src/md5sum.py`, `src/utils.py` — `compute_md5` (4 KB chunks) and
  `get_file_mtime_in_ms`.

### Schema

One table, created on every run by `initialize_db`:

```sql
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    md5sum TEXT,
    size INTEGER,
    last_modified INTEGER,
    path TEXT UNIQUE
)
```

There are no indexes beyond the implicit `path` unique index, so duplicate
reporting is a full table scan and group-by.

If `--db-path` names an existing directory, `file_manager.db` is appended to it.
If `--db-path` is omitted entirely, the database is `./file_manager.db` in the
current directory.

### The skip check

`process_file` (`src/file_ops.py:63`) is what makes rescanning a large tree cheap:
it reads the stored `size` and `last_modified` for the path and returns without
hashing when both match. `last_modified` is `int(os.path.getmtime(path) * 1000)`
— milliseconds as an integer. Any change to how mtime is stored or compared
invalidates every existing database and forces a full rehash, so keep
`get_file_mtime_in_ms` and the inline computation in `process_file` in agreement.

### Concurrency and SQLite

Threads are the only concurrency model. `scan_dir` uses a producer thread feeding
a `Queue` consumed by `--threads` workers, terminated by one empty-string
sentinel per worker. `audit_db` and `scan_and_report_unique_files` use
`ThreadPoolExecutor` directly.

No connection is shared between threads. Every function opens `sqlite3.connect`,
runs its statement, and closes. Writers (`store_file_info`, `remove_record`,
`remove_records_by_regex`, `audit_db`) wrap that in a retry loop: up to
`MAX_RETRIES = 10` attempts, sleeping 0.1s, catching only
`OperationalError` containing "database is locked" and re-raising anything else.
Read paths have no such retry. `audit_db` sets `PRAGMA journal_mode=WAL`; nothing
else does, so a database that has never been audited is in rollback-journal mode.

### Behaviors that will surprise you

- **Two different `remove_record` functions.** `src/db.py:remove_record` deletes
  one exact path. `src/file_ops.py:remove_record` takes a *regex* and deletes
  every matching row. `main.py` imports the `file_ops` one, so the
  `remove-record` CLI action matches by regex despite the usage text saying
  "the record associated with the specified path".
- **`--min-duplicates` is off by one.** `find_duplicates_with_min_count` uses
  `HAVING COUNT(*) > ?`, so the default of 1 returns groups of 2 or more.
- **Comma-separated paths from SQL.** The same function builds its result with
  `GROUP_CONCAT(path)` and splits on `,`, so any file path containing a comma is
  torn into fragments.
- **`report-duplicate-sizes` divides by two.** It sums the size of every row in a
  duplicated group and halves the total, approximating "space reclaimed if one
  copy of each is kept". That is only correct for groups of exactly two.
- **`scan-unique-files` writes into the directory it scans.** It appends a
  `.processed_files.txt` resume log at the root of the target directory and reads
  it back on the next run. Delete it to force a full recheck.
- **`compare-directories` ignores the database.** It hashes both trees in full,
  in-process, and compares with an O(n·m) `md5 not in dict.values()` scan.

### Logging output

Logging goes to stderr at INFO. The scan path also writes a bare `.` to stdout
per skipped file, so redirecting stdout from a large rescan produces a long line
of dots mixed with any report output.
