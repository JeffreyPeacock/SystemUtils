# SystemUtils Development & Project-Management Principles

A growing collection of principles that guide how we **build and sequence** work in this repository —
the durable lessons worth carrying forward, not one-off decisions. Add to it whenever a principle
crystallises; keep each entry short, concrete, and paired with *why* and an example.

Entries 1–3 are adopted from the WhiteFeather/WTIS principles, which this repository's conventions
were adapted from. Entry 4 was written here.

---

## 1 — Prioritize by sequencing, not just severity (foundation-first)

Priority is usually framed around **severity**: a p1 is something *broken*. But priority also encodes
**sequencing**: some work isn't a hard blocker, yet it's foundational scaffolding that should be in
place *before* you build further on top of it. That work is legitimately **p1 ("do this now")** even
though nothing is on fire.

1. **Reduces the calcification of debt.** Ad-hoc structures harden as things get built on them.
2. **The cheapest time to change a foundation is now.** The cost grows with every dependent feature.
3. **It accelerates everything downstream.** Patterns to follow, nothing to work around.
4. **It avoids rework.** Building on a shaky base means redoing the feature when the base shifts.
5. **It compounds.** Each feature on a good foundation is a little better and faster.
6. **It de-risks the scary failure modes.** The gaps that cause catastrophes are usually foundational.

**In practice:** when you're about to build a feature on top of ad-hoc infrastructure, stop and lay
the foundation first. Promote such work to p1 *with intent*, and note **why** it's p1 (foundation,
not fire) so the rationale is visible to whoever triages next.

**Example in this repo:** the test suite could not even be collected — two modules imported names
that do not exist — while `FileManager/docs/REQUIREMENTS.txt` asked for 95% coverage. Writing new tests against a
suite that would not run was pointless; repairing collection came first, and it was cheap precisely
because nothing had been built on top of the broken state yet.

---

## 2 — A run must record the configuration that produced it

Any process that runs unattended — a cron, a batch job, a long scan — must state, in its own output
**and** in its durable log, the **name, resolved value, and origin** of every setting that controlled
its behaviour. Origin means: was this value **set**, or did it **fall back to a built-in default**?

The value of a setting *at the moment a run happened* is not recoverable afterwards. Defaults change
with the code, and a wrapper script carries no history. A log that records only what a run **did**,
without what it was **configured to do**, cannot be re-interpreted later — and "later" is exactly
when you need it.

1. **It is the only chance to capture it.** Everything else can be reconstructed from state.
2. **It answers "why did it do that?" without a re-run** — which for a multi-hour scan is expensive.
3. **Origin catches the mistakes that values alone hide.** A setting you *believe* is configured but
   which is silently defaulting looks identical in the output to one genuinely set.
4. **It makes drift visible between environments.** A diff of two logs becomes the whole audit.
5. **It scales with irreversibility.** Settings that gate deletion deserve this most.

**In practice:** resolve every behaviour-controlling setting through one shared helper that records
name, value, and origin; print the block near the top of the run, before any work output. **Never
route a credential through it** — this output is printed and written to disk.

**Example in this repo:** `audit-db` deletes database rows and `--exclude-prefix` is what stops it
touching an unmounted volume. A run that does not print `--exclude-prefix=<value> (set)` versus
`(default: none)` cannot afterwards be distinguished from one where the flag was forgotten — and the
difference is thousands of deleted rows.

---

## 3 — Enforce with a test what a review cannot see

Some defects are invisible in a diff: file modes, permissions, symlink targets, encodings, line
endings, whether a required binary is on `PATH`, whether a fixture file exists. A reviewer reading a
pull request has no way to notice them, so "we'll catch it in review" is not a control — it is a
hope. These need an **executable rule**: a test that states the invariant and fails when it breaks.

1. **A control you cannot perform is not a control.**
2. **These defects are discovered at the worst moment** — mid-task, on the machine that matters.
3. **They spread silently.** New files are created by copying an existing one.
4. **The test doubles as the documentation**, at the moment of need.
5. **It is cheap.** Usually a few lines, and never needs revisiting.

