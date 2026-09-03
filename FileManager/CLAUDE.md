# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repo-wide workflow, branch naming, and board configuration are in the
**repo-root `CLAUDE.md`** one directory up. This file covers FileManager only.

## Documentation Hierarchy

**`CLAUDE.md`** (this file) = operational reference: commands, config, non-obvious constraints, gotchas. **Target <34k chars, hard limit 40k.** · **`README.md`** = new-developer orientation · **`doc/Architecture+Design.md`** = design decisions (problem / decision / alternatives rejected) · **`doc/REQUIREMENTS.txt`** = the original 2024 specification · repo-root **`doc/Development-Principles.md`** = durable lessons about building and sequencing.

**When trimming, assign every removed item to one of those *before* deleting it.**

## What this is

A CLI that recursively walks directories, computes an MD5 checksum for every
file, and stores `(md5sum, size, last_modified, path)` in SQLite. The database is
then queried to find duplicate files across separate filesystems and mount
points. Its output is a list of files a human may then delete — a wrong answer
has consequences past this process, which is what makes the correctness notes
below worth reading before changing anything.

`doc/REQUIREMENTS.txt` is the original specification. Two of its requirements are
**not met**: the "full featured graphical user-interface" (only a paginated
Tkinter duplicate list exists) and 95% coverage (actual: 29.81%).

## Tech Stack

**Python 3.14.7** · **sqlite3** · **hashlib** · **argparse** · **threading** + **concurrent.futures** + **queue** · **tkinter** (optional GUI) · **pytest** + **pytest-cov** (`pytest.ini`) · **mypy** (`mypy.ini`).

Standard library only — there are no runtime dependencies. `requirements.txt` is
deliberately empty of packages; test and type tooling is in
`requirements-dev.txt`.

## Commands

All commands run **from this directory** (`SystemUtils/FileManager`).
`src/main.py` prepends its parent to `sys.path` and every module imports its
siblings as `src.<module>`, so running from anywhere else breaks the imports.
Note that git paths carry a `FileManager/` prefix, because the repo root is one
level up.

```sh
# Scan (comma-separated list of directories and/or files)
python src/main.py --threads 8 --db-path /path/to/db.db scan /dir/one,/dir/two

# Re-verify every recorded path; drop rows for files that no longer exist
python src/main.py --threads 8 --db-path /path/to/db.db audit-db \
    --exclude-prefix /mnt/offline,/mnt/other

python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 1
python src/main.py --db-path /path/to/db.db report-duplicate-sizes
python src/main.py help          # full action/option list

# Tests — pytest.ini turns on coverage and enforces the floor
python -m pytest
python -m pytest tests/test_md5sum.py                       # one module
python -m pytest tests/test_md5sum.py::TestComputeMD5       # one class
python -m pytest --no-cov -q                                # skip the floor while iterating

# Types
python -m mypy src/
```

## Testing

21 tests across 4 modules, all passing. Coverage is on by default via
`pytest.ini` (`--cov=src --cov-branch`), writes `coverage.xml` and
`test-results.xml`, and enforces `--cov-fail-under=29` against a measured
**29.81%** line+branch coverage.

Current coverage by module — `md5sum` is the only well-covered one:

| Module | Coverage |
|--------|----------|
| `src/md5sum.py` | 100% |
| `src/db.py` | 59% |
| `src/utils.py` | 33% |
| `src/reporting.py` | 16% |
| `src/file_ops.py` | 14% |
| `src/gui.py` | 9% |
| `src/main.py` | 9% |

**The floor is a ratchet — it only goes up.** Raise `--cov-fail-under` in the
same PR that raises real coverage; never lower it to make a red build green.
Same rule for the per-module opt-out stanzas in `mypy.ini`: a module leaves that
list by being annotated. Reasoning in repo-root `doc/Development-Principles.md` §4.

Fixtures live in `test_data/`. `data/` and `duplicate_data/` are a
**byte-identical pair, file for file** — that pairing is the duplicate-detection
fixture, and a file present in one but not the other breaks tests with a
`FileNotFoundError` that names nothing useful. `test_data/bin/generate-files.sh`
regenerates the numbered files.

## Architecture

`src/main.py` is an argparse dispatcher — one `elif` per action — with no logic
beyond argument validation. Below it is a flat module layer, no classes:

- `src/db.py` — every `sqlite3` write, plus the duplicate-finding queries. Owns the schema and the lock-retry behaviour.
- `src/file_ops.py` — directory walking and the decision of whether a file needs hashing. `process_file` is the core routine.
- `src/reporting.py` — read-only queries that print to stdout. Note it opens its own `sqlite3` connections rather than going through `db.py`.
- `src/gui.py` — a Tkinter duplicate browser, reached only via `report-duplicates --use-gui`. Writes `rm_commands.txt` rather than deleting anything itself.
- `src/md5sum.py`, `src/utils.py` — `compute_md5` (4 KB chunks) and `get_file_mtime_in_ms`.

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

