Prepare this session's work for context compaction. Follow all steps in order.

## Step 1 — Identify what changed this session

Run `git log --oneline -20` to see recent commits. Identify anything merged or committed since the last documentation update (look for "Docs:" prefix commits to find the baseline).

## Step 2 — Update CLAUDE.md

Read the `CLAUDE.md` for the utility you worked in (and the repo-root one if the change was cross-cutting). For each change identified in Step 1, update the relevant section:

- New features or behaviour changes → update the matching section
- Closed issues → remove from the Backlog table
- New open issues → add to the Backlog table
- Changed CLI actions or flags → update the Commands section
- Changed scripts → update the relevant table
- Test count or coverage changes → update the Testing section
- Architecture changes → update Directory Layout or the relevant subsection

Do NOT rewrite sections that have not changed. Make targeted edits only.

Keep token count in mind: prefer concise phrasing, remove stale one-time notes, condense repeated details into one-liners with a pointer to the source, and collapse multi-row tables where the rows say essentially the same thing. CLAUDE.md has a 40k character performance limit — flag if the file is approaching it.

### Content disposal rule (when removing anything from CLAUDE.md)

Before deleting any content, assign it to one of these destinations:

| Content type | Destination |
|-------------|-------------|
| New-developer orientation, workflow, operational procedure | `README.md` (or a linked `doc/<Subject>.md` if too long for README) |
| Design decision — problem, decision, alternatives rejected | `doc/Architecture+Design.md` |
| Deep technical reference — too long for README, too important to lose | New `doc/<Subject>.md`, linked from the relevant README section with intro prose |
| A durable lesson about how to build or sequence work | repo-root `doc/Development-Principles.md` |
| Already documented in README or A+D | Safe to drop — note where it lives |
| Pure PR attribution / historical narrative | Safe to drop — belongs in commit messages, not living docs |

Never remove content without a conscious decision about its disposition. Record the disposition in the Step 6 report.

## Step 3 — Update README.md

Read the current `README.md`. Apply the same changes as Step 2 but scoped to user-facing content:

- CLI action changes → update the action table and examples
- Schema changes → update the schema section
- Test count / coverage changes → update the Testing section
- Backlog changes → update the Backlog section issue lists

## Step 4 — Update memory files

Read `MEMORY.md` to see which memory files exist, then read and update the relevant ones based on what changed this session. Update the one-line hook in `MEMORY.md` for any memory file you changed.

Do NOT create new memory files unless genuinely new persistent context was established this session.

## Step 5 — Commit and push

First, verify the current branch:

```bash
git branch --show-current
```

If the current branch is **not `main`**, stop and warn the user — do not commit or push. Docs commits go to `main` only; committing to a feature branch risks losing the changes when the branch is deleted.

If on `main`, stage only the files updated in this command (never `git add .` or `-A`):

```bash
git add FileManager/CLAUDE.md FileManager/README.md
# plus CLAUDE.md / README.md at the repo root, and any doc/ files touched:
git add doc/Development-Principles.md FileManager/doc/Architecture+Design.md   # as applicable
git commit -m "Docs: <concise summary of what changed>"
git push origin main
```

Commit message should name the specific things updated (e.g. "Docs: mark #8 done, record the mtime-in-ms constraint, raise coverage floor to 42").

## Step 6 — Report

List what you updated and what you deliberately left unchanged, so the user can verify before compaction occurs.