**In practice:** when you fix a defect, ask whether a reviewer could have caught it by reading the
change. If the honest answer is no, write the test before closing the ticket — and make the failure
message say how to fix it. Then **verify the guard actually fails** by reintroducing the defect once;
a guard that has never failed has not been shown to work.

**Example in this repo:** `test_data/data/` and `test_data/duplicate_data/` are meant to be a
byte-identical pair, file for file — that pairing *is* the duplicate-detection fixture. One file,
`test-file.txt`, existed only in `data/`, and two tests failed with `FileNotFoundError` rather than
with anything that named the real problem. Nothing in a diff would ever show it. The invariant "every
file in `data/` has an identical counterpart in `duplicate_data/`" is four lines of test.

---

## 3a — A detector that stops nothing is not a gate

A guard has to **change the outcome**, not merely report. The distinction is easy to lose because a
tool that prints a detailed diagnostic *feels* like it is protecting you.

Two of them were tried, in order, for the failure mode that a scan which never terminates **hangs**
rather than raises:

| what was tried | what it actually did |
|---|---|
| pytest's `faulthandler_timeout` | Printed every thread's stack at the timeout — and then **let the test keep running to completion and pass.** A 30-second test under `faulthandler_timeout = 5` reported `1 passed`. |
| a fixture running the work on a daemon thread, failing fast | Failed the test at its own timeout, then **wedged the whole run at interpreter exit**: `ThreadPoolExecutor`'s threads are not daemons, and Python joins them at shutdown. Strictly worse than doing nothing, because it moved the hang somewhere with no output at all. |

Only killing the process worked, which meant a plugin — `pytest-timeout`, `timeout_method = thread`.

**In practice:**

1. **Ask what the tool does after it detects.** Prints? Raises? Exits non-zero? Only the last two are
   gates. A dump on stderr in a hung job that CI later kills is read by nobody.
2. **Measure it on a deliberate failure before believing it**, which is §3's rule about proving a
   guard can fail — extended: proving it fails is not enough, you must also see the *build* go red.
   Both attempts above produced convincing-looking output while the suite reported success.
3. **A guard that relocates a failure has made things worse.** Compare against doing nothing, not
   against the ideal.

**Related:** §3, and `FileManager/pytest.ini`, where the rejected alternatives are recorded beside the
setting so nobody re-derives them.

## 4 — A quality floor is a ratchet, never a target to be lowered

`pytest.ini` pins `--cov-fail-under`, and `mypy.ini` lists the modules still exempt from
`check_untyped_defs`. Both are **floors that only move in one direction**. When a change raises real
coverage, raise the floor in the same PR. When a module becomes fully annotated, delete its opt-out
stanza in the same PR. Neither value is ever lowered to make a red build green.

1. **A floor that can be lowered measures nothing.** If the response to a failing gate is to move the
   gate, the gate has no information content — it only records the last time someone was in a hurry.
2. **The ratchet is what converts intent into progress.** `FileManager/docs/REQUIREMENTS.txt` has asked for 95%
   coverage since 2024 and the code sits at 29.81%. An aspiration in a document changes nothing; a
   number that cannot go down turns each PR into a small, permanent gain.
3. **It makes the gap honest.** A floor set at the real measurement states the distance to the goal
   out loud, every run. A floor set at the goal fails constantly, gets ignored, and then gets deleted.
4. **Raising it in the *same* PR is the whole mechanism.** Deferred to "later", the gain evaporates —
   the next change that dips coverage passes freely, and the floor silently becomes a ceiling.

**In practice:** the floor equals the last measured value, rounded down to a whole number. Raise it
whenever a run reports a whole point or more above it. If a change genuinely must reduce coverage —
deleting well-tested code, say — lower the floor **only** with a one-line comment in `pytest.ini`
saying which change did it and why.

**Example in this repo:** the floor was set to 29 against a measured 29.81% rather than to the 95%
that `FileManager/docs/REQUIREMENTS.txt` demands. 95% would have failed on the first run and been switched off
within a week; 29 fails the moment anything regresses, and every test written from here moves it up.
