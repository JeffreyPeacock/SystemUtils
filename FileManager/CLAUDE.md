# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repo-wide workflow, branch naming, and board configuration are in the
**repo-root `CLAUDE.md`** one directory up. This file covers FileManager only.

## Documentation Hierarchy

**`CLAUDE.md`** (this file) = operational reference: commands, config, non-obvious constraints, gotchas. **Target <34k chars, hard limit 40k.** · **`README.md`** = new-developer orientation · **`docs/Architecture+Design.md`** = design decisions (problem / decision / alternatives rejected) · **`docs/REQUIREMENTS.txt`** = the original 2024 specification · **`man/filemanager.1`** = the user-facing manual, with `man/filemanager.md` generated from it · repo-root **`docs/Development-Principles.md`** = durable lessons about building and sequencing.

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
coverage requirement is **met**, at 99.71%; epic #8 and its children #32-#36
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

# Read the stored checksums BACK. The only action that detects corruption.
# Read-only on the database. Exits 4 on a mismatch, 3 on an unreadable file.
python src/main.py --threads 8 --db-path /path/to/db.db verify-db
python src/main.py --db-path /path/to/db.db verify-db --prefix /mnt/backup

# Remove records. LITERAL by default; --regex matches the WHOLE path.
python src/main.py --db-path /path/to/db.db remove-record /exact/path
python src/main.py --db-path /path/to/db.db remove-record '/a/b/.*' --regex

python src/main.py --db-path /path/to/db.db report-duplicates --min-duplicates 2
python src/main.py --db-path /path/to/db.db report-duplicate-sizes
python src/main.py help          # full action/option list

# The manual. man/filemanager.1 is the source; the .md is GENERATED from it.
man -l man/filemanager.1                 # read it
groff -man -Tutf8 -ww -z man/filemanager.1   # check the troff; silence = clean
scripts/render_man.py                    # -> man/filemanager.md

# Tests — pytest.ini turns on coverage and enforces the floor
python -m pytest
python -m pytest tests/test_md5sum.py                       # one module
python -m pytest tests/test_md5sum.py::TestComputeMD5       # one class
python -m pytest --no-cov -q                                # skip the floor while iterating

# Types
python -m mypy src/