No indexes beyond the implicit `path` unique index, so duplicate reporting is a
full table scan and group-by.

If `--db-path` names an existing directory, `file_manager.db` is appended to it.
If `--db-path` is omitted, the database is `./file_manager.db` in the current
directory.

### The skip check

`process_file` (`src/file_ops.py:63`) is what makes rescanning a large tree
cheap: it reads the stored `size` and `last_modified` for the path and returns
without hashing when both match. `last_modified` is
`int(os.path.getmtime(path) * 1000)` — milliseconds as an integer.

**Any change to how mtime is stored or compared invalidates every existing
database and forces a full rehash of every recorded file.** Keep
`get_file_mtime_in_ms` and the inline computation in `process_file` in agreement.

### Concurrency and SQLite

Threads are the only concurrency model. `scan_dir` uses a producer thread feeding
a `Queue` consumed by `--threads` workers, terminated by one empty-string
sentinel per worker. `audit_db` and `scan_and_report_unique_files` use
`ThreadPoolExecutor` directly.

No connection is shared between threads. Every function opens `sqlite3.connect`,
runs its statement, and closes. Writers (`store_file_info`, `remove_record`,
`remove_records_by_regex`, `audit_db`) wrap that in a retry loop: up to
`MAX_RETRIES = 10` attempts, sleeping 0.1s, catching only `OperationalError`
containing "database is locked" and re-raising anything else. **Read paths have
no such retry.** `audit_db` sets `PRAGMA journal_mode=WAL`; nothing else does, so
a database that has never been audited is still in rollback-journal mode.

## Behaviours that will surprise you

Every entry here is a trap someone already fell into. Do not trim this section.

- **Two different `remove_record` functions.** `src/db.py:remove_record` deletes one exact path. `src/file_ops.py:remove_record` takes a **regex** and deletes every matching row. `main.py` imports the `file_ops` one, so the `remove-record` CLI action matches by regex despite its usage text saying "the record associated with the specified path".
- **That regex is `re.match`, so it is prefix-anchored and unterminated.** `remove_records_by_regex` calls `re.match(pattern, path)`, which anchors at the start of the string but not the end. Passing a literal path `/a/b` therefore also deletes `/a/bc` and everything under `/a/b-old/`. A pattern that does not start at the filesystem root matches nothing at all.
- **`--min-duplicates` is off by one.** `find_duplicates_with_min_count` uses `HAVING COUNT(*) > ?`, so the default of 1 returns groups of 2 or more.
- **Comma-separated paths from SQL.** The same function builds its result with `GROUP_CONCAT(path)` and splits on `,`, so any file path containing a comma is torn into fragments.
- **`report-duplicate-sizes` divides by two.** It sums the size of every row in a duplicated group and halves the total, approximating "space reclaimed if one copy of each is kept". That is only correct for groups of exactly two.
- **`scan-unique-files` writes into the directory it scans.** It appends a `.processed_files.txt` resume log at the root of the target directory and reads it back on the next run. Delete it to force a full recheck.
- **`compare-directories` ignores the database.** It hashes both trees in full, in-process, and compares with an O(n·m) `md5 not in dict.values()` scan.
- **`audit-db --exclude-prefix` is the only guard against an unmounted volume.** Without it, every path under a volume that failed to mount looks deleted and its rows are removed. There is no dry-run mode.

## Logging output

Logging goes to stderr at INFO. The scan path also writes a bare `.` to stdout
per skipped file, so redirecting stdout from a large rescan produces a long line
of dots mixed with any report output.

## Shell wrappers

`fm-scan-Video.sh`, `fm-scan-unique.sh`, and `fm-audit-db-Video.sh` all
`cd /home/jeffp/Workspace/FileManager` — a symlink to a **different, older copy**
of this project (`~/Workspace/File-Manager/github-copilot/FileManager`) with its
own `.venv`. **They do not run the code in this directory.** They also predate
the pyenv-virtualenv setup and still `source .venv/bin/activate`. Repointing them
is open work.

`cmpdirs.sh` is gitignored — its paths are machine-specific.

## Backlog

Tracked on the board: https://github.com/users/JeffreyPeacock/projects/14
(filter `component:file-manager`). Known work not yet filed as issues:

- Coverage is 29.81% against a 95% requirement; `main.py`, `gui.py`, `reporting.py`, and `file_ops.py` are all under 20%
- The `fm-*.sh` wrappers point at the old copy of the project
- `src/reporting.py` opens its own SQLite connections instead of using `db.py`
