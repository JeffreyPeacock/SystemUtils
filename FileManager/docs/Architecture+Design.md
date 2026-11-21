# FileManager — Architecture & Design

A decision record. Each entry states the problem, the decision, what was ruled
out, and the issues involved. Newest first. Entries dated before this file
existed are reconstructed from the code and are marked as such.

---

## Test fixtures port the shape of CaptureServer's conftest, not its contents

**Problem.** `file_ops.py` and `reporting.py` sat at 14% and 16% coverage. The
reason was not difficulty but setup cost: every test first had to build a
database and a tree of files with known duplicate relationships, so no test got
written. CaptureServer is the reference project and has a mature `conftest.py`,
which made "port it" the obvious move.

**Decision.** Port the *shape* — a fresh resource per test, isolated from the
repository — and none of the contents. Roughly 120 of CaptureServer's 159
conftest lines are `autouse` mocks for S3, Celery, FCM, email and rate
limiters. FileManager talks to no external service, so there is nothing to
mock and those lines would have been inert scaffolding that future readers
assume is load-bearing.

**What replaced them** is the part CaptureServer has no equivalent of: a fixture
tree whose duplicate relationships are known in advance. Its shape is chosen,
not incidental:

- `left/` and `right/` hold three byte-identical pairs **and** one unique file each, so a query has something to find *and* something it must correctly ignore. A fixture with only duplicates cannot catch a query that returns everything.
- One pair is named `with,comma.txt`, so any test of the group queries also exercises the `GROUP_CONCAT` splitting defect (#5) without a second fixture. That test is a **strict xfail**: it fails when the bug is fixed, which is what stops the fixture and the fix drifting apart.
- `volatile/` carries one file that changes size and one that changes only mtime, because `process_file`'s skip check compares both and the two take different branches.

**Ruled out.** Reusing `test_data/data` and `test_data/duplicate_data`, which is
what the original tests did. Those are a fixed, committed pair, so a test
needing a third copy or a mutated file has to write into the repository — which
is exactly what the old tests did, leaving `test.db` in the working tree.

**Related issues:** #12, and #5 for the xfail.

---

## The database is a cache, not just a result

**Problem.** The tool exists to be run repeatedly over the same multi-terabyte
trees as they grow. Hashing every file on every run makes that unaffordable —
the cost is dominated by reading bytes, and almost none of those bytes changed
since the last run.

**Decision.** Store `size` and `last_modified` alongside the checksum, and have
`process_file` skip the read entirely when both still match what the database
holds. A rescan of an unchanged archive touches metadata only.

**Consequence.** The database can be wrong in a way a pure result cannot: if a
file is modified without its size or mtime changing, the stale checksum survives.
`audit-db` exists to re-verify the cache against the filesystem, which is why it
is a separate action rather than something `scan` does implicitly.

**Ruled out.** Hashing unconditionally and treating the database as pure output —
correct, and far too slow to run often enough to be useful.

*Reconstructed from the code; predates this file.*

---

## mtime is stored as an integer count of milliseconds

**Problem.** `os.path.getmtime()` returns a float. Comparing floats for exact
equality on every file of every scan is fragile: the value round-trips through
SQLite's storage, and a representation difference of one ULP turns a skip into a
full rehash.

**Decision.** Store `int(os.path.getmtime(path) * 1000)` — milliseconds as an
integer — and compare integers.

**Consequence, and the reason this entry exists.** This format is load-bearing
for every database already in existence. Changing the multiplier, the rounding,
or the type invalidates every stored row and forces a full rehash of every
recorded file on the next run. `get_file_mtime_in_ms` in `src/utils.py` and the
inline computation in `src/file_ops.py:process_file` compute the same value in
two places and **must** stay in agreement.

**Ruled out.** Nanosecond precision via `os.stat().st_mtime_ns` — more faithful,
but no filesystem in use here resolves better than a millisecond, and it would
have made the number harder to read in the one place it is read by a human
(`get-file-info`).

*Reconstructed from the code; predates this file.*

---

## Connection-per-call SQLite with a retry loop on writers only

**Problem.** Scanning is I/O-bound on both reading file bytes and writing rows,
and the tool wants many threads. SQLite connections are not safely shared across
threads.

**Decision.** Never share a connection. Every function opens `sqlite3.connect`,
runs its statement, and closes. Writers wrap that in a retry loop — 10 attempts,
100 ms apart, catching only `OperationalError` containing `database is locked`
and re-raising anything else.

**Consequence.** Read paths have no retry, so a reader that collides with a
long-running write raises rather than waiting. `audit-db` sets
`PRAGMA journal_mode=WAL`, and nothing else does — a database that has never been
audited is still in rollback-journal mode, where readers and writers block each
other far more.

**Ruled out.** A single connection guarded by a lock, which serialises the writes
this design is trying to overlap; and a connection pool, which is more machinery
than a tool with one table needs.

*Reconstructed from the code; predates this file.*

---

## The GUI writes `rm_commands.txt` instead of deleting

**Problem.** `/REQUIREMENTS.txt` §5 asks for a UI that "allows the user to
delete the duplicates in bulk (all), or a selected subset". Deleting files from
inside a duplicate browser, driven by checkboxes over a paginated list, puts an
irreversible operation one misclick away.

**Decision.** The GUI writes the shell commands it *would* run to
`rm_commands.txt` and deletes nothing itself. The user reads the file and runs it.

**Ruled out.** Deleting directly with a confirmation dialog — a confirmation on a
bulk action over a list the user has been scrolling for ten minutes is not
meaningful consent.

**Known defect.** The implementation wrote the `BooleanVar` object's repr rather
than the file path, so the generated file was not runnable. The design was right;
the implementation was broken.

**Status: moved, not abandoned (#51, 2026-11-16).** `src/gui.py` is gone from
this project and the GUI becomes a separate application (#53). **This decision
carries forward unchanged** — the browser emits shell commands for review and
deletes nothing itself — and so does the defect, as a lesson: capture the path
alongside the `BooleanVar` when the checkbox is built, rather than reading the
widget back. The broken output shipped for two years, which is what an untested
widget layer buys.

*Reconstructed from the code; predates this file.*

---

## The coverage floor is set to the measurement, not to the requirement

**Problem.** `/REQUIREMENTS.txt` has required 95% coverage since 2024. Real
coverage is 29.81%. Enforcing 95% in `pytest.ini` would fail every run from the
first one.

**Decision.** Set `--cov-fail-under` to the measured value rounded down (29), and
treat it as a ratchet that only moves up — raised in the same PR that raises real
coverage, never lowered to make a build green.

**Why.** A gate that fails constantly gets switched off within a week, and then
there is no gate at all. A gate set at the real number fails the moment anything
regresses, which is the only thing a floor can usefully detect, and every test
written from here moves it closer to the requirement.

**Ruled out.** Setting 95% and marking the suite `xfail` — the same as having no
floor, with extra ceremony. Setting no floor at all — coverage then silently
decays, which is exactly what produced the 29.81%.

**Related:** repo-root `/Development-Principles.md` §4.

---

## One gateway owns every SQLite connection

**Problem.** `reporting.py` called `sqlite3.connect` in five functions while
`db.py` owned the schema, the retry loop and the WAL pragma. The retry loop is
what made this more than untidiness: `db.py`'s writers wait out a
`database is locked`, reporting did not, so a report run alongside a scan raised
instead of waiting. Each of the five writers also carried its own copy of the
loop, two of them sleeping a hard-coded `0.1` while `RETRY_DELAY` sat unused
beside them.

**Decision.** `db.with_connection(db_path, work, commit=...)` is the only place
in the project that calls `sqlite3.connect`. It opens, runs the callable it is
given, commits if asked, and closes — retrying only on
`OperationalError` containing "database is locked", and re-raising everything
else on the first attempt. Every function in `db.py` goes through it, readers
and writers alike, and reporting's queries moved into `db.py` as named
functions.

**Why a callback rather than a context manager.** The unit being retried is the
whole piece of work, not just the connect: `audit_db` holds a cursor across a
`ThreadPoolExecutor` fan-out, and a `with` block cannot be re-entered from
inside itself when the body fails. Passing the work in makes the retry boundary
the same as the work boundary.

**Ruled out.** Leaving the writers with their inline loops and giving only the
readers a helper — the ticket's own reason for existing is that connection
handling in two places gets changed in one. A connection pool or a
long-lived connection per thread: SQLite's default threading mode forbids
sharing a connection across threads, and this codebase's concurrency is
threads throughout.

**Also fixed by the move.** The old `finally: if conn: conn.close()` referenced
`conn` before assignment whenever `sqlite3.connect` itself raised, so the
failure path was the one that could not run.

**Enforced by** `tests/test_db_owns_the_connection.py`, which parses each module
under `src/` and fails if any but `db.py` imports `sqlite3`. It is parsed rather
than grepped so the comments explaining the rule are not mistaken for
violations, and the walker has its own test proving it reports a file that does
import `sqlite3` — otherwise an empty result would be indistinguishable from a
broken walker (`/Development-Principles.md` §3).

**Related issues:** #10

---

## --min-duplicates counts copies, not copies beyond the first

**Problem.** `find_duplicates_with_min_count` compared with `>`, so
`--min-duplicates 1` returned groups of two and `--min-duplicates 3` returned
groups of four. The flag was off by one at every value, and the ticket (#6) left
the choice of meaning open: "at least N copies" or "at least N duplicates beyond
the first".

**Decision.** The flag counts **copies**. The comparison is `>=` and the default
moves 1 → 2.

**Why.** It is what the flag's name says, and pairing `>=` with a default of 2
leaves the tool's output unchanged for anyone running it today — the default
still reports groups of two or more — while every explicit value starts meaning
what it says.

**Ruled out.** Keeping `>` and restating the help as "beyond the first". That
preserves the arithmetic but leaves `--min-duplicates 3` returning groups of
four, which is the thing people actually trip over.

**Note for whoever tests this next.** A two-copy group cannot tell the two
readings apart — `> 1` and `>= 2` agree there, which is why the defect survived.
Every test in `tests/test_min_duplicates_boundary.py` uses a group of three.

**Related issues:** #6

---

## A hang needs a killer, not a reporter

**Problem.** Both scan paths — `file_ops.scan_dir` and `reporting.scan_dir_report` — shut their
workers down by putting one sentinel per worker on a queue. Getting that wrong does not raise; it
**hangs**. A hung suite never goes red. It is killed by a CI job limit, minutes later, with no
output naming the cause. And this was not hypothetical: `scan_dir_report` had never returned at all
(#43), because its consumer skipped `task_done()` on the sentinel and the closing `queue.join()`
waited on one unfinished task per worker forever.

**Decision.** `pytest-timeout` in `requirements-dev.txt`, with `timeout = 60` and
`timeout_method = thread` in `pytest.ini`. It dumps every thread's stack and then kills the process
with a non-zero status.

**Ruled out, both measured rather than reasoned about.**

- *pytest's built-in `faulthandler_timeout`.* It prints the same tracebacks and **stops nothing**: a
  30-second test under `faulthandler_timeout = 5` ran its full 30 seconds and reported `1 passed`.
  Diagnostics, not a gate.
- *A fixture running the scan on a daemon thread, failing fast.* Worse than nothing. The test goes
  red at its own timeout, and then the run wedges at **interpreter exit** instead, because
  `ThreadPoolExecutor`'s threads are not daemons and Python joins them at shutdown. Measured: pytest
  hung past 90 seconds with no output at all. It moved the hang somewhere with worse diagnostics.

**Why a dependency was accepted.** This repository is standard-library-only at *runtime*, and stays
that way; `requirements-dev.txt` already carries pytest, pytest-cov and mypy. Killing a wedged
interpreter from inside a test is not something a test can do to itself, so a plugin is the only
option that changes the outcome.

**Verified in both directions.** Reintroducing each defect — one sentinel for four workers in
`scan_dir`, and the missing `task_done` in `scan_dir_report` — turns the suite red in eight seconds
with the blocked consumers named in the dump. Restoring the fixes passes.

**Related issues:** #32, #43 · repo-root `/Development-Principles.md` §3a

---

## The untestable module leaves the denominator, not the report

**Problem.** `docs/REQUIREMENTS.txt` asks for 95% coverage. `src/gui.py` is a Tkinter widget tree and
a `mainloop()`, deliberately untested — asserting on widget construction tests the library, not this
code. While it sat inside `--cov=src` it was 82 of 601 statements, so the total capped near **88%**
with every other module at 100%. The floor could never ratchet to 95, and #8 could never close, no
matter how much real testing happened.

**Decision.** Omit `src/gui.py` in `.coveragerc`, and set the floor to what is then measured (93).

**The failure mode this had to avoid is silence, not arithmetic.** An omit list is the easiest place
in a repository to make a number say what you want, and a file dropped from a report is
indistinguishable from a file nobody wrote. So the exclusion is built to stay visible:

- `.coverage-summary.md` keeps a section titled **Excluded from measurement** that names `gui` and
  gives the reason, immediately below the measured table.
- The reason lives in `EXCLUSION_REASONS` in `scripts/coverage_summary.py`. The *list* does not —
  the script reads `.coveragerc`, the one place coverage.py itself acts on, so a second copy cannot
  drift. This is the same rule as `scripts/lib/mask.py`: one definition of the thing, or the two
  copies disagree eventually.
- A file omitted with no recorded reason renders as a warning line saying exactly that, rather than
  quietly appearing in neither table.
- `tests/test_coverage_config.py` fails if an omitted file has no reason, if the summary stops naming
  it, if the omitted path does not exist, or if `.coveragerc` and the rendered report disagree. Each
  guard was verified by breaking it.

**Ruled out.** Testing `gui.py` to raise the number: the tests would assert on Tkinter. Lowering the
requirement to 88%: it hides a real decision behind a number nobody could explain later. A blanket
`# pragma: no cover` scattered through the file: the same exclusion, spread across the code where no
report shows it.

**What is meant to happen next.** The part of `gui.py` worth testing — which selected rows map to
which paths — should be extracted out of the widget code, which is #3. When it is, it lands in a
module that **is** measured. The omit list does not grow to follow it.

**Superseded by #51 (2026-11-16), by a better answer to the same problem.** Rather than extract the
testable part of `gui.py` into a measured module, the whole GUI left this project for one of its own
(#53). `.coveragerc` now has no `omit` key at all. The reasoning above is kept because it is the
justification for the ceremony that still guards the list: re-adding an exclusion needs a recorded
reason, a ticket, **and** an edit to the test that asserts the live config omits nothing.

One thing changed in how that is tested, and it is the part worth carrying. With an empty omit list,
every "for each omitted file" assertion iterates nothing and passes without testing anything — which
is indistinguishable from a working guard (§3a). So `tests/test_coverage_config.py` now drives the
renderer with a fabricated `coverage.xml` and a fabricated omit list, covering an omission with a
reason, one without, and one that is not taking effect. The machinery is kept with an empty dict
rather than deleted, because it is the guard for the next exclusion, not a record of the last one —
and it is now proven to work while unused, instead of passing vacuously until someone needs it.

**Related issues:** #45, #8, #3, #51

---

## `--no-cov` must not rewrite the coverage report

**Problem.** `pytest_sessionfinish` regenerated `.coverage-summary.md` whenever `coverage.xml`
existed. Under `--no-cov` nothing is measured, but the previous run's `coverage.xml` is still on
disk — so the hook rewrote the committed report from stale numbers. Found while testing #45: a
`--no-cov` run regenerated the summary against a `coverage.xml` produced under a different
`.coveragerc`, and the report then disagreed with the configuration it claims to describe.

**Decision.** The hook returns early when `--no-cov` was passed, before it looks at `coverage.xml`
at all. Two independent reasons to decline: nothing was measured, or there is nothing to read.

**Why it matters more than it looks.** The summary is committed, and its whole value is being read
in a pull request diff. A file that silently rewrites itself from data belonging to a different
configuration is worse than one that is occasionally absent — a stale report is believed, a missing
one is noticed. `CLAUDE.md` had claimed this behaviour all along; it was the code that disagreed.

**Related issues:** #45

---

## "Could not check" is a third outcome, and it needs its own channel

**Problem.** `is_file_unique` answered `False` whenever hashing or the database lookup raised.
`False` is not "I could not tell" — it is a verdict, the same one returned for a file that genuinely
has a copy elsewhere. `scan-unique-files` reports the files with no copy anywhere, so an unreadable
file dropped out of that list on the strength of an answer nobody had. Read the output as "these are
the ones to keep" and the sole copy of a file goes, because of one I/O error while it was being
hashed (#41).

**Decision.** A dedicated exception, `UniquenessUnknown`, raised in place of the swallowed
`return False`.

**Why not a sentinel return.** `None` is falsy. Any caller writing `if is_file_unique(path, db):`
would reproduce the original defect exactly, and the code would look correct. An exception cannot be
ignored by accident, which is the whole property being bought. A test asserts the function's own
docstring still documents the third outcome, so a later refactor toward "a return value would be
tidier" fails rather than quietly succeeding.

**What the scan does with it.** `scan_and_report_unique_files` records `unreadable` in
`.processed_files.txt` — a status distinct from both verdicts — leaves the file out of the returned
list, and logs a warning naming the count, because the caller is about to treat that list as
complete.

**The resume log now distinguishes answered from asked.** Only `unique` and `not_unique` count as
processed. An `unreadable` row records that the question was asked and could not be answered, so the
next run asks again. The log exists to avoid repeating work, but repeating a question that was never
answered *is* the work — and permissions and mounts routinely differ between runs, so treating one
bad read as final would make it permanent.

**Related:** user-level `~/.claude/CLAUDE.md`, whose rule this is a direct instance of — a check has
three outcomes, and `CANNOT CHECK` must never collapse into `OK`. It is the same failure as #2,
where a missing mount point was read as a mass deletion, and the same reasoning that gives `audit-db`
its `SUSPECT` state.

**Related issues:** #41, #33, #2

## A headless scanner and a GUI are two programs, not one program with a flag

**Problem.** `src/gui.py` was reachable only through `report-duplicates --use-gui`, but it was not
optional in any way that mattered. `src/main.py` imported it at module scope, so **every** run
imported `tkinter` — including a root scan of five million files on a machine with no display. The
costs were spread thin enough to look acceptable individually:

- CI needed a "Verify tkinter is available" step for a dependency nothing under test used, because
  collecting the suite imported the widget tree.
- The module had to be excluded from coverage, since asserting on widget construction tests Tk
  rather than this code. While measured it capped the total near 88% and put the 95% in
  `docs/REQUIREMENTS.txt` out of reach however well everything else was tested (#45).
- Bundling the scanner to run as root meant either bundling Tk or special-casing the import (#52).
- Its only output had been unrunnable for two years (#3), which no CLI test could have caught.

**Decision (owner, 2026-11-16).** Remove the GUI from this project. FileManager is a headless CLI
scanner: no Tk, no display, no optional GUI flag. The graphical duplicate browser and editor becomes
a separate application (#53) that reads the same database.

This also answers #11, which had asked whether the "full featured graphical user-interface" in
`docs/REQUIREMENTS.txt` §4 was still wanted or whether the requirement should be revised to describe
the paginated list that was actually built. It is still wanted — as its own program. **So
`REQUIREMENTS.txt` is not edited.** It is the original 2024 specification and stays as written; the
requirement is satisfied elsewhere, and that is recorded here rather than by rewriting the spec to
match the code.

**Consequence accepted.** `report-duplicates --use-gui` is now an argparse rejection, exit code 2.
Any wrapper or cron entry carrying the flag breaks rather than silently ignoring it, which is the
right direction: a scan that quietly dropped an unrecognised flag would look like a normal run.

**Ruled out.** Making the import lazy and keeping the GUI — one line, and it would have removed the
CI step and the bundling problem. Rejected because it leaves the coverage hole, the untested widget
layer and the broken output in place; it treats the symptom that was cheapest to see. Deleting the
GUI outright with nothing to replace it: the duplicate browser is the only part of this tool a
non-technical user can operate, and a list of duplicates in a terminal is not a substitute.

**Measured effect.** 18 test modules instead of 17, 209 tests, mypy checking 7 files instead of 8,
and coverage 99.59% → **99.58%** — a 0.01pp fall from deleting *covered* code, not from adding
untested code. The floor stays at 99; a ratchet does not move down.

**Related issues:** #51, #53, #3, #11, #45, #52

---

## The bundle is a zipapp with an absolute isolated-mode shebang

**Problem.** The scan that this tool exists to run — a checksum baseline over `/home2`
and a backup volume — has to run as root, because the trees contain files the developer
account cannot read, and a file skipped for permissions is recorded as nothing at all.
But the project's interpreter is a pyenv virtualenv in the developer's home directory.
Under `sudo` that is the wrong interpreter to reach for and often an unreachable one, and
a scheduled run that resolves `python` from the caller's environment is how #9 happened:
the wrappers pointed at an older checkout for months while every test passed.

**Decision.** Ship one file. `scripts/build-pyz.sh` copies `src/` into a build directory,
writes a three-line `__main__.py`, and calls `python -m zipapp` with
`-p '/usr/bin/python3 -I'`, producing `dist/FileManager.pyz` — 52K, standard library
only, nothing to install at run time.

Three parts of that are deliberate and each is pinned by a test.

**`/usr/bin/python3`, written absolutely, not `env -S python3`.** `env` resolves `python3`
from the caller's `PATH`, which reintroduces a smaller version of exactly the problem the
bundle exists to remove — under `sudo` the PATH is not the one that was tested. `env -S`
also needs coreutils 8.30 or newer. The absolute path says which interpreter runs, and
`tests/test_build_pyz.py` asserts the first line of the artifact is the exact string
`#!/usr/bin/python3 -I`, because a consumer's installer matches on it.

**`-I`, and exactly one option.** Isolated mode drops `PYTHONPATH`, user site-packages
and the script's directory from `sys.path`, so a root run cannot import a module planted
by an unprivileged user in a directory that happens to be on the path. Only one option
fits: Linux passes everything after the interpreter path in a shebang as a **single**
argument, so `-I -B` arrives as the one string `"-I -B"` and the interpreter exits 2 with
`Unknown option`. Verified rather than assumed.

**The build clears `__pycache__` before archiving.** `cp -r src` copies bytecode next to
the source, and a zipapp serves a stale `.pyc` without complaint: CPython invalidates on
`(mtime, size)`, so a file rewritten to the same length inside one second keeps the old
bytecode. This had already produced one wrong conclusion in this repository before the
guard existed.

**Alternatives rejected.** PyInstaller, shiv and vendoring a virtualenv all add a
dependency and a build toolchain to a project whose entire argument is that it needs
neither — there are no runtime dependencies to bundle. Documenting
`sudo -E ~/.pyenv/versions/sys-utils/bin/python src/main.py` instead was rejected because
it is the #9 failure written down as an instruction.

**What the guards cost to be trusted.** Each was proven to fail with the defect
reintroduced before being believed: disabling the `__pycache__` removal put 15 `.pyc`
files in the archive and failed the test; `chmod -x` on the build script failed the mode
check by name; a zipapp whose `__main__.py` raises made the build script exit non-zero.
A detector that stops nothing is not a gate (`docs/Development-Principles.md` §3a).

**What the bundle does not fix.** It changes how the scanner is invoked, not what it
reports. A bundled scan that cannot read part of the tree still exits 0 with no failure
count (#57), and nothing verifies a checksum once recorded (#50). The remaining
packaging requirements — a `--version` carrying the build commit, and a timestamped
header with the zone — are #54.

**Related issues:** #52, #54, #57, #9

---

## An exit status says what happened, and "partly" is its own answer

**Problem.** Three different outcomes were reaching callers as the same number.
A scan that read the whole tree exited 0. A scan that could not read part of the
tree also exited 0, having logged one `ERROR` line per unreadable file among
thousands of per-file `INFO` lines on stderr, and recorded a database that is
indistinguishable from a complete one. And `--help` — the first thing anyone
runs — exited **2**, the code reserved for a rejected command line.

The partial scan is the one with consequences past the process. The database
holds no marker for a file that was skipped, so after the fact there is no way
to tell a file that was absent from the tree from one that could not be opened.
A later `audit-db` has nothing to report, and a duplicate report over the partial
set is internally consistent. For a checksum baseline whose entire purpose is
detecting later change, a silent gap reads as a file that never existed. The
tool's output is a list of files a human may then delete, so this is not a
reporting nicety.

**Decision.** Four codes, each meaning one thing:

| Exit | Meaning |
|---|---|
| 0 | completed, and read everything it was asked to read, or help was requested |
| 1 | a required argument was missing or invalid |
| 2 | `argparse` rejected the command line |
| 3 | completed, but could not read part of the tree |

`scan` and `audit-db` count hashed, skipped-unchanged and failed, and print the
counts and each failed path.

**3 is separate from 1 and 2 rather than folded into either.** 1 and 2 mean
nothing was recorded at all, so there is nothing on disk to reason about. 3 means
part of the tree was recorded and part was not, which is the only case where a
caller has to decide what to do with a half-built database. Collapsing them would
make the distinction unavailable precisely where it matters.

**The counts go to stdout, not through `logging`.** Every log line in this
project goes to stderr, and a scheduled scan suppresses the per-file noise with
`2>/dev/null`. A summary written to the log stream would be discarded by exactly
the runs that most need it. The counts are the result of the run, not a
diagnostic about it.

**The help flags are matched against `sys.argv` before parsing, not registered
with argparse.** Two constraints have to hold together. The help text is
`usage()`, which documents the actions, the options, the exit-code table and
worked examples — argparse's generated help has none of that. And `action` is a
required positional, so `--help` with nothing else would fail the
missing-argument check before argparse ever looked at the flag. The positional
`help` action is kept as well as the flags, because it is documented, it is in
the `fm-*.sh` wrappers, and an external installer probes it.

**Alternatives rejected.** Reusing exit 1 for a partial scan: it is the code for
a bad command line, and conflating "you asked wrongly" with "I could not finish"
is what this entry exists to undo. `add_help=True` alone: it would still have
exited 2, because the `except SystemExit` around `parse_args` returned 2 for
every code including 0 — that handler discarding its input is the underlying
defect, the same shape as #23, and it has to be fixed for `--version` (#54) to
work at all. Raising on the first unreadable file: a baseline scan of millions of
files must not abandon the work that succeeded because one file was unreadable;
the point is to record what can be recorded **and** report the gap.

**What was retracted while building this.** A test asserting that `ScanTally`'s
lock prevents lost increments passes with the lock removed: 32 threads, 50,000
unsynchronised increments each, a 1 ns switch interval, zero lost, on CPython
3.14.7 and on `/usr/bin/python3` 3.12.3. Both are GIL builds, so no test on
either interpreter can distinguish the two versions. It was replaced by one that
can fail — every file in a concurrent scan lands in exactly one bucket, verified
against both a double-count and a dropped outcome. The lock stays, for a
free-threaded build, held by reasoning rather than by a test, and the test module
says so rather than implying otherwise. A detector that cannot fail is not a gate
(`docs/Development-Principles.md` §3a), and the honest response is to label it,
not to keep it as decoration.

**Related issues:** #57, #58, #23, #54

---

## A build records what it was built from, and refuses to guess

An installed bundle is one file, root-owned, outside any checkout. Asked "which
code is this?", it has nothing to consult: no git repository, no source tree, and
not even a usable checksum — zip entries carry file mtimes, so two builds of the
same commit differ byte for byte. A hash of the `.pyz` identifies a *build*, not
a revision. Yet the question has to be answerable, because the thing produces a
list of files a human may then delete, and a 20-hour unattended scan that gave a
wrong answer has to be traceable to the code that produced it. The consumer's
installer refuses to install an artifact that cannot say.

**The decision: embed the values at build time, into the copy being archived.**
`scripts/stamp_build_info.py` writes `src/build_info.py` into `build/pyz/src/`
after `build-pyz.sh` copies the source and before `zipapp` runs. The committed
`src/build_info.py` holds `None` for every field, and **that `None` is the
signal** — `--version` reads it to mean "not a bundle", falls back to asking git
about the working checkout, and labels the answer as a source run.

`None` rather than an empty string, a placeholder, or a row of zeros, because a
zero hash is a *value*: it gets printed, compared, and believed. The same
reasoning produced `UniquenessUnknown` in `db.py` (#41) — "could not determine"
must not be expressible as an answer that looks like one.

**Alternatives rejected.** Asking git at run time fails for the only case that
matters, an installed artifact with no repository near it. Writing the stamp into
the committed `src/` would leave the checkout permanently dirty or the file
permanently gitignored, and a gitignored source module is one more thing that
exists in a build and not in a test run. Putting the formatting inside
`build_info.py` would put logic in a file the build overwrites, so it would exist
in two versions that drift — hence the split into `version.py` (logic, committed)
and `build_info.py` (data, replaced).

**The build refuses a dirty tree**, because a bundle built from uncommitted edits
names a commit that does not contain the code inside it. That is worse than an
unknown answer: it is confidently wrong, and nothing downstream can detect it.
`FM_ALLOW_DIRTY=1` is the deliberate escape and costs the artifact its clean
claim for as long as it exists. The check is scoped to `FileManager/` rather than
the whole repository — a repo-root README edit refusing a build would train
people to pass the override by reflex, which is how a safety check becomes
decoration.

A git question that **cannot be asked** is a third outcome, not a clean tree:
`git status --porcelain` prints nothing for a clean tree *and* nothing when it
cannot read the repository, so emptiness proves nothing on its own. Both the
stamper and `--version` distinguish the three.

**A note on testing it.** Three refusals were written and each was broken in turn
to see which test failed. Two fired. The third — "git could not tell me the tree
state" — broke nothing, because when git cannot be consulted at all `rev-parse
HEAD` fails first and the stamper returns before it ever asks about the tree. The
branch was real and reachable in principle, and unreachable by every test
written for it. An unreadable `.git/index` separates the two calls (`rev-parse`
reads refs and answers; `git status` opens the index and exits 128), which is now
the test that covers it. Recorded because the lesson is not "write a test" but
**"check that the test can fail"**, and this is the third time in this repository
that checking found one that could not (§3a, and #57's lock test).

**Related issues:** #62, #54, #52, #58, #41

---

## A run states its configuration on the channel that survives redirection

A scan of `/home2` takes 20+ hours, runs as root from cron, and produces a
database a human will later delete files on the strength of. The only durable
account of it is its log — read days afterwards, by which time the command line,
the working directory and the state of the checkout are all gone.

There was already a line recording four of the right things:

```python
logging.info(f"ACTION: {args.action}; PATH(s): {args.path}; DB: {db_path}; THREADS: {args.threads}")
```

**It could not do the job, for three separate reasons.** It went to the logging
stream, which is stderr, and every scheduled scan runs with `2>/dev/null` to
suppress the per-file chatter — so the one record of the configuration was thrown
away by the one redirection the real runs all use. It named no version, so the
log could not be tied to the code. And its `asctime` had no zone, which has
already caused output here to be read against the wrong one.

**The decision: a header on stdout, before the first side effect, with the zone.**
Same channel as the scan counts and for the same reason (#57) — the result of a
run and the configuration of a run are both results, not diagnostics. The
per-file logging stays on stderr, where suppressing it remains safe.

`help` and `--version` are excluded. They are questions about the tool rather
than runs of it, and `build-pyz.sh` verifies the artifact by grepping
`--version` output: a header in front of that would turn a passing build check
into a failing one.

**One definition of the timestamp format.** `TIME_FORMAT` lives in
`src/version.py` and `scripts/stamp_build_info.py` imports it rather than
keeping a copy, at the cost of the stamper putting the project root on
`sys.path`. The build time recorded in an artifact and the start time printed by
a run are the same kind of fact; two format strings is how they come to
disagree, and the same argument as `scripts/lib/mask.py` holding the only copy
of the secret patterns.

### Why "no imports inside functions" is a correctness rule here, not style

Requirement 7 of #54 reads like a style preference and is not one. Python's zip
importer resolves a module by **reopening the archive at its path**. A `.pyz`
replaced during a run — an install, an upgrade, a rebuild — leaves the running
process reading the *new* archive for every module it has not yet imported. A
20-hour root scan is long enough for that to happen, and the result is a process
running half of one version and half of another, producing a database that
cannot be accounted for afterwards.

Two report arms imported from `src.reporting` lazily until #54. They are hoisted,
and `tests/test_imports_at_startup.py` parses every module under `src/` with
`ast` and fails on a function-level import. `ast` rather than a text search
because a regex cannot distinguish an import statement from the word "import" in
a docstring — the same choice `tests/test_db_owns_the_connection.py` made.

### What requirement 8 actually required

"No file access relative to `__file__`" is easy to read as "do not call
`open(__file__)`", which nothing here does. The real risk is subtler.
`src/version.py` computes `SOURCE_ROOT` from `__file__`; inside an archive that
is a path like `/…/FileManager.pyz/src/version.py`, naming a directory that does
not exist. The value is **computed but inert**: a bundle reads its commit from
`build_info` and never consults git, so the path is never used.

Nothing in the suite would have noticed that changing. A fallback to asking git
at run time would pass every version test on any machine that has git installed.
So `--version` is also run from the built bundle with `PATH=/nonexistent/bin`:
the one condition under which the difference between "embedded" and "looked up"
is observable.

**Related issues:** #54, #62, #57, #52, #9

---

## Reading the baseline back is a separate action, and it must not repair

The database stores `(md5sum, size, last_modified, path)` and the whole point of
the checksum is to answer "are these bytes still the bytes I recorded?". Until
#50 nothing asked. `scan` and `audit-db` both compare `(size, mtime)` and skip
hashing when they match — which is exactly what makes rescanning a multi-terabyte
archive affordable, and exactly why neither can see corruption: bit rot, a bad
sector and a failing cable all rewrite bytes without touching either field. On a
file rewritten in place with its mtime restored, `scan` reports `0 hashed, 2
skipped unchanged, 0 failed` and `audit-db` reports `failed 0`. Both are correct
about what they measure and both answer the wrong question.

**The decision: a separate action, `verify-db`, that rehashes unconditionally.**
Not a flag on `scan` — the skip check is `scan`'s reason for existing and a
`--force-rehash` would make the cheap path and the expensive path the same code
with opposite performance characteristics. Named as a counterpart to `audit-db`:
that one re-verifies metadata, this one re-verifies content.

**It is read-only on the database, and that is the load-bearing decision.** The
obvious next step after detecting a mismatch — update the row — would be wrong
twice over. It destroys the only evidence that the file ever differed, and it
makes the second run pass, so a scheduled verify would report a problem once and
then be silent forever. A test runs the verify twice and asserts the mismatch is
still reported.

**Three outcomes, never two.** Match, mismatch, could-not-read. An unreadable
file is **not** a pass: its stored checksum is still unverified, which is the
same distinction `UniquenessUnknown` draws (#41) and the same one the scan's
failed count draws (#57).

### Exit 4, and why it is not 3

| code | the operator's question it answers |
|---|---|
| 3 | part of what I asked about is **unknown** — check the volume, run it again |
| 4 | the answer is **known and bad** — a recorded file's contents have changed |

Those call for different actions, so they are different codes. Collapsing them
into "non-zero" would repeat the mistake this area of the code has been fixed
for twice already (#23, #57). A mismatch outranks an unreadable file when both
happen in one run: the definite wrong answer in the database is the more
important fact.

### Scoping: a prefix, not a resume log

Verifying the recorded volumes takes hours, so a run has to be able to be
smaller than all of it. #50 allowed "restartable **or** prefix-scoped" and the
prefix was chosen. A resume log is state that can go stale against the database
— and `scan-unique-files` already demonstrates the second problem with the idea:
its `.processed_files.txt` lands *inside* the tree being scanned and is then
scanned like any other file. A prefix is stateless, and the operator picks the
subtree. `recorded_checksums` orders by path so two runs over one prefix report
in the same order and their output can be diffed.

### What the tests had to prove

Two mutations, because this action's value is entirely in catching a case
everything else misses:

- `verify_one_recording` made to trust `(size, mtime)` instead of rehashing — the
  original defect, reintroduced — **fails 14 tests**.
- A mismatch made to rewrite the stored row, as a well-meaning repair would —
  **fails exactly the test written for it**.

The corruption fixture also asserts on its own effect, comparing size and
`st_mtime_ns` before and after, so a fixture that silently stopped preserving
them would fail rather than quietly test nothing. And the suite keeps a test
stating that `scan` and `audit-db` *still* miss corruption in place: it records
the premise, and if it ever starts failing, this design should be re-read before
being trusted.

**Related issues:** #50, #57, #41, #23

---

## The manual is troff, and its markdown copy is generated

The CLI documented itself in two places that a reader had to already know
about: `usage()`, printed by `help`, and this project's `CLAUDE.md`, which is
written for whoever is changing the code rather than for whoever is running it.
Neither is a manual. An operator installing the bundle on another machine has
no checkout to read, and `man filemanager` is where they would look.

The manual is therefore `man/filemanager.1`, written in troff with the
`man(7)` macros: the format `man` renders, the format a package installs, and
the format whose conventions — SYNOPSIS, EXIT STATUS, FILES, ENVIRONMENT,
BUGS — already have the sections this tool needs. Its exit-code table and its
stdout/stderr split are the two things an unattended caller has to get right,
and both now have a home that is not a comment in `main.py`.

Troff is not readable in an editor, so a markdown rendering is committed beside
it. **The troff is the source and the markdown is generated** — never the other
way round, and never both maintained by hand, which is how two copies of one
document come to disagree.

### Why a renderer in this repository rather than pandoc or groff

`scripts/render_man.py` is about 250 lines of standard library. Both obvious
alternatives were tried first and measured.

`groff -man -Tutf8 | col -b` produces the exact `man` rendering as plain text
and is one line. It was rejected on what the check would then be able to prove:
the gate is a byte comparison between the committed copy and a fresh render, so
the renderer has to run **where the gate runs**, and depending on groff being
installed in CI makes a green build depend on a package the project does not
otherwise need.

`pandoc -f man -t gfm` is also one line, and its output was wrong in three
places. Both `.SY`/`.YS` synopsis groups collapsed into a single run-on
paragraph, losing the distinction between the two ways to invoke the tool.
`.BI scan " path"` rendered as `**scan*** path*`, which is not valid emphasis
in any markdown dialect. And the troff `` ` ``…`'` quoting around literal
commands became backslash-escaped punctuation rather than a code span. Beyond
the output, pandoc's rendering changes between pandoc versions, so a byte
comparison would fail on a version bump rather than on a real drift — a gate
that cries wolf is a gate that gets deleted.

### The renderer refuses rather than guesses

It implements exactly the macros and escapes `man/filemanager.1` uses, and
raises `UnsupportedTroff` on anything else. Nothing is written when it raises.

The alternative — skipping what it does not recognise, which is what a
forgiving renderer does — produces a markdown file that looks finished and is
quietly missing a paragraph. That is the same failure as a check that could not
run reporting success, and it is worse here than an error, because the next
reader believes the document. The first inventory of this page's escapes was
taken with a regex that missed `\fB`, `\fR` and `\fP` entirely; the renderer's
refusal is what surfaced them, which is the argument in miniature.

### Two gates, because one of them cannot see the renderer being wrong

`tests/test_man_page.py` compares the committed markdown against a fresh render
byte for byte. That catches a stale file, a hand-edit, and a commit of the
troff without the markdown. It cannot catch the renderer silently dropping
content, because both sides of the comparison would then be missing it.

So a second test reads the section headings out of the troff directly — not
through the renderer — and looks for each one in the markdown. This was
verified by mutation: with `_do_SS` made to return early and the markdown
regenerated, the byte comparison passes and only the heading test fails
(`docs/Development-Principles.md` §3a). The duplication of the `\-` expansion
in that test is deliberate for the same reason; a check that shares the
renderer's code cannot catch the renderer.

Regeneration itself is a `pytest_sessionfinish` hook, the same arrangement as
`.coverage-summary.md`, but without that file's staleness problem: the coverage
summary declines to run under `--no-cov` because it would rewrite itself from a
previous run's numbers, whereas this render's only input is the troff file, so
it is correct on every run. The hook runs *after* the tests, which is the right
order — a session that starts stale still goes red, and the file is correct for
the next one.

**Related issues:** #54, #57, #50

---

## A git question is scoped to a root, and the environment must not re-scope it

Every git call in this project names the directory it is asking about:
`git -C <root> rev-parse HEAD`, `git -C <root> status --porcelain`. That scope
is the whole design -- `src/version.py` reads the live state of a checkout,
`scripts/stamp_build_info.py` decides what a bundle will claim about itself for
the rest of its life, and both are questions about one specific tree.

**`GIT_DIR` and `GIT_INDEX_FILE` in the environment outrank `-C`.** A command
that inherits them answers about a different repository and reports success, so
the scope the call spells out is silently replaced. git exports both into the
environment of every hook it runs, which is how a value nobody set reaches code
that never asked for one.

The symptom arrived from the Claude-operations lane as #71: the pre-commit hook
runs the FileManager suite, so `tests/test_stamp_build_info.py`'s throwaway
repositories were addressed through *this* repository's index. Nine tests failed
at fixture setup with `error: invalid object ... Error building trees`, and every
local commit touching FileManager code was refused. PR #63 was merged on GitHub,
so no local hook had ever run those tests -- the same shape as a gate that has
never been proven to fire.

### The scrub lives in one place, and reaches past the tests

`src.version.git_env()` returns the environment with every `GIT_*` variable
removed, and `_git` passes it. `scripts/stamp_build_info.py` imports it exactly
as it already imports `TIME_FORMAT`, for the same stated reason: two copies of
one definition is how they come to disagree. The test helpers import it too.

**Fixing only the test helper was the tempting reading of the ticket and the
wrong one.** The tests were what hurt, but the stamper is where the consequence
is permanent: a build driven from a hook would read another repository's HEAD
and tree state and write them into the archive as facts about `root`. The result
is a bundle whose `--version` names a commit it does not contain -- precisely the
confidently-wrong answer the dirty-tree refusal exists to prevent, arrived at by
a route the refusal does not watch. An index built by such a bundle cannot be
traced back to code afterwards.

Scrubbing at each call site was rejected for the same reason the definition is
shared: the property wanted is *every* git question in this project is answered
about the root it names, and a per-call-site opt-in is a property that holds
until the next call site is written.

### Proven to fire, three times

A guard that cannot fail is this repository's named defect (`#45`-era reasoning,
`docs/Development-Principles.md` §3a), and a scrub is invisible when it works.
So each of the three tests was run against a deliberately disabled `git_env()`
and observed to fail there: the scrub itself; the live read, which without it
reports `CANNOT DETERMINE` for a checkout git can answer for perfectly well;
and the stamper, driven against a decoy repository whose HEAD it must not
report. The measurement that opened the ticket was reproduced the same way, with
`GIT_INDEX_FILE` pointing at a *copy* of this repository's index rather than the
index itself -- those fixtures run `git add`, and aiming them at the live index
could have rewritten it.

**Related issues:** #71, #62, #54

---

## The scan queue is bounded by a memory budget, expressed as a path count

**The problem.** `scan_dir` and `scan_dir_report` walk the tree on a producer
thread and hand paths to `--threads` workers through a `Queue`. The walk reads
only metadata and the workers hash contents, so on a baseline scan, where every
file is new, the producer is orders of magnitude faster. The queue was
unbounded, so the producer queued the whole tree before the workers caught up:
about 0.63 GiB of path strings for the 5.58M files on `/home2`. Memory followed
the size of the tree rather than the amount of work in progress, and the
failure was the OOM killer partway through a 20-hour run, which reports nothing.
Exit 3 (#57) covers files that could not be read, not a process that was killed.

**The decision.** Both queues take `maxsize=SCAN_QUEUE_MAXSIZE`, so `put()`
blocks the producer when the workers fall behind. The owner set the bound as
**8 MiB of memory**. A `Queue` limits items, not bytes, so the budget is
converted with the measured cost of one queued path: 122 bytes for a
67-character path, counting the `str` and its deque slot. That gives 68,759
paths, and a full queue of such paths measured 7.63 MiB. The constants are
`SCAN_QUEUE_MEMORY_BYTES` and `BYTES_PER_QUEUED_PATH` in `src/file_ops.py`, and
`reporting` imports the result, so the two scans cannot disagree.

**What was ruled out.**

- *A fixed count of a few thousand* (the first version of the PR, 4096 paths,
  about 0.5 MiB). It worked, but the number did not state what it was for. A
  budget in bytes does.
- *A true byte limit.* Exact accounting needs a `Queue` subclass that tracks the
  size of what it holds and blocks on bytes. A long path costs about one byte
  more per character, so a tree of very long paths can go past 8 MiB, but the
  error is bounded by path length, not by tree size, which is the property
  that mattered. The extra machinery was not worth it.

**Shutdown with a bounded queue.** The sentinel ordering is unchanged: the
producer puts one sentinel per worker after the last path. Those puts can block
on a full queue, and they complete because the workers keep draining until each
has taken its sentinel. `tests/test_scan_queue_bound.py` runs eight workers
against four slots to prove it, with the `timeout = 60` in `pytest.ini`
unchanged. The tests hold the workers on a gate and check the largest `qsize()`
seen. With the bound removed that check alone failed (41 and 48 against a bound
of 4), so it is known to fire.

**Not fixed here.** If the producer raises before its sentinels, the workers
wait forever. Putting the sentinels in `finally` alone would turn that hang into
a partial index reported as complete, so the fix also needs the failure
recorded in the results. Filed as #75.

**Related issues:** #67, #43, #57, #75

---

## Only regular files are read, and a symlink is never followed

**The problem.** Every action that walks a tree opened whatever `os.walk`
listed under `files`, and that list includes devices, FIFOs, sockets and
symlinks. The mahtoh baseline scan of `/home2` never finished. One worker read a
copied `/dev/random` in a backed-up postfix chroot for about 36 hours, because
a character device never reaches end of file. Another worker was blocked in
`open()`, which is how a FIFO with no writer behaves. A root `rsync -a` backup
recreates these files every night, so any backup volume can contain them. The
scan gave no error and wrote no summary, and the database stopped growing 12
hours before anyone looked.

**The decision.** The owner's rule: only regular files are read or recorded,
and a symlink is never followed, whatever it points at. `src/regular_files.py`
is the one definition, and the rule is enforced in three places, each with a
test that fails without it:

1. `walk_regular_files` uses `lstat` and yields only `S_ISREG` entries. It
   counts every other entry by kind, including a symlink to a directory, which
   `os.walk` lists under `dirs` and skips without any record.
2. `process_file` checks before the skip check. A symlink row recorded by an
   older version matches its stored (size, mtime) through the link, so without
   this check it would report `skipped` and keep the row.
3. `compute_md5` checks before it opens anything, opens with
   `O_NOFOLLOW | O_NONBLOCK`, and re-checks the open descriptor with `fstat`. A
   path replaced by a FIFO after the check therefore cannot block the `open()`.
   The check comes *before* the open, and not only after it, because opening a
   device can have effects of its own: a tape drive rewinds.

**A skip is not a failure, and a named path is.** A skipped entry is logged per
path and counted by kind in a second summary line, and it does not change the
exit status, because nothing that belongs in the index was missed. A
non-regular path named on the command line is different: the operator asked
for it and the scan did not cover it, so it counts as a failure (exit 3), like a
missing path.

**What each action does with an existing row.** `audit-db` removes rows whose
path is no longer a regular file, under `--dry-run`, and counts them as
`not regular` apart from deleted files. `verify-db` never writes, so it reports
such a row as unreadable and names `audit-db`. Calling it a pass would break
the three-outcome rule from #50.

**The audit had to change how it tests for "missing".** It used
`os.path.exists`, which follows symlinks and returns False for *any* error. A
recorded file under a directory the auditor could not search was therefore
removed as deleted. Only `FileNotFoundError` and `NotADirectoryError` now count
as missing. Any other error is a failure, the row is kept, and the audit exits
3. This fails closed: a row lost by mistake can only be recovered by a rescan,
while a kept row costs one more audit.

**What was ruled out.**

- *Following a symlink to a regular file.* This would record one file under
  two paths, so every symlink would appear as a duplicate of its own target,
  in a tool whose output is a list of files to delete.
- *Checking only in the consumer.* It works, but the queue would carry entries
  that are never read. Checking in the walk also counts a symlinked directory,
  which never reaches the consumer at all.
- *Relying only on `O_NONBLOCK` and `fstat`.* That would stop the hang but
  still open every device in the tree.

**Related issues:** #74, #50, #57

---

## A walk that stops early must end the scan and must be reported (#75)

**Problem.** Both producer/consumer scans (`scan_dir` in `src/file_ops.py` and
`scan_dir_report` in `src/reporting.py`) stop their workers with one sentinel
per worker. The producer put those sentinels only after the walk finished. If
the walk raised an exception partway through, no sentinel was put, every worker
waited in `queue.get()`, and the scan never returned.

**Decision.** The producer puts the sentinels in a `finally` block, so the
workers always exit. It also records the stopped walk as a failure, because a
`finally` block alone would turn the hang into a partial index reported as a
complete one, which is the problem #57 fixed. `scan` lists the directory as
`walk stopped early: <reason>` in its failure list and exits 3.
`scan_dir_report` keeps no tally, so it returns False and `main` exits 3. The
traceback is logged in both cases.

**What was ruled out.**

- *Only the `finally` block.* It stops the hang but reports exit 0 for a tree
  that was only partly walked.
- *A timeout on `queue.get()` in the workers.* A worker cannot tell a slow walk
  from a stopped one, and a scan of a large tree has long pauses between
  directories.

Each half was removed in both producers and a test failed: without the
`finally` block the test hung until pytest-timeout stopped it, and without the
recording three tests failed in about one second.

**Related issues:** #75, #57, #43
