# FileManager — Architecture & Design

A decision record. Each entry states the problem, the decision, what was ruled
out, and the issues involved. Newest first. Entries dated before this file
existed are reconstructed from the code and are marked as such.

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

**Problem.** `doc/REQUIREMENTS.txt` §5 asks for a UI that "allows the user to
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

**Problem.** `doc/REQUIREMENTS.txt` has required 95% coverage since 2024. Real
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

**Related:** repo-root `doc/Development-Principles.md` §4.
