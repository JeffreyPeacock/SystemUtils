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
| [`doc/Architecture+Design.md`](doc/Architecture+Design.md) | Design decision record — problem, decision, alternatives rejected |
| [`doc/REQUIREMENTS.txt`](doc/REQUIREMENTS.txt) | The original 2024 specification, kept as written |
| [`../doc/Development-Principles.md`](../doc/Development-Principles.md) | Repo-wide principles on building and sequencing work |

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
python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 1
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

- **`remove-record` takes a regex, not a path**, despite the built-in usage text. It is matched with `re.match`, which anchors at the start of the string but **not** the end — so a literal `/a/b` also deletes rows for `/a/bc` and everything under `/a/b-old/`.
- **`audit-db` has no dry-run.** `--exclude-prefix` is the only thing standing between a volume that failed to mount and the removal of every row beneath it.
- **`--min-duplicates` is off by one** — the query is `HAVING COUNT(*) > n`, so the default of 1 returns groups of 2 or more.
- **Paths containing commas break duplicate reporting** — results are assembled with `GROUP_CONCAT(path)` and split on `,`.
- **`report-duplicate-sizes` halves the total**, which is right for pairs and wrong for larger groups.
- **`scan-unique-files` writes `.processed_files.txt` into the directory it is scanning** as a resume log. Delete it to force a full recheck.
- **The `fm-*.sh` wrappers point at an older copy of this project** under `~/Workspace/File-Manager/`, not at this directory.

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
python -m pytest              # 21 tests; coverage on, floor enforced
python -m pytest --no-cov -q  # faster while iterating
python -m mypy src/           # must be clean
```

### Testing

21 tests in 4 modules. `pytest.ini` enables branch coverage, writes
`coverage.xml` and `test-results.xml`, and fails under **29%** — the current real
measurement is 29.81%. `doc/REQUIREMENTS.txt` asks for 95%; the gap is the main
open work on this project. Coverage is concentrated in `md5sum.py` (100%) and
`db.py` (59%); `main.py`, `gui.py`, `reporting.py`, and `file_ops.py` are all
under 20%.

The floor **only moves up** — raise it in the same PR that raises real coverage.
Same for the per-module opt-outs in `mypy.ini`: a module leaves the list by being
annotated, not by loosening the defaults. See
[Development-Principles §4](../doc/Development-Principles.md).

### Fixtures

`test_data/data/` and `test_data/duplicate_data/` are a byte-identical pair, file
for file — that pairing *is* the duplicate-detection fixture. Adding a file to
one means adding it to the other.
`test_data/bin/generate-files.sh` regenerates the numbered files.

---

## Backlog

Tracked on the [SystemUtils board](https://github.com/users/JeffreyPeacock/projects/14),
filtered by `component:file-manager`. The standing items:

- Coverage at 29.81% against the 95% the requirements ask for
- The `fm-*.sh` wrappers run an older copy of the project
- `reporting.py` bypasses `db.py` and opens its own connections
- The GUI is a paginated duplicate list, not the file manager `doc/REQUIREMENTS.txt` describes
