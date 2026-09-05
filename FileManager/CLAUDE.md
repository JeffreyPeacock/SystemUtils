# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repo-wide workflow, branch naming, and board configuration are in the
**repo-root `CLAUDE.md`** one directory up. This file covers FileManager only.

## Documentation Hierarchy

**`CLAUDE.md`** (this file) = operational reference: commands, config, non-obvious constraints, gotchas. **Target <34k chars, hard limit 40k.** · **`README.md`** = new-developer orientation · **`docs/Architecture+Design.md`** = design decisions (problem / decision / alternatives rejected) · **`docs/REQUIREMENTS.txt`** = the original 2024 specification · repo-root **`docs/Development-Principles.md`** = durable lessons about building and sequencing.

**When trimming, assign every removed item to one of those *before* deleting it.**

## What this is

A CLI that recursively walks directories, computes an MD5 checksum for every
file, and stores `(md5sum, size, last_modified, path)` in SQLite. The database is
then queried to find duplicate files across separate filesystems and mount
points. Its output is a list of files a human may then delete — a wrong answer
has consequences past this process, which is what makes the correctness notes
below worth reading before changing anything.

`docs/REQUIREMENTS.txt` is the original specification. Two of its requirements are
**not met**: the "full featured graphical user-interface" (only a paginated
Tkinter duplicate list exists) and 95% coverage (actual: **93.11%** — tracked
by epic #8 and its children #32-#36).

## Tech Stack

**Python 3.14.7** · **sqlite3** · **hashlib** · **argparse** · **threading** + **concurrent.futures** + **queue** · **tkinter** (optional GUI) · **pytest** + **pytest-cov** + **pytest-timeout** (`pytest.ini`) · **mypy** (`mypy.ini`).

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

# Re-verify every recorded path. Deletes rows -- always --dry-run first.
python src/main.py --threads 8 --db-path /path/to/db.db audit-db --dry-run
python src/main.py --threads 8 --db-path /path/to/db.db audit-db \
    --exclude-prefix /mnt/offline,/mnt/other

# Remove records. LITERAL by default; --regex matches the WHOLE path.
python src/main.py --db-path /path/to/db.db remove-record /exact/path
python src/main.py --db-path /path/to/db.db remove-record '/a/b/.*' --regex

python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 2
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

**159 tests across 15 modules, all passing, no xfails.** Coverage is on by default
via `pytest.ini` (`--cov=src --cov-branch`), writes `coverage.xml` and
`test-results.xml`, and enforces `--cov-fail-under=93` against a measured
**93.11%** combined line+branch coverage.

Per-module figures live in `.coverage-summary.md`, regenerated every run and
committed — read that rather than duplicating a table here that goes stale. As
of 2026-09-04 `db`, `file_ops`, `reporting` and `md5sum` are at 100% line and
branch; what is left is `main` 81% (#36) and `utils` 55% (#35).

**`src/gui.py` is omitted from measurement**, in `.coveragerc` — coverage.py does
not read `pytest.ini`, so the omit list cannot live there. It is a Tkinter widget
tree and a `mainloop()`; testing widget construction asserts on the library. It
was measured until #45, where at 82 of 601 statements it capped the total near
88% and put the 95% requirement out of reach however well everything else was
tested. The omission is deliberately **visible**: `.coverage-summary.md` still
names `gui` under "Excluded from measurement" with the reason, and
`tests/test_coverage_config.py` fails if a file is omitted without one, if the
summary stops naming it, or if the summary and `.coveragerc` disagree. Adding a
second entry to that list needs the same standard — a written reason and a
ticket.

**The floor is a ratchet — it only goes up.** Raise `--cov-fail-under` in the
same PR that raises real coverage; never lower it to make a red build green.
Same rule for the per-module opt-out stanzas in `mypy.ini`: a module leaves that
list by being annotated. Reasoning in repo-root `docs/Development-Principles.md` §4.

Every run writes **`.coverage-summary.md`**, and it is **committed**: overall line and
branch tables, a per-file breakdown with 🟢/🟡/🔴 badges, and the test counts.
`--no-cov` runs skip it. A file that is deliberately below full coverage gets a
`†` and a footnote from `COVERAGE_NOTES` in `scripts/coverage_summary.py` —
`gui.py` has one, so its 11% reads as a decision rather than neglect.

It is tracked deliberately, not ignored: the point is to see the per-file
numbers move in a pull request diff. That does mean a commit touching tests
usually carries a one-line churn in this file — regenerate it (`python -m
pytest`) and include it rather than leaving a stale one behind. Add a note
only where the reason is real; if the honest answer is "this should be
restructured so it can be tested", say that instead.

**`timeout = 60`, `timeout_method = thread` is a gate, not a nicety.** Both
producer/consumer scans shut their workers down with one sentinel per worker,
and getting that wrong *hangs* rather than raises — #43 was exactly that, and
`scan-dir-report` never returned at all until it was found. pytest-timeout kills
the process and prints every thread's stack, naming the consumers blocked in
`queue.get()`.

Do not swap it for either of the obvious stdlib alternatives; both were tried
and measured. pytest's own `faulthandler_timeout` dumps the same tracebacks but
**stops nothing** — a 30s test under `faulthandler_timeout = 5` ran its full 30
seconds and passed. A fixture running the scan on a daemon thread is worse: the
test goes red, then the run wedges at interpreter exit, because
`ThreadPoolExecutor`'s threads are not daemons and are joined at shutdown.

Note the summary reports lines and branches **separately**, while pytest prints
one combined figure — `--cov-fail-under` compares against the combined one, so
the numbers differ without disagreeing.

Fixtures live in `test_data/`. `data/` and `duplicate_data/` are a
**byte-identical pair, file for file** — that pairing is the duplicate-detection
fixture, and a file present in one but not the other breaks tests with a
`FileNotFoundError` that names nothing useful. `test_data/bin/generate-files.sh`
regenerates the numbered files.

## Architecture

`src/main.py` is an argparse dispatcher — one `elif` per action — with no logic
beyond argument validation. Below it is a flat module layer, no classes:

- `src/db.py` — the only module that calls `sqlite3.connect`. Owns the schema, every query, and the lock-retry behaviour, all through one gateway: `with_connection(db_path, work, commit=...)`.
- `src/file_ops.py` — directory walking and the decision of whether a file needs hashing. `process_file` is the core routine.
- `src/reporting.py` — formats and prints; every query it runs is a `db.py` function (#10). It must not import `sqlite3`, and `tests/test_db_owns_the_connection.py` fails if it does.
- `src/gui.py` — a Tkinter duplicate browser, reached only via `report-duplicates --use-gui`. Writes `rm_commands.txt` rather than deleting anything itself.
- `src/md5sum.py`, `src/utils.py` — `compute_md5` (4 KB chunks), `get_file_mtime_in_ms`,
  and `report_settings`, which prints each setting's name, value and origin before a
  destructive run and refuses a credential-shaped name outright
  (`docs/Development-Principles.md` §2).
- `scripts/coverage_summary.py` — renders `coverage.xml` as `.coverage-summary.md`,
  invoked by a `pytest_sessionfinish` hook in `tests/conftest.py`.

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

No connection is shared between threads, and none is reused: `with_connection`
opens one, runs the callable it was given, and closes. It retries up to
`MAX_RETRIES = 10` times at `RETRY_DELAY = 0.1`s, catching **only**
`OperationalError` containing "database is locked" and re-raising everything
else, so a malformed statement fails on the first attempt rather than a second
later. Reads get the same retry as writes as of #10 — before that they had
none, and a report run during a scan raised instead of waiting.

`audit_db` sets `PRAGMA journal_mode=WAL`; nothing else does, so a database that
has never been audited is still in rollback-journal mode.

## Behaviours that will surprise you

Every entry here is a trap someone already fell into. Do not trim this section.
Entries change only when the behaviour does — four went on 2026-09-04 with
#1, #2, #4 and #5, and the `--min-duplicates` and `remove_record` entries were
rewritten the same day when #6 and #7 landed.

- **`--min-duplicates` counts copies, and its default is 2.** `find_duplicates_with_min_count` compares with `>=`, so 2 means "a file and at least one other like it". Until #6 the comparison was `>` with a default of 1: the same output, reached by an argument that meant one less than it said, so `--min-duplicates 3` returned groups of four.
- **Record removal is two functions in `db.py`, named apart.** `remove_record_by_path` takes one exact path; `remove_records_by_regex` takes a pattern matched against the whole path. Until #7 both were called `remove_record`, in different modules, with opposite behaviour. `tests/test_removal_function_names.py` fails if any module under `src/` reintroduces the bare name.
- **`scan-unique-files` writes into the directory it scans.** It appends a `.processed_files.txt` resume log at the root of the target directory and reads it back on the next run. Delete it to force a full recheck. Because the log lands *inside* the scanned tree, the next `os.walk` finds it and checks it like any other file — so a second run over an unchanged tree reports exactly one file: the log.
- **`is_file_unique` reports an unreadable file as a duplicate.** Every exception below its `isfile` check becomes `return False`, which means *not unique* — the same answer as a file that genuinely has a copy elsewhere. Open as #41; the current behaviour is pinned by a test, so changing it is a deliberate contract change.
- **`compare-directories` ignores the database.** It hashes both trees in full, in-process, and compares with an O(n·m) `md5 not in dict.values()` scan.
- **`audit-db` keeps rows whose *directory* is also missing.** A deleted file leaves its parent directory behind; an unmounted volume does not. Rows in the second case are reported as `SUSPECT` and **not** removed, so a failed mount no longer empties a subtree (#2). The cost is that a directory you genuinely deleted also survives — `--prune-missing-dirs` removes those deliberately, and `--dry-run` shows either case first.
- **`remove-record` is literal by default.** `--regex` opts into pattern matching, and the pattern must match the **whole** path (`re.fullmatch`). Deleting a subtree is therefore explicit: `'/a/b/.*'`. Before #1 the argument was always a prefix-anchored regex, so a literal `/a/b` also deleted `/a/bc`.
- **An invalid invocation exits non-zero.** 1 for a missing or invalid argument, 2 for an argparse rejection, 0 for `help` (#23). Scripts under `set -e` therefore stop, which they did not before.

## Logging output

Logging goes to stderr at INFO. The scan path also writes a bare `.` to stdout
per skipped file, so redirecting stdout from a large rescan produces a long line
of dots mixed with any report output.

## Shell wrappers

`fm-scan-Video.sh`, `fm-scan-unique.sh` and `fm-audit-db-Video.sh` run **this**
checkout. They resolve their own location from `BASH_SOURCE` and share
`fm-common.sh`, which is sourced and therefore carries neither a shebang nor the
executable bit.

The interpreter comes from `.python-version` via `pyenv exec`, deliberately —
a shell that inherited `VIRTUAL_ENV` from another project silently beats the
pyenv shim, so a bare `python` can be a different interpreter from the one
`pyenv version` reports.

Overrides, all environment variables: `FM_DB` (default `/home/public/Video.db`),
`FM_THREADS` (8), `FM_VIDEO_DIRS`. Each run prints the resolved directory,
interpreter, database and thread count before doing anything.

**`fm-audit-db-Video.sh` defaults to `--dry-run`** and needs `--commit` to
remove rows.

Until #9 these scripts began `cd /home/jeffp/Workspace/FileManager` — a symlink
to an **older copy** of this project with its own `.venv` — so a fix landed here
never reached the scheduled scans. `tests/test_script_conventions.py` now pins
that: no wrapper may hard-code an absolute `cd` or activate a `.venv`, and
shebang must match the executable bit across every script in the repo.

`cmpdirs.sh` is gitignored — its paths are machine-specific.

## Backlog

All known work is filed on the board — filter `component:file-manager`:
https://github.com/users/JeffreyPeacock/projects/14

Do not keep a parallel list here. The board carries Status, Priority and Area;
a list in this file only goes stale. `/priority-review` renders it as a
priority-ordered table in `FileManager/docs/ticket-priority-review.md` when you
want it at a glance.

Both original silent-data-loss paths are now fixed — #1 (prefix-anchored
removal) and #2 (audit-db emptying an unmounted volume). What remains is
11 open tickets, five of them p2. The coverage work is epic **#8**, which is a
tracker rather than a unit of work: its children **#32-#36** each carry a
per-module coverage target and are the things to actually pick up.
