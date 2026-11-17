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

`docs/REQUIREMENTS.txt` is the original specification. Its "full featured
graphical user-interface" requirement is **not met here, and will not be**: the
GUI left this project in #51 and becomes a separate application (#53). This is
a headless CLI scanner — no Tk, no display, no optional GUI flag. The 95%
coverage requirement is **met**, at 99.58%; epic #8 and its children #32-#36
and #45 are closed.

## Tech Stack

**Python 3.14.7** · **sqlite3** · **hashlib** · **argparse** · **threading** + **concurrent.futures** + **queue** · **pytest** + **pytest-cov** + **pytest-timeout** (`pytest.ini`) · **mypy** (`mypy.ini`).

**No tkinter, and nothing else optional.** The GUI moved out in #51, so this
runs on any Python 3 without Tk installed, and CI no longer has to verify
tkinter before the suite. It also means the tool can be pinned to a specific
system interpreter in isolated mode, which a Tk dependency would have made
fragile.

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

# Bundle as one executable, for running as root
scripts/build-pyz.sh     # -> dist/FileManager.pyz (~56K); optional arg overrides
sudo ./dist/FileManager.pyz --threads 8 --db-path /var/lib/filemanager/home2.db scan /home2
```

**`sudo python src/main.py` runs the wrong interpreter.** `sudo` resolves
`python` from *root's* PATH, not the pyenv shim, so it silently picks a
different interpreter or none. `scripts/build-pyz.sh` solves exactly that by
pinning `/usr/bin/env python3` into a `zipapp` archive — stdlib only, no
vendoring, 56K (#52). It verifies the artifact by **running** it from `/`,
because a zipapp can be written successfully and still be unrunnable, and
running it from inside this directory would let `src.` imports resolve from the
working directory rather than from the archive. `tests/test_build_pyz.py`
rebuilds it in CI; its load-bearing assertion is that the archive holds no
`.pyc`, since `cp -r src` copies bytecode and CPython invalidates on
`(mtime, size)`.

## Testing

**264 tests across 20 modules, all passing, no xfails.** Coverage is on by default
via `pytest.ini` (`--cov=src --cov-branch`), writes `coverage.xml` and
`test-results.xml`, and enforces `--cov-fail-under=99` against a measured
**99.64%** combined line+branch coverage.

Per-module figures live in `.coverage-summary.md`, regenerated every run and
committed — read that rather than duplicating a table here that goes stale. As
as of 2026-09-04 every measured module is at 100% line and branch except
`main`, at 99.2%/96.6%. The two statements left there are uncovered on purpose
and named in `tests/test_main_dispatch.py`: `sys.exit(main())` runs only when
the file is executed as a script, and the fall-through past the last `elif` is
unreachable because argparse rejects anything outside `choices`. Forcing either
would assert on a state the CLI cannot produce.

**Nothing is omitted from measurement.** `.coveragerc` has no `omit` key at all
— `src/gui.py` was the only entry, from #45 until #51 removed the GUI from this
project. Coverage now covers all of `src/`. The omit list has to live in
`.coveragerc` rather than `pytest.ini`, because coverage.py does not read
`pytest.ini`.

**Adding the first exclusion back needs three things**, and
`tests/test_coverage_config.py` enforces each: a reason in `EXCLUSION_REASONS`
(`scripts/coverage_summary.py`), a ticket, and an edit to that test, which
currently asserts the live config omits nothing. The third is the real control —
it stops an exclusion being slipped in as a one-line config change.

**The guard is tested against synthetic configs, not the live one.** With an
empty omit list, every "for each omitted file" assertion iterates nothing and
passes without testing anything — which looks identical to a working guard
(§3a). So the renderer is driven with a fabricated `coverage.xml` and a
fabricated omit list, covering an omission with a reason, one without (renders a
⚠️ warning), and one that is not taking effect (the file still appears in the
measured table). That is why the machinery survives with an empty dict rather
than being deleted and rewritten later from memory.

**The floor is a ratchet — it only goes up.** Raise `--cov-fail-under` in the
same PR that raises real coverage; never lower it to make a red build green.
Same rule for the per-module opt-out stanzas in `mypy.ini`: a module leaves that
list by **passing** `check_untyped_defs`, never by the defaults being loosened.
`gui` and `main` left it in #36 without needing annotation at all — the stanzas
had been guarding nothing, which is worth re-testing occasionally rather than
assuming. (`gui` has since left the project altogether with the GUI, #51, so
mypy now checks 7 files.) The three that remain fail on four container literals
between them, named in `mypy.ini`: two in `db`, one each in `file_ops` and
`reporting`.

**Re-run mypy with the stanzas stripped when checking the ratchets, and compare
the per-module counts against what `mypy.ini` says it covers.** An exempt module
absorbs a *new* error without `python -m mypy src/` noticing: #57 added
`counts['failures']` to a dict inferred as `dict[str, int]`, taking `src/db.py`
to 3 errors against the 2 documented, and the suite stayed green. #61 annotated
it back. Reasoning in repo-root `docs/Development-Principles.md` §4.

Every run writes **`.coverage-summary.md`**, and it is **committed**: overall line and
branch tables, a per-file breakdown with 🟢/🟡/🔴 badges, and the test counts.
Below them, an **Excluded from measurement** section names every file omitted in
`.coveragerc` with its reason from `EXCLUSION_REASONS` in
`scripts/coverage_summary.py`. The *list* is not duplicated there — the script
reads `.coveragerc`, so the two cannot drift; an omission with no recorded
reason renders as a warning rather than disappearing.

**`--no-cov` runs skip it**, and that is load-bearing rather than an
optimisation. The hook used to regenerate the summary from whatever
`coverage.xml` was left on disk, so a `--no-cov` run could rewrite the committed
report from a previous run's numbers — under a different `.coveragerc`, that
produced a report describing a configuration that was not in effect.

It is tracked deliberately, not ignored: the point is to see the per-file
numbers move in a pull request diff. That does mean a commit touching tests
usually carries a one-line churn in this file — regenerate it (`python -m
pytest`) and include it rather than leaving a stale one behind.

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

- `src/db.py` — the only module that calls `sqlite3.connect`. Owns the schema, every query, and the lock-retry behaviour, all through one gateway: `with_connection(db_path, work, commit=...)`. Also owns `UniquenessUnknown`, raised when a file's uniqueness cannot be determined — never answered as `False`, which is a verdict (#41).
- `src/file_ops.py` — directory walking and the decision of whether a file needs hashing. `process_file` is the core routine.
- `src/reporting.py` — formats and prints; every query it runs is a `db.py` function (#10). It must not import `sqlite3`, and `tests/test_db_owns_the_connection.py` fails if it does.
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

- **`--use-gui` no longer exists, and passing it is a hard failure.** The GUI left this project in #51, so `report-duplicates --use-gui` is an argparse rejection — exit code 2, no report produced. Any wrapper, cron entry or shell history carrying the flag stops working rather than quietly ignoring it, which is the intended direction: a scan that silently dropped the flag would look like it had run normally. The replacement is a separate application (#53).
- **`--min-duplicates` counts copies, and its default is 2.** `find_duplicates_with_min_count` compares with `>=`, so 2 means "a file and at least one other like it". Until #6 the comparison was `>` with a default of 1: the same output, reached by an argument that meant one less than it said, so `--min-duplicates 3` returned groups of four.
- **Record removal is two functions in `db.py`, named apart.** `remove_record_by_path` takes one exact path; `remove_records_by_regex` takes a pattern matched against the whole path. Until #7 both were called `remove_record`, in different modules, with opposite behaviour. `tests/test_removal_function_names.py` fails if any module under `src/` reintroduces the bare name.
- **`scan-unique-files` writes into the directory it scans.** It appends a `.processed_files.txt` resume log at the root of the target directory and reads it back on the next run. Delete it to force a full recheck. Because the log lands *inside* the scanned tree, the next `os.walk` finds it and checks it like any other file — so a second run over an unchanged tree reports exactly one file: the log.
- **`is_file_unique` raises rather than answering when it cannot tell.** `UniquenessUnknown` — not `False`, which is a verdict meaning *not unique*, and not a falsy sentinel any caller would reproduce the bug with (#41). `scan-unique-files` logs such files as `unreadable` in the resume log, leaves them out of both lists, warns how many, and **re-checks them next run**: a verdict is final, "could not check" is not.
- **`compare-directories` ignores the database.** It hashes both trees in full, in-process, and compares with an O(n·m) `md5 not in dict.values()` scan.
- **`audit-db` keeps rows whose *directory* is also missing.** A deleted file leaves its parent directory behind; an unmounted volume does not. Rows in the second case are reported as `SUSPECT` and **not** removed, so a failed mount no longer empties a subtree (#2). The cost is that a directory you genuinely deleted also survives — `--prune-missing-dirs` removes those deliberately, and `--dry-run` shows either case first.
- **`remove-record` is literal by default.** `--regex` opts into pattern matching, and the pattern must match the **whole** path (`re.fullmatch`). Deleting a subtree is therefore explicit: `'/a/b/.*'`. Before #1 the argument was always a prefix-anchored regex, so a literal `/a/b` also deleted `/a/bc`.
- **An invalid invocation exits non-zero.** 1 for a missing or invalid argument, 2 for an argparse rejection, 0 for `help` (#23). Scripts under `set -e` therefore stop, which they did not before.
- **An incomplete scan exits 3, and the counts are on stdout.** `scan` and `audit-db` print `scan complete: N hashed, N skipped unchanged, N failed` followed by each failed path, and return **3** if anything failed (#57). 3 is deliberately not 1 or 2: those mean nothing was recorded, while 3 means part of the tree was recorded and part was not. Before this, an unreadable file produced one ERROR line among the per-file log lines and **exit 0**, so a partial index was indistinguishable from a complete one — and it cannot be detected afterwards, because the database looks the same whether a file was absent or unreadable. A path on the command line that is neither a file nor a directory counts as a failure for the same reason. The summary goes to **stdout** while all logging goes to stderr, so it survives the `2>/dev/null` a scheduled scan uses.
- **Help is intercepted before argparse, on purpose.** `-h`, `--help`, `-?` and the positional `help` all print `usage()` and exit 0 (#58). The flags are matched against `sys.argv` rather than registered with the parser, because the help text is `usage()` — which documents the actions, options, exit codes and examples that argparse's generated help does not — and because `action` is a required positional, so `--help` alone would otherwise fail the missing-argument check first. All four exited 0 only as of #58: `add_help=False` had removed the flags from the parser, and the `except SystemExit` around `parse_args` returned 2 for every exit code including 0. Both had to change together, and the second matters again for `--version` (#54), which will raise `SystemExit(0)` through that same handler.

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

Five silent-wrong-answer paths are fixed — #1 (prefix-anchored removal), #2
(audit-db emptying an unmounted volume), #43 (`scan-dir-report` never returning),
#41 (an unreadable file reported as a duplicate) and #57 (a partial index
reported as a complete one). The coverage epic **#8** is closed, the GUI tickets
#3 and #11 closed with #51 when the GUI left, and #58 fixed `--help` exiting 2.

**#50 is the one to read before trusting this database for integrity
checking.** Neither `scan` nor `audit-db` can detect silent corruption: both
compare `(size, mtime)` and skip hashing when they match, so a rescan skips
exactly the files whose contents were in question. Bit rot, a bad sector and a
failing cable all rewrite bytes without touching size or mtime. The baseline
scan is correct; nothing reads it back. Demonstrated on the ticket.

Also open: **#54** (the remaining zipapp requirements — `--version` with the
embedded commit, which gates the Desktop-Ops installer; the timestamped header with
the zone; the rest of the artifact test) and **#53** (the GUI as its own
application, carrying the decision from #11 and the path-handling bug from #3).
The bundle itself shipped in #52.
