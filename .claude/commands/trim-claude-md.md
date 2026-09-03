Trim a CLAUDE.md to bring it under the 40k character performance limit without losing information that developers actually need.

`$ARGUMENTS` names which file: `root` for the repo-root CLAUDE.md, a utility name (e.g. `file-manager`) for that utility's. Default to the utility you are currently working in.

## Step 1 — Measure

```bash
wc -c CLAUDE.md
```

Report the current size. If it is already under 35k, note that and stop — no trimming needed.

## Step 2 — Read and triage

Read the full `CLAUDE.md`. For every candidate passage to remove, classify it into one of four buckets **before touching the file**:

| Bucket | Criteria | Action |
|--------|----------|--------|
| **Delete** | One-time setup notes for completed actions; boilerplate derivable from the code | Remove — no preservation needed |
| **Save to memory** | "Why" explanations, historical incidents, non-obvious decisions, constraints that shaped current code | Write or update a memory file first, then remove |
| **Move to README** | User-facing design rationale or architectural explanation not already in README | Add a concise version to README.md first, then remove |
| **Move to a principle** | A durable, reusable lesson about how to build or sequence work — not specific to one file | Add to repo-root `docs/Development-Principles.md` first, then remove |

Sections that must **never** be cut:
- The schema and the `--db-path` resolution rule
- The size + mtime skip check and the millisecond-integer mtime format
- Concurrency and SQLite locking behaviour
- Branch naming convention
- Backlog
- Directory layout
- Skills / slash commands table
- "Behaviours that will surprise you" — every entry there is a trap someone already fell into
- Coverage and mypy ratchets

## Step 3 — Preserve displaced content first

Do this **before** editing CLAUDE.md:

- **Memory items:** write or update the relevant file in the project's memory directory. Update `MEMORY.md` if creating a new file.
- **README items:** add the content to `README.md` in the appropriate section. Do not duplicate — one canonical location per fact.
- **Principles:** add a numbered entry to `../../docs/Development-Principles.md`, with the *why* and a concrete example, in the style of the existing entries.

## Step 4 — Apply edits to CLAUDE.md

Make targeted edits only after Step 3 is complete. Prefer condensing a paragraph to one sentence over deleting a section header entirely.

## Step 5 — Verify

```bash
wc -c CLAUDE.md
```

Target 34–37k to leave headroom for future growth. If still over 40k, return to Step 2.

## Step 6 — Commit on main

Verify the branch is `main` before committing. If not, warn and stop.

```bash
git branch --show-current
git add <the CLAUDE.md> <README.md and doc files if changed>
git commit -m "Docs: trim <which> CLAUDE.md from <old>k to <new>k"
git push origin main
```

## Step 7 — Report

List every section trimmed, which bucket each went to (deleted / memory / README / principle), and the before/after file sizes.
