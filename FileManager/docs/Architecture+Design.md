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

**Known defect.** The current implementation writes the `BooleanVar` object's
repr rather than the file path, so the generated file is not runnable. The design
is right; the implementation is broken.

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
