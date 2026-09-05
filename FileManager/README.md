# FileManager

Finds duplicate files across separate filesystems and mount points. It walks a
directory tree, computes an MD5 checksum for every file, records
`(md5sum, size, last_modified, path)` in a SQLite database, and then answers
questions against that database — which files are duplicates, how much space they
occupy, what exists in one tree but not another.

Part of [SystemUtils](../README.md). Standard-library Python only.

### Documentation map

| File | Purpose |
|------|---------|
| `README.md` (this file) | New-developer orientation — what it does, how to run it, how it works |
| `CLAUDE.md` | Operational reference for Claude Code: commands, invariants, gotchas |
| [`docs/Architecture+Design.md`](docs/Architecture+Design.md) | Design decision record — problem, decision, alternatives rejected |
| [`docs/REQUIREMENTS.txt`](docs/REQUIREMENTS.txt) | The original 2024 specification, kept as written |
| [`../docs/Development-Principles.md`](../docs/Development-Principles.md) | Repo-wide principles on building and sequencing work |

---

## Why it is built this way

Hashing a multi-terabyte archive is expensive, and the point of this tool is to
be run **repeatedly** over the same trees as they grow. So the database is not
just a result — it is a cache. Before hashing anything, `process_file` compares
the file's current size and modification time against what the database already
holds and skips the read entirely when both match. A rescan of an unchanged
archive touches metadata only.

Everything else follows from that: the schema stores size and mtime alongside the
checksum, `audit-db` exists to re-verify the cache against reality, and mtime is
stored as an integer count of milliseconds so the comparison is exact rather than
a float equality test.

---

## Running it

All commands run from this directory.

```bash
# Build or update the database over one or more trees
python src/main.py --threads 8 --db-path /path/to/db.db scan /dir/one,/dir/two

# Report
python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 2
python src/main.py --db-path /path/to/db.db report-duplicate-sizes
python src/main.py --db-path /path/to/db.db report-prefix-count --prefix /mnt/x

# Re-verify the database against the filesystem
python src/main.py --threads 8 --db-path /path/to/db.db audit-db \
    --exclude-prefix /mnt/offline

python src/main.py help    # every action and option
```

### Actions

| Action | What it does |
|--------|--------------|
| `scan` | Walk a comma-separated list of directories/files, hash what changed, store it |
| `check-file` | Hash one file and report whether the database already holds a match |
| `scan-dir-report` | Scan a directory and report duplicates as it goes |
| `report-duplicates` | List every duplicate group in the database (`--use-gui` for the Tkinter browser) |
| `report-duplicate-sizes` | Estimate the space reclaimable by deleting redundant copies |
| `report-prefix-count` | Count recorded files under a path prefix |
| `report-files-for-prefix` | List recorded files under a path prefix |
| `audit-db` | Re-check every recorded path; drop rows for files that are gone, rehash those that changed |
| `remove-record` | Delete database rows whose path matches a regex |
| `compare-directories` | Hash two trees in full and report what is unique to each |
| `get-file-info` | Print the stored size, mtime, and checksum for one path |
| `scan-unique-files` | Report files in a directory that have no match in the database |

### Where the database goes

`--db-path` pointing at a **directory** appends `file_manager.db` to it. Omitting
`--db-path` entirely uses `./file_manager.db` in the current directory. `*.db` is
gitignored.

---

## Things to know before you run it

The output of this tool is a list of files a human may then delete, so these are
worth reading first. The full list is in `CLAUDE.md`.