# Bundle as one executable, for running as root
scripts/build-pyz.sh     # -> dist/FileManager.pyz (~68K); optional arg overrides
FM_ALLOW_DIRTY=1 scripts/build-pyz.sh    # build anyway; artifact says "dirty at build time"
./dist/FileManager.pyz --version         # the commit it was built from
sudo ./dist/FileManager.pyz --threads 8 --db-path /var/lib/filemanager/home2.db scan /home2
```

**`sudo python src/main.py` runs the wrong interpreter.** `sudo` resolves
`python` from *root's* PATH, not the pyenv shim, so it silently picks a
different interpreter or none. `scripts/build-pyz.sh` solves exactly that by
pinning `/usr/bin/python3 -I` into a `zipapp` archive — stdlib only, no
vendoring, 68K (#52). It verifies the artifact by **running** it from `/`,
because a zipapp can be written successfully and still be unrunnable, and
running it from inside this directory would let `src.` imports resolve from the
working directory rather than from the archive. `tests/test_build_pyz.py`
rebuilds it in CI; its load-bearing assertion is that the archive holds no
`.pyc`, since `cp -r src` copies bytecode and CPython invalidates on
`(mtime, size)`.

## Testing

**369 tests across 27 modules, all passing, no xfails.** Coverage is on by default
via `pytest.ini` (`--cov=src --cov-branch`), writes `coverage.xml` and
`test-results.xml`, and enforces `--cov-fail-under=99` against a measured
**99.71%** combined line+branch coverage.

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
had been guarding nothing. **`db` left it in #60**, and that one needed work: a
`TypedDict` for `audit_db`'s return plus annotations on `duplicates` and
`md5_to_paths`. mypy now checks 9 files. **Two stanzas remain**, `file_ops` and
`reporting`, each failing on its one `file_queue` literal.

**Re-run mypy with the stanzas stripped when checking the ratchets, and compare
the per-module counts against what `mypy.ini` says it covers.** An exempt module
absorbs a *new* error without `python -m mypy src/` noticing: #57 added
`counts['failures']` to a dict inferred as `dict[str, int]`, taking `src/db.py`
to 3 errors against the 2 documented, and the suite stayed green. #61 patched it
with `dict[str, Any]`; #60 replaced that with a `TypedDict` and retired the
stanza. Reasoning in repo-root `docs/Development-Principles.md` §4.

**`audit_db` returns an `AuditCounts` TypedDict, and the caller is checked
against it.** `src/main.py` was never exempt, so before #60 it typechecked only
because `audit_db` returned `Any` out of an unchecked module —
`_print_audit_summary` indexes that dict and calls `len()` on one of its values.
A `type: ignore` would still silence mypy, so
`tests/test_audit_counts_shape.py` compares the declared fields against the keys
a real audit returns.

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
- `src/file_ops.py` — directory walking and the decision of whether a file needs hashing. `process_file` is the core routine. Also `verify_db` and `VerifyTally` (#50): the orchestration lives here because it is a decision about hashing, while its one bulk query, `db.recorded_checksums`, lives in `db.py` with every other statement.
- `src/reporting.py` — formats and prints; every query it runs is a `db.py` function (#10). It must not import `sqlite3`, and `tests/test_db_owns_the_connection.py` fails if it does.
- `src/version.py`, `src/build_info.py` — what `--version` prints. `build_info.py` is **data only**, because the build overwrites it; every line of logic and the live-git fallback are in `version.py` (#62).
- `src/md5sum.py`, `src/utils.py` — `compute_md5` (4 KB chunks), `get_file_mtime_in_ms`,
  and `report_settings`, which prints each setting's name, value and origin before a
  destructive run and refuses a credential-shaped name outright
  (`docs/Development-Principles.md` §2).
- `scripts/render_man.py` — renders `man/filemanager.1` as `man/filemanager.md`,
  invoked by the same `pytest_sessionfinish` hook. Stdlib only, and it **refuses**
  on a macro or escape it does not know rather than dropping it (#54-era rule: a
  file that looks complete and is missing a paragraph is worse than no file).
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
- **`verify-db` is the only action that can detect corruption, and it never writes.** `scan` and `audit-db` both compare `(size, mtime)` and skip hashing when they match, so they skip exactly the files whose contents were in question — bit rot, a bad sector and a failing cable all rewrite bytes without touching either (#50). `verify-db` rehashes unconditionally and compares against the **stored** `md5sum`. It issues one read query and no writes, deliberately: a verify that repaired the baseline on a mismatch would destroy the only evidence *and* pass on its second run. Three outcomes, never two — match, mismatch, could-not-read — and an unreadable file is **not** a pass. `tests/test_verify_db.py` also records that `scan` and `audit-db` still miss corruption in place, because that is the action's whole reason for existing.
- **A mismatch exits 4, which is deliberately not 3.** 3 means part of the answer is unknown; 4 means the answer is known and bad, and an operator does something different about each. A mismatch outranks an unreadable file when both happen in one run.
- **An incomplete scan exits 3, and the counts are on stdout.** `scan` and `audit-db` print `scan complete: N hashed, N skipped unchanged, N failed` followed by each failed path, and return **3** if anything failed (#57). 3 is deliberately not 1 or 2: those mean nothing was recorded, while 3 means part of the tree was recorded and part was not. Before this, an unreadable file produced one ERROR line among the per-file log lines and **exit 0**, so a partial index was indistinguishable from a complete one — and it cannot be detected afterwards, because the database looks the same whether a file was absent or unreadable. A path on the command line that is neither a file nor a directory counts as a failure for the same reason. The summary goes to **stdout** while all logging goes to stderr, so it survives the `2>/dev/null` a scheduled scan uses.
- **Every action prints a header on stdout before it does anything** (#54 requirement 10): the start time *with its zone*, the version, the action, the paths, the database and the thread count. stdout rather than the logging stream, because a scheduled scan runs with `2>/dev/null`. `help` and `--version` do **not** print it -- they are questions about the tool rather than runs of it, and `scripts/build-pyz.sh` verifies the artifact by grepping `--version` output, which a header would sit in front of. This replaced a `logging.info` line that carried four of the same fields on stderr, with no version and no zone. `TIME_FORMAT` in `src/version.py` is the one definition of the format and the build stamper imports it.
- **No module under `src/` may import inside a function** (#54 requirement 7), and `tests/test_imports_at_startup.py` fails on one. The zip importer reopens the archive **by its path** on every resolution, so an import executed mid-run reads whichever `.pyz` is at that path then -- and an unattended scan runs 20+ hours, long enough for the file to be replaced under it. Two report arms did this lazily until #54.
- **`--version` is embedded at build time, and a dirty tree refuses to build.** The archive has no git repository at run time, so `scripts/stamp_build_info.py` writes `src/build_info.py` into the copy `build-pyz.sh` archives (#62). The **committed** copy holds `None` for every field, and that `None` is how `--version` knows it is not a bundle: a source checkout says `not a build -- source checkout` and reads git live. A question git cannot answer prints `CANNOT DETERMINE`, never `clean`. Two consequences that will catch you out: **`scripts/build-pyz.sh` refuses to run while anything under `FileManager/` is uncommitted** — `FM_ALLOW_DIRTY=1` overrides and the artifact then reports `dirty at build time` permanently — and `tests/test_build_pyz.py` therefore sets that variable in its fixtures, because a developer's tree is normally dirty and the module asserts on the archive, not on the checkout. The refusal itself is tested against throwaway repositories in `tests/test_stamp_build_info.py`, so opting out of it in one place does not leave it untested. **When a consumer needs a clean build and the tree cannot be committed yet, build from a detached worktree rather than reaching for `FM_ALLOW_DIRTY`** — `git worktree add --detach <tmp> <commit>` is clean by construction, and the `.python-version` it lacks can be copied in (it is gitignored, so it does not dirty the worktree). `FM_ALLOW_DIRTY` marks that artifact for the rest of its life, and an index built by a bundle that names no commit cannot be traced to code afterwards (#54, 2026-11-17). Measured the same day: a dirty build and a clean build of the same commit differed in `src/build_info.py` and nothing else, so the flag is about provenance, not about different code.
- **`man/filemanager.md` is generated, and editing it fails the suite.** `man/filemanager.1` is the manual; the markdown beside it is rendered from the troff by `scripts/render_man.py`, which `tests/conftest.py` runs after **every** test session — including `--no-cov` ones, because unlike the coverage summary its only input is the troff file, so it can never be rebuilt from stale data. `tests/test_man_page.py` compares the committed markdown against a fresh render byte for byte, so a hand-edit or a commit of the troff alone goes red. Two consequences: the gate fires **once** and the hook then fixes the file, so a stale commit is refused and the second attempt succeeds; and the markdown is **not** the place to fix a typo. One test there reads the section headings straight out of the troff rather than through the renderer — with the renderer blinded to `.SS` and the markdown regenerated, the byte comparison passes and only that test fails (§3a).
- **Help is intercepted before argparse, on purpose.** `-h`, `--help`, `-?` and the positional `help` all print `usage()` and exit 0 (#58). The flags are matched against `sys.argv` rather than registered with the parser, because the help text is `usage()` — which documents the actions, options, exit codes and examples that argparse's generated help does not — and because `action` is a required positional, so `--help` alone would otherwise fail the missing-argument check first. All four exited 0 only as of #58: `add_help=False` had removed the flags from the parser, and the `except SystemExit` around `parse_args` returned 2 for every exit code including 0. Both had to change together. The `exc.code` fix stands on its own; `--version` ended up **not** using it (#62) — it is matched against `sys.argv` in the same place and for the same reasons as the help flags, rather than registered as argparse's `action='version'`, because two mechanisms answering two conventional flags in two places is one more thing to keep true.

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

**#50 closed with `verify-db`**, so the database can now be read back: a
recorded file whose contents changed under it is reported with both checksums
and exits 4. `scan` and `audit-db` still cannot detect corruption and are not
meant to — the `(size, mtime)` skip is what makes rescanning a large tree cheap.
Use `verify-db` for integrity, scoped with `--prefix` since verifying the
recorded volumes takes hours.

**The zipapp spec #54 is closed.** Requirements 1-5 and 8 landed in #52, 11 as
#57, 9 as #62, and 7, 10 and 12 in PR #64 — so the bundle is installable and the
Desktop-Ops installer's gate is cleared. Requirement 6 (dropping the
`sys.path.append` in `main.py`) was **rejected by the owner**: it stays.

Also open: **#53** (the GUI as its own application, carrying the decision from
#11 and the path-handling bug from #3). #60 closed with the `AuditCounts`
TypedDict.