- **`audit-db` deletes rows, so run it with `--dry-run` first.** It keeps rows whose *directory* is also missing and reports them as `SUSPECT`, so a volume that failed to mount no longer empties its subtree. The trade: a directory you genuinely deleted also survives — `--prune-missing-dirs` removes those on purpose.
- **`remove-record` is literal by default.** `--regex` opts in, and the pattern must match the whole path, so deleting a subtree is explicit: `'/a/b/.*'`.
- **`--min-duplicates` counts copies** — the default is 2, meaning a file and at least one other like it. It was off by one until #6.
- **`scan-unique-files` writes `.processed_files.txt` into the directory it is scanning** as a resume log. Delete it to force a full recheck. The log lands inside the scanned tree, so the next run finds and checks it like any other file.
- **`is_file_unique` reports a file it could not read as a duplicate**, not as unknown — so an I/O error during hashing keeps a genuinely unique file out of the output. Open as #41.
- **The `fm-*.sh` wrappers run whichever checkout they live in**, resolved from `BASH_SOURCE`, with the interpreter from `.python-version` via `pyenv exec`. They used to `cd` to an older copy with its own `.venv`, so fixes never reached the scheduled scans (#9); `tests/test_script_conventions.py` now fails any wrapper that hard-codes a path or activates a `.venv`.

---

## How it works

```
main.py  (argparse dispatch, no logic)
   │
   ├── file_ops.py    walk the tree, decide what needs hashing
   │      └── md5sum.py     4 KB-chunked hashlib.md5
   ├── db.py          every write; owns the schema and lock retries
   ├── reporting.py   read-only queries, printed to stdout
   └── gui.py         Tkinter duplicate browser (writes rm_commands.txt)
```

### Schema

```sql
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    md5sum TEXT,
    size INTEGER,
    last_modified INTEGER,   -- int(mtime * 1000), milliseconds
    path TEXT UNIQUE
)
```

There are no indexes beyond the implicit unique index on `path`, so duplicate
reporting is a full scan and group-by. That is acceptable at current scale and is
the first thing to change if it stops being.

### Concurrency

Threads throughout; `--threads` sets the width. `scan_dir` runs a producer thread
filling a `Queue` that N workers drain, each stopped by its own sentinel.
Connections are never shared — every function opens SQLite, runs one statement,
and closes. Writers retry up to 10 times at 100 ms intervals on
`database is locked`; readers do not retry at all. `audit-db` is the only action
that sets `PRAGMA journal_mode=WAL`.

---

## Development

Setup is repo-wide — see the [root README](../README.md). In short:
Python 3.14.7 via the `sys-utils` pyenv-virtualenv, then
`pip install -r requirements-dev.txt`.

```bash
python -m pytest              # 194 tests; coverage on, floor enforced
python -m pytest --no-cov -q  # faster while iterating
python -m mypy src/           # must be clean
```

### Testing

194 tests in 17 modules, no xfails. `pytest.ini` enables branch coverage, writes
`coverage.xml` and `test-results.xml`, and fails under **99%** — the current real
measurement is 99.57%, which meets the 95% `docs/REQUIREMENTS.txt` has asked for
since 2024. `src/gui.py` is omitted from measurement in `.coveragerc` and named
as excluded in the summary; see `CLAUDE.md` for why. The gap was closed by epic
[#8](https://github.com/JeffreyPeacock/SystemUtils/issues/8) and its children
#32–#36 and #45.

Every run also writes **`.coverage-summary.md`**, which is committed — read it
for the per-file breakdown rather than trusting a table in a README. As of
2026-09-04 every measured module is at 100% line and branch except `main`, at
99.2%, whose two remaining statements are uncovered on purpose and named in
`tests/test_main_dispatch.py`. `gui` is listed there under "Excluded from
measurement", with the reason.

The floor **only moves up** — raise it in the same PR that raises real coverage.
Same for the per-module opt-outs in `mypy.ini`: a module leaves the list by
passing `check_untyped_defs`, not by loosening the defaults. `gui` and `main`
left it in #36; `db`, `file_ops` and `reporting` each need one annotation, named
in `mypy.ini`. See
[Development-Principles §4](../docs/Development-Principles.md).

### Fixtures

`test_data/data/` and `test_data/duplicate_data/` are a byte-identical pair, file
for file — that pairing *is* the duplicate-detection fixture. Adding a file to
one means adding it to the other.
`test_data/bin/generate-files.sh` regenerates the numbered files.

---

## Backlog

Tracked on the [SystemUtils board](https://github.com/users/JeffreyPeacock/projects/14),
filtered by `component:file-manager` — **3 open** at the time of writing: #41,
and the two GUI tickets #3 and #11.

Two are worth reading before relying on this tool for anything destructive:

- **#41** — a file that could not be hashed is reported as a duplicate rather than as unknown, so an I/O error can keep the only copy out of the unique list
- **#3** — the GUI writes the checkbox object rather than the path, so `rm_commands.txt` is not runnable

Three silent-wrong-answer paths are fixed: #1 and #2, and #43 —
`scan-dir-report` never returned at all until its shutdown was tested.
